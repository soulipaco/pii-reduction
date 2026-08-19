"""Command line entry points.

``pii-reduction build-corpus`` regenerates the synthetic corpus; ``pii-reduction
benchmark`` runs the pipeline over it and prints the metrics table. Both are thin:
the work lives in :mod:`pii_reduction.synthetic` and :mod:`pii_reduction.benchmark`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pii_reduction import __version__
from pii_reduction.benchmark import BenchmarkOutcome, run_benchmark, summarise
from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.evaluation.gates import (
    GateConfigurationError,
    GateReport,
    evaluate_gates,
    load_gate_file,
    load_measured_strategy,
)
from pii_reduction.evaluation.report import render_markdown
from pii_reduction.synthetic.corpus import build_corpus, write_corpus
from pii_reduction.synthetic.fetch import DEFAULT_CACHE_DIR
from pii_reduction.synthetic.packs import (
    DEFAULT_REGISTRY,
    PACKS,
    build_pack,
    fetch_dataset,
    pack_spec,
)

__all__ = ["main"]

DEFAULT_CORPUS_DIR = Path("tests/fixtures/corpus")
DEFAULT_CONFIGS_DIR = Path("configs")
DEFAULT_PACK_DIR = Path("demo/packs")
#: These two define the committed corpus. `configs/benchmark_gates.yaml` records them
#: as the provenance of every gate value, and a test asserts the two agree — regenerate
#: with different values and you are measuring a different corpus.
DEFAULT_SEED = 42
DEFAULT_DOCUMENTS_PER_LANGUAGE = 34


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pii-reduction", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    corpus = subparsers.add_parser(
        "build-corpus", help="generate the deterministic synthetic corpus and its manifest"
    )
    corpus.add_argument("--out", type=Path, default=DEFAULT_CORPUS_DIR)
    corpus.add_argument("--seed", type=int, default=DEFAULT_SEED)
    corpus.add_argument(
        "--documents-per-language", type=int, default=DEFAULT_DOCUMENTS_PER_LANGUAGE
    )

    download = subparsers.add_parser(
        "fetch-dataset",
        help="download a registered public dataset and verify it against its checksums",
    )
    download.add_argument("dataset", help="registry key, e.g. bitext_customer_support")
    download.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    download.add_argument("--cache", type=Path, default=DEFAULT_CACHE_DIR)

    pack = subparsers.add_parser(
        "build-pack", help="build a demo pack from a public dataset (fetching it if needed)"
    )
    pack.add_argument("pack", choices=sorted(PACKS), help="which pack to build")
    pack.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"output directory (default: {DEFAULT_PACK_DIR}/<pack>)",
    )
    pack.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    pack.add_argument("--cache", type=Path, default=DEFAULT_CACHE_DIR)
    pack.add_argument("--seed", type=int, default=DEFAULT_SEED)
    pack.add_argument(
        "--documents", type=int, default=None, help="override the pack's document count"
    )
    pack.add_argument(
        "--offline",
        action="store_true",
        help="fail rather than download; use only what the cache already holds",
    )

    benchmark = subparsers.add_parser(
        "benchmark", help="run the pipeline over a corpus and print the metrics table"
    )
    benchmark.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_DIR)
    benchmark.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS_DIR)
    benchmark.add_argument(
        "--split",
        action="append",
        dest="splits",
        help="restrict to a split (dev/calibration/test); repeatable",
    )
    benchmark.add_argument(
        "--chain",
        dest="provider_chain",
        help="override the configured provider chain (e.g. deterministic_presidio)",
    )
    benchmark.add_argument(
        "--strategy",
        dest="reducer",
        choices=["redact", "mask", "pseudonymize"],
        help=(
            "override the configured reduction strategy (ADR-0013). Leakage numbers are "
            "per strategy and must not be compared across strategies"
        ),
    )
    benchmark.add_argument("--markdown", action="store_true", help="render as a markdown table")
    benchmark.add_argument(
        "--gates",
        type=Path,
        help=(
            "check the result against the regression gates in this file "
            "(e.g. configs/benchmark_gates.yaml); exits non-zero if any gate fails"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Exit codes: 0 success, 1 a gate failed, 2 the command could not run.

    A failing gate and a malformed gate file are different events and must not look
    the same to whoever reads the CI log — one is a regression to investigate, the
    other is a typo to fix. The package's own exceptions are written to be
    privacy-safe and actionable, so they are printed as a line rather than raised as
    a traceback; anything else keeps its traceback, because an unexpected error
    should look unexpected.
    """
    try:
        return _run(argv)
    except PiiReductionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _run(argv: Sequence[str] | None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "build-corpus":
        corpus = build_corpus(seed=args.seed, documents_per_language=args.documents_per_language)
        written = write_corpus(corpus, args.out)
        print(
            f"wrote {corpus.meta['documents']} documents, "
            f"{corpus.meta['entities']} entities, "
            f"{corpus.meta['protected_tokens']} protected tokens"
        )
        for name, path in sorted(written.items()):
            print(f"  {name}: {path}")
        return 0

    if args.command == "fetch-dataset":
        return _fetch_dataset(args)

    if args.command == "build-pack":
        return _build_pack(args)

    outcome = run_benchmark(
        corpus_dir=args.corpus,
        configs_dir=args.configs,
        splits=args.splits,
        provider_chain=args.provider_chain,
        reducer=args.reducer,
        benchmark_run_id="benchmark_local",
    )
    render = render_markdown if args.markdown else lambda rows, title: outcome.table(title=title)
    print(render(outcome.rows, title="PII reduction benchmark"))
    print()
    print(summarise(outcome))

    if args.gates is None:
        return 0
    report = _check_gates(outcome, args.gates, splits=args.splits)
    print()
    print(report.render())
    return 0 if report.passed else 1


def _fetch_dataset(args: argparse.Namespace) -> int:
    """Download one registered dataset. The licence gate runs before the transfer.

    Deliberately a separate command from ``build-pack``: on a machine that will build
    several packs, or one behind a proxy, "did the download work" and "did the build
    work" are different questions and should be answerable separately.
    """
    entry, fetched = fetch_dataset(args.dataset, registry_path=args.registry, cache_dir=args.cache)
    retrieval = entry.require_retrieval()
    print(f"{entry.name} ({entry.license}) — {retrieval.repository}@{retrieval.revision[:12]}")
    for role, path in fetched:
        print(f"  {role}: {path} (sha256 verified)")
    if entry.attribution_required:
        print(f"  note: {entry.license} requires attribution and an indication of changes")
    if entry.share_alike:
        print(
            f"  note: {entry.license} is share-alike — anything built from this carries "
            "the same obligation"
        )
    return 0


def _build_pack(args: argparse.Namespace) -> int:
    spec = pack_spec(args.pack)
    corpus = build_pack(
        args.pack,
        registry_path=args.registry,
        cache_dir=args.cache,
        seed=args.seed,
        documents=args.documents,
        allow_download=not args.offline,
    )
    out = args.out if args.out is not None else DEFAULT_PACK_DIR / args.pack
    written = write_corpus(corpus, out)
    print(
        f"pack {spec.key}: {corpus.meta['documents']} documents, "
        f"{corpus.meta['entities']} entities, "
        f"{corpus.meta['protected_tokens']} protected tokens "
        f"from {corpus.meta['dataset_name']} ({corpus.meta['license']})"
    )
    for name, path in sorted(written.items()):
        print(f"  {name}: {path}")
    print(f"\nbenchmark it with:\n  pii-reduction benchmark --corpus {out}")
    return 0


def _check_gates(
    outcome: BenchmarkOutcome,
    path: Path,
    *,
    splits: Sequence[str] | None,
) -> GateReport:
    """Check the run against the gate set named after the chain that produced it.

    Selecting the set by chain rather than by flag is what stops a hybrid-chain result
    being scored against the deterministic floors, which would pass trivially. The same
    argument applies to splits: the shipped gates are measured over the whole corpus
    (``measured.splits`` in the gate file), so scoring one split against them compares
    numbers that were never comparable. Refused rather than warned about — a benchmark
    that quietly answers a different question than the one asked is the failure this
    module exists to prevent.
    """
    measured_strategy = load_measured_strategy(path)
    if outcome.strategy != measured_strategy:
        # Data-level like the chain guard, not flag-level: a dataset config that sets
        # `reducer: mask` reaches here with no --strategy flag at all, and a mask run
        # would PASS redact leakage floors — masking covers the exact surface just as
        # redaction does, so the full-value metric cannot tell them apart. Leakage is
        # per strategy (ADR-0013 §5); a gate that measures a different question than it
        # asks is the failure this module exists to stop.
        raise GateConfigurationError(
            f"these gates were measured under strategy {measured_strategy!r} but the run "
            f"used {outcome.strategy!r}. Run the gates under the measured strategy, or "
            "add a gate set measured on this one"
        )
    if splits:
        raise GateConfigurationError(
            f"--gates cannot be combined with --split ({', '.join(splits)}): the shipped "
            "gates are measured over the whole corpus, so a single split would be judged "
            "against floors it was never measured against. Run the gates on the full "
            "corpus, or add a gate set measured on that split"
        )
    chain = outcome.provider_chain
    if "," in chain:
        raise GateConfigurationError(
            f"the run mixed provider chains ({chain}); gates are defined per chain, so "
            "run one chain at a time when checking them"
        )
    gates = load_gate_file(path, chain)
    return evaluate_gates(outcome.rows, gates, gate_set=chain)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())

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
from pii_reduction.benchmark import run_benchmark, summarise
from pii_reduction.evaluation.report import render_markdown
from pii_reduction.synthetic.corpus import build_corpus, write_corpus

__all__ = ["main"]

DEFAULT_CORPUS_DIR = Path("tests/fixtures/corpus")
DEFAULT_CONFIGS_DIR = Path("configs")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pii-reduction", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    corpus = subparsers.add_parser(
        "build-corpus", help="generate the deterministic synthetic corpus and its manifest"
    )
    corpus.add_argument("--out", type=Path, default=DEFAULT_CORPUS_DIR)
    corpus.add_argument("--seed", type=int, default=42)
    corpus.add_argument("--documents-per-language", type=int, default=34)

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
    benchmark.add_argument("--markdown", action="store_true", help="render as a markdown table")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
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

    outcome = run_benchmark(
        corpus_dir=args.corpus,
        configs_dir=args.configs,
        splits=args.splits,
        provider_chain=args.provider_chain,
        benchmark_run_id="benchmark_local",
    )
    render = render_markdown if args.markdown else lambda rows, title: outcome.table(title=title)
    print(render(outcome.rows, title="PII reduction benchmark"))
    print()
    print(summarise(outcome))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())

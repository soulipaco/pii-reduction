"""``pii-reduction-databricks`` — the driver-path front door (ADR-0025).

A separate entry point from ``pii-reduction`` on purpose. The core CLI must stay
importable in an environment with no Spark: `tests/test_package.py` asserts
statically that nothing outside this package imports it, so a `--databricks` flag on
the core CLI would either break that guard or hide the import from it. A second
console script inside the surface costs one line of packaging and keeps the boundary
literal.

What it does is deliberately thin: resolve the dataset configuration, obtain a
session from whichever credentials the environment offers — a CLI profile,
``DATABRICKS_HOST`` plus a token or service principal, or the ambient credentials of
Databricks compute — and hand both to :func:`run_driver`. The reduction
itself is the same ``build_pipeline``/``process`` the local run uses (`AGENTS.md`
rule 10) — there is no second implementation here to drift.

Output is metadata only: run id, row and field counts, table names. Never source
text, never a detected value (`AGENTS.md` rule 8).

**Which environment.** This script needs the ``databricks`` extra, which lives in its
own venv rather than the core one because Databricks Connect couples client and
server versions (ADR-0006). Install it there — ``pip install -e ".[databricks]"`` —
and run it from that venv; the core ``.venv`` has no Spark and the script will say so
at the first session call rather than at import.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pii_reduction.config import load_resolved_dataset
from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.databricks.runner import run_driver
from pii_reduction.databricks.session import get_session

__all__ = ["cli", "main"]

DEFAULT_CONFIGS_DIR = Path("configs")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-reduction-databricks",
        description="Run one configured reduction on Databricks (driver path).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_command = subparsers.add_parser(
        "run", help="read a Unity Catalog table, reduce it, write Delta tables"
    )
    run_command.add_argument("dataset", help="dataset name under <configs>/datasets/")
    run_command.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS_DIR)
    run_command.add_argument(
        "--profile",
        default=None,
        help=(
            "Databricks CLI profile. Optional: without it the session falls back to "
            "DATABRICKS_CONFIG_PROFILE, then to DATABRICKS_HOST plus a token or "
            "service principal, then to ambient credentials on Databricks compute"
        ),
    )
    # Every override below defaults to what the dataset config names. They exist so
    # one config can be pointed at a throwaway table without editing the file.
    run_command.add_argument("--source-table", default=None, help="override catalog.schema.table")
    run_command.add_argument(
        "--destination-prefix", default=None, help="override the catalog.schema written to"
    )
    run_command.add_argument(
        "--reduced-only-prefix",
        default=None,
        help=(
            "additionally write <dataset>_reduced_only — the frame without the "
            "configured raw text columns — to this catalog.schema (ADR-0024)"
        ),
    )
    run_command.add_argument(
        "--mode",
        choices=["overwrite", "append", "errorifexists"],
        default=None,
        help="override the destination write mode",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[..., Any] = get_session,
) -> int:
    """Exit codes: 0 success, 1 the run completed with failed fields, 2 it could
    not be performed at all.

    Exit 1 mirrors ``pii-reduction run`` deliberately: partial output must look like
    a failure to a scripted caller, and on this path the caller is usually a job
    scheduler (ADR-0025 rung 3). The reduced table is still written — the failed
    fields are null with ``pii_status`` recording why (ADR-0023) — so the exit code
    is the signal that something needs looking at, not a claim that nothing landed.

    ``session_factory`` is injected so the argument wiring can be tested in the
    default tier against a fake session, with no workspace and no Spark — the same
    seam the runner's init-once semantics use.
    """
    try:
        return _run(argv, session_factory)
    except PiiReductionError as error:
        # This package's own errors are written to be privacy-safe and actionable.
        print(f"error: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        # Everything else gets its class and nothing more. The core CLI lets an
        # unexpected exception keep its traceback, which is right for a local run;
        # here the un-wrapped crossing is `session_factory` → Databricks Connect,
        # whose messages carry the workspace URL and profile, and this output lands
        # in a job or CI log (AGENTS.md rules 1 and 8, the same doctrine
        # `processing/pipeline.py` applies to per-field failures).
        print(f"error: unexpected {type(error).__name__}", file=sys.stderr)
        return 2


def _run(argv: Sequence[str] | None, session_factory: Callable[..., Any]) -> int:
    args = _build_parser().parse_args(argv)
    config = load_resolved_dataset(args.configs, args.dataset)
    spark = session_factory(args.profile)
    result = run_driver(
        spark,
        config,
        source_table=args.source_table,
        destination_prefix=args.destination_prefix,
        reduced_only_prefix=args.reduced_only_prefix,
        mode=args.mode,
    )
    print(
        f"dataset={config.dataset.name} run_id={result.run_id} rows={result.rows} "
        f"config={result.config_hash[:12]}\n"
        f"  reduced: {result.reduced_table}\n"
        f"  audit: {result.audit_table}\n"
        f"  metrics: {result.metrics_table}"
    )
    if result.reduced_only_table is not None:
        print(f"  reduced_only: {result.reduced_only_table}")
    if result.fields_failed:
        print(
            f"  status={result.status} fields_failed={result.fields_failed} — "
            f"see pii_status in {result.reduced_table}"
        )
        return 1
    return 0


def cli() -> None:
    """Console-script and job entry point: turn the exit code into a real exit.

    ``main`` returns an ``int`` so tests can assert on it. A terminal invocation
    would exit correctly either way — setuptools' console-script wrapper calls
    ``sys.exit(main())`` for us — but **a Databricks `python_wheel_task` calls the
    entry point as a plain function and ignores what it returns.** Measured on the
    workspace 2026-08-21: a run that printed `error: ...` and returned 2 was recorded
    by the job as `SUCCESS`. A scheduler would have seen green over a failed
    reduction, which is the exact outcome the exit code exists to prevent, so the
    entry point has to raise rather than return.

    **Only a failing code raises.** Databricks runs the wheel task under IPython,
    where *any* ``SystemExit`` — including ``SystemExit(0)`` — is reported as a task
    error. Raising unconditionally therefore turned a successful reduction into a red
    job, which the same 2026-08-21 run showed immediately: 25 rows read from a volume
    and three Delta tables written, and the task still marked failed. Success must
    return normally; only a non-zero code may raise.
    """
    code = main()
    if code:
        raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover - module entry point
    cli()

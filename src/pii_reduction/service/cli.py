"""``pii-reduction-service`` — start rung 4 (ADR-0026).

A third console script rather than a `pii-reduction serve` subcommand, and the reason
is a guard rather than a preference: a subcommand would make `cli.py` import
`pii_reduction.service`, which `tests/test_package.py` forbids for everything outside
this package — including from inside a function, since the guard walks the AST. The
engine does not learn that a service exists, and the packaging reflects it.

**The default bind is `127.0.0.1`.** No authentication is implemented (ADR-0026):
hosted as a Databricks App the platform authenticates and authorizes as the end user,
and run locally this is a developer tool. Binding anywhere else needs `--host`
explicitly, because with no auth the bind address is the entire control.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.service.errors import RuntimeUnavailableError
from pii_reduction.service.runs import RunStore
from pii_reduction.service.runtimes import Runtime
from pii_reduction.service.runtimes.local import local_runtime

__all__ = ["build_runtimes", "main"]

DEFAULT_CONFIGS_DIR = Path("configs")
LOCALHOST = "127.0.0.1"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-reduction-service",
        description=(
            "Serve the PII reduction service layer: build a dataset configuration, "
            "trigger a run, read run metadata. No endpoint accepts or returns text."
        ),
    )
    parser.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS_DIR)
    parser.add_argument(
        "--host",
        default=LOCALHOST,
        help=(
            "bind address (default 127.0.0.1). This service implements no "
            "authentication; exposing it on a network is a deployment decision that "
            "needs one in front of it"
        ),
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--databricks",
        action="store_true",
        help=(
            "also offer the 'databricks' runtime, which runs the driver path. Needs "
            "the databricks extra, which lives in its own venv (ADR-0006)"
        ),
    )
    parser.add_argument(
        "--profile",
        default=None,
        help=(
            "Databricks CLI profile for the databricks runtime. Optional: without it "
            "the session falls back to DATABRICKS_CONFIG_PROFILE, then to "
            "DATABRICKS_HOST plus a token or service principal, then to ambient "
            "credentials on Databricks compute"
        ),
    )
    return parser


def build_runtimes(*, databricks: bool = False, profile: str | None = None) -> dict[str, Any]:
    """Wire the runtimes this process offers.

    The Databricks import is function-local and conditional, so a service started
    without ``--databricks`` never touches the optional surface.

    **The extra is probed here, at startup.** Importing the runtime module succeeds
    without `databricks-connect` — that is the point of the lazy session seam — so
    without this check a service started from the wrong virtual environment would
    accept a run, fail it on the worker thread, and record a bare
    `error_category="DatabricksError"`. The install instruction that error carries
    would never reach anybody. Refusing to start is the honest answer, and it is what
    `RuntimeUnavailableError` exists to say.
    """
    runtimes: dict[str, Runtime] = {"local": local_runtime}
    if databricks:
        if find_spec("databricks") is None or find_spec("databricks.connect") is None:
            raise RuntimeUnavailableError(
                "the 'databricks' runtime needs the databricks extra, which is not "
                "installed in this environment. It lives in its own virtual "
                'environment (ADR-0006): pip install -e ".[databricks]" there, and '
                "start the service from it"
            )
        from pii_reduction.service.runtimes.databricks import databricks_runtime

        runtimes["databricks"] = databricks_runtime(profile)
    return runtimes


def main(argv: Sequence[str] | None = None) -> int:
    """Exit codes: 0 on a clean shutdown, 2 when the service could not start.

    Startup failures are configuration failures — a malformed `project.yaml`, an
    invalid template — and they are reported as a line rather than a traceback,
    because the package's own errors are written to be read.
    """
    args = _build_parser().parse_args(argv)
    try:
        import uvicorn

        from pii_reduction.service.api import create_app
    except ImportError as error:
        # Scoped to the two framework imports only. Wrapping `create_app` in the same
        # handler would report an unrelated ImportError from below as "install the
        # service extra", which is the wrong instruction confidently given.
        print(
            f"error: {error.name or 'a dependency'} is not installed. The service "
            'needs the service extra: pip install -e ".[service]"',
            file=sys.stderr,
        )
        return 2
    try:
        runtimes = build_runtimes(databricks=args.databricks, profile=args.profile)
        store = RunStore(runtimes)
        app = create_app(args.configs, store=store)
    except PiiReductionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.host != LOCALHOST:
        print(
            f"warning: binding {args.host} — this service implements no "
            "authentication (ADR-0026); put one in front of it",
            file=sys.stderr,
        )
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        # The worker thread joins on the way out rather than relying on the
        # interpreter's atexit join, which is what happens by accident otherwise.
        store.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

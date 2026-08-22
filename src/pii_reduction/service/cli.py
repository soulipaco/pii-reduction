"""``pii-reduction-service`` — start rung 4 (ADR-0026).

A third console script rather than a `pii-reduction serve` subcommand, and the reason
is a guard rather than a preference: a subcommand would make `cli.py` import
`pii_reduction.service`, which `tests/test_package.py` forbids for everything outside
this package — including from inside a function, since the guard walks the AST. The
engine does not learn that a service exists, and the packaging reflects it.

**The default bind is `127.0.0.1`, and any other bind is refused** unless
`--i-provide-authentication` says something in front of this service authenticates
callers. No authentication is implemented here (ADR-0026), so with no auth the bind
address is the entire control, and a warning printed into a container log nobody
reads would not be one.

Hosted as a Databricks App the platform authenticates the end user. **Whether it
*authorizes* as them is a separate question this project has not verified** — data
access defaults to the App's service principal, and on-behalf-of-user authorization
is an opt-in. `docs/19_SERVICE_LAYER.md` carries the full statement; it matters
because `docs/09`'s conditions for a Class B display surface require reading under
the end user's identity.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.observability.logging import get_logger, safe_fields
from pii_reduction.service.errors import RuntimeUnavailableError
from pii_reduction.service.journal import FileRunJournal
from pii_reduction.service.runs import RunStore
from pii_reduction.service.runtimes import Runtime
from pii_reduction.service.runtimes.local import local_runtime

__all__ = ["build_runtimes", "main"]

logger = get_logger("service")

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
            "authentication, so any other address is refused unless "
            "--i-provide-authentication is passed as well"
        ),
    )
    parser.add_argument(
        "--i-provide-authentication",
        action="store_true",
        help=(
            "acknowledge that something in front of this service authenticates and "
            "authorizes callers. Required for any --host other than 127.0.0.1"
        ),
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-ui",
        dest="ui",
        action="store_false",
        help=(
            "do not serve the control panel at / and /ui. The API is unchanged either "
            "way; the page renders only what the API returns (ADR-0035)"
        ),
    )
    parser.add_argument(
        "--databricks",
        action="store_true",
        help=(
            "also offer the 'databricks' runtime, which runs the driver path. Needs "
            "the databricks extra, which lives in its own venv (ADR-0006)"
        ),
    )
    parser.add_argument(
        "--run-journal",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "append run metadata to this file so run history survives a restart. "
            "Without it the store is process-local and GET /runs/{id} answers 404 for "
            "a run this process did not submit. Metadata only — the same fields the "
            "API returns, never text. Single writer: one replica per file"
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


def _serve(app: Any, *, host: str, port: int) -> None:
    """Hand the application to the server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


def main(
    argv: Sequence[str] | None = None,
    *,
    serve: Callable[..., None] = _serve,
) -> int:
    """Exit codes: 0 on a clean shutdown, 2 when the service could not start.

    Startup failures are configuration failures — a malformed `project.yaml`, an
    invalid template — and they are reported as a line rather than a traceback,
    because the package's own errors are written to be read.

    ``serve`` is injected for the same reason `databricks/cli.py` injects
    ``session_factory``: the argument wiring and the bind refusal are then testable in
    the default tier without opening a listener.
    """
    args = _build_parser().parse_args(argv)
    if args.host != LOCALHOST and not args.i_provide_authentication:
        # Checked **before** anything is built. This service implements no
        # authentication, so the bind address is the entire control, and a warning on
        # stderr is invisible in a container log nobody reads. Fail-closed, like
        # ADR-0023's failure mode and the Delta writer's `errorifexists`.
        print(
            f"error: refusing to bind {args.host}. This service implements no "
            "authentication (ADR-0026); hosted as a Databricks App the platform "
            "provides it, and anywhere else something must. Pass "
            "--i-provide-authentication to confirm that it does",
            file=sys.stderr,
        )
        return 2
    if serve is _serve and find_spec("uvicorn") is None:
        # Probed, not imported, and only when the **default** server is the one that
        # will be used. `uvicorn` lives in the `service` extra and not in `dev`, so
        # the environment CI provisions has fastapi and no uvicorn — without this the
        # most likely operator mistake would raise a traceback from the bottom of
        # `main`, after the app and its worker thread had already been built, instead
        # of this instruction. Probing rather than importing is what lets a caller who
        # injects their own `serve` (the tests, an embedder) run with no server
        # installed at all, which is the honest requirement: `main` needs a server
        # only if it is going to start one.
        print(
            "error: uvicorn is not installed. The service "
            'needs the service extra: pip install -e ".[service]"',
            file=sys.stderr,
        )
        return 2
    try:
        from pii_reduction.service.api import create_app
    except ImportError as error:
        # Scoped to the framework import, and nothing else: wrapping `create_app`'s
        # own body in the same handler would report an unrelated ImportError from
        # below as "install the service extra", which is a wrong instruction given
        # confidently.
        print(
            f"error: {error.name or 'a dependency'} is not installed. The service "
            'needs the service extra: pip install -e ".[service]"',
            file=sys.stderr,
        )
        return 2
    try:
        runtimes = build_runtimes(databricks=args.databricks, profile=args.profile)
        # The path comes from the operator's command line and nowhere else. A request
        # that could name it would make the service write wherever its own credentials
        # reach — the confused-deputy shape ADR-0026's server-side templates exist for.
        journal = FileRunJournal(args.run_journal) if args.run_journal else None
        store = RunStore(runtimes, journal=journal)
        app = create_app(args.configs, store=store, ui=args.ui)
    except PiiReductionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.i_provide_authentication:
        # The riskiest configuration this CLI can produce leaves a record. Metadata
        # only, through the same allowlisted path everything else logs through.
        logger.warning(
            "service bound beyond localhost on an operator's authentication assertion %s",
            safe_fields(destination=f"{args.host}:{args.port}", status="auth_asserted"),
        )
    try:
        serve(app, host=args.host, port=args.port)
    finally:
        # The worker thread joins on the way out rather than relying on the
        # interpreter's atexit join, which is what happens by accident otherwise.
        store.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

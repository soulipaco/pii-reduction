"""The HTTP surface (ADR-0026). The only module in this package that names FastAPI.

Route decorators run at import time, so this module cannot defer its framework import
the way `providers/presidio_provider.py` defers Presidio. The contract is therefore on
the package instead: **`service/__init__.py` must not import this module**, or
`pii_reduction.service` stops being importable in a core install. A subprocess guard
in `tests/test_package.py` holds it.

Three things this file does that are load-bearing rather than incidental:

* **It installs its own validation-error handler.** Pydantic's error dicts echo the
  offending ``input``, and FastAPI's default handler serializes them into the 422
  body. That is a framework *default*, not an exception the service raises, so
  "report by category" does not reach it — `docs/09` requires the handler.
* **It answers unexpected exceptions with a category and nothing else.** The same
  doctrine `databricks/cli.py` applies: an exception crossing into this layer may
  carry a workspace URL, a profile name, or text from below.
* **It has no endpoint that returns, streams or links to text**, and no endpoint that
  accepts any. That is how it satisfies `docs/09` — by absence, not by filtering.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Request, Response
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pii_reduction import __version__
from pii_reduction.config import TAXONOMY
from pii_reduction.config.errors import ConfigurationError
from pii_reduction.config.loader import load_project_config
from pii_reduction.service.builder import build_dataset_config, write_dataset_config
from pii_reduction.service.catalog import (
    check_dataset_names,
    describe_dataset,
    list_dataset_names,
    load_dataset,
)
from pii_reduction.service.errors import ServiceError
from pii_reduction.service.knobs import OFFERABLE_PARSER_OPTIONS
from pii_reduction.service.models import (
    DATASET_NAME_PATTERN,
    RUN_ID_PATTERN,
    BuildConfigRequest,
    BuiltConfigResponse,
    DatasetSummary,
    EntitySummary,
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    RunRecord,
    RunRequest,
    TemplateSummary,
)
from pii_reduction.service.runs import RunStore
from pii_reduction.service.templates import (
    DatasetTemplate,
    check_template_chains,
    load_templates,
)

__all__ = ["create_app"]


#: A location part safe to put in an error body: a field name this service declared.
#: Deliberately narrower than `_NAME_PATTERN` — a *path* segment never legitimately
#: contains a dot, which would make the joined path ambiguous as well as leaky.
_SAFE_LOC_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: What a caller-supplied key is replaced with. Says *where* the error is without
#: saying what was sent, which is the whole contract of the 422 handler.
REDACTED_LOC_PART = "<key>"


def _safe_loc_part(part: object) -> str:
    """One segment of a pydantic error location, safe to show.

    An index is a number the caller did not choose. A declared field name is one this
    service published. **Anything else is a caller-supplied mapping key** — pydantic
    puts it in `loc` before the constraint that rejected it applies — and is replaced
    rather than echoed, however harmless it looks: a request body is Class B from the
    moment it exists (`docs/09`, *the inbound half*), and the service cannot know what
    a client put in a key by mistake.
    """
    if isinstance(part, int):
        return str(part)
    text = str(part)
    return text if _SAFE_LOC_PART.match(text) else REDACTED_LOC_PART


def _error(status_code: int, category: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(category=category, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _entity_summaries() -> tuple[EntitySummary, ...]:
    """The taxonomy, with the caveat attached rather than left to a README.

    `ADDRESS` is a known label that **no shipped provider detects** (ADR-0002). A
    column picker that lists it without saying so invites a configuration whose run
    reports success and reduces nothing.
    """
    return tuple(
        EntitySummary(
            label=definition.label,
            replacement=definition.replacement,
            detected_at_baseline=definition.detected_at_baseline,
        )
        for _, definition in sorted(TAXONOMY.items())
    )
    # `replacement` here is the **taxonomy default**. A project's `entities.yaml` may
    # override it, and a run uses the overridden value; recomputing that here would
    # mean reimplementing `config/loader.py`'s layering in the service, which is the
    # one thing this layer must not do. `docs/19` says the value is a default.


def _template_summary(
    template: DatasetTemplate, *, project_chains: tuple[str, ...]
) -> TemplateSummary:
    return TemplateSummary(
        name=template.name,
        description=template.description,
        source_type=template.source.type,
        destination_type=template.destination.type,
        columns=template.columns,
        row_id_columns=template.offered_row_id_columns(),
        entities=template.entities or tuple(sorted(TAXONOMY)),
        parsers=template.offered_parsers(),
        provider_chains=template.provider_chains or project_chains,
        reducers=template.offered_reducers(),
        # Which parser accepts each offered option, so a UI can attach a toggle to
        # the right parser instead of guessing — and so a template offering
        # `split_lines` alongside a transcript-only parser list is visibly wrong.
        parser_options={
            option: tuple(
                sorted(
                    parser
                    for parser in template.offered_parsers()
                    if option in OFFERABLE_PARSER_OPTIONS.get(parser, frozenset())
                )
            )
            for option in template.offered_parser_options()
        },
        requires_databricks=template.requires_databricks,
    )


def create_app(configs_dir: Path, *, store: RunStore) -> FastAPI:
    """Build the ASGI application.

    Configuration is read **once, at startup**: the project layer and the templates.
    A malformed configuration is then a service that refuses to start rather than one
    that fails on somebody's first request, which is the same rule
    `config/loader.py` follows for a run.

    The ``store`` — and therefore the set of runtimes this process offers — is
    injected rather than discovered. That is what keeps this module free of any
    Databricks import: the wiring lives in `service/cli.py`, and the Databricks
    runtime itself in the one file permitted to name that surface.
    """
    # The directory, not the file: `load_project_config` merges the optional
    # sibling files (entities/providers/languages) only when given the directory,
    # and without providers.yaml every chain name is undefined.
    project = load_project_config(configs_dir)
    templates = load_templates(configs_dir)
    project_chains = tuple(sorted(project.chains))
    check_template_chains(templates, project_chains)
    # Refuse a configuration directory whose dataset names already collide. Two files
    # declaring one name write over each other's output, and a file declaring another
    # file's stem makes that other file unreachable — operator errors in files the
    # service did not write, which belong at startup rather than as a 404 blaming an
    # innocent dataset.
    check_dataset_names(configs_dir)
    run_store = store

    app = FastAPI(
        title="PII reduction service",
        version=__version__,
        summary="Build a dataset configuration, trigger a run, read run metadata.",
        description=(
            "Rung 4 of ADR-0025's platform ladder. This service owns no reduction "
            "logic: it assembles configurations that the engine validates, and "
            "triggers the same entry points a person would run by hand. No endpoint "
            "accepts or returns source text, reduced text, or a detected value "
            "(ADR-0026, docs/09)."
        ),
        # Never on. Starlette's debug mode returns a traceback in the response body,
        # which is a display surface carrying whatever the exception held.
        debug=False,
    )

    # -- error handling ----------------------------------------------------------

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> Response:
        """Answer a schema violation without echoing what was sent.

        Pydantic puts the rejected value in ``input`` and sometimes in ``ctx``;
        FastAPI's default handler serializes both. A caller gets the field path and
        the reason, which is everything they need to fix the request, and none of
        what they sent — because the service cannot know that a field a caller
        misused did not contain text.

        **The path itself is caller-supplied wherever a request field is a mapping.**
        Pydantic puts a rejected *dict key* into ``loc``, before the key's own pattern
        constraint is what rejected it — so joining ``loc`` raw reflects an unbounded
        string. That was already true of an `extra="forbid"` typo; ADR-0034's
        `parser_options` made it a place a caller is *meant* to send keys, which turns
        "somebody sent junk" into "a client mapped a column's content into an options
        map". `_safe_loc_part` is why the docstring above is true of the path as well
        as the value.
        """
        fields = "; ".join(
            f"{'.'.join(_safe_loc_part(part) for part in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors()
        )
        # The literal, not `status.HTTP_422_*`: Starlette renamed the constant and
        # deprecated the old name, and this handler must not start emitting warnings
        # on somebody else's upgrade schedule.
        return _error(422, "invalid_body", fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> Response:
        """404 for an unknown path and 405 for a wrong method are the framework's.

        Without this they answer `{"detail": "Not Found"}` and the documented envelope
        would be a claim with two exceptions nobody had noticed.
        """
        return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> Response:
        return _error(exc.status_code, exc.category, str(exc))

    @app.exception_handler(ConfigurationError)
    async def _configuration_error(_: Request, exc: ConfigurationError) -> Response:
        # The configuration layer's messages name the file, the dataset and the field
        # and are written to be shown to whoever has to fix them. That is the whole
        # value of the builder: an invalid choice comes back as an instruction.
        return _error(400, "invalid_configuration", str(exc))

    # There is deliberately **no** handler for `PiiReductionError` as a whole. An
    # earlier draft relayed `str(exc)` for the entire tree, which includes
    # `DatabricksError` — whose messages exist precisely because Databricks Connect
    # quotes the workspace URL. `ServiceError` and `ConfigurationError` are relayed
    # because this layer or the configuration layer composed them; everything else
    # falls through to the handler below and becomes a category (ADR-0026 rule 5).

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> Response:
        # Category only. Anything that reaches here crossed into this layer from
        # below — a driver, a client library, the filesystem — and its message is not
        # one this layer can vouch for (`AGENTS.md` rule 8, `docs/09`).
        # Note that this governs the *response* only. Starlette's
        # `ServerErrorMiddleware` re-raises after this handler runs, so the traceback
        # still reaches the server's own log — which is the operator's channel, not a
        # caller's, and is subject to the same `docs/09` rules as any other log.
        return _error(500, "unexpected_error", f"unexpected {type(exc).__name__}")

    # -- read ---------------------------------------------------------------------

    # Every route below is a plain `def`, not `async def`. They touch the filesystem
    # — globbing the dataset directory, reading YAML, writing a config — and a
    # coroutine would do that on the event loop, blocking every other request behind
    # a disk read. Starlette runs a sync endpoint in its threadpool instead.

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(version=__version__, runtimes=run_store.runtimes)

    @app.get("/entities", response_model=tuple[EntitySummary, ...])
    def entities() -> tuple[EntitySummary, ...]:
        """The entity labels a configuration may name — the engine's taxonomy."""
        return _entity_summaries()

    @app.get("/templates", response_model=tuple[TemplateSummary, ...])
    def templates_index() -> tuple[TemplateSummary, ...]:
        return tuple(
            _template_summary(template, project_chains=project_chains)
            for _, template in sorted(templates.items())
        )

    @app.get("/datasets", response_model=tuple[str, ...])
    def datasets_index() -> tuple[str, ...]:
        return list_dataset_names(configs_dir)

    @app.get("/datasets/{name}", response_model=DatasetSummary)
    def dataset_detail(
        name: Annotated[str, PathParam(pattern=DATASET_NAME_PATTERN)],
    ) -> DatasetSummary:
        return describe_dataset(load_dataset(configs_dir, name))

    # -- build --------------------------------------------------------------------

    @app.post("/configs", response_model=BuiltConfigResponse, status_code=201)
    def build_config(request: BuildConfigRequest) -> BuiltConfigResponse:
        """Assemble a dataset configuration and let the engine's config layer judge it.

        Source, destination and the processing switches come from the named template.
        The caller chooses identity, columns and entities; everything else is refused
        by the request model having nowhere to put it (ADR-0026 rule 4).
        """
        built = build_dataset_config(request, templates=templates, project=project)
        saved: str | None = None
        if request.save:
            # Relative to the configuration directory, never absolute: an absolute
            # path is a server-environment string (it carries the deployment root and,
            # on a developer machine, an OS username) and this value goes to a caller.
            saved = write_dataset_config(built, configs_dir).relative_to(configs_dir).as_posix()
        return BuiltConfigResponse(
            dataset=describe_dataset(built.resolved),
            config_yaml=built.to_yaml(),
            saved_path=saved,
        )

    # -- run ----------------------------------------------------------------------

    @app.post("/runs", response_model=RunRecord, status_code=202)
    def trigger_run(request: RunRequest) -> RunRecord:
        """Start a run and answer immediately. 202, because it has not happened yet.

        The dataset is resolved here rather than on the worker thread, so a
        configuration error is a 400 the caller sees rather than a failed run they
        have to go and look up.
        """
        config = load_dataset(configs_dir, request.dataset)
        return run_store.submit(config, runtime=request.runtime)

    @app.get("/runs", response_model=tuple[RunRecord, ...])
    def runs_index() -> tuple[RunRecord, ...]:
        return run_store.list()

    @app.get("/runs/{run_id}", response_model=RunRecord)
    def run_detail(run_id: Annotated[str, PathParam(pattern=RUN_ID_PATTERN)]) -> RunRecord:
        return run_store.get(run_id)

    return app

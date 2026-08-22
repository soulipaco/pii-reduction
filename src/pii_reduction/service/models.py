"""Request and response contracts for the service layer (ADR-0026).

**Every model here is metadata by construction.** There is no field that can hold
source text, reduced text or a detected value, and that is the mechanism by which the
API satisfies `docs/09`'s *Display surfaces, API responses, and request payloads*
rather than by filtering on the way out. A filter can be wrong; an absent field
cannot. `tests/test_service_contracts.py` asserts the property over every model in
this module, by name, so adding one is a decision somebody has to make on purpose.

The same reasoning runs inbound: no request model accepts text either. A caller sends
names — of a template, a dataset, a column, an entity label — never content.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BuildConfigRequest",
    "BuiltConfigResponse",
    "ColumnRequest",
    "ColumnSummary",
    "DatasetSummary",
    "EntitySummary",
    "ErrorBody",
    "ErrorResponse",
    "HealthResponse",
    "ParserOptionSummary",
    "RunRecord",
    "RunRequest",
    "RunState",
    "RunSummary",
    "TemplateSummary",
]

#: A dataset name becomes a file name under ``configs/datasets/`` and a Delta table
#: prefix (``<dataset>_reduced``), so it is validated as an identifier rather than
#: sanitised as a string: no separators, no dots, no leading digit. This is what
#: makes "a server-derived filename" true — the server derives it from a name it has
#: already proved cannot escape a directory or a SQL identifier.
DATASET_NAME_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"
_COLUMN_PATTERN = r"^[A-Za-z_][A-Za-z0-9_ .-]{0,63}$"
#: Names of things the server already knows about — templates, runtimes, chains,
#: parsers, reducers, entity labels. Bounded and pattern-checked so an unknown one
#: is refused by the 422 handler, which does not echo what was sent, rather than by
#: a 404 whose message quotes it back. Self-reflection discloses nothing new to that
#: caller, but an unbounded string in an error body is still an unbounded string in
#: an error body — and for a path parameter it is in the access log as well.
_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$"


class ServiceModel(BaseModel):
    """Strict and immutable, like the configuration models: an unknown key is a typo."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HealthResponse(ServiceModel):
    status: str = "ok"
    version: str
    runtimes: tuple[str, ...] = ()


class TemplateSummary(ServiceModel):
    """What a caller may choose from, and nothing about what the source contains."""

    name: str
    description: str = ""
    source_type: str
    destination_type: str
    #: The column menu, declared server-side. The service does **not** read the source
    #: to discover columns: a preview endpoint is forbidden (ADR-0026). The engine has
    #: had a schema-only path since ADR-0031, but `service/` may not import `sources/`,
    #: and an endpoint listing *every* column would disclose the ones this menu
    #: deliberately withholds.
    columns: tuple[str, ...] = ()
    row_id_columns: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    parsers: tuple[str, ...] = ()
    provider_chains: tuple[str, ...] = ()
    reducers: tuple[str, ...] = ()
    #: Parser options this template lets a caller set (ADR-0034), each with the
    #: parsers that accept it and the engine's default. A UI renders these as toggles;
    #: an empty mapping means the template offers none, which is the default. The value
    #: is the *menu*, never this dataset's setting.
    parser_options: dict[str, ParserOptionSummary] = Field(default_factory=dict)
    #: True when this template's source or destination needs a Spark session, so a
    #: caller learns *before* triggering that it needs the Databricks runtime.
    requires_databricks: bool = False


class ParserOptionSummary(ServiceModel):
    """One parser option a template offers, and what it does if left alone.

    `default` is the **engine's** value, reported so a client renders the truth rather
    than remembering it (ADR-0035). A page that keeps its own copy of a default is a
    page that silently overrides one when it changes.
    """

    #: Which of the template's parsers accept this option. A tuple rather than one
    #: name because nothing in the design forbids two parsers sharing an option name —
    #: a test notices if that ever becomes true.
    parsers: tuple[str, ...]
    default: bool
    #: What the option means, in words a surface should show. Server-side because a
    #: caption a client writes is a caption nobody reviewed, and `docs/19` requires
    #: these to describe the *shape of text an option suits* rather than to recommend.
    caption: str = ""


class EntitySummary(ServiceModel):
    """One entity label a configuration may name.

    ``detected_at_baseline`` is carried because a column picker is exactly the surface
    where the difference matters: `ADDRESS` is in the taxonomy and **no shipped
    provider detects it** (ADR-0002), so a caller who selects it gets a run that
    reduces none of them and reports success. Listing an entity does not make a chain
    capable of it, and the API should not imply otherwise.
    """

    label: str
    replacement: str
    detected_at_baseline: bool


class ColumnRequest(ServiceModel):
    column: str = Field(pattern=_COLUMN_PATTERN)
    entities: tuple[Annotated[str, Field(pattern=_NAME_PATTERN)], ...] = Field(min_length=1)
    parser: str | None = Field(default=None, pattern=_NAME_PATTERN)
    provider_chain: str | None = Field(default=None, pattern=_NAME_PATTERN)
    reducer: str | None = Field(default=None, pattern=_NAME_PATTERN)
    #: Parser options, from the template's own menu (ADR-0034).
    #:
    #: **`bool` values, not `Any`.** The annotation is the guard: pydantic refuses a
    #: string, a list or a number here before the builder is reached, so a request
    #: cannot deliver a delimiter, a path or a policy name into a parser. Which
    #: *names* are permitted is the template's decision, checked by the builder —
    #: this type only fixes the shape of a value.
    parser_options: dict[Annotated[str, Field(pattern=_NAME_PATTERN)], bool] = Field(
        default_factory=dict
    )


class BuildConfigRequest(ServiceModel):
    """Pick a template, name the dataset, choose columns and entities.

    Deliberately *not* here: source, destination, `failure_mode`, `preserve_original`
    and `projection`. Each moves a privacy boundary rather than expressing a
    preference — `preserve_original_and_record_error` is ADR-0023's raw-text
    pass-through, `preserve_original: false` is the controlled replacement workflow
    `AGENTS.md` rule 4 requires a configuration to define explicitly, and `projection`
    is ADR-0024's grant boundary. They come from the template, server-side (ADR-0026
    rule 4).
    """

    template: str = Field(pattern=_NAME_PATTERN)
    dataset_name: str = Field(pattern=DATASET_NAME_PATTERN)
    row_id: str = Field(pattern=_COLUMN_PATTERN)
    columns: tuple[ColumnRequest, ...] = Field(min_length=1)
    #: Write the result to ``<configs>/datasets/<dataset_name>.yaml``. Refused when
    #: the file exists: a builder that silently replaces a configuration somebody is
    #: running is a worse failure than one that asks for a different name.
    save: bool = False


class ColumnSummary(ServiceModel):
    column: str
    output_column: str
    parser: str
    provider_chain: str
    reducer: str
    entities: tuple[str, ...]
    language_mode: str
    #: Per column, because that is where the resolved configuration puts them — and
    #: they are the two switches an operator most needs to see before triggering a
    #: run: `preserve_original_and_record_error` writes raw text into the reduced
    #: column (ADR-0023), and `preserve_original: false` is the controlled
    #: replacement workflow of `AGENTS.md` rule 4.
    failure_mode: str
    preserve_original: bool
    #: Resolved parser options, so a caller can see what a saved dataset actually
    #: does rather than what it was asked for.
    #:
    #: **`bool`, and only the options the API governs.** A dataset YAML is
    #: hand-writable and the engine types its options `Any`, so a template-side option
    #: could hold a delimiter list or an operator's free text; this field reports the
    #: governed subset, which keeps the model metadata-only by *shape* rather than by
    #: trusting a file. It also means `GET /datasets/{name}` and `POST /configs` speak
    #: the same dialect — what comes back can be sent again.
    parser_options: dict[str, bool] = Field(default_factory=dict)


class DatasetSummary(ServiceModel):
    """A configured dataset, described. Configuration values only — no data."""

    name: str
    row_id: str
    source_type: str
    destination_type: str
    projection: str
    config_hash: str
    requires_databricks: bool
    columns: tuple[ColumnSummary, ...]


class BuiltConfigResponse(ServiceModel):
    dataset: DatasetSummary
    #: The YAML the builder produced. It is a *configuration document* — names,
    #: types, entity labels and paths that came from a server-side template — and
    #: contains no data by construction, because none of its inputs can.
    config_yaml: str
    saved_path: str | None = None


class RunRequest(ServiceModel):
    """Run a dataset that already exists in the service's configuration directory.

    The caller names a dataset, not a table. Resolving what that dataset reads and
    writes is the server's job (ADR-0026 rule 4): the service runs with its own
    credentials, so a caller-supplied `catalog.schema.table` would make it a confused
    deputy for whoever called it.
    """

    dataset: str = Field(pattern=DATASET_NAME_PATTERN)
    runtime: str = Field(default="local", pattern=_NAME_PATTERN)


class RunState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunSummary(ServiceModel):
    """What a runtime reports back, converted at the boundary.

    The service never holds an engine or adapter object. ``ProcessingOutcome`` carries
    `frame` (source *and* reduced text) and `row_results` (whose fields carry the
    reduced text and a relayed error message); ``DriverRunResult`` is metadata-only
    but its type lives in the Databricks surface, which only one file in this package
    may name. So each runtime converts to *this* model and the store holds only this
    (ADR-0026 rule 3).

    The optional counters are ``None`` on the driver path, which reports rows and
    failed fields but not per-entity totals. A null is the honest answer; a zero would
    read as "none detected".
    """

    engine_run_id: str
    config_hash: str
    status: str
    rows_read: int = 0
    rows_written: int = 0
    fields_processed: int | None = None
    fields_failed: int = 0
    entities_detected: int | None = None
    entities_reduced: int | None = None
    #: Artifact name → destination. A path or table name that came from
    #: configuration, which `docs/09` allows under `destination`.
    outputs: dict[str, str] = Field(default_factory=dict)


class RunRecord(ServiceModel):
    run_id: str
    dataset: str
    runtime: str
    state: RunState
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: RunSummary | None = None
    #: Set when the run failed. A *category*, never a relayed message — and never a
    #: message from below this layer, whose text this layer cannot vouch for.
    error_category: str | None = None


class ErrorBody(ServiceModel):
    category: str
    message: str


class ErrorResponse(ServiceModel):
    error: ErrorBody


#: Compiled once; used by the contract test and by the builder's own checks.
DATASET_NAME_RE = re.compile(DATASET_NAME_PATTERN)

#: A run id is `uuid.uuid4().hex`. Bounded as a path parameter for the reason
#: above: an unbounded path segment is echoed by a 404 *and* recorded in the
#: access log, where a caller's string becomes an operator-channel string.
RUN_ID_PATTERN = r"^[0-9a-f]{32}$"

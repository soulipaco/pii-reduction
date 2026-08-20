"""Typed configuration models (``docs/06_CONFIGURATION_CONTRACT.md``).

These models validate *structure*: types, ranges, unknown keys. Cross-references
(does this chain exist? is this parser registered?) are validated by
:mod:`pii_reduction.config.loader`, which knows the file, dataset and column the
value came from and can therefore produce the actionable message the contract
requires.

Layering is project → dataset → column, more specific winning. Override models carry
``None`` for "not specified at this layer" so a merge never has to guess whether
``False`` meant "off" or "unset".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ChainSettings",
    "ColumnConfig",
    "CsvDestination",
    "CsvSource",
    "DatasetConfig",
    "DatasetIdentity",
    "DeltaTableDestination",
    "DestinationConfig",
    "EntityOverride",
    "FailureMode",
    "LanguageMode",
    "LanguageOverrides",
    "LanguageRoute",
    "LanguageSettings",
    "ObservabilitySettings",
    "ParquetDestination",
    "ParquetSource",
    "ProcessingOverrides",
    "ProcessingSettings",
    "ProjectConfig",
    "ProjectIdentity",
    "ProviderSettings",
    "ReducerSettings",
    "SourceConfig",
    "SparkTableSource",
    "ValidationSettings",
]


class ConfigModel(BaseModel):
    """Strict, immutable base: an unknown key is a typo, not an extension point."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FailureMode(StrEnum):
    FAIL_FAST = "fail_fast"
    QUARANTINE_ROW = "quarantine_row"
    PRESERVE_ORIGINAL_AND_RECORD_ERROR = "preserve_original_and_record_error"


class LanguageMode(StrEnum):
    #: Run the configured detector over eligible text.
    DETECT = "detect"
    #: Every row is the same configured language.
    STATIC = "static"
    #: Read the language from a source column.
    COLUMN = "column"


def _sorted_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


class ProjectIdentity(ConfigModel):
    name: str = Field(min_length=1)
    environment: str = Field(default="local", min_length=1)
    seed: int = 42


class ProcessingSettings(ConfigModel):
    preserve_original: bool = True
    output_suffix: str = Field(default="_pii_redacted", min_length=1)
    default_parser: str = "plain_text"
    default_reducer: str = "redact"
    default_provider_chain: str | None = None
    # Fail-closed by default (ADR-0023): an unconfigured failure mode quarantines the
    # field rather than passing raw source text into a column named "reduced".
    # `preserve_original_and_record_error` remains available as an explicit opt-in.
    failure_mode: FailureMode = FailureMode.QUARANTINE_ROW


class ProcessingOverrides(ConfigModel):
    preserve_original: bool | None = None
    output_suffix: str | None = None
    default_parser: str | None = None
    default_reducer: str | None = None
    default_provider_chain: str | None = None
    failure_mode: FailureMode | None = None


class LanguageSettings(ConfigModel):
    """Language policy plus the short-text gate of ADR-0012.

    ``min_alpha_chars`` exists because confidence alone cannot gate short text: the
    probe in session 2 had ``maria@example.com`` alone scoring ``en`` at 0.95. The
    alphabetic-character count is measured after stripping emails, URLs and digits.
    """

    mode: LanguageMode = LanguageMode.DETECT
    detector: str = "lingua"
    static_language: str | None = None
    language_column: str | None = None
    supported: tuple[str, ...] = ("en", "de", "el")
    min_chars: int = Field(default=20, ge=0)
    min_alpha_chars: int = Field(default=12, ge=0)
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    unknown_language: str = Field(default="und", min_length=2)
    fallback_chain: str | None = None

    @field_validator("supported")
    @classmethod
    def _sort_supported(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value)

    def merged(self, override: LanguageOverrides | None) -> LanguageSettings:
        """Apply a narrower layer; ``None`` fields leave the broader value alone."""
        if override is None:
            return self
        data = self.model_dump()
        data.update({k: v for k, v in override.model_dump().items() if v is not None})
        return LanguageSettings.model_validate(data)


class LanguageOverrides(ConfigModel):
    mode: LanguageMode | None = None
    detector: str | None = None
    static_language: str | None = None
    language_column: str | None = None
    supported: tuple[str, ...] | None = None
    min_chars: int | None = Field(default=None, ge=0)
    min_alpha_chars: int | None = Field(default=None, ge=0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    unknown_language: str | None = None
    fallback_chain: str | None = None


class LanguageRoute(ConfigModel):
    """One entry of ``languages.yaml``: which provider chain serves a language."""

    chain: str = Field(min_length=1)


class ObservabilitySettings(ConfigModel):
    log_level: str = "INFO"
    #: Raw text in logs is forbidden outside local debugging (``AGENTS.md`` rule 8);
    #: the loader rejects ``true`` unless ``project.environment`` is ``local``.
    log_raw_text: bool = False
    write_detection_audit: bool = True


class LeakageCheckSettings(ConfigModel):
    enabled: bool = True
    benchmark_only: bool = True


class ValidationSettings(ConfigModel):
    require_row_count_match: bool = True
    require_original_unchanged: bool = True
    require_output_columns: bool = True
    roundtrip_parser_test: bool = True
    leakage_check: LeakageCheckSettings = LeakageCheckSettings()


class EntityOverride(ConfigModel):
    """Project-level override of a taxonomy default."""

    replacement: str | None = None
    priority: int | None = None


class ProviderSettings(ConfigModel):
    """One configured provider instance.

    There is no ``threshold`` field, deliberately: Presidio's scores are recognizer
    constants, and one global threshold of 0.5 would drop every phone number
    (ADR-0005). Thresholds are per entity.
    """

    type: str = Field(min_length=1)
    languages: tuple[str, ...] | None = None
    entities: tuple[str, ...] = ()
    thresholds: dict[str, float] = Field(default_factory=dict)
    #: Provenance of the thresholds above, carried into every run's metadata as
    #: ``RunMetadata.threshold_calibration`` prefixed with this provider's name —
    #: the record describes the configured providers, not which ones a given run's
    #: chain reached. Empty means nobody has reviewed them; with no note anywhere the
    #: run records ``default_uncalibrated``, which is the honest default. NOTE: this
    #: string feeds the config fingerprint, so rewording it changes ``config_hash``
    #: — provenance prose is load-bearing (docs/06).
    calibration: str = ""
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entities")
    @classmethod
    def _sort_entities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value)

    @field_validator("thresholds")
    @classmethod
    def _check_threshold_range(cls, value: dict[str, float]) -> dict[str, float]:
        for label, threshold in value.items():
            if not 0.0 <= threshold <= 1.0:
                raise ValueError(f"threshold for {label!r} must be within [0, 1], got {threshold}")
        return value


class ChainSettings(ConfigModel):
    providers: tuple[str, ...] = Field(min_length=1)
    overlap_policy: str = "priority_score_length"


class ReducerSettings(ConfigModel):
    type: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class CsvSource(ConfigModel):
    type: Literal["csv"]
    path: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class ParquetSource(ConfigModel):
    type: Literal["parquet"]
    path: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


#: ``catalog.schema.table``, plain identifiers only. Shape validation lives here so
#: a typo fails at configuration load with a readable message rather than at the
#: first query; ``databricks.source.require_table_name`` validates again at the SQL
#: interpolation boundary, which is a security check rather than a duplicate —
#: `tests/test_databricks_adapters.py::TestTableNameShapesAgree` pins the two against
#: the same cases, including the trailing-newline one.
#:
#: The anchor differs from `databricks/source.py`'s ``\Z`` on purpose and the two
#: still agree: pydantic compiles this with the Rust regex engine, where ``$`` means
#: end of haystack, while Python's ``re`` lets ``$`` match before a final newline —
#: which is why the hand-written validator needs ``\Z`` and this one cannot use it
#: (the Rust engine rejects the escape outright).
_QUALIFIED_TABLE = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2}$"
#: ``catalog.schema`` — the table name is appended per write by the Delta adapter.
_QUALIFIED_PREFIX = r"^[A-Za-z_][A-Za-z0-9_]*$"


class SparkTableSource(ConfigModel):
    """A Unity Catalog table, read through a Spark session (ADR-0025).

    Configuration names the table; the **runtime** supplies the session. That split
    is the resolution of the open design point `docs/06_CONFIGURATION_CONTRACT.md`
    recorded: a session cannot come from a dataset file (it is not a value, and
    `sources/` may not depend on Spark — `docs/01_ARCHITECTURE.md`), so the adapter
    is constructed by `databricks.runner.run_driver`, which has one.
    """

    type: Literal["spark_table"]
    table: str = Field(min_length=1, pattern=_QUALIFIED_TABLE)
    options: dict[str, Any] = Field(default_factory=dict)


SourceConfig = Annotated[CsvSource | ParquetSource | SparkTableSource, Field(discriminator="type")]


#: What the dataset artifact contains (ADR-0024). ``full`` keeps the source
#: columns beside the reduced ones (non-destructive, AGENTS.md rule 4);
#: ``reduced_only`` drops exactly the columns configured for reduction, so the
#: written artifact can be granted to consumers who must not see the raw text of
#: the configured columns. Whether any other column carries PII is the
#: operator's scope declaration, which the projection does not override.
ProjectionMode = Literal["full", "reduced_only"]


class CsvDestination(ConfigModel):
    type: Literal["csv"]
    path: str = Field(min_length=1)
    mode: Literal["overwrite", "error"] = "overwrite"
    projection: ProjectionMode = "full"
    options: dict[str, Any] = Field(default_factory=dict)


class ParquetDestination(ConfigModel):
    type: Literal["parquet"]
    path: str = Field(min_length=1)
    mode: Literal["overwrite", "error"] = "overwrite"
    projection: ProjectionMode = "full"
    options: dict[str, Any] = Field(default_factory=dict)


class DeltaTableDestination(ConfigModel):
    """Delta tables under a ``catalog.schema`` prefix (ADR-0025).

    ``schema`` is the YAML key because that is the Unity Catalog word; the field is
    ``db_schema`` because ``schema`` shadows a ``BaseModel`` attribute and pydantic
    warns about it at class-definition time. ``populate_by_name`` keeps
    ``model_dump()`` → ``model_validate()`` round-tripping, which the distributed
    path relies on when it ships the config payload to workers.

    There is no ``table``: one prefix serves a run's reduced, audit and metrics
    tables, each named from the dataset (``<dataset>_reduced`` and friends), which is
    what keeps them in one schema by construction (`docs/07` lakehouse layout).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    type: Literal["delta_table"]
    catalog: str = Field(min_length=1, pattern=_QUALIFIED_PREFIX)
    db_schema: str = Field(alias="schema", min_length=1, pattern=_QUALIFIED_PREFIX)
    #: The Delta writer's modes, not the local file ones: ``errorifexists`` is the
    #: default everywhere and refuses to touch an existing table.
    mode: Literal["overwrite", "append", "errorifexists"] = "errorifexists"
    projection: ProjectionMode = "full"

    @property
    def prefix(self) -> str:
        """``catalog.schema`` — what ``DeltaTableOutput`` takes."""
        return f"{self.catalog}.{self.db_schema}"


DestinationConfig = Annotated[
    CsvDestination | ParquetDestination | DeltaTableDestination, Field(discriminator="type")
]


class ColumnConfig(ConfigModel):
    """Per-column policy. Every unset field falls back to the dataset/project layer."""

    process: bool = True
    parser: str | None = None
    parser_options: dict[str, Any] = Field(default_factory=dict)
    output_column: str | None = None
    entities: tuple[str, ...] | None = None
    language: LanguageOverrides | None = None
    provider_chain: str | None = None
    reducer: str | None = None

    @field_validator("entities")
    @classmethod
    def _sort_entities(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else _sorted_unique(value)


class DatasetIdentity(ConfigModel):
    name: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    source_version: str | None = None


class ProjectConfig(ConfigModel):
    """The project layer, assembled from ``project.yaml`` and its sibling files."""

    project: ProjectIdentity
    processing: ProcessingSettings = ProcessingSettings()
    language: LanguageSettings = LanguageSettings()
    observability: ObservabilitySettings = ObservabilitySettings()
    validation: ValidationSettings = ValidationSettings()
    entities: dict[str, EntityOverride] = Field(default_factory=dict)
    providers: dict[str, ProviderSettings] = Field(default_factory=dict)
    chains: dict[str, ChainSettings] = Field(default_factory=dict)
    reducers: dict[str, ReducerSettings] = Field(default_factory=dict)
    languages: dict[str, LanguageRoute] = Field(default_factory=dict)


class DatasetConfig(ConfigModel):
    """One dataset file."""

    dataset: DatasetIdentity
    source: SourceConfig
    destination: DestinationConfig
    columns: dict[str, ColumnConfig] = Field(default_factory=dict)
    processing: ProcessingOverrides | None = None
    language: LanguageOverrides | None = None

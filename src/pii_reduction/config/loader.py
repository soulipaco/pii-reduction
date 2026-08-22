"""YAML loading, layered merge, and cross-reference validation.

Structure is validated by the pydantic models; this module owns everything that
needs *context* to be actionable — which file, which dataset, which column — plus
every reference check (does this chain exist, is this parser registered).

Validation happens before processing begins, never halfway through a run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from pii_reduction.config.errors import ConfigurationError, config_context
from pii_reduction.config.models import (
    ChainSettings,
    ColumnConfig,
    DatasetConfig,
    LanguageMode,
    LanguageSettings,
    ProcessingSettings,
    ProjectConfig,
)
from pii_reduction.config.registries import (
    KNOWN_DESTINATION_TYPES,
    KNOWN_LANGUAGE_DETECTORS,
    KNOWN_OVERLAP_POLICIES,
    KNOWN_PARSER_OPTIONS,
    KNOWN_PARSERS,
    KNOWN_PROVIDER_TYPES,
    KNOWN_REDUCERS,
    KNOWN_SOURCE_TYPES,
)
from pii_reduction.config.resolved import (
    EffectiveEntity,
    ResolvedColumnPolicy,
    ResolvedDataset,
)
from pii_reduction.entities.errors import UnknownEntityLabelError
from pii_reduction.entities.taxonomy import TAXONOMY, require_known

__all__ = [
    "PROJECT_FILE",
    "load_dataset_config",
    "load_project_config",
    "load_resolved_dataset",
    "load_yaml_mapping",
    "resolve_dataset",
]

PROJECT_FILE = "project.yaml"
DATASETS_DIR = "datasets"

#: Optional sibling files and the top-level keys each may contribute (``docs/06``).
SIDE_FILES: dict[str, frozenset[str]] = {
    "entities.yaml": frozenset({"entities"}),
    "providers.yaml": frozenset({"providers", "chains", "reducers"}),
    "languages.yaml": frozenset({"languages"}),
}

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _known(names: frozenset[str]) -> str:
    return ", ".join(sorted(names))


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file that must contain a mapping (or nothing)."""
    if not path.is_file():
        raise ConfigurationError(f"configuration file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"file {str(path)!r}: invalid YAML ({exc.__class__.__name__})"
        ) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigurationError(
            f"file {str(path)!r}: expected a YAML mapping at the top level, "
            f"got {type(loaded).__name__}"
        )
    return loaded


def _format_validation_error(exc: ValidationError) -> str:
    """Render pydantic errors as ``field.path: message``, without echoing input values."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "<root>"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def _validate_model(model_cls: type[_ModelT], data: dict[str, Any], *, context: str) -> _ModelT:
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(f"{context}{_format_validation_error(exc)}") from exc


def _require_entity_label(label: str, *, context: str) -> str:
    try:
        return require_known(label, context=context.rstrip(": ") or None)
    except UnknownEntityLabelError as exc:
        raise ConfigurationError(str(exc)) from exc


def _check_source_type(
    raw: dict[str, Any], *, key: str, known: frozenset[str], context: str
) -> None:
    """Give unknown source/destination types a readable message before pydantic sees them."""
    section = raw.get(key)
    if isinstance(section, dict):
        declared = section.get("type")
        if isinstance(declared, str) and declared not in known:
            raise ConfigurationError(
                f"{context}{key} type {declared!r} is not registered (known: {_known(known)})"
            )


def load_project_config(path: Path) -> ProjectConfig:
    """Load the project layer.

    ``path`` may be ``configs/`` (``project.yaml`` plus optional ``entities.yaml``,
    ``providers.yaml``, ``languages.yaml``) or a single project file.
    """
    project_path = path / PROJECT_FILE if path.is_dir() else path
    data = load_yaml_mapping(project_path)

    if path.is_dir():
        for filename, allowed_keys in SIDE_FILES.items():
            side_path = path / filename
            if not side_path.is_file():
                continue
            side_data = load_yaml_mapping(side_path)
            unexpected = sorted(set(side_data) - allowed_keys)
            if unexpected:
                raise ConfigurationError(
                    f"file {str(side_path)!r}: unexpected top-level keys "
                    f"{', '.join(unexpected)} (allowed: {_known(allowed_keys)})"
                )
            duplicated = sorted(set(side_data) & set(data))
            if duplicated:
                raise ConfigurationError(
                    f"file {str(side_path)!r}: keys {', '.join(duplicated)} are already "
                    f"defined in {PROJECT_FILE}; define each section in exactly one file"
                )
            data.update(side_data)

    context = config_context(path=str(project_path))
    _check_global_threshold(data, context=context)
    project = _validate_model(ProjectConfig, data, context=context)
    _validate_project(project, context=context)
    return project


def _check_global_threshold(data: dict[str, Any], *, context: str) -> None:
    """Reject the tempting global ``threshold:`` key with the reason, not a schema error.

    A single threshold of 0.5 silently drops every phone number, because Presidio's
    PhoneRecognizer emits a constant 0.40 (ADR-0005).
    """
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return
    for name, settings in providers.items():
        if isinstance(settings, dict) and "threshold" in settings:
            raise ConfigurationError(
                f"{context}provider {name!r}: 'threshold' is not supported. Provider scores are "
                "recognizer constants, not calibrated probabilities, so a global threshold is "
                "forbidden (ADR-0005). Use per-entity 'thresholds', e.g. "
                "thresholds: {PHONE: 0.3, EMAIL: 0.6, PERSON: 0.5}"
            )


def _validate_language(settings: LanguageSettings, *, context: str) -> None:
    if settings.detector not in KNOWN_LANGUAGE_DETECTORS:
        raise ConfigurationError(
            f"{context}language detector {settings.detector!r} is not registered "
            f"(known: {_known(KNOWN_LANGUAGE_DETECTORS)})"
        )
    if settings.mode is LanguageMode.STATIC and not settings.static_language:
        raise ConfigurationError(
            f"{context}language mode 'static' requires 'static_language' (e.g. static_language: en)"
        )
    if settings.mode is LanguageMode.COLUMN and not settings.language_column:
        raise ConfigurationError(
            f"{context}language mode 'column' requires 'language_column' naming the source column"
        )
    if settings.mode is LanguageMode.DETECT and settings.detector == "none":
        raise ConfigurationError(
            f"{context}language mode 'detect' requires a detector; got 'none'. "
            "Use mode 'static' or 'column' when no detector is available"
        )
    if settings.unknown_language in settings.supported:
        raise ConfigurationError(
            f"{context}unknown_language {settings.unknown_language!r} must not also be listed "
            "as a supported language"
        )


def _validate_processing(processing: ProcessingSettings, *, context: str) -> None:
    if processing.default_parser not in KNOWN_PARSERS:
        raise ConfigurationError(
            f"{context}parser {processing.default_parser!r} is not registered "
            f"(known: {_known(KNOWN_PARSERS)})"
        )
    if processing.default_reducer not in KNOWN_REDUCERS:
        raise ConfigurationError(
            f"{context}reducer {processing.default_reducer!r} is not registered "
            f"(known: {_known(KNOWN_REDUCERS)})"
        )


def _validate_project(project: ProjectConfig, *, context: str) -> None:
    for name, provider in project.providers.items():
        provider_context = f"{context}provider {name!r}: "
        if provider.type not in KNOWN_PROVIDER_TYPES:
            raise ConfigurationError(
                f"{provider_context}type {provider.type!r} is not registered "
                f"(known: {_known(KNOWN_PROVIDER_TYPES)})"
            )
        for label in provider.entities:
            _require_entity_label(label, context=provider_context)
        for label in provider.thresholds:
            _require_entity_label(label, context=f"{provider_context}threshold ")

    for name, chain in project.chains.items():
        chain_context = f"{context}chain {name!r}: "
        _validate_chain(chain, providers=set(project.providers), context=chain_context)

    for name, reducer in project.reducers.items():
        if reducer.type not in KNOWN_REDUCERS:
            raise ConfigurationError(
                f"{context}reducer {name!r}: type {reducer.type!r} is not registered "
                f"(known: {_known(KNOWN_REDUCERS)})"
            )

    for label in project.entities:
        _require_entity_label(label, context=f"{context}entity override ")

    for code, route in project.languages.items():
        if route.chain not in project.chains:
            raise ConfigurationError(
                f"{context}language {code!r}: provider chain {route.chain!r} is not defined "
                f"(defined: {_known(frozenset(project.chains))})"
            )

    _validate_processing(project.processing, context=context)
    _validate_language(project.language, context=context)

    for field_name, chain_name in (
        ("processing.default_provider_chain", project.processing.default_provider_chain),
        ("language.fallback_chain", project.language.fallback_chain),
    ):
        if chain_name is not None and chain_name not in project.chains:
            raise ConfigurationError(
                f"{context}{field_name}: provider chain {chain_name!r} is not defined "
                f"(defined: {_known(frozenset(project.chains))})"
            )

    if project.observability.log_raw_text and project.project.environment != "local":
        raise ConfigurationError(
            f"{context}observability.log_raw_text may only be enabled when "
            f"project.environment is 'local'; got {project.project.environment!r}"
        )


def _validate_chain(chain: ChainSettings, *, providers: set[str], context: str) -> None:
    missing = [name for name in chain.providers if name not in providers]
    if missing:
        raise ConfigurationError(
            f"{context}providers {', '.join(missing)} are not defined "
            f"(defined: {_known(frozenset(providers))})"
        )
    if chain.overlap_policy not in KNOWN_OVERLAP_POLICIES:
        raise ConfigurationError(
            f"{context}overlap_policy {chain.overlap_policy!r} is not registered "
            f"(known: {_known(KNOWN_OVERLAP_POLICIES)})"
        )


def load_dataset_config(path: Path) -> DatasetConfig:
    """Load one dataset file."""
    data = load_yaml_mapping(path)
    context = config_context(path=str(path))
    _check_source_type(data, key="source", known=KNOWN_SOURCE_TYPES, context=context)
    _check_source_type(data, key="destination", known=KNOWN_DESTINATION_TYPES, context=context)
    return _validate_model(DatasetConfig, data, context=context)


def _effective_processing(project: ProjectConfig, dataset: DatasetConfig) -> ProcessingSettings:
    data = project.processing.model_dump()
    if dataset.processing is not None:
        data.update({k: v for k, v in dataset.processing.model_dump().items() if v is not None})
    return ProcessingSettings.model_validate(data)


def _resolve_column(
    name: str,
    column: ColumnConfig,
    *,
    project: ProjectConfig,
    dataset: DatasetConfig,
    processing: ProcessingSettings,
    context: str,
) -> ResolvedColumnPolicy:
    parser = column.parser or processing.default_parser
    if parser not in KNOWN_PARSERS:
        raise ConfigurationError(
            f"{context}parser {parser!r} is not registered (known: {_known(KNOWN_PARSERS)})"
        )

    reducer = column.reducer or processing.default_reducer
    if reducer not in KNOWN_REDUCERS:
        raise ConfigurationError(
            f"{context}reducer {reducer!r} is not registered (known: {_known(KNOWN_REDUCERS)})"
        )

    if not column.entities:
        raise ConfigurationError(
            f"{context}no entities configured. Entity scope is never inferred "
            f"(AGENTS.md rule 7); list them explicitly, e.g. entities: [EMAIL, PHONE]"
        )
    entities = tuple(_require_entity_label(label, context=context) for label in column.entities)

    chain_name = column.provider_chain or processing.default_provider_chain
    if chain_name is None:
        raise ConfigurationError(
            f"{context}no provider chain configured and no processing.default_provider_chain is set"
        )
    chain = project.chains.get(chain_name)
    if chain is None:
        raise ConfigurationError(
            f"{context}provider chain {chain_name!r} is not defined "
            f"(defined: {_known(frozenset(project.chains))})"
        )

    # A parser option the parser does not know is refused **here**, not when the
    # pipeline constructs the parser (ADR-0034). Before this check a typo in a
    # dataset YAML survived every validation the config layer performs and surfaced
    # as a `ParserError` after the source had been resolved — on the Databricks path,
    # after a Spark session existed. `describe`, `run`, the driver and the service all
    # reach this function, so all four gain the check at once.
    unknown_options = sorted(set(column.parser_options) - KNOWN_PARSER_OPTIONS.get(parser, set()))
    if unknown_options:
        raise ConfigurationError(
            f"{context}parser {parser!r} has no parser_option(s) "
            f"{', '.join(unknown_options)} "
            f"(known: {_known(KNOWN_PARSER_OPTIONS.get(parser, frozenset()))})"
        )

    language = project.language.merged(dataset.language).merged(column.language)
    _validate_language(language, context=context)

    output_column = column.output_column or f"{name}{processing.output_suffix}"
    if processing.preserve_original and output_column == name:
        raise ConfigurationError(
            f"{context}output_column {output_column!r} would overwrite the source column while "
            "processing.preserve_original is true (AGENTS.md rule 4)"
        )

    return ResolvedColumnPolicy(
        column=name,
        parser=parser,
        parser_options=dict(column.parser_options),
        output_column=output_column,
        entities=entities,
        language=language,
        provider_chain=chain_name,
        providers=chain.providers,
        overlap_policy=chain.overlap_policy,
        reducer=reducer,
        failure_mode=processing.failure_mode,
        preserve_original=processing.preserve_original,
    )


def _effective_entities(project: ProjectConfig) -> dict[str, EffectiveEntity]:
    effective: dict[str, EffectiveEntity] = {}
    for label, definition in TAXONOMY.items():
        override = project.entities.get(label)
        effective[label] = EffectiveEntity(
            label=label,
            replacement=(
                override.replacement
                if override and override.replacement
                else definition.replacement
            ),
            priority=(
                override.priority
                if override and override.priority is not None
                else definition.priority
            ),
        )
    return effective


def resolve_dataset(dataset: DatasetConfig, project: ProjectConfig) -> ResolvedDataset:
    """Apply the project → dataset → column layering and validate every reference."""
    dataset_name = dataset.dataset.name
    processing = _effective_processing(project, dataset)

    policies: list[ResolvedColumnPolicy] = []
    for name, column in dataset.columns.items():
        if not column.process:
            continue
        context = config_context(dataset=dataset_name, column=name)
        policies.append(
            _resolve_column(
                name,
                column,
                project=project,
                dataset=dataset,
                processing=processing,
                context=context,
            )
        )

    dataset_context = config_context(dataset=dataset_name)
    if not policies:
        raise ConfigurationError(
            f"{dataset_context}no columns are configured for processing "
            "(every column is missing or has process: false)"
        )

    seen_outputs: dict[str, str] = {}
    source_columns = set(dataset.columns)
    for policy in policies:
        if policy.output_column in source_columns and policy.output_column != policy.column:
            raise ConfigurationError(
                f"{config_context(dataset=dataset_name, column=policy.column)}output_column "
                f"{policy.output_column!r} collides with another configured source column"
            )
        previous = seen_outputs.get(policy.output_column)
        if previous is not None:
            raise ConfigurationError(
                f"{dataset_context}columns {previous!r} and {policy.column!r} both write to "
                f"output column {policy.output_column!r}"
            )
        seen_outputs[policy.output_column] = policy.column

    if getattr(dataset.destination, "projection", "full") == "reduced_only":
        # ADR-0024: the projection drops the configured source columns. Under the
        # rule-4 replacement workflow the source column IS the reduced column, so
        # the projection would silently drop the reduction output itself — refuse
        # the confused combination (replacement mode already yields a raw-free
        # artifact and needs no projection).
        replaced = [policy.column for policy in policies if policy.output_column == policy.column]
        if replaced:
            raise ConfigurationError(
                f"{dataset_context}destination.projection 'reduced_only' cannot be combined "
                f"with in-place replacement (column {replaced[0]!r} writes to itself): the "
                "projection would drop the reduced text. Replacement mode already produces "
                "an artifact without raw text (ADR-0024)"
            )

    return ResolvedDataset(
        project=project.project,
        dataset=dataset.dataset,
        source=dataset.source,
        destination=dataset.destination,
        columns=tuple(policies),
        entities=_effective_entities(project),
        providers=dict(project.providers),
        chains=dict(project.chains),
        reducers=dict(project.reducers),
        languages=dict(project.languages),
        observability=project.observability,
        validation=project.validation,
    )


def load_resolved_dataset(configs_dir: Path, dataset_name: str) -> ResolvedDataset:
    """Load ``configs/project.yaml`` + ``configs/datasets/<name>.yaml`` and resolve them."""
    project = load_project_config(configs_dir)
    dataset_path = configs_dir / DATASETS_DIR / f"{dataset_name}.yaml"
    if not dataset_path.is_file():
        available = sorted(p.stem for p in (configs_dir / DATASETS_DIR).glob("*.yaml"))
        raise ConfigurationError(
            f"dataset {dataset_name!r} not found at {dataset_path} "
            f"(available: {', '.join(available) if available else 'none'})"
        )
    dataset = load_dataset_config(dataset_path)
    return resolve_dataset(dataset, project)

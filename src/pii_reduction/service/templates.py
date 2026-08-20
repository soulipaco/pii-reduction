"""Server-side dataset templates: the half of a configuration a caller may not choose.

A template is the answer to "pick a source" that does not hand a caller the ability
to name one. It declares, server-side:

* the source and destination — so a request can never point the service's credentials
  at a table the caller could not read, or land output where they could
  (`docs/09`, *Choosing where data is read from and written to*);
* the privacy switches — `failure_mode`, `preserve_original`, `projection` — which
  move a boundary rather than express a preference (ADR-0026 rule 4);
* the menu the caller *does* choose from: which columns, which entity labels, which
  parsers, chains and reducers are on offer for this source.

Templates live in one YAML file beside `project.yaml`, so adding one is an ordinary
reviewed configuration change made by whoever operates the service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from pii_reduction.config import known_labels
from pii_reduction.config.errors import ConfigurationError
from pii_reduction.config.loader import load_yaml_mapping
from pii_reduction.config.models import (
    DestinationConfig,
    LanguageOverrides,
    ProcessingOverrides,
    SourceConfig,
)
from pii_reduction.config.registries import KNOWN_PARSERS, KNOWN_REDUCERS
from pii_reduction.service.catalog import requires_databricks

__all__ = [
    "TEMPLATES_FILE",
    "DatasetTemplate",
    "check_template_chains",
    "load_templates",
]

TEMPLATES_FILE = "service_templates.yaml"


def _all_known(value: tuple[str, ...], known: frozenset[str], *, what: str) -> tuple[str, ...]:
    """Refuse an unregistered name at load, not at the first caller who picks it.

    Silently intersecting with the registry — which an earlier draft did — turns a
    typo into an empty menu and an "available: (none)" message pointing at the
    caller. The operator wrote the template; the operator should get the error.
    """
    unknown = sorted(set(value) - known)
    if unknown:
        raise ValueError(
            f"unknown {what}(s) {', '.join(unknown)}; known: {', '.join(sorted(known))}"
        )
    return value


class DatasetTemplate(BaseModel):
    """One offer: a fixed source and destination, plus the choices left open."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    source: SourceConfig
    destination: DestinationConfig
    #: The column menu. Declared rather than discovered: the service does not read
    #: the source to find out (ADR-0026 forbids a preview endpoint, and `sources/`
    #: has no schema-only path).
    columns: tuple[str, ...] = Field(min_length=1)
    #: Which of those columns may serve as the row identifier. Empty means any of
    #: them, which is the common case for a single-key table.
    row_id_columns: tuple[str, ...] = ()
    #: Entity labels on offer. Empty means the whole taxonomy.
    entities: tuple[str, ...] = ()
    parsers: tuple[str, ...] = tuple(sorted(KNOWN_PARSERS))
    #: Chain names, checked against the project configuration at **startup** by
    #: `service.api.create_app` — this model cannot do it, because a chain is
    #: defined in `providers.yaml` and a template does not hold the project layer.
    #: Empty means every chain the project defines.
    provider_chains: tuple[str, ...] = ()
    reducers: tuple[str, ...] = tuple(sorted(KNOWN_REDUCERS))
    #: Server-side privacy switches. A caller cannot reach these.
    processing: ProcessingOverrides | None = None
    language: LanguageOverrides | None = None

    @field_validator("parsers")
    @classmethod
    def _known_parsers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _all_known(value, KNOWN_PARSERS, what="parser")

    @field_validator("reducers")
    @classmethod
    def _known_reducers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _all_known(value, KNOWN_REDUCERS, what="reducer")

    @field_validator("entities")
    @classmethod
    def _known_entities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _all_known(value, known_labels(), what="entity label")

    @property
    def requires_databricks(self) -> bool:
        """True when running this template needs a Spark session."""
        return requires_databricks(self.source.type, self.destination.type)

    def offered_row_id_columns(self) -> tuple[str, ...]:
        return self.row_id_columns or self.columns

    def offered_parsers(self) -> tuple[str, ...]:
        return tuple(sorted(self.parsers))

    def offered_reducers(self) -> tuple[str, ...]:
        return tuple(sorted(self.reducers))


def check_template_chains(
    templates: dict[str, DatasetTemplate], project_chains: tuple[str, ...]
) -> None:
    """Refuse a template advertising a chain the project configuration lacks.

    Lives here rather than in `api.py` because it is configuration validation and
    needs no framework: `load_templates` cannot do it (a chain is defined in
    `providers.yaml`, which a template does not hold), but every caller of
    `load_templates` should be able to apply it — including one that never installs
    the `service` extra.

    Without it the menu is a promise the builder cannot keep: `GET /templates` lists
    the chain, and the caller who picks it gets a 400 naming a mistake the *operator*
    made. Startup is where an operator's error belongs.
    """
    for name, template in sorted(templates.items()):
        unknown = sorted(set(template.provider_chains) - set(project_chains))
        if unknown:
            raise ConfigurationError(
                f"service template {name!r}: provider chain(s) {', '.join(unknown)} "
                f"are not defined by the project configuration "
                f"(defined: {', '.join(project_chains) or 'none'})"
            )


def load_templates(configs_dir: Path) -> dict[str, DatasetTemplate]:
    """Load ``<configs_dir>/service_templates.yaml``.

    A missing file is not an error — a service can be started against a
    configuration directory that offers no builder, and `GET /templates` then
    answers with an empty list rather than a stack trace. A *malformed* file is an
    error, and it is raised at startup rather than at the first request, which is the
    same rule the config loader follows.
    """
    path = configs_dir / TEMPLATES_FILE
    if not path.is_file():
        return {}
    raw = load_yaml_mapping(path)
    section = raw.get("templates", {})
    if not isinstance(section, dict):
        raise ConfigurationError(
            f"file {str(path)!r}: 'templates' must be a mapping of name to template, "
            f"got {type(section).__name__}"
        )
    templates: dict[str, DatasetTemplate] = {}
    for name, body in section.items():
        if not isinstance(body, dict):
            raise ConfigurationError(
                f"file {str(path)!r}: template {name!r} must be a mapping, "
                f"got {type(body).__name__}"
            )
        payload: dict[str, Any] = {"name": str(name), **body}
        try:
            templates[str(name)] = DatasetTemplate.model_validate(payload)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
                for error in exc.errors()
            )
            raise ConfigurationError(
                f"file {str(path)!r}: template {name!r} is invalid ({details})"
            ) from exc
    return templates

"""The normalized entity taxonomy (``docs/04_PII_ENGINE.md``).

This is the single central definition of which entity labels exist, what they are
replaced with by default, and how they rank when spans collide. Provider-native
labels never appear here — each provider adapter owns its own mapping table into
this taxonomy (ADR-0004).

``ADDRESS`` is part of the taxonomy but no shipped provider claims it at v0.1: no
permissively-licensed model probed emits an address-shaped label, and composing one
from ``LOC``/``GPE`` failed on probe examples (ADR-0002). It stays here so
configuration, fixtures and the benchmark schema are ready for the Phase 7 provider
that can actually detect it.

Priority ordering follows ``docs/04``: EMAIL/PHONE > ADDRESS > PERSON. Higher number
wins. Priorities and replacements are defaults; ``entities.yaml`` may override them
per project (``docs/06_CONFIGURATION_CONTRACT.md``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pii_reduction.contracts.labels import NORMALIZED_LABEL_PATTERN
from pii_reduction.entities.errors import UnknownEntityLabelError

__all__ = [
    "ADDRESS",
    "EMAIL",
    "PERSON",
    "PHONE",
    "TAXONOMY",
    "EntityDefinition",
    "default_priority",
    "default_replacement",
    "is_known",
    "known_labels",
    "require_known",
]

PERSON = "PERSON"
EMAIL = "EMAIL"
PHONE = "PHONE"
ADDRESS = "ADDRESS"

_LABEL_RE = re.compile(NORMALIZED_LABEL_PATTERN)


@dataclass(frozen=True)
class EntityDefinition:
    """Static definition of one normalized entity type."""

    label: str
    replacement: str
    priority: int
    description: str
    detected_at_baseline: bool = True


TAXONOMY: Mapping[str, EntityDefinition] = MappingProxyType(
    {
        EMAIL: EntityDefinition(
            label=EMAIL,
            replacement="<EMAIL>",
            priority=100,
            description="Email address. Deterministic recognizer at baseline.",
        ),
        PHONE: EntityDefinition(
            label=PHONE,
            replacement="<PHONE>",
            priority=90,
            description="Telephone number. Deterministic recognizer at baseline.",
        ),
        ADDRESS: EntityDefinition(
            label=ADDRESS,
            replacement="<ADDRESS>",
            priority=60,
            description="Postal address. No provider claims it at v0.1 (ADR-0002).",
            detected_at_baseline=False,
        ),
        PERSON: EntityDefinition(
            label=PERSON,
            replacement="<PERSON>",
            priority=50,
            description="Person name. Requires an NLP provider (Increment B).",
        ),
    }
)


def known_labels() -> frozenset[str]:
    """Every label in the normalized taxonomy."""
    return frozenset(TAXONOMY)


def is_known(label: str) -> bool:
    return label in TAXONOMY


def require_known(label: str, *, context: str | None = None) -> str:
    """Return ``label`` if it is in the taxonomy, else raise with an actionable message."""
    if label in TAXONOMY:
        return label
    prefix = f"{context}: " if context else ""
    if not _LABEL_RE.match(label):
        raise UnknownEntityLabelError(
            f"{prefix}entity label {label!r} is not normalized "
            "(expected upper snake case, e.g. 'PERSON')"
        )
    raise UnknownEntityLabelError(
        f"{prefix}entity label {label!r} is not in the taxonomy "
        f"(known: {', '.join(sorted(TAXONOMY))})"
    )


def default_replacement(label: str) -> str:
    return TAXONOMY[require_known(label)].replacement


def default_priority(label: str) -> int:
    return TAXONOMY[require_known(label)].priority

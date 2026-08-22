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
    "line_bounded_labels",
    "markup_guarded_labels",
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
    #: Does this entity have a machine-checkable grammar of its own?
    #:
    #: A static fact about the surface, like ``surface_may_span_lines``. A string that
    #: matches the email or phone grammar *is* one, whatever surrounds it — so the
    #: markup guard (ADR-0027) never touches those spans: dropping one would be a leak,
    #: which is strictly worse than the over-redaction the guard exists to prevent.
    #: PERSON and ADDRESS are model-inferred and carry no such grammar.
    format_defined: bool = False
    #: May a single instance of this entity legitimately span more than one line?
    #:
    #: A static fact about the surface, not a policy: a person's name never contains a
    #: line break, a postal address written across several lines is still one address.
    #: Providers use it to trim spans an NER model ran through a break (ADR-0016), so
    #: the answer lives here rather than being restated per layer.
    surface_may_span_lines: bool = True


TAXONOMY: Mapping[str, EntityDefinition] = MappingProxyType(
    {
        EMAIL: EntityDefinition(
            label=EMAIL,
            replacement="<EMAIL>",
            priority=100,
            description="Email address. Deterministic recognizer at baseline.",
            format_defined=True,
            surface_may_span_lines=False,
        ),
        PHONE: EntityDefinition(
            label=PHONE,
            replacement="<PHONE>",
            priority=90,
            description="Telephone number. Deterministic recognizer at baseline.",
            format_defined=True,
            surface_may_span_lines=False,
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
            surface_may_span_lines=False,
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


def line_bounded_labels() -> frozenset[str]:
    """Labels whose surface cannot contain a line break.

    One definition, read by the provider boundary (which trims such spans) and by
    anything else that needs the fact. ``ADDRESS`` is absent: a postal address written
    across several lines is one address, and trimming it would cut a real entity.
    """
    return frozenset(
        label for label, definition in TAXONOMY.items() if not definition.surface_may_span_lines
    )


def markup_guarded_labels() -> frozenset[str]:
    """Labels the markup guard may clip (ADR-0027).

    The complement of ``format_defined``: EMAIL and PHONE are exempt because a string
    matching their grammar is that thing regardless of the tag beside it, and clipping
    one would leak an address the run was asked to remove. One definition, read by the
    provider boundary, for the same reason as :func:`line_bounded_labels`.
    """
    return frozenset(
        label for label, definition in TAXONOMY.items() if not definition.format_defined
    )


def default_priority(label: str) -> int:
    return TAXONOMY[require_known(label)].priority

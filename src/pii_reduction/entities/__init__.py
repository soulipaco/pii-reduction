"""Normalized entity taxonomy and the label-mapping machinery providers plug into."""

from pii_reduction.entities.errors import LabelMappingError, UnknownEntityLabelError
from pii_reduction.entities.mapping import DropCounter, LabelMapping
from pii_reduction.entities.reconcile import (
    ReconciliationPolicy,
    ReconciliationResult,
    RejectedMatch,
    reconcile,
)
from pii_reduction.entities.taxonomy import (
    ADDRESS,
    EMAIL,
    PERSON,
    PHONE,
    TAXONOMY,
    EntityDefinition,
    default_priority,
    default_replacement,
    is_known,
    known_labels,
    require_known,
)

__all__ = [
    "ADDRESS",
    "EMAIL",
    "PERSON",
    "PHONE",
    "TAXONOMY",
    "DropCounter",
    "EntityDefinition",
    "LabelMapping",
    "LabelMappingError",
    "ReconciliationPolicy",
    "ReconciliationResult",
    "RejectedMatch",
    "UnknownEntityLabelError",
    "default_priority",
    "default_replacement",
    "is_known",
    "known_labels",
    "reconcile",
    "require_known",
]

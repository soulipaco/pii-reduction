"""Core contracts shared by every layer.

This package imports nothing else from ``pii_reduction``: it is the hub the
dependency direction in ``docs/01_ARCHITECTURE.md`` points at.
"""

from pii_reduction.contracts.entities import EntityMatch, ResolvedEntity
from pii_reduction.contracts.errors import PiiReductionError, SpanContractError
from pii_reduction.contracts.labels import NORMALIZED_LABEL_PATTERN, NormalizedLabel
from pii_reduction.contracts.language import UNKNOWN_LANGUAGE, LanguageResult
from pii_reduction.contracts.reduction import ReductionOperation
from pii_reduction.contracts.results import (
    ProcessedFieldResult,
    ProcessingStatus,
    RecordContext,
    RowResult,
    RunMetadata,
)
from pii_reduction.contracts.segments import TextSegment
from pii_reduction.contracts.spans import Span

__all__ = [
    "NORMALIZED_LABEL_PATTERN",
    "UNKNOWN_LANGUAGE",
    "EntityMatch",
    "LanguageResult",
    "NormalizedLabel",
    "PiiReductionError",
    "ProcessedFieldResult",
    "ProcessingStatus",
    "RecordContext",
    "ReductionOperation",
    "ResolvedEntity",
    "RowResult",
    "RunMetadata",
    "Span",
    "SpanContractError",
    "TextSegment",
]

"""Row, field and run result contracts (``docs/03_DATA_CONTRACTS.md`` sections 2, 9-11).

Partial failure must stay visible: a field that fell back to its original text is a
different outcome from a field that was processed cleanly, and both are different
from a row that failed. That distinction is what ``ProcessingStatus`` encodes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from pii_reduction.contracts.base import FrozenModel

__all__ = [
    "ProcessedFieldResult",
    "ProcessingStatus",
    "RecordContext",
    "RowResult",
    "RunMetadata",
]


class ProcessingStatus(StrEnum):
    """Outcome of processing a field or a row."""

    SUCCESS = "success"
    SUCCESS_WITH_FALLBACK = "success_with_fallback"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    SKIPPED = "skipped"


class RecordContext(FrozenModel):
    """Identity of one source row. ``row_id`` is not assumed to be PII."""

    dataset: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    source_version: str | None = None


class ProcessedFieldResult(FrozenModel):
    """Result of processing one configured column of one row.

    ``output_text`` is the reduced text. The original is not duplicated here — it
    stays on the source row (``docs/03`` §9) and is preserved unchanged
    (``AGENTS.md`` rule 4).
    """

    original_column: str = Field(min_length=1)
    output_column: str = Field(min_length=1)
    output_text: str | None
    parser: str = Field(min_length=1)
    provider_chain: tuple[str, ...] = ()
    language_summary: dict[str, int] = Field(default_factory=dict)
    entity_counts: dict[str, int] = Field(default_factory=dict)
    entities_detected: int = Field(default=0, ge=0)
    entities_reduced: int = Field(default=0, ge=0)
    status: ProcessingStatus = ProcessingStatus.SUCCESS
    error_category: str | None = None
    error: str | None = None


class RowResult(FrozenModel):
    """Result of processing one row across all its configured columns."""

    dataset: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    field_results: tuple[ProcessedFieldResult, ...] = ()
    processing_ms: float = Field(default=0.0, ge=0.0)
    status: ProcessingStatus = ProcessingStatus.SUCCESS
    error_category: str | None = None


class RunMetadata(FrozenModel):
    """Run-level record (``docs/03`` §11).

    ``config_hash`` is the configuration fingerprint
    (:func:`pii_reduction.config.fingerprint.config_fingerprint`), which is what ties
    a benchmark number back to the exact settings that produced it.
    """

    run_id: str = Field(min_length=1)
    pipeline_version: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    source_dataset: str = Field(min_length=1)
    source_version: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    status: ProcessingStatus = ProcessingStatus.SUCCESS
    provider_versions: dict[str, str] = Field(default_factory=dict)
    language_detector_version: str | None = None
    rows_read: int = Field(default=0, ge=0)
    rows_written: int = Field(default=0, ge=0)
    fields_processed: int = Field(default=0, ge=0)
    fields_failed: int = Field(default=0, ge=0)
    entities_detected: int = Field(default=0, ge=0)
    entities_reduced: int = Field(default=0, ge=0)
    dropped_labels: dict[str, int] = Field(default_factory=dict)
    threshold_calibration: str = "default_uncalibrated"

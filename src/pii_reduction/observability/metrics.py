"""Run-metrics accumulation.

Everything here is metadata: counts, categories, timings, distributions. No text and
no detected values, so the metrics file is safe to commit to a benchmark history or
attach to a ticket (``docs/03_DATA_CONTRACTS.md`` §11, ``AGENTS.md`` rule 8).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pii_reduction.contracts.results import ProcessingStatus, RunMetadata

__all__ = ["RunMetricsAccumulator"]


@dataclass
class RunMetricsAccumulator:
    """Collects run-level counters and renders the run record."""

    run_id: str
    pipeline_version: str
    config_hash: str
    source_dataset: str
    source_version: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    rows_read: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    fields_processed: int = 0
    fields_failed: int = 0
    #: Fields that succeeded only via a parser or language fallback. Visible in the
    #: run status so "it worked" and "it worked, but" are not the same report.
    fields_with_fallback: int = 0
    entities_detected: int = 0
    entities_reduced: int = 0
    processing_ms: float = 0.0

    entity_counts: Counter[str] = field(default_factory=Counter)
    language_counts: Counter[str] = field(default_factory=Counter)
    parser_fallbacks: Counter[str] = field(default_factory=Counter)
    rejections: Counter[str] = field(default_factory=Counter)
    dropped_labels: Counter[str] = field(default_factory=Counter)
    error_categories: Counter[str] = field(default_factory=Counter)
    row_statuses: Counter[str] = field(default_factory=Counter)

    provider_versions: dict[str, str] = field(default_factory=dict)
    language_detector_version: str | None = None
    pseudonymization_key_id: str | None = None
    threshold_calibration: str = "default_uncalibrated"
    reduction_strategies: Counter[str] = field(default_factory=Counter)

    def record_language(self, language: str, *, fallback_used: bool) -> None:
        self.language_counts[language] += 1
        if fallback_used:
            self.language_counts["_fallback"] += 1

    def record_fallbacks(self, reasons: tuple[str, ...]) -> None:
        for reason in reasons:
            self.parser_fallbacks[reason] += 1

    def record_rejections(self, counts: dict[str, int]) -> None:
        for reason, count in counts.items():
            self.rejections[reason] += count

    def status(self) -> ProcessingStatus:
        if self.fields_failed and self.fields_processed == 0:
            return ProcessingStatus.FAILED
        if self.fields_failed:
            return ProcessingStatus.PARTIAL_FAILURE
        if self.fields_with_fallback:
            return ProcessingStatus.SUCCESS_WITH_FALLBACK
        return ProcessingStatus.SUCCESS

    def build(self, *, completed_at: datetime | None = None) -> RunMetadata:
        return RunMetadata(
            run_id=self.run_id,
            pipeline_version=self.pipeline_version,
            config_hash=self.config_hash,
            source_dataset=self.source_dataset,
            source_version=self.source_version,
            started_at=self.started_at,
            completed_at=completed_at or datetime.now(UTC),
            status=self.status(),
            provider_versions=dict(self.provider_versions),
            language_detector_version=self.language_detector_version,
            pseudonymization_key_id=self.pseudonymization_key_id,
            rows_read=self.rows_read,
            rows_written=self.rows_written,
            fields_processed=self.fields_processed,
            fields_failed=self.fields_failed,
            entities_detected=self.entities_detected,
            entities_reduced=self.entities_reduced,
            dropped_labels=dict(self.dropped_labels),
            threshold_calibration=self.threshold_calibration,
        )

    def detail(self) -> dict[str, Any]:
        """Distributions that sit alongside the run record in the metrics file."""
        return {
            "rows_skipped": self.rows_skipped,
            "fields_with_fallback": self.fields_with_fallback,
            "processing_ms": round(self.processing_ms, 3),
            "entity_counts": dict(self.entity_counts),
            "language_counts": dict(self.language_counts),
            "parser_fallbacks": dict(self.parser_fallbacks),
            "reconciliation_rejections": dict(self.rejections),
            "error_categories": dict(self.error_categories),
            "row_statuses": dict(self.row_statuses),
            "reduction_strategies": dict(self.reduction_strategies),
        }

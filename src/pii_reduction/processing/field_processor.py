"""One configured column of one row, end to end.

parse → resolve language → detect → reconcile → reduce → reconstruct.

Each stage is an injected collaborator, so this module contains sequencing and
failure handling and no domain logic of its own. That is deliberate: it is the place
most likely to accumulate "just one special case", and the architecture depends on it
staying thin (``docs/01_ARCHITECTURE.md``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.contracts.language import LanguageResult
from pii_reduction.contracts.results import ProcessedFieldResult, ProcessingStatus
from pii_reduction.entities.reconcile import ReconciliationPolicy, reconcile
from pii_reduction.language.base import LanguageResolver
from pii_reduction.parsers.base import BaseParser
from pii_reduction.providers.base import BaseProvider
from pii_reduction.reducers.base import BaseReducer

__all__ = ["FieldOutcome", "FieldProcessor"]


@dataclass(frozen=True)
class FieldOutcome:
    """Result plus the observability by-products of processing one field."""

    result: ProcessedFieldResult
    language: LanguageResult | None = None
    audit: tuple[dict[str, Any], ...] = ()
    fallbacks: tuple[str, ...] = ()
    rejections: dict[str, int] = field(default_factory=dict)


@dataclass
class FieldProcessor:
    """Sequences the pipeline stages for one column."""

    column: str
    output_column: str
    parser: BaseParser
    resolver: LanguageResolver
    providers: Sequence[BaseProvider]
    reducer: BaseReducer
    entities: frozenset[str]
    policy: ReconciliationPolicy

    def process(
        self,
        value: object,
        *,
        row: Mapping[str, Any],
        run_id: str,
        row_id: str,
    ) -> FieldOutcome:
        """Process one cell. Null in, null out (``docs/03_DATA_CONTRACTS.md`` §18)."""
        if _is_null(value):
            return FieldOutcome(result=self._skipped(None))
        text = str(value)

        parsed = self.parser.parse(text)
        language = self.resolver.resolve(text, row=row)

        transformed: dict[str, str] = {}
        audit: list[dict[str, Any]] = []
        rejections: dict[str, int] = {}
        detected = 0
        reduced = 0
        entity_counts: dict[str, int] = {}

        for segment in parsed.processable_segments:
            if not segment.text:
                continue
            matches = []
            for provider in self.providers:
                matches.extend(
                    provider.detect(
                        segment.text,
                        language=language.language,
                        entities=self.entities,
                    )
                )
            detected += len(matches)

            resolution = reconcile(matches, policy=self.policy)
            for reason, count in resolution.rejection_counts().items():
                rejections[reason] = rejections.get(reason, 0) + count
            if not resolution.entities:
                continue

            reduction = self.reducer.reduce(segment.text, list(resolution.entities))
            transformed[segment.segment_id] = reduction.text
            reduced += len(reduction.operations)
            for label, count in reduction.entity_counts.items():
                entity_counts[label] = entity_counts.get(label, 0) + count
            audit.extend(
                self._audit_rows(
                    resolution.entities,
                    segment_id=segment.segment_id,
                    segment_start=segment.source_start or 0,
                    language=language.language,
                    run_id=run_id,
                    row_id=row_id,
                )
            )

        output_text = self.parser.reconstruct(parsed, transformed)
        status = (
            ProcessingStatus.SUCCESS_WITH_FALLBACK
            if parsed.fallback_used or language.fallback_used
            else ProcessingStatus.SUCCESS
        )
        result = ProcessedFieldResult(
            original_column=self.column,
            output_column=self.output_column,
            output_text=output_text,
            parser=self.parser.name,
            provider_chain=tuple(provider.name for provider in self.providers),
            language_summary={language.language: 1},
            entity_counts=entity_counts,
            entities_detected=detected,
            entities_reduced=reduced,
            status=status,
        )
        return FieldOutcome(
            result=result,
            language=language,
            audit=tuple(audit),
            fallbacks=parsed.fallbacks,
            rejections=rejections,
        )

    def _skipped(self, output_text: str | None) -> ProcessedFieldResult:
        return ProcessedFieldResult(
            original_column=self.column,
            output_column=self.output_column,
            output_text=output_text,
            parser=self.parser.name,
            provider_chain=tuple(provider.name for provider in self.providers),
            status=ProcessingStatus.SKIPPED,
        )

    def failed(self, *, error_category: str, error: str | None) -> ProcessedFieldResult:
        """Build the result recorded when a field fails under the configured policy."""
        return ProcessedFieldResult(
            original_column=self.column,
            output_column=self.output_column,
            output_text=None,
            parser=self.parser.name,
            provider_chain=tuple(provider.name for provider in self.providers),
            status=ProcessingStatus.FAILED,
            error_category=error_category,
            error=error,
        )

    def _audit_rows(
        self,
        entities: Sequence[ResolvedEntity],
        *,
        segment_id: str,
        segment_start: int,
        language: str,
        run_id: str,
        row_id: str,
    ) -> list[dict[str, Any]]:
        """Privacy-safe span metadata (``docs/03_DATA_CONTRACTS.md`` §12).

        Offsets, labels, scores and provenance — never the matched text.

        ``start``/``end`` are **field-relative**: a segment-relative offset would be
        unusable next to ground truth, which is measured against the whole document.
        ``segment_start`` is kept so a span can still be traced back to its segment.
        """
        rows = []
        for entity in entities:
            supporting = entity.supporting_matches
            rows.append(
                {
                    "run_id": run_id,
                    "row_id": row_id,
                    "column_name": self.column,
                    "segment_id": segment_id,
                    "segment_start": segment_start,
                    "entity_type": entity.entity_type,
                    "start": segment_start + entity.start,
                    "end": segment_start + entity.end,
                    "score": entity.score,
                    "provider": entity.selected_provider,
                    "recognizer": supporting[0].recognizer if supporting else None,
                    "language": language,
                    "resolution_rule": entity.resolution_rule,
                }
            )
        return rows


def _is_null(value: object) -> bool:
    """``None`` and pandas' float NaN both mean "no value here"."""
    if value is None:
        return True
    return isinstance(value, float) and value != value

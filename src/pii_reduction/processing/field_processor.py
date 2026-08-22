"""One configured column of one row, end to end.

parse → resolve language → route to a provider chain → detect → reconcile → reduce →
reconstruct.

Each stage is an injected collaborator, so this module contains sequencing and
failure handling and no domain logic of its own. That is deliberate: it is the place
most likely to accumulate "just one special case", and the architecture depends on it
staying thin (``docs/01_ARCHITECTURE.md``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pii_reduction.contracts.entities import EntityMatch, ResolvedEntity
from pii_reduction.contracts.language import LanguageResult
from pii_reduction.contracts.results import ProcessedFieldResult, ProcessingStatus
from pii_reduction.entities.reconcile import ReconciliationPolicy, reconcile
from pii_reduction.language.base import LanguageResolver
from pii_reduction.parsers.base import BaseParser
from pii_reduction.providers.base import BaseProvider
from pii_reduction.reducers.base import BaseReducer

__all__ = ["AUDIT_COLUMNS", "FieldOutcome", "FieldProcessor", "ProviderChain"]

#: The complete audit-row schema, in emission order. Public because the Delta output
#: path needs to write a schema-stable empty audit table when a run detects nothing,
#: and the parity test asserts the written table carries exactly these columns —
#: an exact set rather than a denylist, so a future field carrying raw text under a
#: new name cannot slip past the metadata-only guarantee (AGENTS.md rule 8).
AUDIT_COLUMNS = (
    "run_id",
    "row_id",
    "column_name",
    "segment_id",
    "segment_start",
    "entity_type",
    "start",
    "end",
    "score",
    "provider",
    "recognizer",
    "language",
    "resolution_rule",
)


@dataclass(frozen=True)
class ProviderChain:
    """A named set of providers plus the policy for reconciling their output.

    ``entity_scopes`` and ``language_scopes`` carry the per-provider narrowing from
    configuration (``docs/06_CONFIGURATION_CONTRACT.md``, provider configuration).
    They are enforced here rather than trusted to each adapter: a provider declared as
    ``entities: [PERSON]`` that still returns EMAIL is exactly the silent scope drift
    ``AGENTS.md`` rule 7 forbids, in the direction of doing more than configured.
    """

    name: str
    providers: tuple[BaseProvider, ...]
    policy: ReconciliationPolicy
    #: Provider name to its configured entity scope. Absent means "no narrowing".
    entity_scopes: Mapping[str, frozenset[str]] = field(default_factory=dict)
    #: Provider name to its configured languages. Absent means "any language".
    language_scopes: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def entities_for(self, provider_name: str, requested: frozenset[str]) -> frozenset[str]:
        configured = self.entity_scopes.get(provider_name)
        return requested if configured is None else requested & configured

    def serves_language(self, provider_name: str, language: str) -> bool:
        configured = self.language_scopes.get(provider_name)
        return configured is None or language in configured


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
    reducer: BaseReducer
    entities: frozenset[str]
    #: Used when the resolved language has no explicit route.
    default_chain: ProviderChain
    #: Language code to chain, from the ``languages:`` configuration block.
    routing: Mapping[str, ProviderChain] = field(default_factory=dict)
    #: Used when the language is unknown or unsupported. Defaults to the default
    #: chain when configuration names no safe fallback.
    fallback_chain: ProviderChain | None = None

    @property
    def providers(self) -> tuple[BaseProvider, ...]:
        """Every provider this column can use, for metrics collection."""
        chains = [self.default_chain, *self.routing.values()]
        if self.fallback_chain is not None:
            chains.append(self.fallback_chain)
        seen: dict[int, BaseProvider] = {}
        for chain in chains:
            for provider in chain.providers:
                seen.setdefault(id(provider), provider)
        return tuple(seen.values())

    def chain_for(self, language: LanguageResult) -> ProviderChain:
        """Route to a provider chain (``docs/04_PII_ENGINE.md``, provider routing).

        An unknown or unsupported language takes the safe fallback chain rather than
        a guess: running an English NER model over text of unknown language is how
        false positives are manufactured.
        """
        if not language.supported:
            return self.fallback_chain or self.default_chain
        return self.routing.get(language.language, self.default_chain)

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

        # Language is resolved from eligible text only: transcript timestamps and
        # speaker names are structure, and feeding them to a detector biases it
        # toward whatever language the metadata happens to look like
        # (``AGENTS.md``, language detector).
        eligible = "\n".join(segment.text for segment in parsed.processable_segments)
        language = self.resolver.resolve(eligible or text, row=row)
        chain = self.chain_for(language)

        transformed: dict[str, str] = {}
        audit: list[dict[str, Any]] = []
        rejections: dict[str, int] = {}
        detected = 0
        reduced = 0
        entity_counts: dict[str, int] = {}

        # **One detection call per provider per row, not per segment** (ADR-0033).
        # A provider with native batching gets the row's whole segment list in one
        # call; the default implementation still loops, so nothing changes for a
        # provider that has no batch path. The batch is single-language by
        # construction — `language` is resolved once above, for the row — which is
        # what lets the Presidio adapter hand it straight to `analyze_iterator`.
        #
        # Batching *across rows* is deliberately not done: it would move detection
        # outside the per-row try/except that ADR-0023's `quarantine_row` depends on,
        # so one bad row would take its whole batch with it.
        segments = [segment for segment in parsed.processable_segments if segment.text]
        segment_texts = [segment.text for segment in segments]
        by_segment: list[list[EntityMatch]] = [[] for _ in segments]
        for provider in chain.providers:
            scope = chain.entities_for(provider.name, self.entities)
            if not scope or not chain.serves_language(provider.name, language.language):
                continue
            # `strict=True` because a misaligned result is the worst outcome available
            # here: spans computed on one segment applied to another would leave the
            # real entity in cleartext *and* destroy unrelated text at those offsets.
            # `BaseProvider.detect_batch` already checks the hook's result count, but
            # nothing forbids a provider from overriding the public method instead, so
            # the call site refuses to trust it silently.
            for accumulated, found in zip(
                by_segment,
                provider.detect_batch(
                    segment_texts,
                    languages=[language.language] * len(segment_texts),
                    entities=scope,
                ),
                strict=True,
            ):
                accumulated.extend(found)

        for segment, matches in zip(segments, by_segment, strict=True):
            detected += len(matches)

            resolution = reconcile(matches, policy=chain.policy, text=segment.text)
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
            provider_chain=(chain.name, *(provider.name for provider in chain.providers)),
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
            provider_chain=(self.default_chain.name,),
            status=ProcessingStatus.SKIPPED,
        )

    def failed(self, *, error_category: str, error: str | None) -> ProcessedFieldResult:
        """Build the result recorded when a field fails under the configured policy."""
        return ProcessedFieldResult(
            original_column=self.column,
            output_column=self.output_column,
            output_text=None,
            parser=self.parser.name,
            provider_chain=(self.default_chain.name,),
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

"""Contract invariants (``docs/03_DATA_CONTRACTS.md``)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pii_reduction.contracts import (
    UNKNOWN_LANGUAGE,
    EntityMatch,
    LanguageResult,
    ProcessedFieldResult,
    ProcessingStatus,
    ReductionOperation,
    ResolvedEntity,
    Span,
    SpanContractError,
    TextSegment,
)

pytestmark = pytest.mark.unit

GREEK_TEXT = "Το email μου είναι maria.papadopoulou@example.com"


class TestSpan:
    def test_valid_span_reports_length_and_slice(self) -> None:
        span = Span(start=19, end=len(GREEK_TEXT))
        assert span.length == len(GREEK_TEXT) - 19
        assert span.slice_of(GREEK_TEXT) == "maria.papadopoulou@example.com"

    @pytest.mark.parametrize(("start", "end"), [(-1, 5), (5, 5), (6, 5), (0, 0)])
    def test_invalid_offsets_are_rejected(self, start: int, end: int) -> None:
        with pytest.raises(ValidationError):
            Span(start=start, end=end)

    def test_span_past_end_of_text_raises_span_contract_error(self) -> None:
        span = Span(start=0, end=10)
        with pytest.raises(SpanContractError) as exc_info:
            span.validate_within("short")
        assert "length 5" in str(exc_info.value)

    def test_span_contract_error_never_echoes_the_text(self) -> None:
        span = Span(start=0, end=99)
        with pytest.raises(SpanContractError) as exc_info:
            span.slice_of(GREEK_TEXT)
        assert "maria.papadopoulou@example.com" not in str(exc_info.value)

    def test_offsets_are_codepoints_not_bytes(self) -> None:
        # The Greek prefix is longer in UTF-8 bytes than in codepoints; the contract
        # is codepoint-based (ADR-0011), so the slice must still be the email.
        start = GREEK_TEXT.index("maria")
        assert len(GREEK_TEXT.encode("utf-8")) > len(GREEK_TEXT)
        assert Span(start=start, end=len(GREEK_TEXT)).slice_of(GREEK_TEXT).startswith("maria")

    def test_overlap_detection_is_half_open(self) -> None:
        assert Span(start=0, end=5).overlaps(Span(start=4, end=9))
        assert not Span(start=0, end=5).overlaps(Span(start=5, end=9))

    def test_spans_are_immutable(self) -> None:
        span = Span(start=0, end=1)
        with pytest.raises(ValidationError):
            span.start = 2  # type: ignore[misc]


class TestEntityMatch:
    def test_normalized_label_is_required(self) -> None:
        match = EntityMatch(start=0, end=5, entity_type="EMAIL", provider="deterministic")
        assert match.entity_type == "EMAIL"

    @pytest.mark.parametrize("label", ["email", "Person", "EMAIL_ADDRESS ", "1EMAIL", ""])
    def test_non_normalized_labels_are_rejected(self, label: str) -> None:
        with pytest.raises(ValidationError):
            EntityMatch(start=0, end=5, entity_type=label, provider="deterministic")

    def test_provider_native_shaped_labels_still_need_the_taxonomy_check(self) -> None:
        # Shape validation alone cannot catch this: EMAIL_ADDRESS *looks* normalized.
        # Membership is entities.taxonomy's job (see test_entities.py).
        match = EntityMatch(start=0, end=5, entity_type="EMAIL_ADDRESS", provider="presidio")
        assert match.entity_type == "EMAIL_ADDRESS"

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EntityMatch(
                start=0,
                end=5,
                entity_type="EMAIL",
                provider="deterministic",
                matched_text="maria@example.com",  # type: ignore[call-arg]
            )

    def test_match_carries_no_surface_text_field(self) -> None:
        assert "text" not in EntityMatch.model_fields
        assert "matched_text" not in EntityMatch.model_fields


class TestResolvedEntity:
    def test_from_match_keeps_provenance(self) -> None:
        match = EntityMatch(
            start=3, end=9, entity_type="PHONE", provider="deterministic", score=1.0
        )
        resolved = ResolvedEntity.from_match(match, resolution_rule="single_candidate")
        assert (resolved.start, resolved.end) == (3, 9)
        assert resolved.selected_provider == "deterministic"
        assert resolved.supporting_matches == (match,)
        assert resolved.resolution_rule == "single_candidate"


class TestTextSegment:
    def test_segment_with_consistent_source_offsets(self) -> None:
        segment = TextSegment(
            segment_id="turn_0001_body",
            ordinal=1,
            text=" Hello",
            processable=True,
            segment_type="transcript_body",
            source_start=10,
            source_end=16,
        )
        assert segment.metadata == {}

    def test_source_offsets_must_match_text_length(self) -> None:
        with pytest.raises(ValidationError):
            TextSegment(
                segment_id="s",
                ordinal=0,
                text="abc",
                processable=True,
                segment_type="plain_text",
                source_start=0,
                source_end=99,
            )

    def test_source_offsets_must_be_set_together(self) -> None:
        with pytest.raises(ValidationError):
            TextSegment(
                segment_id="s",
                ordinal=0,
                text="abc",
                processable=True,
                segment_type="plain_text",
                source_start=0,
            )

    def test_empty_segment_is_allowed(self) -> None:
        segment = TextSegment(
            segment_id="turn_0002_body",
            ordinal=2,
            text="",
            processable=True,
            segment_type="transcript_body",
            source_start=5,
            source_end=5,
        )
        assert segment.text == ""


class TestLanguageResult:
    def test_unknown_language_cannot_be_supported(self) -> None:
        with pytest.raises(ValidationError):
            LanguageResult(
                language=UNKNOWN_LANGUAGE, detector="lingua", supported=True, confidence=0.9
            )

    def test_unknown_language_is_explicit(self) -> None:
        result = LanguageResult(
            language=UNKNOWN_LANGUAGE,
            detector="lingua",
            supported=False,
            fallback_used=True,
            reason="below_min_alpha_chars",
        )
        assert result.is_unknown
        assert result.confidence is None

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_confidence_must_be_a_probability(self, confidence: float) -> None:
        with pytest.raises(ValidationError):
            LanguageResult(language="en", detector="lingua", supported=True, confidence=confidence)


class TestReductionAndResults:
    def test_reduction_operation_records_offsets_and_strategy(self) -> None:
        operation = ReductionOperation(
            start=12, end=29, entity_type="PHONE", replacement="<PHONE>", strategy="redact"
        )
        assert operation.length == 17
        assert "original" not in ReductionOperation.model_fields

    def test_field_result_defaults_to_success(self) -> None:
        result = ProcessedFieldResult(
            original_column="body",
            output_column="body_pii_redacted",
            output_text="Contact <EMAIL>",
            parser="plain_text",
            provider_chain=("deterministic",),
            entity_counts={"EMAIL": 1},
            entities_detected=1,
            entities_reduced=1,
        )
        assert result.status is ProcessingStatus.SUCCESS

    def test_null_input_is_representable_as_null_output(self) -> None:
        result = ProcessedFieldResult(
            original_column="body",
            output_column="body_pii_redacted",
            output_text=None,
            parser="plain_text",
            status=ProcessingStatus.SKIPPED,
        )
        assert result.output_text is None

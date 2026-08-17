"""Evaluation math, against hand-computed cases (``docs/10_TESTING_QA.md`` §8)."""

from __future__ import annotations

import pytest

from pii_reduction.evaluation import (
    RELAXED,
    STRICT,
    MetricRow,
    Prediction,
    TruthSpan,
    detection_metrics,
    detection_metrics_by,
    iou,
    leakage_metrics,
    match_spans,
    over_redaction_metrics,
    precision_recall_f1,
    render_markdown,
    render_table,
)

pytestmark = pytest.mark.unit

DOC = "doc_0001"


def truth(entity_type: str, start: int, end: int, *, entity_id: str = "e0", **kwargs: object):  # type: ignore[no-untyped-def]
    return TruthSpan(
        document_id=kwargs.pop("document_id", DOC),  # type: ignore[arg-type]
        entity_id=entity_id,
        entity_type=entity_type,
        start=start,
        end=end,
        **kwargs,  # type: ignore[arg-type]
    )


def prediction(entity_type: str, start: int, end: int, *, document_id: str = DOC):  # type: ignore[no-untyped-def]
    return Prediction(
        document_id=document_id, entity_type=entity_type, start=start, end=end, provider="p"
    )


DOC_TRUTHS = [truth("PERSON", 0, 10, entity_id="e0"), truth("EMAIL", 20, 40, entity_id="e1")]
DOC_PREDICTIONS = [prediction("PERSON", 0, 10), prediction("PHONE", 20, 40)]

# Language and tier belong to a document, so each language lives in its own document,
# exactly as the generated corpus does.
SLICE_TRUTHS = [
    truth("EMAIL", 0, 10, entity_id="a", language="en", difficulty_tier=1),
    truth("PERSON", 40, 50, entity_id="c", language="en", difficulty_tier=1),
    truth(
        "EMAIL",
        20,
        30,
        entity_id="b",
        language="en",
        difficulty_tier=2,
        document_id="doc_0002",
    ),
    truth(
        "PERSON",
        0,
        10,
        entity_id="d",
        language="el",
        difficulty_tier=1,
        document_id="doc_0003",
    ),
]

LEAK_TRUTHS = [
    truth("EMAIL", 0, 17, entity_id="a"),
    truth("PERSON", 30, 41, entity_id="b", document_id="doc_0002"),
]
LEAK_SURFACES = {"a": "maria@example.com", "b": "Maria Rossi"}


class TestDocumentedExample:
    """The exact case in ``docs/10_TESTING_QA.md`` §8.

    Ground truth PERSON [0,10], EMAIL [20,40]; predictions PERSON [0,10], PHONE [20,40].
    Expected: PERSON TP = 1, EMAIL FN = 1, PHONE FP = 1.
    """

    def test_overall_counts(self) -> None:
        metric = detection_metrics(DOC_TRUTHS, DOC_PREDICTIONS)
        assert (metric.true_positives, metric.false_positives, metric.false_negatives) == (1, 1, 1)

    def test_per_entity_counts(self) -> None:
        by_entity = detection_metrics_by(DOC_TRUTHS, DOC_PREDICTIONS, dimensions=("entity_type",))
        assert by_entity[("PERSON",)].true_positives == 1
        assert by_entity[("EMAIL",)].false_negatives == 1
        assert by_entity[("PHONE",)].false_positives == 1

    def test_precision_recall_f1(self) -> None:
        metric = detection_metrics(DOC_TRUTHS, DOC_PREDICTIONS)
        assert metric.precision == 0.5
        assert metric.recall == 0.5
        assert metric.f1 == 0.5
        assert metric.support == 2


class TestStrictMatching:
    def test_exact_match_counts_once(self) -> None:
        result = match_spans([truth("EMAIL", 5, 15)], [prediction("EMAIL", 5, 15)], mode=STRICT)
        assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 0, 0)

    def test_one_character_boundary_error_is_a_miss(self) -> None:
        result = match_spans([truth("EMAIL", 5, 15)], [prediction("EMAIL", 5, 16)], mode=STRICT)
        assert (result.true_positives, result.false_negatives, result.false_positives) == (0, 1, 1)

    def test_right_span_wrong_type_is_a_miss_and_a_false_positive(self) -> None:
        result = match_spans([truth("EMAIL", 5, 15)], [prediction("PHONE", 5, 15)], mode=STRICT)
        assert (result.false_negatives, result.false_positives) == (1, 1)

    def test_spans_in_other_documents_do_not_match(self) -> None:
        result = match_spans(
            [truth("EMAIL", 5, 15)],
            [prediction("EMAIL", 5, 15, document_id="doc_0002")],
            mode=STRICT,
        )
        assert (result.true_positives, result.false_positives) == (0, 1)

    def test_duplicate_predictions_produce_one_match_and_one_false_positive(self) -> None:
        result = match_spans(
            [truth("EMAIL", 5, 15)],
            [prediction("EMAIL", 5, 15), prediction("EMAIL", 5, 15)],
            mode=STRICT,
        )
        assert (result.true_positives, result.false_positives) == (1, 1)

    def test_no_predictions_means_all_missed(self) -> None:
        result = match_spans([truth("EMAIL", 5, 15)], [], mode=STRICT)
        assert result.false_negatives == 1


class TestRelaxedMatching:
    def test_iou_is_computed_over_half_open_ranges(self) -> None:
        assert iou(0, 10, 0, 10) == 1.0
        assert iou(0, 10, 10, 20) == 0.0
        assert iou(0, 10, 5, 15) == pytest.approx(5 / 15)

    def test_overlapping_span_matches_when_iou_clears_the_threshold(self) -> None:
        # The Greek boundary case from the session-2 probe: the model swallowed the
        # preceding verb, covering the name but failing strict matching.
        strict = match_spans([truth("PERSON", 11, 30)], [prediction("PERSON", 0, 30)], mode=STRICT)
        relaxed = match_spans(
            [truth("PERSON", 11, 30)], [prediction("PERSON", 0, 30)], mode=RELAXED
        )
        assert strict.true_positives == 0
        assert relaxed.true_positives == 1

    def test_small_overlap_still_fails(self) -> None:
        result = match_spans([truth("PERSON", 0, 10)], [prediction("PERSON", 8, 40)], mode=RELAXED)
        assert result.true_positives == 0

    def test_best_overlap_wins_and_predictions_are_used_once(self) -> None:
        truths = [truth("PERSON", 0, 10, entity_id="a"), truth("PERSON", 0, 20, entity_id="b")]
        result = match_spans(truths, [prediction("PERSON", 0, 10)], mode=RELAXED)
        assert result.true_positives == 1
        assert result.matched[0][0].entity_id == "a"

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            match_spans([], [], mode="fuzzy")


class TestSlicing:
    def test_support_counts_are_reported_per_slice(self) -> None:
        sliced = detection_metrics_by(
            SLICE_TRUTHS, [prediction("EMAIL", 0, 10)], dimensions=("entity_type", "language")
        )
        assert sliced[("EMAIL", "en")].support == 2
        assert sliced[("EMAIL", "en")].recall == 0.5  # one of the two en emails found
        assert sliced[("PERSON", "el")].support == 1
        assert sliced[("PERSON", "el")].recall == 0.0

    def test_an_entity_with_no_predictions_still_appears(self) -> None:
        sliced = detection_metrics_by(SLICE_TRUTHS, [], dimensions=("entity_type",))
        assert set(sliced) == {("EMAIL",), ("PERSON",)}
        assert all(metric.recall == 0.0 for metric in sliced.values())

    def test_empty_input_yields_zero_not_an_error(self) -> None:
        metric = detection_metrics([], [])
        assert (metric.precision, metric.recall, metric.f1, metric.support) == (0.0, 0.0, 0.0, 0)

    def test_precision_recall_f1_helper_matches_the_metric(self) -> None:
        assert precision_recall_f1(1, 1, 1) == (0.5, 0.5, 0.5)


class TestLeakage:
    def test_removed_values_do_not_leak(self) -> None:
        reduced = {"doc_0001": "<EMAIL> ...", "doc_0002": "... <PERSON> ..."}
        metric = leakage_metrics(LEAK_TRUTHS, reduced, LEAK_SURFACES)
        assert metric.leaked == 0
        assert metric.rate == 0.0
        assert metric.document_clean_rate == 1.0

    def test_a_surviving_value_leaks(self) -> None:
        reduced = {"doc_0001": "maria@example.com ...", "doc_0002": "... <PERSON> ..."}
        metric = leakage_metrics(LEAK_TRUTHS, reduced, LEAK_SURFACES)
        assert metric.leaked == 1
        assert metric.rate == 0.5
        assert metric.document_clean_rate == 0.5

    def test_a_missing_document_counts_as_leaked(self) -> None:
        metric = leakage_metrics(LEAK_TRUTHS, {"doc_0001": "<EMAIL>"}, LEAK_SURFACES)
        assert metric.leaked == 1

    def test_strategy_is_recorded_because_mask_leakage_is_not_comparable(self) -> None:
        # ADR-0013 §5: masking retains part of the value by design.
        metric = leakage_metrics(LEAK_TRUTHS, {}, LEAK_SURFACES, strategy="mask")
        assert metric.strategy == "mask"


class TestOverRedaction:
    def test_surviving_tokens_score_zero(self) -> None:
        metric = over_redaction_metrics(
            [("doc_0001", "INC00128492", "ticket")], {"doc_0001": "Ticket INC00128492 closed"}
        )
        assert metric.rate == 0.0
        assert metric.total == 1

    def test_a_removed_token_is_over_redaction(self) -> None:
        metric = over_redaction_metrics(
            [("doc_0001", "INC00128492", "ticket")], {"doc_0001": "Ticket <PHONE> closed"}
        )
        assert metric.rate == 1.0
        assert metric.modified_kinds == ("ticket",)

    def test_no_protected_tokens_is_zero_not_an_error(self) -> None:
        assert over_redaction_metrics([], {}).rate == 0.0


class TestReport:
    rows = (
        MetricRow(
            benchmark_run_id="run",
            provider="deterministic_only",
            language="*",
            entity_type="EMAIL",
            document_type="*",
            difficulty_tier="*",
            metric_name="strict_recall",
            metric_value=1.0,
            support=51,
        ),
    )

    def test_table_shows_values_and_support(self) -> None:
        rendered = render_table(self.rows, title="benchmark")
        assert "benchmark" in rendered
        assert "strict_recall" in rendered
        assert "1.000" in rendered
        assert "51" in rendered

    def test_markdown_is_a_table(self) -> None:
        rendered = render_markdown(self.rows, title="benchmark")
        assert rendered.startswith("## benchmark")
        assert "| EMAIL |" in rendered

    def test_empty_rows_say_so(self) -> None:
        assert "(no metrics)" in render_table([])

"""ADR-0028: separating "the detector missed it" from "the detector never saw it".

Default tier. The decomposition is offset arithmetic over a committed corpus and the
chain it is measured on here is the model-free one, so it runs on every push.

**This adds a metric; it moves no published number.** Every gate in
`configs/benchmark_gates.yaml` and `configs/incident_gates.yaml` passed unchanged
before and after — the reachability rows are additive and no gate reads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pii_reduction.benchmark import run_benchmark
from pii_reduction.evaluation.matching import TruthSpan
from pii_reduction.evaluation.metrics import is_reachable, reachability_metrics

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def truth(start: int, end: int, document_id: str = "doc_1") -> TruthSpan:
    return TruthSpan(
        document_id=document_id,
        entity_id=f"e_{start}_{end}",
        entity_type="PERSON",
        start=start,
        end=end,
        language="en",
        difficulty_tier=1,
    )


class TestThePredicate:
    def test_a_span_inside_a_processable_range_is_reachable(self) -> None:
        assert is_reachable(truth(12, 20), [(10, 30)])

    def test_a_span_in_preserved_structure_is_not(self) -> None:
        assert not is_reachable(truth(2, 8), [(10, 30)])

    def test_a_span_straddling_a_segment_boundary_is_not(self) -> None:
        # A provider is handed the segments separately, so it never sees the whole
        # surface. Calling that reachable would credit an opportunity nobody had.
        assert not is_reachable(truth(25, 35), [(10, 30), (31, 50)])

    def test_a_span_touching_both_ends_of_a_range_is(self) -> None:
        assert is_reachable(truth(10, 30), [(10, 30)])

    def test_a_document_with_no_processable_range_has_nothing_reachable(self) -> None:
        assert not is_reachable(truth(0, 5), [])


class TestTheMetric:
    def test_it_splits_the_truth(self) -> None:
        metric = reachability_metrics(
            [truth(12, 20), truth(2, 8), truth(21, 25)], {"doc_1": [(10, 30)]}
        )
        assert (metric.reachable, metric.unreachable, metric.total) == (2, 1, 3)
        assert metric.unreachable_rate == pytest.approx(1 / 3)

    def test_a_document_the_caller_could_not_parse_counts_as_unreachable(self) -> None:
        # Asserting the opposite would claim an opportunity nobody can point to.
        metric = reachability_metrics([truth(0, 4, "missing")], {})
        assert (metric.reachable, metric.unreachable) == (0, 1)

    def test_an_empty_truth_set_reports_zero_rather_than_raising(self) -> None:
        metric = reachability_metrics([], {})
        assert (metric.total, metric.unreachable_rate) == (0, 0.0)


class TestItRefusesToGuess:
    def test_a_frame_without_the_columns_it_needs_raises(self) -> None:
        """ "Found nothing" must not be reachable by accident.

        Without a text column every lookup returns nothing, every entity is classified
        unreachable, and the run reports a plausible number that is entirely wrong.
        """
        import pandas as pd

        from pii_reduction.benchmark import _eligible_ranges

        with pytest.raises(KeyError, match="silent wrong answer"):
            _eligible_ranges("plain_text", {}, pd.DataFrame({"document_id": ["d1"]}))


class TestTheBenchmarkCorpusIsFullyReachable:
    """The property the injector maintains: entities are placed at `eligible_offsets`,
    so every one of them is inside a processable segment. If this ever fails, the
    corpus and the parser configuration have drifted apart and every recall number on
    it silently became a blend."""

    def test_nothing_is_unreachable(self) -> None:
        outcome = run_benchmark(
            corpus_dir=REPO_ROOT / "tests" / "fixtures" / "corpus",
            configs_dir=REPO_ROOT / "configs",
        )
        assert outcome.reachability.unreachable == 0
        assert outcome.reachable_strict.recall == outcome.strict.recall


@pytest.fixture(scope="module")
def incident_outcome():  # type: ignore[no-untyped-def]
    """The model-free run over the incident corpus, built once for the class below."""
    return run_benchmark(
        corpus_dir=REPO_ROOT / "tests" / "fixtures" / "incidents",
        configs_dir=REPO_ROOT / "configs",
    )


class TestTheIncidentCorpusIsNot:
    """The finding this metric exists to make visible (ADR-0022, ADR-0028).

    The tier-4 work notes put the author's name in the speaker prefix, which
    `TranscriptParser` marks as structure. 90 of 315 ground-truth entities therefore
    reach no provider, and the corpus's PERSON tier-4 recall of 0.000 is a *scope*
    consequence with an open design question behind it (the speaker-prefix ADR), not a
    detection result. Before this metric, nothing in the metric grain said so.
    """

    def test_the_unreachable_share_is_what_the_speaker_prefixes_hold(  # type: ignore[no-untyped-def]
        self, incident_outcome
    ) -> None:
        reachability = incident_outcome.reachability
        assert (reachability.unreachable, reachability.total) == (90, 315)
        assert incident_outcome.reachability.unreachable_rate == pytest.approx(0.286, abs=0.001)

    def test_recall_over_what_was_offered_is_far_higher(self, incident_outcome) -> None:  # type: ignore[no-untyped-def]
        # Model-free chain: EMAIL and PHONE are all it can find, and it finds all of
        # them. The gap between these two numbers is the whole point of the metric.
        assert incident_outcome.strict.recall == pytest.approx(0.571, abs=0.001)
        assert incident_outcome.reachable_strict.recall == pytest.approx(0.800, abs=0.001)
        assert incident_outcome.reachable_strict.support == 225

    def test_both_rows_reach_the_metric_grain(self, incident_outcome) -> None:  # type: ignore[no-untyped-def]
        names = {
            row.metric_name: row.metric_value
            for row in incident_outcome.rows
            if (row.language, row.entity_type, row.document_type, row.difficulty_tier)
            == ("*", "*", "*", "*")
        }
        assert names["unreachable_entity_rate"] == pytest.approx(0.286, abs=0.001)
        assert names["reachable_strict_recall"] == pytest.approx(0.800, abs=0.001)

    def test_the_summary_says_so_in_words(self, incident_outcome) -> None:  # type: ignore[no-untyped-def]
        from pii_reduction.benchmark import summarise

        summary = summarise(incident_outcome)
        assert "unreachable entities=90/315" in summary
        # Metadata only: a summary is a display surface (AGENTS.md rule 8).
        assert "@" not in summary

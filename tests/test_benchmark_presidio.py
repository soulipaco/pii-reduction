"""Increment B's exit criterion: the same benchmark, two chains, compared.

Marked ``integration`` — it loads three spaCy models. Run with ``pytest -m integration``.

These assertions are floors taken from a measured baseline, not aspirations. They
exist so a regression in the provider chain is caught by a failing test rather than
by someone re-reading a table.
"""

from __future__ import annotations

import pytest

from pii_reduction.benchmark import BenchmarkOutcome, run_benchmark
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.evaluation import detection_metrics_by
from tests.test_benchmark import CONFIGS_DIR, CORPUS_DIR, _truths

pytestmark = [pytest.mark.integration, pytest.mark.slow]

pytest.importorskip("presidio_analyzer", reason="needs the 'presidio' extra")

#: Floors from the Increment B baseline (see .claude/SESSION_HANDOFF.md).
MIN_PERSON_RECALL_OVERALL = 0.55
MIN_PERSON_RECALL_EN_DE = 0.80
MIN_DOCUMENT_CLEAN_RATE = 0.70


@pytest.fixture(scope="module")
def deterministic() -> BenchmarkOutcome:
    return run_benchmark(
        corpus_dir=CORPUS_DIR,
        configs_dir=CONFIGS_DIR,
        provider_chain="deterministic_only",
        benchmark_run_id="bench_det",
    )


@pytest.fixture(scope="module")
def hybrid() -> BenchmarkOutcome:
    return run_benchmark(
        corpus_dir=CORPUS_DIR,
        configs_dir=CONFIGS_DIR,
        provider_chain="deterministic_presidio",
        benchmark_run_id="bench_hybrid",
    )


def person_recall_by_language(outcome: BenchmarkOutcome, language: str | None = None) -> float:
    dimensions = ("entity_type",) if language is None else ("entity_type", "language")
    key = (PERSON,) if language is None else (PERSON, language)
    return detection_metrics_by(_truths(), outcome.predictions, dimensions=dimensions)[key].recall


class TestPersonNowDetected:
    def test_person_recall_is_no_longer_zero(self, hybrid: BenchmarkOutcome) -> None:
        assert person_recall_by_language(hybrid) >= MIN_PERSON_RECALL_OVERALL

    @pytest.mark.parametrize("language", ["en", "de"])
    def test_person_recall_per_language(self, hybrid: BenchmarkOutcome, language: str) -> None:
        assert person_recall_by_language(hybrid, language) >= MIN_PERSON_RECALL_EN_DE

    def test_german_per_is_normalized_to_person(self, hybrid: BenchmarkOutcome) -> None:
        german = [
            prediction
            for prediction in hybrid.predictions
            if prediction.entity_type == PERSON and prediction.provider == "presidio"
        ]
        assert german
        assert all(prediction.entity_type in {PERSON, EMAIL, PHONE} for prediction in german)

    def test_greek_is_reported_with_full_support_however_it_scores(
        self, hybrid: BenchmarkOutcome
    ) -> None:
        # Greek runs through xx_ent_wiki_sm because el_core_news_* is non-commercial
        # (ADR-0007). Quality is poor and that is published rather than hidden: the
        # support must be the true count, and the row must exist in the table.
        metric = detection_metrics_by(
            _truths(), hybrid.predictions, dimensions=("entity_type", "language")
        )[(PERSON, "el")]
        assert metric.support == 26
        greek_rows = [
            row for row in hybrid.rows if row.entity_type == PERSON and row.language == "el"
        ]
        assert greek_rows


class TestChainComparison:
    def test_the_hybrid_chain_beats_deterministic_only(
        self, deterministic: BenchmarkOutcome, hybrid: BenchmarkOutcome
    ) -> None:
        assert hybrid.strict.f1 > deterministic.strict.f1
        assert hybrid.leakage.rate < deterministic.leakage.rate
        assert hybrid.leakage.document_clean_rate >= MIN_DOCUMENT_CLEAN_RATE

    def test_deterministic_entities_are_unchanged_by_adding_a_provider(
        self, deterministic: BenchmarkOutcome, hybrid: BenchmarkOutcome
    ) -> None:
        # EMAIL and PHONE were already perfect; a second provider must not disturb
        # them. The reconciler prefers the deterministic span on identical matches.
        for label in (EMAIL, PHONE):
            before = detection_metrics_by(
                _truths(), deterministic.predictions, dimensions=("entity_type",)
            )[(label,)]
            after = detection_metrics_by(
                _truths(), hybrid.predictions, dimensions=("entity_type",)
            )[(label,)]
            assert after.recall == before.recall == 1.0
            assert after.false_positives == 0

    def test_non_pii_identifiers_still_survive(self, hybrid: BenchmarkOutcome) -> None:
        # The probe found the word "Email" tagged PERSON at 0.85, so over-redaction
        # is the number to watch when an NER provider joins.
        assert hybrid.over_redaction.rate == 0.0, hybrid.over_redaction.modified_kinds

    def test_the_strict_relaxed_gap_becomes_informative(self, hybrid: BenchmarkOutcome) -> None:
        # With deterministic spans only, strict == relaxed. Once an NER model joins,
        # the gap is boundary quality (ADR-0011).
        assert hybrid.relaxed.f1 > hybrid.strict.f1

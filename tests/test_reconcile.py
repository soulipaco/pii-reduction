"""Deterministic overlap resolution (``docs/04_PII_ENGINE.md``)."""

from __future__ import annotations

import pytest

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities import ReconciliationPolicy, reconcile
from pii_reduction.entities.reconcile import (
    REASON_BELOW_THRESHOLD,
    REASON_OUT_OF_SCOPE,
    REASON_OVERLAP,
)
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE

pytestmark = pytest.mark.unit

TEXT = "John Smith <john.smith@example.com> called from +30 210 000 0000."


def match(entity_type: str, start: int, end: int, *, provider: str = "p1", score: float = 0.9):  # type: ignore[no-untyped-def]
    return EntityMatch(
        start=start, end=end, entity_type=entity_type, provider=provider, score=score
    )


class TestOverlapResolution:
    def test_email_beats_nested_person_fragments(self) -> None:
        email_start = TEXT.index("john.smith@example.com")
        email_end = email_start + len("john.smith@example.com")
        result = reconcile(
            [
                match(EMAIL, email_start, email_end, provider="deterministic", score=1.0),
                match(PERSON, email_start, email_start + 4, provider="ner", score=0.85),
                match(PERSON, email_start + 5, email_start + 10, provider="ner", score=0.85),
            ]
        )
        assert [(e.entity_type, e.start, e.end) for e in result.entities] == [
            (EMAIL, email_start, email_end)
        ]
        assert result.rejection_counts() == {REASON_OVERLAP: 2}

    def test_longer_person_span_beats_a_nested_fragment(self) -> None:
        result = reconcile([match(PERSON, 0, 10), match(PERSON, 0, 4)])
        assert [(e.start, e.end) for e in result.entities] == [(0, 10)]

    def test_higher_score_wins_within_one_provider(self) -> None:
        result = reconcile([match(PERSON, 0, 10, score=0.6), match(PERSON, 2, 12, score=0.95)])
        assert [(e.start, e.end) for e in result.entities] == [(2, 12)]

    def test_identical_spans_from_two_providers_corroborate_rather_than_conflict(self) -> None:
        policy = ReconciliationPolicy(provider_order=("deterministic", "presidio"))
        result = reconcile(
            [
                match(EMAIL, 12, 34, provider="presidio", score=1.0),
                match(EMAIL, 12, 34, provider="deterministic", score=1.0),
            ],
            policy=policy,
        )
        assert len(result.entities) == 1
        assert result.entities[0].selected_provider == "deterministic"
        assert {m.provider for m in result.entities[0].supporting_matches} == {
            "deterministic",
            "presidio",
        }
        assert result.rejected == ()

    def test_provider_order_breaks_remaining_ties(self) -> None:
        policy = ReconciliationPolicy(provider_order=("first", "second"))
        result = reconcile(
            [
                match(PERSON, 0, 5, provider="second", score=0.85),
                match(PERSON, 0, 5, provider="first", score=0.85),
            ],
            policy=policy,
        )
        assert result.entities[0].selected_provider == "first"

    def test_adjacent_spans_both_survive(self) -> None:
        result = reconcile([match(PERSON, 0, 5), match(PHONE, 5, 12)])
        assert [(e.start, e.end) for e in result.entities] == [(0, 5), (5, 12)]

    def test_results_are_ordered_by_position(self) -> None:
        result = reconcile([match(PHONE, 40, 50), match(EMAIL, 10, 20), match(PERSON, 0, 5)])
        assert [e.start for e in result.entities] == [0, 10, 40]

    def test_resolution_rule_is_recorded(self) -> None:
        result = reconcile([match(PERSON, 0, 5)])
        assert result.entities[0].resolution_rule == "priority_score_length"

    def test_custom_priorities_change_the_winner(self) -> None:
        # A project that ranks PERSON above EMAIL gets the opposite outcome.
        policy = ReconciliationPolicy(priorities={PERSON: 200, EMAIL: 10})
        result = reconcile(
            [match(EMAIL, 0, 20, score=1.0), match(PERSON, 0, 10, score=0.5)], policy=policy
        )
        assert result.entities[0].entity_type == PERSON

    def test_empty_input_is_empty_output(self) -> None:
        assert reconcile([]).entities == ()


class TestFiltering:
    def test_per_provider_per_entity_thresholds_apply(self) -> None:
        # ADR-0005: a global 0.5 would drop Presidio's 0.40 phones. Thresholds are
        # per provider and per entity, so PHONE can sit at 0.3 while PERSON is 0.5.
        policy = ReconciliationPolicy(
            thresholds={"presidio": {PHONE: 0.3, PERSON: 0.5}},
        )
        result = reconcile(
            [
                match(PHONE, 0, 10, provider="presidio", score=0.40),
                match(PERSON, 20, 30, provider="presidio", score=0.45),
            ],
            policy=policy,
        )
        assert [e.entity_type for e in result.entities] == [PHONE]
        assert result.rejection_counts() == {REASON_BELOW_THRESHOLD: 1}

    def test_threshold_of_one_provider_does_not_affect_another(self) -> None:
        policy = ReconciliationPolicy(thresholds={"presidio": {PERSON: 0.9}})
        result = reconcile([match(PERSON, 0, 5, provider="ner", score=0.5)], policy=policy)
        assert len(result.entities) == 1

    def test_unscored_matches_pass_thresholds(self) -> None:
        policy = ReconciliationPolicy(thresholds={"p1": {PERSON: 0.9}})
        unscored = EntityMatch(start=0, end=5, entity_type=PERSON, provider="p1", score=None)
        assert len(reconcile([unscored], policy=policy).entities) == 1

    def test_entities_outside_the_configured_scope_are_rejected(self) -> None:
        policy = ReconciliationPolicy(entities=frozenset({EMAIL}))
        result = reconcile([match(EMAIL, 0, 10), match(PERSON, 20, 30)], policy=policy)
        assert [e.entity_type for e in result.entities] == [EMAIL]
        assert result.rejection_counts() == {REASON_OUT_OF_SCOPE: 1}


class TestRejectionRecords:
    def test_rejections_carry_no_text(self) -> None:
        result = reconcile([match(EMAIL, 0, 20, score=1.0), match(PERSON, 0, 10, score=0.85)])
        rejected = result.rejected[0]
        assert (rejected.entity_type, rejected.start, rejected.end) == (PERSON, 0, 10)
        assert rejected.reason == REASON_OVERLAP
        assert not hasattr(rejected, "text")

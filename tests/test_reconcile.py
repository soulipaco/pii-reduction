"""Deterministic overlap resolution (``docs/04_PII_ENGINE.md``)."""

from __future__ import annotations

import pytest

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.contracts.errors import SpanContractError
from pii_reduction.entities import ReconciliationPolicy, reconcile
from pii_reduction.entities.reconcile import (
    DEFAULT_IDENTIFIER_GUARD,
    REASON_BELOW_THRESHOLD,
    REASON_IDENTIFIER_SHAPED,
    REASON_OUT_OF_SCOPE,
    REASON_OVERLAP,
)
from pii_reduction.entities.taxonomy import ADDRESS, EMAIL, PERSON, PHONE

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

    def test_chain_order_outranks_a_higher_score_from_a_later_provider(self) -> None:
        # ADR-0005: provider scores are recognizer constants, not calibrated
        # probabilities, so 0.95 from one model is not evidence against 0.85 from
        # another. Chain order is the operator's statement of which to trust, and it
        # must not stop mattering the day a provider with higher constants is added.
        policy = ReconciliationPolicy(provider_order=("trusted", "other"))
        result = reconcile(
            [
                match(PERSON, 0, 11, provider="other", score=0.95),
                match(PERSON, 0, 5, provider="trusted", score=0.85),
            ],
            policy=policy,
        )
        assert result.entities[0].selected_provider == "trusted"
        assert (result.entities[0].start, result.entities[0].end) == (0, 5)

    def test_score_still_decides_within_one_provider(self) -> None:
        policy = ReconciliationPolicy(provider_order=("only", "other"))
        result = reconcile(
            [
                match(PERSON, 0, 10, provider="only", score=0.6),
                match(PERSON, 2, 12, provider="only", score=0.95),
            ],
            policy=policy,
        )
        assert (result.entities[0].start, result.entities[0].end) == (2, 12)

    def test_an_unlisted_provider_ranks_after_every_configured_one(self) -> None:
        policy = ReconciliationPolicy(provider_order=("configured",))
        result = reconcile(
            [
                match(PERSON, 0, 8, provider="unlisted", score=1.0),
                match(PERSON, 0, 5, provider="configured", score=0.3),
            ],
            policy=policy,
        )
        assert result.entities[0].selected_provider == "configured"

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


class TestIdentifierGuard:
    """A PERSON span whose surface is a machine identifier is a model error.

    Measured cause (ADR-0016, session 5): once a key/value label stops giving the
    model context, ``KB Article: KB000002739`` and ``Rechnername: DEMO-PC-6963`` are
    tagged PERSON and redacted, taking benchmark over-redaction from 0.000 to 0.020.
    The guard is what lets line-scoped segmentation ship at all.
    """

    def test_an_identifier_tagged_as_a_person_is_rejected(self) -> None:
        text = "KB000002739"
        result = reconcile([match(PERSON, 0, len(text))], text=text)
        assert result.entities == ()
        assert [r.reason for r in result.rejected] == [REASON_IDENTIFIER_SHAPED]

    @pytest.mark.parametrize(
        "surface", ["INC00100000", "KB000002739", "DEMO-PC-6963", "v4.12.3", "12345"]
    )
    def test_every_protected_identifier_shape_is_rejected(self, surface: str) -> None:
        result = reconcile([match(PERSON, 0, len(surface))], text=surface)
        assert result.entities == ()

    @pytest.mark.parametrize(
        "surface", ["Grace Okafor", "Jürgen Müller", "Μαρία Παπαδοπούλου", "O'Brien", "Anne-Marie"]
    )
    def test_names_are_untouched_in_every_language(self, surface: str) -> None:
        result = reconcile([match(PERSON, 0, len(surface))], text=surface)
        assert len(result.entities) == 1

    def test_a_name_beside_a_number_is_kept(self) -> None:
        # Rejecting this would leave the name unredacted. Leaking a name is worse
        # than over-redacting a year, so the guard demands that *no* token be
        # name-like before it rejects.
        text = "Maria Rossi 2026"
        result = reconcile([match(PERSON, 0, len(text))], text=text)
        assert len(result.entities) == 1

    def test_phone_numbers_are_never_guarded(self) -> None:
        # PHONE surfaces are supposed to be all digits. Guarding them would reject
        # every phone number in the corpus.
        text = "+1 202 555 0140"
        result = reconcile([match(PHONE, 0, len(text))], text=text)
        assert len(result.entities) == 1

    def test_emails_are_never_guarded(self) -> None:
        text = "grace.okafor2@example.net"
        result = reconcile([match(EMAIL, 0, len(text))], text=text)
        assert len(result.entities) == 1

    def test_without_text_the_guard_cannot_and_does_not_run(self) -> None:
        # Callers that reason about spans alone keep working; the guard is the one
        # rule here that needs a surface rather than an offset.
        result = reconcile([match(PERSON, 0, 11)])
        assert len(result.entities) == 1

    def test_the_guard_can_be_disabled(self) -> None:
        policy = ReconciliationPolicy(identifier_guard=frozenset())
        result = reconcile([match(PERSON, 0, 11)], policy=policy, text="KB000002739")
        assert len(result.entities) == 1

    def test_a_rejection_carries_offsets_and_no_text(self) -> None:
        # AGENTS.md rule 8: rejections are debug metadata and must never quote a value.
        text = "Customer: KB000002739"
        result = reconcile([match(PERSON, 10, len(text))], text=text)
        rejected = result.rejected[0]
        assert (rejected.start, rejected.end) == (10, len(text))
        assert "KB000002739" not in repr(rejected)

    def test_a_span_beyond_its_text_is_a_loud_error(self) -> None:
        # A span that overruns its own text means the caller passed the wrong string —
        # field text against segment-relative offsets, most likely. Skipping the guard
        # silently would hide that and produce three different behaviours across one
        # document, none of them visible in review.
        with pytest.raises(SpanContractError, match="runs past the end"):
            reconcile([match(PERSON, 0, 50)], text="short")

    def test_the_mismatch_error_names_offsets_and_not_the_text(self) -> None:
        with pytest.raises(SpanContractError) as exc_info:
            reconcile([match(PERSON, 0, 50)], text="secret surface")
        assert "secret surface" not in str(exc_info.value)
        assert "[0, 50)" in str(exc_info.value)

    def test_the_guard_is_counted_in_rejection_metrics(self) -> None:
        result = reconcile([match(PERSON, 0, 5)], text="12345")
        assert result.rejection_counts() == {REASON_IDENTIFIER_SHAPED: 1}


class TestIdentifierGuardEdges:
    """The boundary between a code and a name, pinned.

    The first version of the guard classified a token as name-like only when it held
    no digit at all, which rejected ``Mueller2024``, ``jmueller01`` and
    ``grace.okafor2`` — and a rejected PERSON span means the name survives into the
    output. Counting letters against digits does not separate the cases that matter
    (``DEMO-PC-6963`` is 6/4, ``Mueller2024`` is 7/4); lowercase runs do.
    """

    @pytest.mark.parametrize(
        "surface", ["Mueller2024", "jmueller01", "grace.okafor2", "Παππά2026", "O2 Arena"]
    )
    def test_a_name_carrying_digits_is_still_a_name(self, surface: str) -> None:
        # Usernames, handles and login ids are routine in real support data, and this
        # is the failure that leaks rather than over-redacts.
        result = reconcile([match(PERSON, 0, len(surface))], text=surface)
        assert len(result.entities) == 1, f"{surface!r} would not be redacted"

    def test_an_all_caps_name_beside_another_token_is_kept(self) -> None:
        text = "MARIA MUELLER2024"
        result = reconcile([match(PERSON, 0, len(text))], text=text)
        assert len(result.entities) == 1

    def test_a_lone_all_caps_name_with_digits_is_a_known_gap(self) -> None:
        # Documented in `patterns.is_identifier_shaped`: a single all-caps token with
        # digits is indistinguishable from an asset code without more context, so it
        # is rejected and the name is not redacted. Pinned so the gap stays visible
        # rather than latent; Increment D's real data is where to re-test it.
        result = reconcile([match(PERSON, 0, 11)], text="MUELLER2024")
        assert result.entities == ()

    def test_address_is_not_guarded_by_default(self) -> None:
        # A postcode or house number alone is legitimately all digits, and no shipped
        # provider emits ADDRESS, so there is no measurement behind guarding it.
        assert ADDRESS not in DEFAULT_IDENTIFIER_GUARD
        result = reconcile([match(ADDRESS, 0, 5)], text="10115")
        assert len(result.entities) == 1

    def test_the_default_scope_is_person_only(self) -> None:
        assert frozenset({PERSON}) == DEFAULT_IDENTIFIER_GUARD

    @pytest.mark.parametrize("surface", ["Wei2", "Li3", "Bo2"])
    def test_a_short_name_with_a_digit_is_the_same_known_gap(self, surface: str) -> None:
        # Documented in `patterns.is_identifier_shaped`: the gap is "lowercase run
        # shorter than three", not "all caps". Pinned so the real boundary is visible.
        result = reconcile([match(PERSON, 0, len(surface))], text=surface)
        assert result.entities == ()

    def test_cyrillic_names_with_digits_are_kept(self) -> None:
        # Cyrillic is cased, so the rule works there; caseless scripts are the
        # documented exposure, not this one.
        text = "Иванов2024"
        result = reconcile([match(PERSON, 0, len(text))], text=text)
        assert len(result.entities) == 1

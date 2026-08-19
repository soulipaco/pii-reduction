"""ADR-0021: widening a PERSON span over one preceding token.

Default tier — the rule is pure text arithmetic with no model behind it, so the
refusals that keep it safe are checked on every push rather than nightly. What the
rule does to the corpus is a benchmark gate, not a test.

The direction matters more than the rule. Session 7 measured and rejected the
*trim* form of this repair (drop a capitalised token ahead of the name), because it
can cut the first token of a genuine three-token name and leak a name part — the
invisible error ADR-0016 chose against. Extension fails the other way: it can swallow
a neighbouring word, which over-redacts, and over-redaction is measured and gated.
"""

from __future__ import annotations

import pytest

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.reconcile import reconcile
from pii_reduction.entities.taxonomy import EMAIL, PERSON
from pii_reduction.providers.base import extend_person_span_left
from pii_reduction.providers.deterministic import DeterministicProvider

pytestmark = pytest.mark.unit


def span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


class TestItExtends:
    def test_over_a_preceding_capitalised_token(self) -> None:
        text = "Γιώργος Δημητρίου ζητά να τηλεφωνήσουμε."
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(
            text, "Γιώργος Δημητρίου"
        )

    def test_over_a_tab_separated_token(self) -> None:
        text = "Γιώργος\tΔημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == (0, len(text))

    def test_only_one_token(self) -> None:
        # Two tokens would be a rule about how long names are, which this is not.
        text = "Από Γιώργος Δημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(
            text, "Γιώργος Δημητρίου"
        )

    def test_the_end_offset_never_moves(self) -> None:
        # What lets `detect` validate spans *before* repairing them: no repair can
        # push a span past the end of the text it was validated against.
        text = "Γιώργος Δημητρίου ζητά"
        start, end = span(text, "Δημητρίου")
        assert extend_person_span_left(text, start, end)[1] == end


class TestItRefuses:
    """Each refusal is structural. None is a list of words in any language."""

    def test_across_a_line_break(self) -> None:
        text = "Γραμμή\nΔημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(text, "Δημητρίου")

    def test_an_identifier_shaped_token(self) -> None:
        # The over-redaction gate is 0.000 and this is what keeps it there.
        text = "Αίτημα INC00101332 Δημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(text, "Δημητρίου")

    def test_a_field_label_ending_in_a_colon(self) -> None:
        text = "Από: Δημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(text, "Δημητρίου")

    @pytest.mark.parametrize("separator", ["·", "·"])
    def test_an_ano_teleia(self, separator: str) -> None:
        # ADR-0019 mechanism 3: the άνω τελεία is a boundary signal, in both the
        # codepoint the corpus uses and the one Unicode prefers for Greek.
        text = f"Παππά{separator} Δημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(text, "Δημητρίου")

    @pytest.mark.parametrize("mark", [".", "!", "?", ";", ";"])
    def test_sentence_final_punctuation(self, mark: str) -> None:
        # A name opening a sentence must not absorb the previous sentence's last word.
        # Both semicolons are listed: ASCII U+003B and the Greek question mark U+037E
        # render identically and only one of them was covered at first.
        text = f"Καλημέρα{mark} Δημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(text, "Δημητρίου")

    def test_an_uncased_token(self) -> None:
        text = "ο πελάτης Δημητρίου"
        assert extend_person_span_left(text, *span(text, "Δημητρίου")) == span(text, "Δημητρίου")

    def test_at_the_start_of_the_text(self) -> None:
        assert extend_person_span_left("Δημητρίου", 0, 9) == (0, 9)

    def test_when_only_whitespace_precedes(self) -> None:
        text = "   Δημητρίου"
        assert extend_person_span_left(text, 3, len(text)) == (3, len(text))


class TestTheProviderOptIn:
    """Off by default, and PERSON-only — it is not a general span widener."""

    def test_a_provider_does_not_extend_unless_it_opts_in(self) -> None:
        assert DeterministicProvider().extend_person_left is False

    def test_only_person_spans_are_extended(self) -> None:
        provider = DeterministicProvider()
        provider.extend_person_left = True
        text = "Γιώργος a@example.com"
        match = EntityMatch(start=8, end=len(text), entity_type=EMAIL, score=1.0, provider="x")
        assert provider._extend_left(match, text) == [match]

    def test_an_extended_span_says_so(self) -> None:
        provider = DeterministicProvider()
        provider.extend_person_left = True
        text = "Γιώργος Δημητρίου"
        match = EntityMatch(start=8, end=17, entity_type=PERSON, score=0.85, provider="x")
        widened, original = provider._extend_left(match, text)
        assert (widened.start, widened.end) == (0, 17)
        assert widened.metadata["extended"] is True
        assert original is match, "the narrow span is kept as the reconciler's fallback"

    def test_an_unmoved_span_is_returned_unchanged(self) -> None:
        # The original object, not a copy: nothing should stamp `extended` on a span
        # that was not, and a refused extension must offer exactly one candidate.
        provider = DeterministicProvider()
        provider.extend_person_left = True
        text = "ο πελάτης Δημητρίου"
        match = EntityMatch(start=10, end=19, entity_type=PERSON, score=0.85, provider="x")
        assert provider._extend_left(match, text) == [match]
        assert provider._extend_left(match, text)[0] is match


class TestItCannotCauseALeak:
    """The failure mode the first version of this repair actually had.

    Extension was originally written to *replace* the narrow span. Two independent
    reviews reproduced the same consequence: the reconciler resolves overlaps by
    entity priority and is greedy without backtracking, so a PERSON span widened into
    overlap with a higher-priority EMAIL is rejected outright — and the name it was
    covering survives in cleartext. That is under-redaction, the invisible error this
    repair was justified by avoiding.

    The fix is to offer the reconciler both spans. These tests pin it, because the
    argument in ADR-0021 is only true while the fallback exists.
    """

    def provider(self) -> DeterministicProvider:
        provider = DeterministicProvider()
        provider.extend_person_left = True
        return provider

    def test_both_the_wide_and_narrow_spans_are_offered(self) -> None:
        text = "Γιώργος Δημητρίου"
        match = EntityMatch(start=8, end=17, entity_type=PERSON, score=0.85, provider="x")
        offered = self.provider()._extend_left(match, text)
        assert [(m.start, m.end) for m in offered] == [(0, 17), (8, 17)]

    def test_the_name_survives_when_the_wide_span_loses_to_an_email(self) -> None:
        # The exact shape both reviews built: a capitalised email local part directly
        # before a name. It is not identifier-shaped and it is capitalised, so the
        # extension fires and collides with the higher-priority EMAIL.
        text = "Maria.Papadopoulou@example.com Δημητρίου"
        start = text.index("Δημητρίου")
        person = EntityMatch(
            start=start, end=len(text), entity_type=PERSON, score=0.85, provider="x"
        )
        email = EntityMatch(start=0, end=30, entity_type=EMAIL, score=1.0, provider="d")
        candidates = [email, *self.provider()._extend_left(person, text)]

        approved = reconcile(candidates, text=text).entities
        covered = [text[e.start : e.end] for e in approved]
        assert "Δημητρίου" in covered, "the name must still be redacted"
        assert any(e.entity_type == EMAIL for e in approved)

    def test_a_neighbouring_person_is_not_evicted(self) -> None:
        # Peer eviction: two adjacent PERSON spans, the second widening over the
        # first's last token and winning the length tie-break. Without the fallback
        # the first span's given name was left in cleartext.
        text = "Μαρία Παπαδοπούλου Δημητρίου"
        first = EntityMatch(start=0, end=18, entity_type=PERSON, score=0.85, provider="x")
        second_start = text.index("Δημητρίου")
        second = EntityMatch(
            start=second_start, end=len(text), entity_type=PERSON, score=0.85, provider="x"
        )
        # `detect` passes every candidate from the same call as `siblings`, which is
        # what lets the repair see the neighbour it would otherwise claim a token from.
        siblings = [first, second]
        candidates = [first, *self.provider()._extend_left(second, text, siblings)]

        approved = reconcile(candidates, text=text).entities
        redacted = "".join(text[e.start : e.end] for e in approved)
        assert "Μαρία" in redacted, "the neighbouring given name must still be covered"
        assert len(candidates) == 2, "the extension must be refused, not merely offered"

    def test_an_identifier_span_is_never_widened_past_its_guard(self) -> None:
        # The reconciler rejects a PERSON span whose surface is a machine identifier.
        # Widening it over a capitalised word makes the joined surface name-like, which
        # would unblock it and redact the identifier — over-redaction, gated at 0.000.
        text = "Παραγγελία INC00101332"
        start = text.index("INC00101332")
        match = EntityMatch(
            start=start, end=len(text), entity_type=PERSON, score=0.85, provider="x"
        )
        assert self.provider()._extend_left(match, text) == [match]

    def test_firing_is_counted(self) -> None:
        # `_bound_to_line` counts its repairs so a provider upgrade cannot change
        # coverage silently; this one is held to the same standard.
        provider = self.provider()
        text = "Γιώργος Δημητρίου"
        match = EntityMatch(start=8, end=17, entity_type=PERSON, score=0.85, provider="x")
        provider._extend_left(match, text)
        assert provider.drop_counter.declared[f"{provider.name}:person_extended_left"] == 1

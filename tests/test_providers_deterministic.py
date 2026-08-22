"""Deterministic EMAIL/PHONE provider.

All fixtures are synthetic. Emails use RFC 2606 reserved domains (ADR-0003);
``.test`` appears only where the point is documenting recognizer behavior.
"""

from __future__ import annotations

import pytest

from pii_reduction.config.registries import KNOWN_PROVIDER_TYPES
from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.taxonomy import ADDRESS, EMAIL, PERSON, PHONE
from pii_reduction.providers import (
    DeterministicProvider,
    ProviderError,
    available_provider_types,
    build_provider,
)
from pii_reduction.providers.base import LINE_BOUNDED_ENTITIES, BaseProvider
from pii_reduction.providers.deterministic import (
    SCORE_EMAIL,
    SCORE_PHONE_POSSIBLE,
    SCORE_PHONE_VALID,
)
from tests.provider_contract import ProviderContractTests

pytestmark = pytest.mark.unit

SAMPLE = "Contact Maria Rossi at maria.rossi@example.com or +30 210 000 0000."
GREEK_SAMPLE = "Το email μου είναι maria.papadopoulou@example.com και το τηλέφωνο +30 210 000 0000."


def provider(**options: object) -> DeterministicProvider:
    return DeterministicProvider(dict(options) if options else None)


def labels(matches: list) -> list[str]:  # type: ignore[type-arg]
    return [match.entity_type for match in matches]


def surfaces(text: str, matches: list) -> list[str]:  # type: ignore[type-arg]
    return [text[match.start : match.end] for match in matches]


class TestDeterministicProviderContract(ProviderContractTests):
    """The shared provider suite, applied to this provider."""

    provider = DeterministicProvider()
    sample_text = SAMPLE


class TestRegistry:
    def test_every_configurable_provider_type_can_be_built(self) -> None:
        # Since Increment B both types exist, so configuration and the registry agree
        # exactly. Constructing the Presidio provider does not load a model.
        assert available_provider_types() == KNOWN_PROVIDER_TYPES

    def test_a_pending_type_would_name_the_increment(self) -> None:
        # The mechanism stays covered even though nothing is pending today.
        from pii_reduction.providers import registry

        original = dict(registry.PENDING_PROVIDER_TYPES)
        registry.PENDING_PROVIDER_TYPES["gliner"] = "roadmap Phase 7"
        try:
            with pytest.raises(ProviderError) as exc_info:
                build_provider("gliner")
        finally:
            registry.PENDING_PROVIDER_TYPES.clear()
            registry.PENDING_PROVIDER_TYPES.update(original)
        message = str(exc_info.value)
        assert "not implemented yet" in message
        assert "Phase 7" in message

    def test_instance_name_can_be_overridden(self) -> None:
        built = build_provider("deterministic", name="deterministic_eu")
        assert built.name == "deterministic_eu"
        assert built.detect(SAMPLE)[0].provider == "deterministic_eu"

    def test_unknown_type_is_actionable(self) -> None:
        with pytest.raises(ProviderError) as exc_info:
            build_provider("regex_v2")
        assert "not registered" in str(exc_info.value)


class TestEmailDetection:
    def test_finds_an_email_with_score_one(self) -> None:
        matches = provider().detect(SAMPLE, entities={EMAIL})
        assert surfaces(SAMPLE, matches) == ["maria.rossi@example.com"]
        assert matches[0].score == SCORE_EMAIL
        assert matches[0].recognizer == "email_pattern"

    @pytest.mark.parametrize(
        "text",
        [
            "maria@example.com",
            "Email: maria@example.com",
            "Write to maria@example.com.",
            "(maria@example.com)",
            "<maria@example.com>",
            "maria@example.com, please",
            "first.last+tag@example.co.uk",
            "MARIA@EXAMPLE.ORG",
        ],
    )
    def test_email_is_found_regardless_of_surrounding_punctuation(self, text: str) -> None:
        matches = provider().detect(text, entities={EMAIL})
        assert len(matches) == 1
        assert "@" in text[matches[0].start : matches[0].end]
        assert not text[matches[0].start : matches[0].end].endswith((".", ",", ")", ">"))

    def test_reserved_tlds_are_accepted_unlike_presidio(self) -> None:
        # ADR-0003: the deterministic regex accepts any >=2-letter TLD, including
        # .test and .invalid, which Presidio's default recognizer rejects. The
        # difference is measured by the benchmark, not hidden.
        for text in ("maria@example.test", "agent@support.invalid"):
            assert len(provider().detect(text, entities={EMAIL})) == 1

    @pytest.mark.parametrize(
        "text",
        ["not an email @ all", "maria@", "@example.com", "maria@example", "maria@example.c"],
    )
    def test_non_emails_are_not_matched(self, text: str) -> None:
        assert provider().detect(text, entities={EMAIL}) == []

    def test_offsets_are_codepoint_true_after_non_latin_text(self) -> None:
        matches = provider().detect(GREEK_SAMPLE, entities={EMAIL})
        assert len(matches) == 1
        assert GREEK_SAMPLE[matches[0].start : matches[0].end] == "maria.papadopoulou@example.com"

    def test_multiple_emails_are_all_found_in_order(self) -> None:
        text = "From maria@example.com to jan@example.org"
        matches = provider().detect(text, entities={EMAIL})
        assert surfaces(text, matches) == ["maria@example.com", "jan@example.org"]


class TestPhoneDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "Call +30 210 000 0000 today",
            "Call +49 30 23125 020 today",
            "Call 0030 210 000 0000 today",
            "Call +1 (202) 555-0143 today",
            "Call +30 210 000 0000 ext. 12 today",
        ],
    )
    def test_phone_formats_are_matched(self, text: str) -> None:
        matches = provider().detect(text, entities={PHONE})
        assert len(matches) == 1
        assert matches[0].entity_type == PHONE
        assert matches[0].recognizer == "phonenumbers_matcher"

    def test_valid_number_scores_higher_than_merely_possible(self) -> None:
        valid = provider().detect("Call +30 210 000 0000 today", entities={PHONE})
        assert valid[0].score == SCORE_PHONE_VALID
        assert SCORE_PHONE_POSSIBLE < SCORE_PHONE_VALID

    def test_possible_leniency_is_opt_in_because_it_matches_plain_identifiers(self) -> None:
        # Why 'valid' is the default: at 'possible' leniency phonenumbers reports
        # ordinary numbers as phones. The 0.85 tier of ADR-0005 belongs to exactly
        # these opt-in matches.
        text = "Order 12345 shipped"
        assert provider().detect(text, entities={PHONE}) == []
        lenient = provider(leniency="possible").detect(text, entities={PHONE})
        assert len(lenient) == 1
        assert lenient[0].score == SCORE_PHONE_POSSIBLE

    def test_national_format_needs_a_configured_region(self) -> None:
        text = "Rufen Sie 030 23125 020 an"
        assert provider(regions=["DE"]).detect(text, entities={PHONE})
        assert provider(regions=["GR"]).detect(text, entities={PHONE}) == []

    def test_the_same_number_is_reported_once_across_region_passes(self) -> None:
        text = "Call +30 210 000 0000 today"
        matches = provider(regions=["GR", "DE", "US"]).detect(text, entities={PHONE})
        assert len(matches) == 1


class TestNegativeCases:
    """Non-PII identifiers must survive (``docs/10_TESTING_QA.md`` §6)."""

    @pytest.mark.parametrize(
        "text",
        [
            "Ticket INC00128492 was closed",
            "See KB000002715 for details",
            "Machine DEMO-PC-6915 rebooted",
            "Upgraded to v4.12.3 last night",
            "Logged at 2026-04-03 09:15:04",
            "Department: Support",
            "Order 12345 shipped",
        ],
    )
    def test_identifiers_are_not_detected(self, text: str) -> None:
        assert provider().detect(text) == []

    def test_a_ticket_id_next_to_a_real_phone_does_not_hide_it(self) -> None:
        text = "Ticket INC00128492: call +30 210 000 0000"
        matches = provider().detect(text, entities={PHONE})
        assert surfaces(text, matches) == ["+30 210 000 0000"]


class TestScopeAndOptions:
    def test_asking_for_email_only_returns_no_phone(self) -> None:
        assert labels(provider().detect(SAMPLE, entities={EMAIL})) == [EMAIL]

    def test_asking_for_phone_only_returns_no_email(self) -> None:
        assert labels(provider().detect(SAMPLE, entities={PHONE})) == [PHONE]

    def test_unsupported_entity_is_silently_out_of_scope(self) -> None:
        # PERSON is a valid taxonomy label this provider simply cannot produce.
        assert provider().detect(SAMPLE, entities={"PERSON"}) == []

    def test_default_scope_is_everything_supported(self) -> None:
        assert set(labels(provider().detect(SAMPLE))) == {EMAIL, PHONE}

    def test_unknown_option_is_actionable(self) -> None:
        with pytest.raises(ProviderError) as exc_info:
            provider(region="GR")
        assert "region" in str(exc_info.value)
        assert "regions" in str(exc_info.value)

    def test_invalid_region_code_is_rejected(self) -> None:
        with pytest.raises(ProviderError):
            provider(regions=["Greece"])

    def test_unknown_leniency_is_rejected(self) -> None:
        with pytest.raises(ProviderError) as exc_info:
            provider(leniency="anything_goes")
        assert "anything_goes" in str(exc_info.value)

    def test_language_is_recorded_on_matches(self) -> None:
        matches = provider().detect(GREEK_SAMPLE, language="el")
        assert {match.language for match in matches} == {"el"}


class _SpanProvider(BaseProvider):
    """A provider that returns exactly the spans it was given.

    The trimming lives in ``BaseProvider.detect``, so exercising it needs a subclass
    whose raw output is under the test's control rather than a real recognizer's.
    """

    name = "span_double"

    def __init__(self, spans: list[tuple[str, int, int]]) -> None:
        self._spans = spans

    def supported_entities(self) -> frozenset[str]:
        return frozenset({PERSON, EMAIL, PHONE})

    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        return [
            EntityMatch(start=start, end=end, entity_type=label, provider=self.name, score=0.85)
            for label, start, end in self._spans
            if label in entities
        ]


class TestLineBoundedSpans:
    """A PERSON span may not cross a line break; it is split into one span per line.

    Measured cause (ADR-0016): handed a multi-line key/value block, spaCy returns a
    PERSON span covering the name, the break and the next line's first word. The model
    is right about the entity and wrong about where it stops.

    Every fragment is kept rather than the best one, because a name can be *split by*
    the break rather than merely running past it — a hard-wrapped `Jürgen` + break +
    `Müller` is one name in two pieces, and keeping either piece leaves the other in
    the output. That leak is invisible to `leakage_rate`, which matches only the exact
    full surface. Over-redacting a neighbouring label is the direction this project
    can measure, and it is gated at 0.000.
    """

    @staticmethod
    def _surfaces(text: str, span: tuple[int, int]) -> list[str]:
        provider = _SpanProvider([(PERSON, span[0], span[1])])
        return [text[m.start : m.end] for m in provider.detect(text, entities=(PERSON,))]

    def test_a_name_running_past_the_break_yields_an_exact_name_span(self) -> None:
        text = "Customer: Grace Okafor" + chr(10) + "Mobile number: 000"
        surfaces = self._surfaces(text, (10, text.index("number") - 1))
        assert surfaces[0] == "Grace Okafor"

    def test_a_name_split_by_the_break_keeps_both_halves(self) -> None:
        # The case that makes "keep one fragment" unsafe: either half alone leaks the
        # other, and the leakage metric cannot see a partial surface.
        text = "Jürgen" + chr(10) + "Müller"
        assert self._surfaces(text, (0, len(text))) == ["Jürgen", "Müller"]

    def test_a_name_after_the_break_is_not_lost(self) -> None:
        text = "Customer:" + chr(10) + "Peter Novak"
        assert "Peter Novak" in self._surfaces(text, (0, len(text)))

    def test_trailing_whitespace_goes_with_the_break(self) -> None:
        text = "Grace Okafor   " + chr(10) + "next"
        assert self._surfaces(text, (0, len(text)))[0] == "Grace Okafor"

    def test_offsets_stay_true_across_a_two_character_break(self) -> None:
        # CRLF is two characters; assuming one silently shifts every span after it.
        text = "Kunde:" + chr(13) + chr(10) + "Jürgen Müller"
        assert self._surfaces(text, (0, len(text))) == ["Kunde:", "Jürgen Müller"]

    def test_a_span_of_nothing_but_structure_is_dropped_and_counted(self) -> None:
        text = "a" + chr(10) + "b"
        provider = _SpanProvider([(PERSON, 1, 2)])
        assert provider.detect(text, entities=(PERSON,)) == []
        assert provider.drop_counter.as_dict() == {"span_double:line_bounded_empty": 1}

    def test_a_split_span_is_counted(self) -> None:
        # ADR-0004: a silent change to what a provider reports is how coverage moves
        # without anyone noticing.
        text = "Peter Novak" + chr(10) + "Mobile"
        provider = _SpanProvider([(PERSON, 0, len(text))])
        provider.detect(text, entities=(PERSON,))
        assert provider.drop_counter.as_dict() == {"span_double:line_bounded_split": 1}

    def test_a_span_without_a_break_is_returned_unchanged(self) -> None:
        text = "Grace Okafor called"
        assert self._surfaces(text, (0, 12)) == ["Grace Okafor"]

    def test_a_malformed_span_still_fails_loudly(self) -> None:
        # Repair must not swallow a provider bug: an out-of-range span is a contract
        # violation and has to name the provider and the offsets, not raise IndexError.
        provider = _SpanProvider([(PERSON, 0, 50)])
        with pytest.raises(ProviderError, match="exceeds text"):
            provider.detect("short", entities=(PERSON,))

    def test_email_and_phone_surfaces_cannot_span_lines_either(self) -> None:
        # True of them as well, and a no-op in practice: the deterministic patterns
        # never match across a break. The point is that the fact is declared once, in
        # the taxonomy, rather than restated per layer.
        assert {EMAIL, PHONE} <= LINE_BOUNDED_ENTITIES

    def test_address_is_excluded_because_it_may_span_lines(self) -> None:
        # A postal address written across several lines is one address; trimming it
        # would cut a real entity in half.
        assert ADDRESS not in LINE_BOUNDED_ENTITIES

"""Deterministic EMAIL/PHONE provider.

All fixtures are synthetic. Emails use RFC 2606 reserved domains (ADR-0003);
``.test`` appears only where the point is documenting recognizer behavior.
"""

from __future__ import annotations

import pytest

from pii_reduction.config.registries import KNOWN_PROVIDER_TYPES
from pii_reduction.entities.taxonomy import EMAIL, PHONE
from pii_reduction.providers import (
    DeterministicProvider,
    ProviderError,
    available_provider_types,
    build_provider,
)
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
            "Call +49 30 901820 today",
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
        text = "Rufen Sie 030 901820 an"
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

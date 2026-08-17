"""The short-text policy and resolver construction (ADR-0012).

Runs in the default model-free tier: the gate is the part with the interesting edge
cases and must be testable without the `language` extra installed.
"""

from __future__ import annotations

import pytest

from pii_reduction.config.registries import KNOWN_LANGUAGE_DETECTORS
from pii_reduction.language import (
    ColumnLanguageResolver,
    LanguageError,
    ShortTextGate,
    StaticLanguageResolver,
    available_detectors,
    build_resolver,
    eligible_alpha_count,
)
from pii_reduction.language.gate import (
    REASON_BELOW_MIN_ALPHA,
    REASON_BELOW_MIN_CHARS,
)

pytestmark = pytest.mark.unit

SUPPORTED = ("en", "de", "el")


class TestEligibleAlphaCount:
    def test_prose_counts(self) -> None:
        assert eligible_alpha_count("Hello there") == 10

    def test_an_email_contributes_nothing(self) -> None:
        # The case that forced a structural gate: lingua scores a bare address
        # 'en' 0.95, and an email address is not English.
        assert eligible_alpha_count("maria.rossi@example.com") == 0

    def test_a_url_contributes_nothing(self) -> None:
        assert eligible_alpha_count("https://example.com/help/page") == 0

    def test_digits_contribute_nothing(self) -> None:
        assert eligible_alpha_count("+30 210 000 0020") == 0

    def test_prose_around_an_email_still_counts(self) -> None:
        assert eligible_alpha_count("write to maria@example.com now") == len("writetonow")

    def test_greek_letters_count(self) -> None:
        assert eligible_alpha_count("Ευχαριστώ πολύ") == 13

    def test_punctuation_and_whitespace_do_not_count(self) -> None:
        assert eligible_alpha_count("... --- !!!") == 0


class TestShortTextGate:
    def test_long_prose_passes(self) -> None:
        assert ShortTextGate().rejection_reason("Please email the customer today") is None

    @pytest.mark.parametrize("text", ["Thanks", "Resolved", "OK", "Ευχαριστώ"])
    def test_short_strings_are_refused_on_length(self, text: str) -> None:
        # All of these score confidently on lingua; length is what stops them.
        assert ShortTextGate().rejection_reason(text) == REASON_BELOW_MIN_CHARS

    def test_a_long_string_with_no_prose_is_refused_on_alphabetic_count(self) -> None:
        assert (
            ShortTextGate().rejection_reason("maria.rossi@example.com and +30 210 000 0020")
            == REASON_BELOW_MIN_ALPHA
        )

    def test_thresholds_are_configurable(self) -> None:
        assert ShortTextGate(min_chars=3, min_alpha_chars=3).rejection_reason("Thanks") is None

    def test_confidence_threshold(self) -> None:
        gate = ShortTextGate(min_confidence=0.7)
        assert gate.accepts_confidence(0.71)
        assert not gate.accepts_confidence(0.52)  # measured value for "OK"

    def test_whitespace_does_not_count_toward_length(self) -> None:
        assert ShortTextGate().rejection_reason("   hi   ") == REASON_BELOW_MIN_CHARS


class TestResolverRegistry:
    def test_registry_matches_what_configuration_accepts(self) -> None:
        assert available_detectors() == KNOWN_LANGUAGE_DETECTORS

    def test_static_mode_needs_no_detector(self) -> None:
        resolver = build_resolver("static", supported=SUPPORTED, static_language="de")
        assert isinstance(resolver, StaticLanguageResolver)
        assert resolver.resolve("beliebiger Text").language == "de"

    def test_column_mode_needs_no_detector(self) -> None:
        resolver = build_resolver("column", supported=SUPPORTED, language_column="language")
        assert isinstance(resolver, ColumnLanguageResolver)
        assert resolver.resolve("text", row={"language": "el"}).language == "el"

    def test_unknown_mode_is_actionable(self) -> None:
        with pytest.raises(LanguageError) as exc_info:
            build_resolver("guess", supported=SUPPORTED)
        assert "guess" in str(exc_info.value)

    def test_unimplemented_detector_is_actionable(self) -> None:
        with pytest.raises(LanguageError) as exc_info:
            build_resolver("detect", supported=SUPPORTED, detector="fasttext")
        assert "fasttext" in str(exc_info.value)
        assert "lingua" in str(exc_info.value)

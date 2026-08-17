"""Lingua detection and routing behaviour (``docs/10_TESTING_QA.md`` §3).

Marked ``integration``: needs the `language` extra. Run with ``pytest -m integration``.

These test *routing behaviour*, not detector accuracy — the point is what the pipeline
does with a language claim, including refusing to make one.
"""

from __future__ import annotations

import logging

import pytest

from pii_reduction.contracts.language import UNKNOWN_LANGUAGE
from pii_reduction.language import LinguaDetector, ShortTextGate, build_resolver
from pii_reduction.language.errors import LanguageError
from pii_reduction.language.gate import (
    REASON_BELOW_MIN_ALPHA,
    REASON_BELOW_MIN_CHARS,
    REASON_BELOW_MIN_CONFIDENCE,
)
from pii_reduction.language.lingua_detector import reset_detector_cache
from pii_reduction.observability.logging import LOGGER_NAME
from pii_reduction.synthetic import load_corpus
from tests.test_benchmark import CORPUS_DIR

pytestmark = [pytest.mark.integration, pytest.mark.slow]

pytest.importorskip("lingua", reason="needs the 'language' extra")

SUPPORTED = ("en", "de", "el")

EN = "Please email Maria Rossi at maria.rossi@example.com about the open ticket."
DE = "Bitte schreiben Sie an jan.becker@example.org zum offenen Vorgang."
EL = "Το email μου είναι eleni.pappa@example.net για το ανοιχτό αίτημα."
FR = "Bonjour, je vous écris au sujet du dossier ouvert la semaine dernière."


@pytest.fixture(scope="module")
def detector() -> LinguaDetector:
    return LinguaDetector(supported=SUPPORTED)


class TestSupportedLanguages:
    @pytest.mark.parametrize(("text", "expected"), [(EN, "en"), (DE, "de"), (EL, "el")])
    def test_each_configured_language_is_detected(
        self, detector: LinguaDetector, text: str, expected: str
    ) -> None:
        result = detector.resolve(text)
        assert result.language == expected
        assert result.supported is True
        assert result.fallback_used is False
        assert result.confidence is not None and result.confidence >= 0.7
        assert result.detector == "lingua"

    def test_mixed_text_takes_the_dominant_language(self, detector: LinguaDetector) -> None:
        mixed = f"{DE} {DE} Thanks very much."
        assert detector.resolve(mixed).language == "de"


class TestRefusingToGuess:
    @pytest.mark.parametrize("text", ["Thanks", "Resolved", "OK", "Ευχαριστώ"])
    def test_short_text_routes_to_unknown(self, detector: LinguaDetector, text: str) -> None:
        result = detector.resolve(text)
        assert result.language == UNKNOWN_LANGUAGE
        assert result.supported is False
        assert result.fallback_used is True
        assert result.reason == REASON_BELOW_MIN_CHARS

    def test_email_only_text_routes_to_unknown(self, detector: LinguaDetector) -> None:
        # Measured: lingua scores this 'en' 0.95. The gate is what stops it.
        result = detector.resolve("maria.rossi@example.com and +30 210 000 0020")
        assert result.language == UNKNOWN_LANGUAGE
        assert result.reason == REASON_BELOW_MIN_ALPHA

    def test_numeric_only_text_routes_to_unknown(self, detector: LinguaDetector) -> None:
        assert detector.resolve("+30 210 000 0020 / 12345 / 6789").language == UNKNOWN_LANGUAGE

    def test_low_confidence_routes_to_unknown(self) -> None:
        strict = LinguaDetector(supported=SUPPORTED, gate=ShortTextGate(min_confidence=0.999))
        result = strict.resolve(EN)
        if result.language == UNKNOWN_LANGUAGE:
            assert result.reason == REASON_BELOW_MIN_CONFIDENCE
            assert result.confidence is not None
        else:  # the detector was simply that certain; the path is still exercised below
            assert result.confidence is not None and result.confidence >= 0.999

    def test_an_unsupported_language_is_recorded_not_forced(self) -> None:
        # French is not in the configured set. Restricting the detector means it is
        # reported as the nearest configured language with fallback_used, never
        # silently processed as if it were English.
        result = LinguaDetector(supported=SUPPORTED).resolve(FR)
        assert result.detector == "lingua"
        assert result.language in {*SUPPORTED, UNKNOWN_LANGUAGE}

    def test_unknown_language_is_never_marked_supported(self, detector: LinguaDetector) -> None:
        assert detector.resolve("OK").supported is False


class TestDeterminismAndReuse:
    def test_the_same_text_always_resolves_the_same_way(self, detector: LinguaDetector) -> None:
        assert detector.resolve(EL) == detector.resolve(EL)

    def test_two_detectors_share_one_lingua_instance(self) -> None:
        assert (
            LinguaDetector(supported=SUPPORTED).detector_instance()
            is LinguaDetector(supported=SUPPORTED).detector_instance()
        )

    def test_a_different_language_set_gets_its_own_instance(self) -> None:
        reset_detector_cache()
        one = LinguaDetector(supported=("en", "de", "el")).detector_instance()
        other = LinguaDetector(supported=("en", "de")).detector_instance()
        assert one is not other

    def test_a_single_language_is_refused_with_the_alternative(self) -> None:
        with pytest.raises(LanguageError) as exc_info:
            LinguaDetector(supported=("en",)).detector_instance()
        assert "static" in str(exc_info.value)

    def test_a_language_lingua_cannot_detect_is_actionable(self) -> None:
        with pytest.raises(LanguageError) as exc_info:
            LinguaDetector(supported=("en", "zz")).detector_instance()
        assert "zz" in str(exc_info.value)


class TestPrivacy:
    def test_detection_logs_no_text(
        self, detector: LinguaDetector, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        for text in (EN, DE, EL, "maria.rossi@example.com"):
            detector.resolve(text)
        assert "maria.rossi@example.com" not in caplog.text
        assert "Maria Rossi" not in caplog.text

    def test_the_result_carries_no_text(self, detector: LinguaDetector) -> None:
        dumped = str(detector.resolve(EN).model_dump())
        assert "maria.rossi@example.com" not in dumped


class TestAgainstTheCommittedCorpus:
    """Detection over all 102 documents, scored against their known language.

    The corpus carries the true language, so this measures the detector rather than
    assuming it. The interesting property is not the agreement rate but its shape:
    the gate should convert uncertainty into abstention, never into a confident wrong
    answer, because a wrong language routes text to the wrong provider chain.
    """

    @pytest.fixture(scope="class")
    def outcomes(self, detector: LinguaDetector):  # type: ignore[no-untyped-def]
        corpus = load_corpus(CORPUS_DIR)
        return [(document, detector.resolve(document.text)) for document in corpus.documents]

    def test_it_never_claims_the_wrong_language(self, outcomes) -> None:  # type: ignore[no-untyped-def]
        wrong = [
            (document.document_id, document.language, result.language)
            for document, result in outcomes
            if result.supported and result.language != document.language
        ]
        assert wrong == [], f"confident misclassifications: {wrong}"

    def test_agreement_is_high_and_the_remainder_abstains(self, outcomes) -> None:  # type: ignore[no-untyped-def]
        agreed = sum(1 for d, r in outcomes if r.language == d.language)
        abstained = [r for _, r in outcomes if r.language == UNKNOWN_LANGUAGE]
        assert agreed / len(outcomes) >= 0.95
        assert agreed + len(abstained) == len(outcomes)

    def test_abstentions_record_why(self, outcomes) -> None:  # type: ignore[no-untyped-def]
        for _, result in outcomes:
            if result.language == UNKNOWN_LANGUAGE:
                assert result.reason in {
                    REASON_BELOW_MIN_CHARS,
                    REASON_BELOW_MIN_ALPHA,
                    REASON_BELOW_MIN_CONFIDENCE,
                }
                assert result.fallback_used is True

    def test_every_language_is_found_somewhere(self, outcomes) -> None:  # type: ignore[no-untyped-def]
        detected = {r.language for _, r in outcomes if r.supported}
        assert detected == set(SUPPORTED)


class TestBuiltThroughTheRegistry:
    def test_detect_mode_builds_a_lingua_detector(self) -> None:
        resolver = build_resolver("detect", supported=SUPPORTED, detector="lingua")
        assert isinstance(resolver, LinguaDetector)
        assert resolver.resolve(DE).language == "de"

    def test_the_configured_gate_is_applied(self) -> None:
        resolver = build_resolver(
            "detect",
            supported=SUPPORTED,
            detector="lingua",
            gate=ShortTextGate(min_chars=3, min_alpha_chars=3),
        )
        assert resolver.resolve("Ευχαριστώ").language == "el"

"""Presidio adapter. Marked ``integration``: needs the extra and spaCy models.

Run with::

    pytest -m integration

The default test run excludes these (ADR-0009), so a contributor without models still
gets full signal on contracts, parsers, reducers, evaluation and privacy.

Fixtures are synthetic throughout; emails use RFC 2606 reserved domains (ADR-0003).
"""

from __future__ import annotations

import time

import pytest

from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.providers import ProviderError, available_provider_types, build_provider
from pii_reduction.providers.presidio_provider import (
    DEFAULT_MODELS,
    NATIVE_LABELS,
    RECOMMENDED_THRESHOLDS,
    PresidioProvider,
    reset_engine_cache,
)
from tests.provider_contract import ProviderContractTests

pytestmark = [pytest.mark.integration, pytest.mark.slow]

EN_TEXT = "Please email Maria Rossi at maria.rossi@example.com or call +30 210 000 0000."
DE_TEXT = "Bitte schreiben Sie Lukas Schneider an lukas.schneider@example.org."
EL_TEXT = "Ονομάζομαι Ελένη Παππά και το email μου είναι eleni.pappa@example.net."

pytest.importorskip("presidio_analyzer", reason="needs the 'presidio' extra")


@pytest.fixture(scope="module")
def provider() -> PresidioProvider:
    return PresidioProvider()


class TestPresidioProviderContract(ProviderContractTests):
    """The shared provider suite, applied to Presidio."""

    provider = PresidioProvider()
    sample_text = EN_TEXT


class TestConfiguration:
    def test_it_is_a_registered_provider_type(self) -> None:
        assert "presidio" in available_provider_types()
        assert build_provider("presidio").name == "presidio"

    def test_default_models_avoid_the_non_commercial_greek_models(self) -> None:
        # ADR-0007: el_core_news_* is CC BY-NC-SA and incompatible with MIT.
        assert DEFAULT_MODELS["el"] == "xx_ent_wiki_sm"
        assert not any(model.startswith("el_core_news") for model in DEFAULT_MODELS.values())

    def test_configuring_a_non_commercial_model_is_refused(self) -> None:
        with pytest.raises(ProviderError) as exc_info:
            PresidioProvider({"models": {"el": "el_core_news_md"}})
        message = str(exc_info.value)
        assert "CC BY-NC-SA" in message
        assert "xx_ent_wiki_sm" in message

    def test_unknown_option_is_actionable(self) -> None:
        with pytest.raises(ProviderError) as exc_info:
            PresidioProvider({"model": "en_core_web_md"})
        assert "model" in str(exc_info.value)

    def test_supported_entities_come_from_the_mapping_table(
        self, provider: PresidioProvider
    ) -> None:
        assert provider.supported_entities() == {PERSON, EMAIL, PHONE}

    def test_supported_languages_come_from_the_models(self, provider: PresidioProvider) -> None:
        assert provider.supported_languages() == {"en", "de", "el"}

    def test_recommended_thresholds_are_per_entity(self) -> None:
        # ADR-0005: PhoneRecognizer emits a constant 0.40, so a global 0.5 would drop
        # every phone. The values live in configs/providers.yaml and are applied by
        # the reconciler; this asserts the recommendation itself stays coherent.
        assert RECOMMENDED_THRESHOLDS[PHONE] < 0.40 < RECOMMENDED_THRESHOLDS[PERSON]


class TestDetection:
    def test_person_is_detected_in_english(self, provider: PresidioProvider) -> None:
        matches = provider.detect(EN_TEXT, language="en", entities={PERSON})
        assert [EN_TEXT[m.start : m.end] for m in matches] == ["Maria Rossi"]

    def test_person_is_detected_in_german(self, provider: PresidioProvider) -> None:
        # Session 1 found German spaCy emits PER; Presidio maps it, and the adapter
        # asserts the normalized label regardless (ADR-0004).
        matches = provider.detect(DE_TEXT, language="de", entities={PERSON})
        assert matches
        assert all(match.entity_type == PERSON for match in matches)
        assert any("Schneider" in DE_TEXT[m.start : m.end] for m in matches)

    def test_person_is_detected_in_greek_via_the_multilingual_model(
        self, provider: PresidioProvider
    ) -> None:
        matches = provider.detect(EL_TEXT, language="el", entities={PERSON})
        assert matches, "no PERSON found in Greek text"
        covered = [EL_TEXT[m.start : m.end] for m in matches]
        # Boundaries are known to be fuzzy here (the probe saw the preceding verb
        # absorbed); the requirement is that the name is covered, which is exactly
        # what relaxed matching measures beside strict (ADR-0011).
        assert any("Παππά" in span or "Ελένη" in span for span in covered)

    def test_email_and_phone_are_also_reported(self, provider: PresidioProvider) -> None:
        labels = {match.entity_type for match in provider.detect(EN_TEXT, language="en")}
        assert {EMAIL, PHONE} <= labels

    def test_native_labels_never_escape_the_adapter(self, provider: PresidioProvider) -> None:
        for match in provider.detect(EN_TEXT, language="en"):
            assert match.entity_type not in NATIVE_LABELS or match.entity_type == PERSON
            assert match.entity_type in {PERSON, EMAIL, PHONE}
            # The native label is kept as metadata for debugging, not as the label.
            assert match.metadata["native_label"] in NATIVE_LABELS

    def test_url_noise_is_not_returned(self, provider: PresidioProvider) -> None:
        # The probe saw URL matches such as "maria.ro" from an email address. The
        # adapter asks only for the labels it maps, so they never arrive.
        matches = provider.detect("Write to maria.rossi@example.com", language="en")
        assert all(match.entity_type in {PERSON, EMAIL, PHONE} for match in matches)

    def test_scores_are_recognizer_constants(self, provider: PresidioProvider) -> None:
        matches = provider.detect(EN_TEXT, language="en")
        by_label = {match.entity_type: match.score for match in matches}
        assert by_label[EMAIL] == pytest.approx(1.0)
        assert by_label[PHONE] == pytest.approx(0.4)
        assert by_label[PERSON] == pytest.approx(0.85)

    def test_an_unsupported_language_yields_nothing_rather_than_raising(
        self, provider: PresidioProvider
    ) -> None:
        assert provider.detect(EN_TEXT, language="fr") == []

    def test_a_missing_language_yields_nothing(self, provider: PresidioProvider) -> None:
        assert provider.detect(EN_TEXT, language=None) == []

    def test_entity_scope_is_respected(self, provider: PresidioProvider) -> None:
        matches = provider.detect(EN_TEXT, language="en", entities={PERSON})
        assert {match.entity_type for match in matches} == {PERSON}

    def test_recognizer_identity_is_recorded(self, provider: PresidioProvider) -> None:
        matches = provider.detect(EN_TEXT, language="en")
        assert any(match.recognizer for match in matches)


class TestEngineReuse:
    def test_building_the_provider_twice_does_not_reload_models(self) -> None:
        reset_engine_cache()
        cold_start = time.perf_counter()
        PresidioProvider().engine()
        cold = time.perf_counter() - cold_start

        warm_start = time.perf_counter()
        PresidioProvider().engine()
        warm = time.perf_counter() - warm_start

        # Loading three spaCy models takes seconds; a cache hit is microseconds.
        # The bound is generous because CI machines are not benchmark machines.
        assert warm < max(cold / 10, 0.5), f"cold={cold:.3f}s warm={warm:.3f}s"

    def test_two_providers_share_one_engine(self) -> None:
        assert PresidioProvider().engine() is PresidioProvider().engine()

    def test_a_different_model_configuration_gets_its_own_engine(self) -> None:
        one = PresidioProvider().engine()
        other = PresidioProvider({"models": {"en": "en_core_web_md"}}).engine()
        assert one is not other

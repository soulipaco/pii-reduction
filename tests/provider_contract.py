"""Reusable provider contract suite (``docs/10_TESTING_QA.md`` §4).

Every provider must pass these, so Increment B's Presidio adapter subclasses this
class instead of restating the rules. Subclasses supply a provider and a sample text
that provider is expected to find something in.

The class name deliberately does not start with ``Test`` so pytest collects it only
through its subclasses.
"""

from __future__ import annotations

import pytest

from pii_reduction.entities.taxonomy import known_labels
from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.errors import ProviderError


class ProviderContractTests:
    """Contract every provider owes its callers."""

    provider: BaseProvider
    #: Text the provider is expected to find at least one entity in.
    sample_text: str = ""
    #: Language code to pass; providers may ignore it.
    sample_language: str | None = "en"

    def detect(self, text: str, **kwargs: object) -> list:  # type: ignore[type-arg]
        return self.provider.detect(text, language=self.sample_language, **kwargs)  # type: ignore[arg-type]

    def test_provider_exposes_identity(self) -> None:
        assert self.provider.name
        assert self.provider.supported_entities() <= known_labels()
        assert self.provider.supported_entities()

    def test_returns_normalized_labels_only(self) -> None:
        for match in self.detect(self.sample_text):
            assert match.entity_type in known_labels()

    def test_offsets_are_slice_true(self) -> None:
        for match in self.detect(self.sample_text):
            assert 0 <= match.start < match.end <= len(self.sample_text)
            assert self.sample_text[match.start : match.end] == match.slice_of(self.sample_text)

    def test_matches_are_attributed_to_the_provider(self) -> None:
        for match in self.detect(self.sample_text):
            assert match.provider == self.provider.name

    def test_results_are_sorted_by_position(self) -> None:
        matches = self.detect(self.sample_text)
        assert matches == sorted(matches, key=lambda m: (m.start, m.end, m.entity_type))

    def test_entity_scope_is_respected(self) -> None:
        for label in sorted(self.provider.supported_entities()):
            matches = self.detect(self.sample_text, entities={label})
            assert all(match.entity_type == label for match in matches)

    def test_empty_entity_scope_returns_nothing(self) -> None:
        assert self.detect(self.sample_text, entities=set()) == []

    def test_empty_text_returns_nothing(self) -> None:
        assert self.detect("") == []

    def test_unknown_requested_label_is_actionable(self) -> None:
        with pytest.raises(ProviderError) as exc_info:
            self.detect(self.sample_text, entities={"SSN"})
        assert "SSN" in str(exc_info.value)

    def test_source_text_is_not_mutated(self) -> None:
        original = self.sample_text
        self.detect(self.sample_text)
        assert self.sample_text == original

    def test_null_text_is_rejected(self) -> None:
        with pytest.raises(ProviderError):
            self.provider.detect(None)  # type: ignore[arg-type]

    def test_detection_is_repeatable(self) -> None:
        first = self.detect(self.sample_text)
        second = self.detect(self.sample_text)
        assert first == second

    def test_batch_matches_single_calls(self) -> None:
        texts = [self.sample_text, "", self.sample_text]
        batched = self.provider.detect_batch(texts, languages=[self.sample_language] * 3)
        assert batched == [self.detect(text) for text in texts]

    def test_batch_rejects_mismatched_language_count(self) -> None:
        with pytest.raises(ProviderError):
            self.provider.detect_batch([self.sample_text], languages=["en", "de"])

    def test_matches_carry_no_surface_text(self) -> None:
        for match in self.detect(self.sample_text):
            assert "text" not in match.model_dump()

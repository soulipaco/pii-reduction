"""Taxonomy and provider label-mapping machinery."""

from __future__ import annotations

import pytest

from pii_reduction.entities import (
    ADDRESS,
    EMAIL,
    PERSON,
    PHONE,
    TAXONOMY,
    DropCounter,
    LabelMapping,
    LabelMappingError,
    UnknownEntityLabelError,
    default_priority,
    default_replacement,
    is_known,
    known_labels,
    require_known,
)

pytestmark = pytest.mark.unit

# Native label tables belong to provider adapters (ADR-0004). These are test doubles
# standing in for the tables Increment B will ship inside providers/.
# LOC is dropped rather than mapped to ADDRESS: composing an address from LOC failed
# on the session-2 probes (ADR-0002).
SPACY_DE_TABLE = {"PER": PERSON}
SPACY_DE_DROPPED = frozenset({"LOC", "ORG", "MISC"})
PRESIDIO_TABLE = {"EMAIL_ADDRESS": EMAIL, "PHONE_NUMBER": PHONE, "PERSON": PERSON}
PRESIDIO_DROPPED = frozenset({"URL", "LOCATION"})


class TestTaxonomy:
    def test_baseline_labels_are_present(self) -> None:
        assert known_labels() == {PERSON, EMAIL, PHONE, ADDRESS}

    def test_priority_order_matches_the_documented_hierarchy(self) -> None:
        # EMAIL/PHONE > ADDRESS > PERSON (docs/04_PII_ENGINE.md)
        assert default_priority(EMAIL) > default_priority(ADDRESS)
        assert default_priority(PHONE) > default_priority(ADDRESS)
        assert default_priority(ADDRESS) > default_priority(PERSON)

    def test_address_is_in_the_taxonomy_but_not_detected_at_baseline(self) -> None:
        # ADR-0002: no shipped provider claims ADDRESS at v0.1.
        assert is_known(ADDRESS)
        assert TAXONOMY[ADDRESS].detected_at_baseline is False
        assert all(TAXONOMY[label].detected_at_baseline for label in (EMAIL, PHONE, PERSON))

    def test_default_replacements_are_bracketed_labels(self) -> None:
        assert default_replacement(PERSON) == "<PERSON>"
        assert default_replacement(EMAIL) == "<EMAIL>"

    def test_provider_native_label_is_not_in_the_taxonomy(self) -> None:
        assert not is_known("EMAIL_ADDRESS")
        assert not is_known("PER")

    def test_require_known_names_the_known_labels(self) -> None:
        with pytest.raises(UnknownEntityLabelError) as exc_info:
            require_known("EMAIL_ADDRESS")
        message = str(exc_info.value)
        assert "EMAIL_ADDRESS" in message
        assert "PERSON" in message and "EMAIL" in message

    def test_require_known_distinguishes_a_non_normalized_label(self) -> None:
        with pytest.raises(UnknownEntityLabelError) as exc_info:
            require_known("email")
        assert "not normalized" in str(exc_info.value)

    def test_require_known_includes_caller_context(self) -> None:
        with pytest.raises(UnknownEntityLabelError) as exc_info:
            require_known("SSN", context="dataset 'demo', column 'body'")
        assert "dataset 'demo', column 'body'" in str(exc_info.value)

    def test_taxonomy_is_read_only(self) -> None:
        with pytest.raises(TypeError):
            TAXONOMY["SSN"] = TAXONOMY[EMAIL]  # type: ignore[index]


class TestLabelMapping:
    def test_maps_native_labels_to_the_taxonomy(self) -> None:
        # German spaCy emits PER where English emits PERSON: mapping is per model.
        mapping = LabelMapping(provider="spacy_de", table=SPACY_DE_TABLE, dropped=SPACY_DE_DROPPED)
        assert mapping.normalize("PER") == PERSON
        assert mapping.normalize("LOC") is None

    def test_presidio_style_table_normalizes_its_own_labels(self) -> None:
        mapping = LabelMapping(provider="presidio", table=PRESIDIO_TABLE, dropped=PRESIDIO_DROPPED)
        assert mapping.normalize("EMAIL_ADDRESS") == EMAIL
        assert mapping.normalize("PHONE_NUMBER") == PHONE
        assert mapping.normalize("PERSON") == PERSON

    def test_declared_drops_return_none_and_are_counted(self) -> None:
        mapping = LabelMapping(provider="presidio", table=PRESIDIO_TABLE, dropped=PRESIDIO_DROPPED)
        counter = DropCounter()
        assert mapping.normalize("URL", counter=counter) is None
        assert mapping.normalize("LOCATION", counter=counter) is None
        assert counter.as_dict() == {"presidio:URL": 1, "presidio:LOCATION": 1}
        assert not counter.unmapped

    def test_unknown_native_labels_are_counted_separately(self) -> None:
        mapping = LabelMapping(provider="presidio", table=PRESIDIO_TABLE, dropped=PRESIDIO_DROPPED)
        counter = DropCounter()
        assert mapping.normalize("NRP", counter=counter) is None
        assert counter.unmapped == {"presidio:NRP": 1}
        assert not counter.declared
        assert counter.total == 1

    def test_dropping_without_a_counter_is_allowed(self) -> None:
        mapping = LabelMapping(provider="presidio", table=PRESIDIO_TABLE)
        assert mapping.normalize("URL") is None

    def test_mapping_to_a_label_outside_the_taxonomy_is_rejected(self) -> None:
        with pytest.raises(LabelMappingError) as exc_info:
            LabelMapping(provider="presidio", table={"LOCATION": "GPE"})
        assert "GPE" in str(exc_info.value)

    def test_a_label_cannot_be_both_mapped_and_dropped(self) -> None:
        with pytest.raises(LabelMappingError) as exc_info:
            LabelMapping(provider="presidio", table=PRESIDIO_TABLE, dropped=frozenset({"PERSON"}))
        assert "PERSON" in str(exc_info.value)

    def test_supported_entities_reports_normalized_labels(self) -> None:
        mapping = LabelMapping(provider="presidio", table=PRESIDIO_TABLE)
        assert mapping.supported_entities() == {EMAIL, PHONE, PERSON}

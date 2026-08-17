"""Reduction strategies: redact, mask, deterministic pseudonymization.

Fixtures are synthetic; emails use RFC 2606 reserved domains (ADR-0003). The
pseudonymization key used here is an obvious test placeholder set on a monkeypatched
environment variable — never a real key, never read from configuration.
"""

from __future__ import annotations

import pytest

from pii_reduction.config.registries import KNOWN_REDUCERS
from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.reducers import (
    MaskReducer,
    PseudonymizationKeyError,
    PseudonymizeReducer,
    RedactReducer,
    ReducerError,
    available_reducers,
    build_reducer,
)
from pii_reduction.reducers.pseudonymize import DEFAULT_KEY_ENV

pytestmark = pytest.mark.unit

TEXT = "Maria Rossi wrote from maria.rossi@example.com and called +30 210 000 0000."
PERSON_SPAN = (0, 11)
EMAIL_SPAN = (23, 46)
PHONE_SPAN = (58, 74)

TEST_KEY = "test-key-not-a-real-secret-0123456789"


def entity(entity_type: str, span: tuple[int, int], *, provider: str = "deterministic"):  # type: ignore[no-untyped-def]
    return ResolvedEntity(
        start=span[0],
        end=span[1],
        entity_type=entity_type,
        selected_provider=provider,
        resolution_rule="priority_score_length",
    )


ALL_ENTITIES = [
    entity(PERSON, PERSON_SPAN, provider="ner"),
    entity(EMAIL, EMAIL_SPAN),
    entity(PHONE, PHONE_SPAN),
]


@pytest.fixture
def keyed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DEFAULT_KEY_ENV, TEST_KEY)


def test_spans_used_by_these_tests_are_accurate() -> None:
    assert TEXT[slice(*PERSON_SPAN)] == "Maria Rossi"
    assert TEXT[slice(*EMAIL_SPAN)] == "maria.rossi@example.com"
    assert TEXT[slice(*PHONE_SPAN)] == "+30 210 000 0000"


class TestRegistry:
    def test_registry_matches_what_configuration_accepts(self) -> None:
        assert available_reducers() == KNOWN_REDUCERS

    def test_every_configurable_reducer_can_be_built(self, keyed_env: None) -> None:
        for name in KNOWN_REDUCERS:
            assert build_reducer(name, scope_value="demo_dataset").name == name

    def test_unknown_reducer_is_actionable(self) -> None:
        with pytest.raises(ReducerError) as exc_info:
            build_reducer("shred")
        assert "not registered" in str(exc_info.value)


class TestSharedReplacementLoop:
    """Behavior every strategy inherits from ``BaseReducer``."""

    def test_replacements_are_applied_right_to_left(self) -> None:
        result = RedactReducer().reduce(TEXT, ALL_ENTITIES)
        assert result.text == "<PERSON> wrote from <EMAIL> and called <PHONE>."

    def test_operations_are_recorded_against_original_offsets(self) -> None:
        result = RedactReducer().reduce(TEXT, ALL_ENTITIES)
        assert [(op.entity_type, op.start, op.end) for op in result.operations] == [
            (PERSON, *PERSON_SPAN),
            (EMAIL, *EMAIL_SPAN),
            (PHONE, *PHONE_SPAN),
        ]
        assert {op.strategy for op in result.operations} == {"redact"}

    def test_operations_never_record_the_original_value(self) -> None:
        result = RedactReducer().reduce(TEXT, ALL_ENTITIES)
        dumped = str([op.model_dump() for op in result.operations])
        assert "maria.rossi@example.com" not in dumped
        assert "Maria Rossi" not in dumped

    def test_entity_counts_are_available(self) -> None:
        result = RedactReducer().reduce(TEXT, ALL_ENTITIES)
        assert result.entity_counts == {PERSON: 1, EMAIL: 1, PHONE: 1}

    def test_no_entities_leaves_text_untouched(self) -> None:
        result = RedactReducer().reduce(TEXT, [])
        assert result.text == TEXT
        assert result.operations == ()

    def test_replacement_at_string_start_and_end(self) -> None:
        text = "maria@example.com is +30 210 000 0000"
        result = RedactReducer().reduce(
            text, [entity(EMAIL, (0, 17)), entity(PHONE, (21, len(text)))]
        )
        assert result.text == "<EMAIL> is <PHONE>"

    def test_adjacent_entities(self) -> None:
        text = "MariaRossi"
        result = RedactReducer().reduce(text, [entity(PERSON, (0, 5)), entity(PERSON, (5, 10))])
        assert result.text == "<PERSON><PERSON>"

    def test_repeated_entity_is_replaced_every_time(self) -> None:
        text = "maria@example.com and maria@example.com"
        result = RedactReducer().reduce(text, [entity(EMAIL, (0, 17)), entity(EMAIL, (22, 39))])
        assert result.text == "<EMAIL> and <EMAIL>"

    def test_unicode_offsets_are_codepoint_true(self) -> None:
        text = "Το email είναι maria@example.com 👍"
        start = text.index("maria")
        result = RedactReducer().reduce(text, [entity(EMAIL, (start, start + 17))])
        assert result.text == "Το email είναι <EMAIL> 👍"

    def test_overlapping_spans_are_refused(self) -> None:
        with pytest.raises(ReducerError) as exc_info:
            RedactReducer().reduce(TEXT, [entity(EMAIL, (0, 20)), entity(PERSON, (10, 30))])
        assert "reconcile" in str(exc_info.value)

    def test_span_past_the_end_of_text_is_refused(self) -> None:
        with pytest.raises(ReducerError):
            RedactReducer().reduce("short", [entity(EMAIL, (0, 99))])

    def test_unordered_input_is_handled(self) -> None:
        result = RedactReducer().reduce(TEXT, list(reversed(ALL_ENTITIES)))
        assert result.text == "<PERSON> wrote from <EMAIL> and called <PHONE>."


class TestRedact:
    def test_default_replacements_come_from_the_taxonomy(self) -> None:
        assert (
            RedactReducer().reduce(TEXT, [entity(PERSON, PERSON_SPAN)]).text.startswith("<PERSON>")
        )

    def test_configured_replacements_win(self) -> None:
        reducer = RedactReducer(replacements={PERSON: "[name removed]"})
        assert reducer.reduce(TEXT, [entity(PERSON, PERSON_SPAN)]).text.startswith("[name removed]")

    def test_replacement_for_an_unknown_entity_is_refused(self) -> None:
        with pytest.raises(ReducerError) as exc_info:
            RedactReducer(replacements={"SSN": "<SSN>"})
        assert "SSN" in str(exc_info.value)

    def test_redacted_output_does_not_contain_the_original(self) -> None:
        result = RedactReducer().reduce(TEXT, ALL_ENTITIES)
        for value in ("Maria Rossi", "maria.rossi@example.com", "+30 210 000 0000"):
            assert value not in result.text

    def test_redaction_is_idempotent_over_its_own_output(self) -> None:
        once = RedactReducer().reduce(TEXT, ALL_ENTITIES).text
        # No entity spans remain to be found in the reduced text.
        assert RedactReducer().reduce(once, []).text == once


class TestMask:
    def test_default_rules_follow_the_configuration_contract(self) -> None:
        # PERSON -> full, EMAIL -> partial_email, PHONE -> last4 (docs/06).
        result = MaskReducer().reduce(TEXT, ALL_ENTITIES)
        assert result.text == (
            "***** ***** wrote from ma***@example.com and called *** *** *** 0000."
        )

    def test_partial_email_keeps_the_domain(self) -> None:
        result = MaskReducer().reduce(TEXT, [entity(EMAIL, EMAIL_SPAN)])
        assert "ma***@example.com" in result.text
        assert "maria.rossi@" not in result.text

    def test_last4_keeps_the_final_four_characters(self) -> None:
        result = MaskReducer().reduce(TEXT, [entity(PHONE, PHONE_SPAN)])
        assert result.text.endswith("0000.")
        assert "+30 210" not in result.text

    def test_full_mask_preserves_whitespace_shape(self) -> None:
        result = MaskReducer().reduce(TEXT, [entity(PERSON, PERSON_SPAN)])
        assert result.text.startswith("***** *****")

    def test_rules_are_configurable_per_entity(self) -> None:
        reducer = MaskReducer({"rules": {EMAIL: "full"}})
        result = reducer.reduce(TEXT, [entity(EMAIL, EMAIL_SPAN)])
        assert "@" not in result.text.split(" and ")[0].split("from ")[1]

    def test_mask_character_is_configurable(self) -> None:
        reducer = MaskReducer({"mask_char": "#"})
        assert reducer.reduce(TEXT, [entity(PERSON, PERSON_SPAN)]).text.startswith("##### #####")

    def test_unknown_rule_is_actionable(self) -> None:
        with pytest.raises(ReducerError) as exc_info:
            MaskReducer({"rules": {EMAIL: "hash_it"}})
        assert "hash_it" in str(exc_info.value)
        assert "partial_email" in str(exc_info.value)

    def test_unknown_entity_in_rules_is_actionable(self) -> None:
        with pytest.raises(ReducerError):
            MaskReducer({"rules": {"SSN": "full"}})

    def test_unknown_option_is_actionable(self) -> None:
        with pytest.raises(ReducerError) as exc_info:
            MaskReducer({"mask_chars": "*"})
        assert "mask_chars" in str(exc_info.value)

    def test_masking_deliberately_leaves_part_of_the_value(self) -> None:
        # This is the property that makes masking a different benchmark story from
        # redaction (ADR-0013): the domain and last four digits survive on purpose.
        result = MaskReducer().reduce(TEXT, ALL_ENTITIES)
        assert "example.com" in result.text
        assert "0000" in result.text


class TestPseudonymize:
    def test_same_value_yields_the_same_token(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer(scope_value="demo")
        text = "Maria Rossi met Maria Rossi"
        result = reducer.reduce(text, [entity(PERSON, (0, 11)), entity(PERSON, (16, 27))])
        first, second = result.text.split(" met ")
        assert first == second
        assert first.startswith("PERSON_")

    def test_different_values_yield_different_tokens(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer(scope_value="demo")
        assert reducer.token_for(PERSON, "Maria Rossi") != reducer.token_for(PERSON, "Jan Novak")

    def test_tokens_are_stable_across_reducer_instances(self, keyed_env: None) -> None:
        first = PseudonymizeReducer(scope_value="demo").token_for(PERSON, "Maria Rossi")
        second = PseudonymizeReducer(scope_value="demo").token_for(PERSON, "Maria Rossi")
        assert first == second

    def test_scope_changes_the_token(self, keyed_env: None) -> None:
        one = PseudonymizeReducer(scope_value="dataset_a").token_for(PERSON, "Maria Rossi")
        two = PseudonymizeReducer(scope_value="dataset_b").token_for(PERSON, "Maria Rossi")
        assert one != two

    def test_global_scope_ignores_the_scope_value(self, keyed_env: None) -> None:
        one = PseudonymizeReducer({"scope": "global"}).token_for(PERSON, "Maria Rossi")
        two = PseudonymizeReducer({"scope": "global"}, scope_value="x").token_for(
            PERSON, "Maria Rossi"
        )
        assert one == two

    def test_entity_type_is_part_of_the_token(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer(scope_value="demo")
        assert reducer.token_for(PERSON, "same value") != reducer.token_for(EMAIL, "same value")

    def test_a_different_key_yields_different_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DEFAULT_KEY_ENV, "test-key-one-0123456789abcdefghij")
        one = PseudonymizeReducer(scope_value="demo").token_for(PERSON, "Maria Rossi")
        monkeypatch.setenv(DEFAULT_KEY_ENV, "test-key-two-0123456789abcdefghij")
        two = PseudonymizeReducer(scope_value="demo").token_for(PERSON, "Maria Rossi")
        assert one != two

    def test_case_is_significant_by_default(self, keyed_env: None) -> None:
        # ADR-0011: nothing normalizes text, so 'Maria' and 'maria' are distinct
        # subjects unless the operator opts out deliberately.
        reducer = PseudonymizeReducer(scope_value="demo")
        assert reducer.token_for(PERSON, "Maria") != reducer.token_for(PERSON, "maria")

    def test_case_insensitivity_is_opt_in(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer({"case_sensitive": False}, scope_value="demo")
        assert reducer.token_for(PERSON, "Maria") == reducer.token_for(PERSON, "maria")

    def test_output_does_not_contain_the_original(self, keyed_env: None) -> None:
        result = PseudonymizeReducer(scope_value="demo").reduce(TEXT, ALL_ENTITIES)
        for value in ("Maria Rossi", "maria.rossi@example.com", "+30 210 000 0000"):
            assert value not in result.text

    def test_missing_key_names_the_variable_and_refuses_to_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEFAULT_KEY_ENV, raising=False)
        with pytest.raises(PseudonymizationKeyError) as exc_info:
            PseudonymizeReducer(scope_value="demo")
        message = str(exc_info.value)
        assert DEFAULT_KEY_ENV in message
        assert "never be stored in configuration" in message

    def test_the_key_is_never_echoed_in_errors(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer(scope_value="demo")
        with pytest.raises(ReducerError) as exc_info:
            reducer.reduce("short", [entity(EMAIL, (0, 99))])
        assert TEST_KEY not in str(exc_info.value)

    def test_non_global_scope_requires_a_scope_value(self, keyed_env: None) -> None:
        with pytest.raises(ReducerError) as exc_info:
            PseudonymizeReducer()
        assert "requires a scope value" in str(exc_info.value)

    def test_unknown_scope_is_actionable(self, keyed_env: None) -> None:
        with pytest.raises(ReducerError) as exc_info:
            PseudonymizeReducer({"scope": "universe"}, scope_value="demo")
        assert "universe" in str(exc_info.value)

    def test_token_length_is_bounded(self, keyed_env: None) -> None:
        with pytest.raises(ReducerError):
            PseudonymizeReducer({"token_length": 2}, scope_value="demo")

    def test_longer_tokens_reduce_collision_risk(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer({"token_length": 16}, scope_value="demo")
        token = reducer.token_for(PERSON, "Maria Rossi")
        assert len(token.split("_", 1)[1]) == 16

    def test_no_reverse_mapping_is_exposed(self, keyed_env: None) -> None:
        reducer = PseudonymizeReducer(scope_value="demo")
        reducer.token_for(PERSON, "Maria Rossi")
        # The in-process collision index stores digests, never plaintext.
        assert "Maria Rossi" not in str(reducer.__dict__)

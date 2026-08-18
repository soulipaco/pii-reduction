"""Parser + provider + reconciler + reducer, composed by hand.

This is Demo 2 of ``docs/12_DEMO_SCENARIOS.md`` and Increment A4's exit criterion:
transcript metadata prefixes must come back byte-identical while the bodies are
reduced. The pipeline that wires these together arrives in Increment A5; composing
them manually here proves the boundaries actually fit before an orchestrator hides
the seams.

PERSON is not detected by the v0.1 chain — the deterministic provider covers EMAIL
and PHONE only, and no NLP provider ships until Increment B (ADR-0002 for ADDRESS,
plan §2 for the detected baseline). The tests below show that honestly: the
provider-driven case leaves the name in place, and a separate case supplies a PERSON
span by hand to prove the reduction path handles it once a provider can produce one.
"""

from __future__ import annotations

import pytest

from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.entities import reconcile
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.parsers import TranscriptParser
from pii_reduction.providers import DeterministicProvider
from pii_reduction.reducers import MaskReducer, PseudonymizeReducer, RedactReducer
from pii_reduction.reducers.base import BaseReducer
from pii_reduction.reducers.pseudonymize import DEFAULT_KEY_ENV

pytestmark = pytest.mark.unit

DEMO_2 = (
    "2026-04-03 09:15:04 - Support Agent: Hello, how can I help?\n"
    "2026-04-03 09:15:13 - Guest: Hi, I'm Maria Rossi. Please call me on +30 210 000 0000.\n"
    "2026-04-03 09:15:42 - Support Agent: Can you confirm your email?\n"
    "2026-04-03 09:15:49 - Guest: maria.rossi@example.com\n"
)

PREFIXES = (
    "2026-04-03 09:15:04 - Support Agent:",
    "2026-04-03 09:15:13 - Guest:",
    "2026-04-03 09:15:42 - Support Agent:",
    "2026-04-03 09:15:49 - Guest:",
)


def process(
    text: str,
    *,
    reducer: BaseReducer,
    entities: frozenset[str] = frozenset({EMAIL, PHONE}),
    extra: dict[str, list[ResolvedEntity]] | None = None,
) -> str:
    """Run one field through the full local path and reconstruct it."""
    parser = TranscriptParser()
    provider = DeterministicProvider()
    parsed = parser.parse(text)

    transformed: dict[str, str] = {}
    for segment in parsed.processable_segments:
        matches = provider.detect(segment.text, language="en", entities=entities)
        # text= matters: this hand-composed chain is the production path in miniature,
        # and omitting it would quietly run without the identifier guard.
        resolved = list(reconcile(matches, text=segment.text).entities)
        resolved.extend((extra or {}).get(segment.segment_id, []))
        resolved.sort(key=lambda entity: entity.start)
        if resolved:
            transformed[segment.segment_id] = reducer.reduce(segment.text, resolved).text

    return parser.reconstruct(parsed, transformed)


class TestDemoTwo:
    def test_prefixes_are_byte_identical_after_redaction(self) -> None:
        output = process(DEMO_2, reducer=RedactReducer())
        for prefix in PREFIXES:
            assert prefix in output
        assert output.count("2026-04-03") == 4
        assert output.endswith("\n")
        assert output.count("\n") == DEMO_2.count("\n")

    def test_email_and_phone_are_reduced(self) -> None:
        output = process(DEMO_2, reducer=RedactReducer())
        assert "maria.rossi@example.com" not in output
        assert "+30 210 000 0000" not in output
        assert "<EMAIL>" in output and "<PHONE>" in output

    def test_person_is_not_detected_by_the_v01_chain(self) -> None:
        # Honest baseline: no shipped provider detects PERSON yet (Increment B).
        output = process(DEMO_2, reducer=RedactReducer())
        assert "Maria Rossi" in output
        assert "<PERSON>" not in output

    def test_documented_demo_output_is_reached_once_person_spans_exist(self) -> None:
        # Supplying the PERSON span by hand shows the reduction path is complete;
        # only detection is missing.
        parser = TranscriptParser()
        parsed = parser.parse(DEMO_2)
        body = next(s for s in parsed.processable_segments if "Maria Rossi" in s.text)
        start = body.text.index("Maria Rossi")
        person = ResolvedEntity(
            start=start,
            end=start + len("Maria Rossi"),
            entity_type=PERSON,
            selected_provider="hand_supplied",
            resolution_rule="test_fixture",
        )
        output = process(DEMO_2, reducer=RedactReducer(), extra={body.segment_id: [person]})
        assert output == (
            "2026-04-03 09:15:04 - Support Agent: Hello, how can I help?\n"
            "2026-04-03 09:15:13 - Guest: Hi, I'm <PERSON>. Please call me on <PHONE>.\n"
            "2026-04-03 09:15:42 - Support Agent: Can you confirm your email?\n"
            "2026-04-03 09:15:49 - Guest: <EMAIL>\n"
        )

    def test_non_pii_turns_are_untouched(self) -> None:
        output = process(DEMO_2, reducer=RedactReducer())
        assert "Hello, how can I help?" in output
        assert "Can you confirm your email?" in output

    def test_reduction_is_deterministic(self) -> None:
        assert process(DEMO_2, reducer=RedactReducer()) == process(DEMO_2, reducer=RedactReducer())


class TestOtherStrategiesOnTheSameSlice:
    def test_masking_keeps_structure_and_prefixes(self) -> None:
        output = process(DEMO_2, reducer=MaskReducer())
        for prefix in PREFIXES:
            assert prefix in output
        assert "ma***@example.com" in output
        assert "maria.rossi@example.com" not in output
        assert output.rstrip().endswith("ma***@example.com")

    def test_pseudonymization_links_repeated_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DEFAULT_KEY_ENV, "test-key-not-a-real-secret-0123456789")
        text = (
            "Agent: Contact maria.rossi@example.com about the case.\n"
            "Guest: Yes, maria.rossi@example.com is correct.\n"
        )
        output = process(text, reducer=PseudonymizeReducer(scope_value="demo_dataset"))
        tokens = [word for word in output.split() if word.startswith("EMAIL_")]
        assert len(tokens) == 2
        assert tokens[0].rstrip(".") == tokens[1]
        assert "maria.rossi@example.com" not in output
        assert output.startswith("Agent:")

    def test_transcript_prefixes_survive_every_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEFAULT_KEY_ENV, "test-key-not-a-real-secret-0123456789")
        for reducer in (
            RedactReducer(),
            MaskReducer(),
            PseudonymizeReducer(scope_value="demo_dataset"),
        ):
            output = process(DEMO_2, reducer=reducer)
            for prefix in PREFIXES:
                assert prefix in output, reducer.name

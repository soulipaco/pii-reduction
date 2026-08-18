"""Injection into text this project did not write (Increment D).

The A6 generator knows where every entity is because it rendered the document. These
tests cover the harder case: a base document that already exists, into which entities
are placed and exact spans recorded. If the manifest's offsets drift, every metric
computed from a public-dataset pack is fiction, so the slice-true invariant is asserted
from several directions rather than once.

Base texts here are invented for the test. Injected values come from the committed
synthetic pools (ADR-0014).
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from pii_reduction.entities.taxonomy import ADDRESS, EMAIL, PERSON, PHONE
from pii_reduction.parsers import TranscriptParser
from pii_reduction.providers import DeterministicProvider
from pii_reduction.synthetic.errors import CorpusError, GroundTruthError
from pii_reduction.synthetic.injection import (
    InjectionPlan,
    eligible_offsets,
    inject,
)

pytestmark = pytest.mark.unit

BASE = "I cannot log in to the portal. It fails after the password screen."
TRANSCRIPT = "Agent: How can I help?\nGuest: My order is late.\nAgent: Let me check."

PERSON_PLAN = InjectionPlan(PERSON, ("Please contact {value} about this.",))
EMAIL_PLAN = InjectionPlan(EMAIL, ("Reply to {value} when resolved.",))
PHONE_PLAN = InjectionPlan(PHONE, ("Callback number {value}.",))
ALL_PLANS = (PERSON_PLAN, EMAIL_PLAN, PHONE_PLAN)


def run(text: str = BASE, plans: tuple[InjectionPlan, ...] = ALL_PLANS, **kwargs: object):  # type: ignore[no-untyped-def]
    options: dict[str, object] = {
        "document_id": "doc_0001",
        "language": "en",
        "document_type": "plain",
        "difficulty_tier": 1,
        "seed": 42,
    }
    options.update(kwargs)
    return inject(text, plans, **options)  # type: ignore[arg-type]


class TestSpansAreTrue:
    def test_every_span_slices_back_to_its_own_surface(self) -> None:
        result = run()
        for entity in result.entities:
            assert result.document.text[entity.start : entity.end] == entity.surface

    def test_spans_survive_later_insertions(self) -> None:
        # The failure this guards: an earlier entity's offsets are stale once a second
        # entity is inserted before it. Ten plans give the shifting plenty of chances.
        plans = tuple(PERSON_PLAN for _ in range(10))
        result = run(plans=plans)
        assert len(result.entities) == 10
        for entity in result.entities:
            assert result.document.text[entity.start : entity.end] == entity.surface

    def test_two_entities_of_the_same_type_get_distinct_spans(self) -> None:
        # A search-based implementation would attach both to the first occurrence.
        # Offsets are computed at insertion time precisely to avoid that.
        result = run(plans=(PERSON_PLAN, PERSON_PLAN))
        starts = {entity.start for entity in result.entities}
        assert len(starts) == 2
        for entity in result.entities:
            assert result.document.text[entity.start : entity.end] == entity.surface

    def test_a_drifting_span_is_refused_rather_than_recorded(self) -> None:
        class Liar:
            def person(self, language: str):  # type: ignore[no-untyped-def]
                from pii_reduction.synthetic.values import SyntheticValue

                # Claims a value longer than what is actually rendered.
                return SyntheticValue("person_bad", "Grace Okafor")

        # Rendering the value then mutating the text underneath it is the shape of the
        # bug; simulate it by asking for a phrase that swallows the value.
        with pytest.raises(GroundTruthError, match="does not slice back"):
            from pii_reduction.synthetic.corpus import SyntheticDocument, TruthEntity
            from pii_reduction.synthetic.injection import _verify

            _verify(
                SyntheticDocument(
                    document_id="doc_0001",
                    language="en",
                    document_type="plain",
                    tier=1,
                    split="",
                    text="nothing here",
                ),
                [
                    TruthEntity(
                        document_id="doc_0001",
                        entity_id="doc_0001_e00",
                        entity_type=PERSON,
                        start=0,
                        end=5,
                        surface="Grace Okafor",
                        language="en",
                        difficulty_tier=1,
                        document_type="plain",
                        injection_rule="person_phrase",
                        synthetic_value_id="person_bad",
                    )
                ],
            )

    def test_the_error_names_offsets_and_not_the_value(self) -> None:
        # AGENTS.md rule 8: this code may one day be pointed at real text.
        from pii_reduction.synthetic.corpus import SyntheticDocument, TruthEntity
        from pii_reduction.synthetic.injection import _verify

        with pytest.raises(GroundTruthError) as exc_info:
            _verify(
                SyntheticDocument(
                    document_id="doc_0001",
                    language="en",
                    document_type="plain",
                    tier=1,
                    split="",
                    text="nothing here",
                ),
                [
                    TruthEntity(
                        document_id="doc_0001",
                        entity_id="doc_0001_e00",
                        entity_type=PERSON,
                        start=0,
                        end=5,
                        surface="Grace Okafor",
                        language="en",
                        difficulty_tier=1,
                        document_type="plain",
                        injection_rule="person_phrase",
                        synthetic_value_id="person_bad",
                    )
                ],
            )
        assert "Grace Okafor" not in str(exc_info.value)
        assert "[0, 5)" in str(exc_info.value)


class TestTheBaseTextIsRespected:
    def test_the_original_words_all_survive(self) -> None:
        # Injection inserts; it never edits. A pack whose base text was altered is no
        # longer a test against the public corpus.
        result = run()
        for word in BASE.split():
            assert word in result.document.text

    def test_line_structure_is_preserved(self) -> None:
        result = run(TRANSCRIPT, plans=(PERSON_PLAN,), document_type="transcript")
        assert result.document.text.count("\n") == TRANSCRIPT.count("\n")

    def test_insertions_do_not_fuse_with_neighbouring_text(self) -> None:
        # `...0128.I cannot log in` is not text anyone would write, and the phone
        # recognizer's boundary guard would reject a number glued to a letter — the
        # corpus would be measuring the injector rather than the provider.
        text = run().document.text
        assert ".I" not in text
        assert not any(
            left.isalnum() and right.isalnum() for left, right in pairwise(text) if left in ".!?"
        )


class TestDeterminism:
    def test_the_same_seed_reproduces_the_document(self) -> None:
        assert run().document.text == run().document.text

    def test_a_different_seed_changes_it(self) -> None:
        assert run().document.text != run(seed=7).document.text

    def test_a_repetitive_corpus_does_not_get_the_same_entities_everywhere(self) -> None:
        """Bitext and MASSIVE repeat their templates; a pack must not repeat its values.

        The first version took a shared `ValueProvider` and advanced it per document,
        which made a document's values depend on its *position* in the pack — so the
        same document regenerated differently on its own. Deriving the provider seed
        from `(seed, document_id)` gives variety across the pack and reproducibility
        per document at the same time; they were never actually in conflict.
        """
        surfaces = {
            inject(
                BASE,
                (PERSON_PLAN,),
                document_id=f"doc_{index:04d}",
                language="en",
                document_type="plain",
                difficulty_tier=1,
            )
            .entities[0]
            .surface
            for index in range(20)
        }
        assert len(surfaces) > 1

    def test_a_document_regenerates_identically_on_its_own(self) -> None:
        # ADR-0011: same seed, byte-identical result — without replaying the pack.
        first = run(document_id="doc_0042")
        second = run(document_id="doc_0042")
        assert first.document.text == second.document.text
        assert [e.surface for e in first.entities] == [e.surface for e in second.entities]

    def test_the_split_matches_the_synthetic_corpus_rule(self) -> None:
        # A pack that assigned splits differently would make `--split` mean two things.
        from pii_reduction.synthetic.corpus import split_for

        result = run(document_id="doc_0042")
        assert result.document.split == split_for("doc_0042", 42)
        assert result.document.split in {"dev", "calibration", "test"}


class TestInjectedValuesAreFindable:
    def test_the_deterministic_provider_finds_the_injected_email_and_phone(self) -> None:
        # If the injector produced values the shipped recognizers cannot see, the pack
        # would measure the injector's formatting rather than detection quality.
        result = run()
        found = {
            (match.start, match.end)
            for match in DeterministicProvider().detect(
                result.document.text, language="en", entities=(EMAIL, PHONE)
            )
        }
        expected = {
            (entity.start, entity.end)
            for entity in result.entities
            if entity.entity_type in {EMAIL, PHONE}
        }
        assert expected <= found


class TestPlanValidation:
    def test_address_is_refused_because_nothing_detects_it(self) -> None:
        with pytest.raises(CorpusError, match="ADR-0002"):
            InjectionPlan(ADDRESS, ("at {value}",))

    def test_a_phrase_needs_exactly_one_placeholder(self) -> None:
        with pytest.raises(CorpusError, match="exactly one"):
            InjectionPlan(PERSON, ("no placeholder here",))
        with pytest.raises(CorpusError, match="exactly one"):
            InjectionPlan(PERSON, ("{value} and {value}",))

    def test_a_plan_needs_a_phrase(self) -> None:
        with pytest.raises(CorpusError, match="at least one phrase"):
            InjectionPlan(PERSON, ())

    def test_non_string_text_is_refused(self) -> None:
        with pytest.raises(CorpusError, match="requires str"):
            run(None)  # type: ignore[arg-type]


class TestEligibleOffsets:
    def test_empty_text_still_offers_the_start(self) -> None:
        # A pack of short utterances (MASSIVE) would otherwise receive no entities.
        assert eligible_offsets("") == [0]

    def test_sentence_ends_and_line_starts_are_offered(self) -> None:
        offsets = eligible_offsets("One. Two.\nThree")
        assert 0 in offsets
        assert 5 in offsets  # after "One. "
        assert 10 in offsets  # after the newline

    def test_offsets_stay_inside_the_text(self) -> None:
        text = "One. Two."
        assert all(0 <= offset <= len(text) for offset in eligible_offsets(text))


class TestParsedStructureSurvives:
    """Injection must not destroy the structure the pack exists to measure.

    Found by the session-5 architecture audit. `eligible_offsets` offered every line
    start, so an entity could land *before* a transcript speaker prefix; that line then
    parses as one body with no prefix at all, and a MultiWOZ-style pack quietly stops
    containing transcripts. The old test only counted newlines, which is why it passed.
    """

    @staticmethod
    def prefixes(text: str) -> list[str]:
        return [
            segment.text
            for segment in TranscriptParser().parse(text).segments
            if segment.segment_type == "transcript_prefix"
        ]

    def test_every_speaker_prefix_survives_injection(self) -> None:
        result = inject(
            TRANSCRIPT,
            (PERSON_PLAN, EMAIL_PLAN),
            document_id="mwoz_0001",
            language="en",
            document_type="transcript",
            difficulty_tier=4,
            parser=TranscriptParser(),
        )
        assert self.prefixes(result.document.text) == self.prefixes(TRANSCRIPT)

    def test_injected_spans_land_inside_processable_segments(self) -> None:
        # An entity hidden in a non-processable prefix is guaranteed leakage that no
        # correct pipeline can avoid — it is never offered to a provider.
        parser = TranscriptParser()
        result = inject(
            TRANSCRIPT,
            (PERSON_PLAN, PHONE_PLAN),
            document_id="mwoz_0002",
            language="en",
            document_type="transcript",
            difficulty_tier=4,
            parser=parser,
        )
        regions = [
            (segment.source_start, segment.source_end)
            for segment in parser.parse(result.document.text).processable_segments
            if segment.source_start is not None and segment.source_end is not None
        ]
        for entity in result.entities:
            assert any(start <= entity.start and entity.end <= end for start, end in regions), (
                f"{entity.entity_type} landed outside every processable segment"
            )

    def test_without_a_parser_the_caller_gets_no_structural_guarantee(self) -> None:
        # Documented rather than silently safe: the pack builder must pass the parser
        # its dataset is configured with.
        parser = TranscriptParser()
        offsets = eligible_offsets(TRANSCRIPT)
        guarded = eligible_offsets(TRANSCRIPT, parser=parser)

        regions = [
            (segment.source_start, segment.source_end)
            for segment in parser.parse(TRANSCRIPT).processable_segments
            if segment.source_start is not None and segment.source_end is not None
        ]
        # Every unguarded line start is a *prefix* position here, and none survives.
        assert not set(guarded) & set(offsets)
        assert guarded
        assert all(any(start <= at <= end for start, end in regions) for at in guarded)

    def test_a_turn_with_no_sentence_break_can_still_receive_an_entity(self) -> None:
        """Region starts are candidates, so entities are not all funnelled into one turn.

        Restricting to sentence breaks alone would leave a short turn — `Guest: My order
        is late.` has no *internal* break — with nowhere to put an entity, so a two-turn
        document would put every name in whichever turn happened to be longest.
        """
        parser = TranscriptParser()
        guarded = eligible_offsets(TRANSCRIPT, parser=parser)
        starts = {
            segment.source_start
            for segment in parser.parse(TRANSCRIPT).processable_segments
            if segment.source_start is not None
        }
        assert starts <= set(guarded)

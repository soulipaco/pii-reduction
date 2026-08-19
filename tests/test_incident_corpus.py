"""The incident-notes stress corpus (ADR-0022).

Default tier: generating and validating the corpus needs no model. What the *pipeline*
does to it is a gate set (`configs/incident_gates.yaml`), not a test — landing in the
commit after this one, because a gate file must name the commit its floors were
measured against and a commit cannot name its own.

These tests hold three things the corpus would be worthless without: that it is
reproducible, that it actually carries the identifier density it was built for, and
that the two findings it produced are recorded as tests rather than only as prose.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from pii_reduction.entities.taxonomy import PERSON
from pii_reduction.parsers.registry import build_parser
from pii_reduction.patterns import is_identifier_shaped
from pii_reduction.synthetic.corpus import build_corpus, load_corpus
from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.incidents import INCIDENT_TEMPLATES, incident_templates

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
INCIDENTS_DIR = REPO_ROOT / "tests" / "fixtures" / "incidents"

#: The benchmark corpus's density, which this corpus exists to improve on.
BENCHMARK_TOKENS_PER_DOCUMENT = 1.0


@pytest.fixture(scope="module")
def corpus():  # type: ignore[no-untyped-def]
    return load_corpus(INCIDENTS_DIR)


class TestItIsReproducible:
    def test_the_committed_corpus_regenerates_exactly(self, corpus) -> None:  # type: ignore[no-untyped-def]
        rebuilt = build_corpus(
            seed=corpus.meta["seed"],
            documents_per_language=corpus.meta["documents_per_language"],
            templates=incident_templates,
            id_prefix="inc",
            profile="incident_notes",
        )
        assert [d.text for d in rebuilt.documents] == [d.text for d in corpus.documents]
        assert [e.surface for e in rebuilt.entities] == [e.surface for e in corpus.entities]
        assert [p.token for p in rebuilt.protected] == [p.token for p in corpus.protected]

    def test_it_records_which_profile_generated_it(self, corpus) -> None:  # type: ignore[no-untyped-def]
        # Two corpora now come out of `build_corpus`; a corpus that cannot say which
        # one it is could be scored against the wrong gate file without complaint.
        assert corpus.meta["profile"] == "incident_notes"

    def test_its_ids_cannot_be_confused_with_the_benchmark_corpus(self, corpus) -> None:  # type: ignore[no-untyped-def]
        assert all(d.document_id.startswith("inc_") for d in corpus.documents)


class TestItStressesWhatItClaimsTo:
    """Without density this corpus is just a second synthetic corpus."""

    def test_it_carries_far_more_identifiers_per_document(self, corpus) -> None:  # type: ignore[no-untyped-def]
        per_document = len(corpus.protected) / len(corpus.documents)
        assert per_document > 5 * BENCHMARK_TOKENS_PER_DOCUMENT, (
            f"{per_document:.2f} protected tokens per document; the benchmark corpus "
            "already carries 1.00, so this corpus would add nothing"
        )

    def test_every_document_carries_identifiers(self, corpus) -> None:  # type: ignore[no-untyped-def]
        # On the benchmark corpus only 66 of 102 documents have any protected token.
        with_tokens = {token.document_id for token in corpus.protected}
        assert with_tokens == {document.document_id for document in corpus.documents}

    def test_it_spans_more_identifier_kinds_than_any_other_corpus(self, corpus) -> None:  # type: ignore[no-untyped-def]
        # Equality, not a subset: the first version of this asserted `>=` and sat beside
        # prose claiming eight kinds when the corpus carries seven. A subset assertion
        # cannot catch a count the documentation overstates.
        kinds = set(Counter(token.kind for token in corpus.protected))
        assert kinds == {"ticket", "kb", "machine", "version", "change", "request", "asset"}

    def test_every_protected_token_is_identifier_shaped(self, corpus) -> None:  # type: ignore[no-untyped-def]
        # The reconciler's guard is what protects these. A token the guard cannot
        # recognize would make an over-redaction number that says nothing about it.
        not_recognized = sorted(
            {token.token for token in corpus.protected if not is_identifier_shaped(token.token)}
        )
        assert not_recognized == []

    def test_all_three_languages_are_present(self, corpus) -> None:  # type: ignore[no-untyped-def]
        assert {d.language for d in corpus.documents} == {"en", "de", "el"}


class TestTheFindingsItProduced:
    """Both were invisible to every corpus that existed before this one."""

    def test_a_work_note_author_is_never_offered_to_a_provider(self, corpus) -> None:  # type: ignore[no-untyped-def]
        """The tier-4 leak, pinned structurally rather than as a metric.

        The transcript parser treats `2026-04-03 09:12:04 - Peter Novak:` as structure.
        That is right when a speaker label is a role (`Customer`, `Πελάτης`) — what the
        benchmark corpus uses — and wrong when the author is a person. Those names
        cannot be redacted by any provider or repair rule, which is why PERSON recall
        is 0.000 at tier 4 in all three languages.

        If this test ever fails, the parser's structure/body split has changed and
        ADR-0022's explanation of that 0.000 is stale.
        """
        parser = build_parser("transcript", {})
        unreachable = 0
        for document in corpus.documents:
            if document.document_type != "transcript":
                continue
            parsed = parser.parse(document.text)
            spans = [
                (segment.source_start, segment.source_start + len(segment.text))
                for segment in parsed.processable_segments
                if segment.source_start is not None
            ]
            for entity in corpus.entities:
                if entity.document_id != document.document_id or entity.entity_type != PERSON:
                    continue
                if not any(start <= entity.start < end for start, end in spans):
                    unreachable += 1
        assert unreachable > 0, (
            "no tier-4 PERSON sits in the speaker prefix any more; the gate file's "
            "explanation of PERSON tier-4 recall 0.000 needs rewriting"
        )

    def test_the_identifier_guard_passes_a_span_that_mixes_a_word_and_an_id(self) -> None:
        """The over-redaction finding, pinned at its cause.

        14 Greek ticket ids are destroyed because a PERSON span covers
        `Περιστατικό INC…`, and the guard refuses a span only when *no* token is
        name-like. That asymmetry is deliberate (`patterns.py`): it prefers
        over-redacting a year to leaking a name. This records the price.

        13 of the 14 spans are native `PERSON` labels from the base model and survive
        `promote: []`; one is promotion-attributable. The first draft of ADR-0022 said
        the opposite, having probed a single document.
        """
        assert is_identifier_shaped("INC00102257")
        assert not is_identifier_shaped("Περιστατικό INC00102257")


class TestStructureIsPreserved:
    def test_every_document_round_trips_byte_for_byte(self, corpus) -> None:  # type: ignore[no-untyped-def]
        """AGENTS.md rule 5, on the two shapes the parser fixtures do not cover.

        This corpus adds an em-dash header line with no speaker delimiter and a
        timestamped *author* prefix. It matters more here than elsewhere: the eventual
        fix for the tier-4 leak has to reach into that prefix, and this is what says it
        did not damage the reconstruction while doing so.
        """
        for document in corpus.documents:
            parser = build_parser(
                "transcript" if document.document_type == "transcript" else "plain_text", {}
            )
            parsed = parser.parse(document.text)
            assert parser.reconstruct(parsed, {}) == document.text, document.document_id


class TestTemplates:
    def test_an_unknown_language_is_refused_with_the_known_ones(self) -> None:
        with pytest.raises(CorpusError, match="no incident templates"):
            incident_templates("fr")

    def test_every_language_has_a_header_and_a_note_history(self) -> None:
        for language, specs in INCIDENT_TEMPLATES.items():
            tiers = {spec.tier for spec in specs}
            assert tiers == {3, 4}, f"{language}: expected a tier-3 header and tier-4 notes"

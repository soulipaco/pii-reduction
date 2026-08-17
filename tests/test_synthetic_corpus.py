"""Synthetic corpus generation and ground-truth loading."""

from __future__ import annotations

import json
from pathlib import Path

import phonenumbers
import pytest

from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.synthetic import (
    CorpusError,
    GroundTruthError,
    PoolValueProvider,
    build_corpus,
    load_corpus,
    write_corpus,
)
from pii_reduction.synthetic.corpus import CORPUS_FILE, MANIFEST_FILE, META_FILE, PROTECTED_FILE
from pii_reduction.synthetic.values import PHONES

pytestmark = pytest.mark.unit

COMMITTED_CORPUS = Path(__file__).resolve().parent / "fixtures" / "corpus"


class TestGeneration:
    def test_generates_the_requested_size_across_languages(self) -> None:
        corpus = build_corpus(seed=7, documents_per_language=6)
        assert len(corpus.documents) == 18
        assert {document.language for document in corpus.documents} == {"en", "de", "el"}

    def test_covers_all_four_difficulty_tiers(self) -> None:
        corpus = build_corpus(seed=7, documents_per_language=12)
        assert {document.tier for document in corpus.documents} == {1, 2, 3, 4}

    def test_covers_both_document_types(self) -> None:
        corpus = build_corpus(seed=7, documents_per_language=12)
        assert {document.document_type for document in corpus.documents} == {"plain", "transcript"}

    def test_injects_all_three_entity_types(self) -> None:
        corpus = build_corpus(seed=7, documents_per_language=12)
        assert {entity.entity_type for entity in corpus.entities} == {PERSON, EMAIL, PHONE}

    def test_emits_protected_non_pii_tokens(self) -> None:
        corpus = build_corpus(seed=7, documents_per_language=12)
        kinds = {token.kind for token in corpus.protected}
        assert kinds <= {"ticket", "kb", "machine", "version", "order"}
        assert kinds

    def test_splits_are_deterministic_and_cover_the_documented_ratio(self) -> None:
        corpus = build_corpus(seed=42, documents_per_language=40)
        splits = [document.split for document in corpus.documents]
        assert set(splits) == {"dev", "calibration", "test"}
        # 20/20/60 by seeded hash (ADR-0011); exact counts vary with the sample.
        assert splits.count("test") > splits.count("dev")
        again = build_corpus(seed=42, documents_per_language=40)
        assert [document.split for document in again.documents] == splits

    def test_rejects_a_nonsensical_size(self) -> None:
        with pytest.raises(CorpusError):
            build_corpus(seed=1, documents_per_language=0)


class TestGroundTruth:
    def test_every_span_slices_to_its_injected_value(self) -> None:
        corpus = build_corpus(seed=11, documents_per_language=12)
        texts = corpus.texts()
        for entity in corpus.entities:
            assert texts[entity.document_id][entity.start : entity.end] == entity.surface

    def test_every_protected_span_slices_to_its_token(self) -> None:
        corpus = build_corpus(seed=11, documents_per_language=12)
        texts = corpus.texts()
        for token in corpus.protected:
            assert texts[token.document_id][token.start : token.end] == token.token

    def test_offsets_survive_non_latin_text(self) -> None:
        # Greek documents shift every subsequent offset; spans are codepoint indices
        # measured at injection time, so they must still slice true (ADR-0011).
        corpus = build_corpus(seed=11, documents_per_language=12)
        greek = [entity for entity in corpus.entities if entity.language == "el"]
        assert greek
        texts = corpus.texts()
        for entity in greek:
            assert texts[entity.document_id][entity.start : entity.end] == entity.surface

    def test_all_pooled_phone_numbers_are_valid(self) -> None:
        for numbers in PHONES.values():
            for number in numbers:
                assert phonenumbers.is_valid_number(phonenumbers.parse(number, None))

    def test_emails_use_reserved_domains(self) -> None:
        corpus = build_corpus(seed=11, documents_per_language=12)
        for entity in corpus.entities:
            if entity.entity_type == EMAIL:
                assert entity.surface.endswith(("example.com", "example.org", "example.net"))


class TestDeterminism:
    def test_same_seed_gives_identical_documents(self) -> None:
        first = build_corpus(seed=42, documents_per_language=10)
        second = build_corpus(seed=42, documents_per_language=10)
        assert first.documents == second.documents
        assert first.entities == second.entities
        assert first.protected == second.protected

    def test_different_seeds_give_different_values(self) -> None:
        first = build_corpus(seed=1, documents_per_language=10)
        second = build_corpus(seed=2, documents_per_language=10)
        assert first.documents != second.documents

    def test_regenerating_is_byte_identical_on_disk(self, tmp_path: Path) -> None:
        one = tmp_path / "one"
        two = tmp_path / "two"
        write_corpus(build_corpus(seed=42, documents_per_language=10), one)
        write_corpus(build_corpus(seed=42, documents_per_language=10), two)
        for name in (CORPUS_FILE, MANIFEST_FILE, PROTECTED_FILE, META_FILE):
            assert (one / name).read_bytes() == (two / name).read_bytes(), name

    def test_value_provider_is_seeded(self) -> None:
        first = PoolValueProvider(5)
        second = PoolValueProvider(5)
        assert [first.person("en").text for _ in range(5)] == [
            second.person("en").text for _ in range(5)
        ]


class TestRoundTrip:
    def test_written_corpus_loads_back_identically(self, tmp_path: Path) -> None:
        corpus = build_corpus(seed=3, documents_per_language=10)
        write_corpus(corpus, tmp_path / "corpus")
        loaded = load_corpus(tmp_path / "corpus")
        assert loaded.documents == corpus.documents
        assert loaded.entities == corpus.entities
        assert loaded.protected == corpus.protected

    def test_transcript_newlines_survive_the_csv_round_trip(self, tmp_path: Path) -> None:
        corpus = build_corpus(seed=3, documents_per_language=12)
        write_corpus(corpus, tmp_path / "corpus")
        loaded = load_corpus(tmp_path / "corpus")
        transcripts = [d for d in loaded.documents if d.document_type == "transcript"]
        assert transcripts
        for document in transcripts:
            assert document.text.count("\n") >= 3

    def test_missing_corpus_directory_is_actionable(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusError) as exc_info:
            load_corpus(tmp_path / "nothing")
        assert "corpus not found" in str(exc_info.value)


class TestManifestValidation:
    def test_a_shifted_span_is_rejected(self, tmp_path: Path) -> None:
        directory = tmp_path / "corpus"
        write_corpus(build_corpus(seed=3, documents_per_language=6), directory)
        manifest = directory / MANIFEST_FILE
        lines = manifest.read_text(encoding="utf-8").splitlines()
        header = lines[0].split(",")
        start_index = header.index("start")
        cells = lines[1].split(",")
        cells[start_index] = str(int(cells[start_index]) + 1)
        lines[1] = ",".join(cells)
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")

        with pytest.raises(GroundTruthError):
            load_corpus(directory)

    def test_rejection_reports_offsets_but_never_the_expected_value(self, tmp_path: Path) -> None:
        # A manifest loader must stay privacy-safe even when pointed at truth for
        # data that is not synthetic (session-2 privacy review, ADR-0011).
        directory = tmp_path / "corpus"
        corpus = build_corpus(seed=3, documents_per_language=6)
        write_corpus(corpus, directory)
        manifest = directory / MANIFEST_FILE
        lines = manifest.read_text(encoding="utf-8").splitlines()
        header = lines[0].split(",")
        cells = lines[1].split(",")
        cells[header.index("start")] = str(int(cells[header.index("start")]) + 1)
        surface = cells[header.index("surface")]
        lines[1] = ",".join(cells)
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")

        with pytest.raises(GroundTruthError) as exc_info:
            load_corpus(directory)
        message = str(exc_info.value)
        assert surface not in message
        assert "document" in message
        assert "does not match the injected value" in message


class TestCommittedCorpus:
    """The corpus under ``tests/fixtures/corpus`` is the deterministic regression set."""

    def test_it_exists_and_loads(self) -> None:
        corpus = load_corpus(COMMITTED_CORPUS)
        assert len(corpus.documents) == 102
        assert len(corpus.entities) == 180

    def test_it_matches_what_the_generator_produces(self) -> None:
        meta = json.loads((COMMITTED_CORPUS / META_FILE).read_text(encoding="utf-8"))
        regenerated = build_corpus(
            seed=int(meta["seed"]),
            documents_per_language=int(meta["documents_per_language"]),
        )
        loaded = load_corpus(COMMITTED_CORPUS)
        assert loaded.documents == regenerated.documents
        assert loaded.entities == regenerated.entities

    def test_it_contains_no_real_looking_domains(self) -> None:
        corpus = load_corpus(COMMITTED_CORPUS)
        for entity in corpus.entities:
            if entity.entity_type == EMAIL:
                assert "example." in entity.surface

"""Demo packs: public text this project did not write, with exact ground truth.

The pack builder is the first real caller of ``inject()``. What has to hold is what
every metric computed from a pack rests on: the manifest slices back to the document,
the protected tokens survive the injection that moved them, the base text is not edited,
and two builds of the same pack are byte-identical.

**No test here reaches the network.** Each builds from a tiny table written into
``tmp_path`` and a registry pointed at it, so the whole path — licence gate, cache
lookup, reader, injection, manifest — runs offline. The fixture text is invented for
the test; the real corpora are downloaded, never committed (ADR-0017).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
import yaml

from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.parsers.transcript import TranscriptParser
from pii_reduction.synthetic.corpus import load_corpus, write_corpus
from pii_reduction.synthetic.errors import CorpusError, DatasetDownloadError
from pii_reduction.synthetic.packs import PACKS, build_pack, pack_spec
from pii_reduction.synthetic.public import read_bitext, read_massive, substitute_order_numbers
from pii_reduction.synthetic.values import PoolValueProvider

pytestmark = pytest.mark.unit

BITEXT_REPO = "bitext/Bitext-customer-support-llm-chatbot-training-dataset"
MASSIVE_REPO = "AmazonScience/massive"
BITEXT_FILE = "table.csv"
REVISION = "b" * 40

#: Invented support text. Row 3 carries a placeholder that is not an order number, so
#: the reader must exclude it rather than leave `{{Person Name}}` in a document.
ROWS = [
    ("i cannot log in to my account", "I am sorry to hear that. Please try a reset first."),
    (
        "where is order {{Order Number}}",
        "Order {{Order Number}} shipped yesterday. It arrives soon.",
    ),
    ("i want to cancel", "Certainly. I can cancel it for you. Anything else?"),
    ("who is my agent", "Your agent is {{Person Name}}. They will be in touch."),
    ("my invoice looks wrong", "Let me check the invoice. I will come back to you today."),
    ("how do i change my address", "You can change it in settings. I can also do it here."),
]

UTTERANCES = [
    "schalte bitte die lichter aus",
    "wie ist das wetter morgen",
    "spiel den nächsten song",
    "erinnere mich an den termin",
]


def _write_registry(tmp_path: Path, cache: Path) -> Path:
    """A registry whose retrieval blocks point at the fixture files, checksums and all."""
    datasets = {}
    for key, repository, files in (
        ("bitext_customer_support", BITEXT_REPO, [("table", BITEXT_FILE)]),
        ("massive", MASSIVE_REPO, [("de", "de-DE/0000.parquet"), ("el", "el-GR/0000.parquet")]),
    ):
        entries = []
        for role, name in files:
            payload = (cache / repository / name).read_bytes()
            entries.append(
                {
                    "role": role,
                    "path": name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            )
        datasets[key] = {
            "name": f"{key} fixture",
            "source_url": f"https://huggingface.co/datasets/{repository}",
            "license": "MIT",
            "redistribution_allowed": True,
            "contains_real_pii": False,
            "retrieval_method": "huggingface",
            "version": "test",
            "document_type": "plain",
            "languages": ["en"],
            "retrieval": {"repository": repository, "revision": REVISION, "files": entries},
        }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "datasets": datasets}), encoding="utf-8")
    return path


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    """A populated cache and a registry that matches it. Returns (registry, cache)."""
    cache = tmp_path / "cache"
    table = cache / BITEXT_REPO / BITEXT_FILE
    table.parent.mkdir(parents=True)
    pd.DataFrame(ROWS, columns=["instruction", "response"]).to_csv(
        table, index=False, encoding="utf-8", lineterminator="\n"
    )
    for language, folder in (("de", "de-DE"), ("el", "el-GR")):
        parquet = cache / MASSIVE_REPO / folder / "0000.parquet"
        parquet.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"utt": UTTERANCES, "locale": [language] * len(UTTERANCES)}).to_parquet(
            parquet
        )
    return _write_registry(tmp_path, cache), cache


def build(key: str, sources: tuple[Path, Path], **kwargs: object):  # type: ignore[no-untyped-def]
    registry, cache = sources
    options: dict[str, object] = {"documents": 4, "allow_download": False}
    options.update(kwargs)
    return build_pack(key, registry_path=registry, cache_dir=cache, **options)  # type: ignore[arg-type]


class TestTheGroundTruthIsTrue:
    def test_every_manifest_span_slices_back_to_its_value(self, sources: tuple[Path, Path]) -> None:
        corpus = build("support_tickets", sources)
        texts = corpus.texts()
        for entity in corpus.entities:
            assert texts[entity.document_id][entity.start : entity.end] == entity.surface

    def test_every_protected_span_slices_back_to_its_token(
        self, sources: tuple[Path, Path]
    ) -> None:
        # These moved: they were recorded against the base text, then injection inserted
        # phrases around them. A drifted one reports over-redaction that never happened.
        corpus = build("support_tickets", sources)
        texts = corpus.texts()
        assert corpus.protected
        for token in corpus.protected:
            assert texts[token.document_id][token.start : token.end] == token.token

    def test_a_written_pack_reloads_and_revalidates(
        self, sources: tuple[Path, Path], tmp_path: Path
    ) -> None:
        # load_corpus re-checks every span, so this is the pack's own acceptance test.
        corpus = build("support_tickets", sources)
        write_corpus(corpus, tmp_path / "pack")
        assert len(load_corpus(tmp_path / "pack").entities) == len(corpus.entities)

    def test_a_pack_with_no_protected_tokens_still_round_trips(
        self, sources: tuple[Path, Path], tmp_path: Path
    ) -> None:
        # MASSIVE carries no identifiers. A headerless empty CSV cannot be read back, so
        # this is the case that would break `load_corpus` on a perfectly valid pack.
        corpus = build("multilingual_utterances", sources)
        assert corpus.protected == ()
        write_corpus(corpus, tmp_path / "pack")
        assert load_corpus(tmp_path / "pack").protected == ()


class TestTheSourceTextIsRespected:
    def test_placeholders_are_gone_and_recorded(self, sources: tuple[Path, Path]) -> None:
        corpus = build("support_tickets", sources)
        assert not any("{{" in document.text for document in corpus.documents)

    def test_a_row_with_an_unfillable_placeholder_is_excluded(
        self, sources: tuple[Path, Path]
    ) -> None:
        # `{{Person Name}}` has no value pool and is not an identifier. Leaving it in
        # would put a PII-shaped token in the text that the manifest knows nothing about,
        # so every provider that found it would score as a false positive.
        corpus = build("support_tickets", sources, documents=5)
        assert not any("Person Name" in document.text for document in corpus.documents)

    def test_the_original_wording_survives(self, sources: tuple[Path, Path]) -> None:
        corpus = build("support_tickets", sources)
        joined = " ".join(document.text for document in corpus.documents)
        assert "I am sorry to hear that." in joined or "Certainly." in joined

    def test_transcript_prefixes_survive_injection(self, sources: tuple[Path, Path]) -> None:
        corpus = build("support_conversations", sources)
        parser = TranscriptParser({"preserve_prefix": True, "fallback": "preserve_line"})
        for document in corpus.documents:
            prefixes = [
                segment.text
                for segment in parser.parse(document.text).segments
                if segment.segment_type == "transcript_prefix"
            ]
            assert "Customer:" in " ".join(prefixes)
            assert "Agent:" in " ".join(prefixes)

    def test_entities_land_where_the_pipeline_will_look(self, sources: tuple[Path, Path]) -> None:
        # An entity hidden in a speaker prefix is guaranteed leakage no pipeline can
        # avoid, and the pack would report a detection failure that is a generator bug.
        corpus = build("support_conversations", sources)
        parser = TranscriptParser({"preserve_prefix": True, "fallback": "preserve_line"})
        texts = corpus.texts()
        for entity in corpus.entities:
            regions = [
                (segment.source_start, segment.source_end)
                for segment in parser.parse(texts[entity.document_id]).processable_segments
                if segment.source_start is not None and segment.source_end is not None
            ]
            assert any(start <= entity.start and entity.end <= end for start, end in regions)


class TestDeterminism:
    def test_two_builds_agree_exactly(self, sources: tuple[Path, Path]) -> None:
        assert build("support_tickets", sources) == build("support_tickets", sources)

    def test_a_different_seed_changes_the_pack(self, sources: tuple[Path, Path]) -> None:
        assert build("support_tickets", sources) != build("support_tickets", sources, seed=7)

    def test_a_repetitive_source_does_not_get_one_name_everywhere(
        self, sources: tuple[Path, Path]
    ) -> None:
        """The failure the value pools would hit head-on.

        Bitext and MASSIVE both repeat their templates heavily. Values derive from the
        document id rather than from a provider's position in the run, so two documents
        with similar text still receive different entities.
        """
        corpus = build("support_tickets", sources)
        names = {entity.surface for entity in corpus.entities if entity.entity_type == PERSON}
        assert len(names) > 1

    def test_the_two_english_packs_hold_the_same_source_rows(
        self, sources: tuple[Path, Path]
    ) -> None:
        # ADR-0018: a difference between their numbers must be a difference in parsing,
        # not in sampling, so selection deliberately ignores the layout.
        tickets = build("support_tickets", sources)
        conversations = build("support_conversations", sources)
        assert [document.document_id for document in tickets.documents] == [
            document.document_id for document in conversations.documents
        ]


class TestProvenanceTravelsWithThePack:
    def test_the_meta_names_the_bytes_it_was_built_from(self, sources: tuple[Path, Path]) -> None:
        # A published number is only reproducible if the source can be named exactly.
        meta = build("support_tickets", sources).meta
        assert meta["source_revision"] == REVISION
        assert meta["source_repository"] == BITEXT_REPO
        assert meta["license"] == "MIT"
        assert meta["contains_real_pii"] is False
        assert isinstance(meta["source_files"], list) and meta["source_files"]

    def test_the_transformation_is_recorded(self, sources: tuple[Path, Path]) -> None:
        # docs/02_PUBLIC_DATA_STRATEGY.md requires it per dataset.
        assert "Order Number" in str(build("support_tickets", sources).meta["transformation"])
        assert "unedited" in str(build("multilingual_utterances", sources).meta["transformation"])


class TestRefusals:
    def test_an_unknown_pack_lists_the_known_ones(self) -> None:
        with pytest.raises(CorpusError, match="unknown pack"):
            pack_spec("incident_notes")

    def test_a_rejected_dataset_cannot_be_built_from(self, tmp_path: Path) -> None:
        # The gate that keeps a corpus carrying real PII out of a published benchmark.
        registry = tmp_path / "registry.yaml"
        registry.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "datasets": {"other": _minimal()},
                    "rejected": {"bitext_customer_support": {"reason": "example reason"}},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(CorpusError, match="examined and rejected"):
            build_pack("support_tickets", registry_path=registry, cache_dir=tmp_path)

    def test_an_absent_download_is_not_silently_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        table = cache / BITEXT_REPO / BITEXT_FILE
        table.parent.mkdir(parents=True)
        pd.DataFrame(ROWS, columns=["instruction", "response"]).to_csv(table, index=False)
        for language in ("de-DE", "el-GR"):
            parquet = cache / MASSIVE_REPO / language / "0000.parquet"
            parquet.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"utt": UTTERANCES}).to_parquet(parquet)
        registry = _write_registry(tmp_path, cache)
        table.unlink()

        with pytest.raises(DatasetDownloadError, match="not in the cache"):
            build_pack(
                "support_tickets",
                registry_path=registry,
                cache_dir=cache,
                documents=2,
                allow_download=False,
            )

    def test_asking_for_more_documents_than_exist_is_an_error(
        self, sources: tuple[Path, Path]
    ) -> None:
        # Rather than a quietly short pack, whose per-slice supports would be wrong.
        with pytest.raises(CorpusError, match="eligible rows are available"):
            build("support_tickets", sources, documents=500)


class TestTheReaders:
    def test_order_numbers_are_recorded_where_they_were_written(self) -> None:
        text, tokens = substitute_order_numbers(
            "order {{Order Number}} and {{Order Number}}",
            document_id="doc_0001",
            provider=PoolValueProvider(seed=1),
        )
        assert "{{" not in text
        assert len(tokens) == 2
        for token in tokens:
            assert text[token.start : token.end] == token.token

    def test_an_unknown_layout_is_refused(self, sources: tuple[Path, Path]) -> None:
        _, cache = sources
        with pytest.raises(CorpusError, match="unknown bitext layout"):
            read_bitext(
                cache / BITEXT_REPO / BITEXT_FILE, count=1, layout="markdown", id_prefix="x"
            )

    def test_a_table_of_the_wrong_shape_names_the_pin(self, tmp_path: Path) -> None:
        # The failure mode when a revision is bumped without checking the reader.
        wrong = tmp_path / "wrong.csv"
        pd.DataFrame({"text": ["hello"]}).to_csv(wrong, index=False)
        with pytest.raises(CorpusError, match="does not match the reader"):
            read_bitext(wrong, count=1, layout="note", id_prefix="x")
        with pytest.raises(CorpusError, match="does not match the reader"):
            read_massive(wrong, language="de", count=1, id_prefix="x")

    def test_utterances_are_taken_as_written(self, sources: tuple[Path, Path]) -> None:
        _, cache = sources
        documents = read_massive(
            cache / MASSIVE_REPO / "de-DE" / "0000.parquet",
            language="de",
            count=3,
            id_prefix="utt",
        )
        assert [document.text for document in documents] == sorted(
            [document.text for document in documents], key=UTTERANCES.index
        )
        assert all(document.language == "de" for document in documents)


class TestTheShippedPackSpecs:
    def test_every_pack_names_a_dataset_the_registry_knows(self) -> None:
        from pii_reduction.synthetic.registry import load_registry

        known = set(load_registry("demo/registry.yaml"))
        assert {spec.dataset for spec in PACKS.values()} <= known

    def test_every_pack_has_phrases_for_every_language_it_claims(self) -> None:
        for spec in PACKS.values():
            for language in spec.languages:
                assert set(spec.phrases[language]) == {PERSON, EMAIL, PHONE}

    def test_the_transcript_pack_uses_the_document_type_the_benchmark_configures(self) -> None:
        # `benchmark.DEFAULT_DATASETS` maps document_type to a dataset config, so a pack
        # whose type is not in that map would silently score zero documents.
        from pii_reduction.benchmark import DEFAULT_DATASETS

        assert {spec.document_type for spec in PACKS.values()} <= set(DEFAULT_DATASETS)


def _minimal() -> dict[str, object]:
    return {
        "name": "other",
        "source_url": "https://example.com/x",
        "license": "MIT",
        "redistribution_allowed": True,
        "contains_real_pii": False,
        "retrieval_method": "manual",
        "version": "1",
        "document_type": "plain",
        "languages": ["en"],
    }

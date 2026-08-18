"""Demo packs: public text, synthetic PII, exact ground truth.

A pack is a :class:`~pii_reduction.synthetic.corpus.Corpus` like the committed
synthetic one — same files, same manifest contract, so ``pii-reduction benchmark
--corpus <pack>`` scores it with no special case anywhere in the evaluator. The only
difference is where the words came from, which is the whole point: the committed corpus
is templates this project wrote, and a provider that does well on those has only been
asked an easy question.

Three packs (ADR-0010, amended by ADR-0018):

===========================  ========  =========  ======  ==================================
pack                         source    type       tier    what it is for
===========================  ========  =========  ======  ==================================
``support_tickets``          Bitext    plain      1       free-text support notes, English
``support_conversations``    Bitext    transcript 4       the same exchanges as turns
``multilingual_utterances``  MASSIVE   plain      2       short lower-case German and Greek
===========================  ========  =========  ======  ==================================

**No pack is committed.** Each is rebuilt from a pinned, checksummed source (ADR-0017)
and written under ``demo/packs/``, which ``.gitignore`` excludes. That is what
``version`` and ``retrieval`` in ``demo/registry.yaml`` are for, and it is why the pack
meta records the source revision: a number published from a pack must be traceable to
the exact bytes it was measured on.

The two English packs are the same sentences under two parsers. A difference between
their numbers is attributable to *parsing*, which is worth knowing — but they are not
two independent corpora, and nothing may report them as agreeing evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.parsers.base import Parser
from pii_reduction.parsers.plain_text import PlainTextParser
from pii_reduction.parsers.transcript import TranscriptParser
from pii_reduction.synthetic.corpus import Corpus, ProtectedToken, SyntheticDocument, TruthEntity
from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.fetch import DEFAULT_CACHE_DIR, fetch
from pii_reduction.synthetic.injection import InjectionPlan, inject
from pii_reduction.synthetic.public import BaseDocument, read_bitext, read_massive
from pii_reduction.synthetic.registry import DatasetEntry, require_publishable

__all__ = [
    "DEFAULT_REGISTRY",
    "PACKS",
    "PACK_VERSION",
    "PackSpec",
    "build_pack",
    "pack_spec",
]

DEFAULT_REGISTRY = Path("demo/registry.yaml")

#: Bumped when a change would alter a pack's bytes for an unchanged source and seed.
PACK_VERSION = "1"

#: Entity types are rotated across documents rather than all injected into every one.
#: A short MASSIVE utterance carrying a name, an address and a phone number is no longer
#: a MASSIVE utterance; rotating keeps each type's support up without burying the
#: public text under injected phrases.
ROTATION = (PERSON, EMAIL, PHONE)

#: Phrasing per language, in the register of the pack it belongs to. The recorded span
#: covers the value only, so the phrase itself is ordinary text a recognizer may ignore
#: — but it still has to read like the corpus around it, or the pack measures how well
#: a provider spots an out-of-place sentence.
SUPPORT_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        PERSON: (
            "My name is {value}.",
            "The account holder is {value}.",
            "Please pass this to {value}.",
            "I spoke to {value} about it yesterday.",
        ),
        EMAIL: (
            "You can reach me at {value}.",
            "My email address is {value}.",
            "Please copy {value} on the reply.",
        ),
        PHONE: (
            "My number is {value}.",
            "Please call me on {value}.",
            "The best callback number is {value}.",
        ),
    }
}

#: MASSIVE is lower case and unpunctuated, so its phrases are too. A capitalised,
#: full-stopped sentence dropped into a lower-case utterance is a cue no real corpus
#: would give, and the pack would measure the seam rather than the recognizer.
UTTERANCE_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "de": {
        PERSON: ("mein name ist {value}", "sag {value} bescheid", "das ist für {value}"),
        EMAIL: ("meine mailadresse ist {value}", "schick das an {value}"),
        PHONE: ("meine nummer ist {value}", "ruf mich unter {value} an"),
    },
    "el": {
        PERSON: ("με λένε {value}", "πες το στον/στην {value}", "είναι για {value}"),
        EMAIL: ("το email μου είναι {value}", "στειλ' το στο {value}"),
        PHONE: ("το τηλεφωνο μου ειναι {value}", "παρε με στο {value}"),
    },
}


@dataclass(frozen=True)
class PackSpec:
    """Everything that is true of a pack rather than of one of its documents.

    The split between this and :func:`~pii_reduction.synthetic.injection.inject`'s
    arguments is the answer to the design question session 5 left open: document id,
    language and split vary per document; document type, tier, seed and phrasing do
    not, and belong here where they are stated once.
    """

    key: str
    dataset: str
    description: str
    document_type: str
    difficulty_tier: int
    documents: int
    languages: tuple[str, ...]
    entities_per_document: int
    phrases: dict[str, dict[str, tuple[str, ...]]]
    layout: str = ""
    #: Document id prefix. Defaults to the pack key, but the two Bitext packs share one
    #: on purpose: the same source row becomes the same document id, so it receives the
    #: same injected values and the same split in both, and a difference between their
    #: numbers is a difference in parsing rather than in sampling (ADR-0018).
    id_prefix: str = ""

    @property
    def ids(self) -> str:
        return self.id_prefix or self.key

    def __post_init__(self) -> None:
        if self.documents % len(self.languages):
            raise CorpusError(
                f"pack {self.key!r}: {self.documents} documents do not divide evenly "
                f"across {len(self.languages)} languages, so one would be under-measured"
            )
        missing = sorted(set(self.languages) - set(self.phrases))
        if missing:
            raise CorpusError(f"pack {self.key!r}: no injection phrases for {', '.join(missing)}")

    @property
    def documents_per_language(self) -> int:
        return self.documents // len(self.languages)


PACKS: dict[str, PackSpec] = {
    "support_tickets": PackSpec(
        key="support_tickets",
        dataset="bitext_customer_support",
        description="English support notes: customer message and agent reply as free text.",
        document_type="plain",
        difficulty_tier=1,
        documents=200,
        languages=("en",),
        entities_per_document=3,
        phrases=SUPPORT_PHRASES,
        layout="note",
        id_prefix="bitext",
    ),
    "support_conversations": PackSpec(
        key="support_conversations",
        dataset="bitext_customer_support",
        description="The same exchanges rendered as Customer/Agent transcript turns.",
        document_type="transcript",
        difficulty_tier=4,
        documents=200,
        languages=("en",),
        entities_per_document=3,
        phrases=SUPPORT_PHRASES,
        layout="conversation",
        id_prefix="bitext",
    ),
    "multilingual_utterances": PackSpec(
        key="multilingual_utterances",
        dataset="massive",
        description="Short lower-case German and Greek assistant utterances.",
        document_type="plain",
        difficulty_tier=2,
        documents=200,
        languages=("de", "el"),
        # Two, not three: a 40-character utterance carrying three injected phrases is
        # mostly injection, and the pack would measure its own generator.
        entities_per_document=2,
        phrases=UTTERANCE_PHRASES,
    ),
}


def pack_spec(key: str) -> PackSpec:
    spec = PACKS.get(key)
    if spec is None:
        raise CorpusError(f"unknown pack {key!r} (known: {', '.join(sorted(PACKS))})")
    return spec


def _parser_for(document_type: str) -> Parser:
    """The parser the *benchmark* will use, so injection respects the same structure.

    These must match ``configs/datasets/benchmark_{plain,transcript}.yaml``. If they
    drift, an entity can be injected into a region the pipeline never processes and the
    pack reports a recall failure that is really a generator bug.
    """
    if document_type == "transcript":
        return TranscriptParser({"preserve_prefix": True, "fallback": "preserve_line"})
    return PlainTextParser()


def _plans(spec: PackSpec, language: str, index: int) -> tuple[InjectionPlan, ...]:
    phrases = spec.phrases[language]
    return tuple(
        InjectionPlan(entity_type, phrases[entity_type])
        for entity_type in (
            ROTATION[(index + offset) % len(ROTATION)]
            for offset in range(spec.entities_per_document)
        )
    )


def _base_documents(
    spec: PackSpec, entry: DatasetEntry, *, cache_dir: str | Path, seed: int, allow_download: bool
) -> list[BaseDocument]:
    retrieval = entry.require_retrieval()
    if spec.dataset == "bitext_customer_support":
        path = fetch(
            retrieval.file_for("table"), cache_dir=cache_dir, allow_download=allow_download
        )
        return read_bitext(
            path,
            count=spec.documents,
            layout=spec.layout,
            id_prefix=spec.ids,
            seed=seed,
        )
    if spec.dataset == "massive":
        documents: list[BaseDocument] = []
        for language in spec.languages:
            path = fetch(
                retrieval.file_for(language), cache_dir=cache_dir, allow_download=allow_download
            )
            documents.extend(
                read_massive(
                    path,
                    language=language,
                    count=spec.documents_per_language,
                    id_prefix=f"{spec.ids}_{language}",
                    seed=seed,
                )
            )
        return documents
    raise CorpusError(
        f"pack {spec.key!r} names dataset {spec.dataset!r}, which has no reader. "
        "A dataset needs both a registry entry and code that knows its shape"
    )


def build_pack(
    key: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    seed: int = 42,
    documents: int | None = None,
    allow_download: bool = True,
) -> Corpus:
    """Fetch, render and inject — the first real caller of ``inject()``.

    The licence gate runs *before* the download, not after: ``require_publishable``
    refuses an unregistered dataset, a non-permissive licence, or a source carrying
    real personal data, and there is no reason to spend a transfer discovering that.
    """
    spec = pack_spec(key)
    if documents is not None:
        spec = replace(spec, documents=documents)
    entry = require_publishable(spec.dataset, path=registry_path)

    base = _base_documents(
        spec, entry, cache_dir=cache_dir, seed=seed, allow_download=allow_download
    )
    parser = _parser_for(spec.document_type)

    built: list[SyntheticDocument] = []
    entities: list[TruthEntity] = []
    protected: list[ProtectedToken] = []

    for index, document in enumerate(base):
        result = inject(
            document.text,
            _plans(spec, document.language, index),
            document_id=document.document_id,
            language=document.language,
            document_type=spec.document_type,
            difficulty_tier=spec.difficulty_tier,
            seed=seed,
            parser=parser,
            protected=document.protected,
        )
        built.append(result.document)
        entities.extend(result.entities)
        protected.extend(result.protected)

    retrieval = entry.require_retrieval()
    meta: dict[str, object] = {
        "pack": spec.key,
        "pack_version": PACK_VERSION,
        "description": spec.description,
        "generator_version": PACK_VERSION,
        "seed": seed,
        "documents": len(built),
        "entities": len(entities),
        "protected_tokens": len(protected),
        "languages": list(spec.languages),
        "document_type": spec.document_type,
        "difficulty_tier": spec.difficulty_tier,
        "layout": spec.layout,
        # Provenance, per docs/02_PUBLIC_DATA_STRATEGY.md. A published number is only
        # reproducible if the bytes it was measured on can be named.
        "dataset": entry.key,
        "dataset_name": entry.name,
        "source_url": entry.source_url,
        "license": entry.license,
        "share_alike": entry.share_alike,
        "contains_real_pii": entry.contains_real_pii,
        "source_repository": retrieval.repository,
        "source_revision": retrieval.revision,
        "source_files": [
            {"path": remote.path, "sha256": remote.sha256, "bytes": remote.size_bytes}
            for remote in retrieval.files
        ],
        "transformation": _transformation(spec),
    }
    return Corpus(
        documents=tuple(built),
        entities=tuple(entities),
        protected=tuple(protected),
        meta=meta,
    )


def _transformation(spec: PackSpec) -> str:
    """What was done to the source before injection — a `docs/02` requirement."""
    if spec.dataset == "bitext_customer_support":
        layout = (
            "rendered as 'Customer:'/'Agent:' transcript turns"
            if spec.layout == "conversation"
            else "rendered as two paragraphs of free text"
        )
        return (
            "rows carrying any {{Placeholder}} other than {{Order Number}} excluded; "
            "instruction and response " + layout + "; every {{Order Number}} replaced "
            "with a synthetic identifier recorded as a protected token; no other edit"
        )
    return "one utterance per document, unedited; no identifiers substituted"

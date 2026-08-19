"""Corpus generation, persistence and ground-truth loading.

Spans are recorded **at injection time**, measured against the exact string being
emitted (ADR-0011, ``AGENTS.md`` benchmark integrity). Nothing here searches finished
text for values it just inserted — that would reverse-engineer ground truth and would
quietly disagree with the document wherever a value happens to appear twice.

No Unicode normalization happens anywhere, so a manifest is valid only against the
byte-identical document it was generated with. ``load_corpus`` enforces exactly that.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import pandas as pd

from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.synthetic.errors import CorpusError, GroundTruthError
from pii_reduction.synthetic.templates import TemplateSpec, templates_for
from pii_reduction.synthetic.values import LANGUAGES, PoolValueProvider, ValueProvider

__all__ = [
    "CORPUS_FILE",
    "MANIFEST_FILE",
    "META_FILE",
    "PROTECTED_FILE",
    "Corpus",
    "ProtectedToken",
    "SyntheticDocument",
    "TruthEntity",
    "build_corpus",
    "document_seed",
    "load_corpus",
    "split_for",
    "write_corpus",
]

CORPUS_FILE = "corpus.csv"
MANIFEST_FILE = "manifest.csv"
PROTECTED_FILE = "protected.csv"
META_FILE = "meta.json"

#: Bumped to 2 when `meta` gained `profile`: two corpora now come out of this
#: generator, and a meta block that cannot say which one it is could be scored against
#: the wrong gate file. The field exists to signal exactly this kind of schema change.
GENERATOR_VERSION = "2"

PLACEHOLDER_RE = re.compile(r"\{([A-Z_]+)\}")

#: Placeholder -> normalized entity label. Everything else is a protected token.
PII_PLACEHOLDERS: dict[str, str] = {
    "PERSON": PERSON,
    "PERSON_SHORT": PERSON,
    "EMAIL": EMAIL,
    "PHONE": PHONE,
    "PHONE_DASHED": PHONE,
    "PHONE_COMPACT": PHONE,
}

PROTECTED_PLACEHOLDERS = frozenset(
    {"TICKET", "KB", "MACHINE", "VERSION", "ORDER", "CHANGE", "REQUEST", "ASSET"}
)

SPLITS = (("dev", 20), ("calibration", 40), ("test", 100))


@dataclass(frozen=True)
class SyntheticDocument:
    document_id: str
    language: str
    document_type: str
    tier: int
    split: str
    text: str


@dataclass(frozen=True)
class TruthEntity:
    """One injected entity (``docs/03_DATA_CONTRACTS.md`` §13).

    ``surface`` is present because this corpus is wholly synthetic and committed; it
    is what the loader validates against and what the leakage metric looks for. A
    manifest over real data would carry only ``synthetic_value_id``.
    """

    document_id: str
    entity_id: str
    entity_type: str
    start: int
    end: int
    surface: str
    language: str
    difficulty_tier: int
    document_type: str
    injection_rule: str
    synthetic_value_id: str


@dataclass(frozen=True)
class ProtectedToken:
    """A non-PII identifier that must survive reduction untouched."""

    document_id: str
    token: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class Corpus:
    documents: tuple[SyntheticDocument, ...]
    entities: tuple[TruthEntity, ...]
    protected: tuple[ProtectedToken, ...]
    meta: dict[str, object]

    def document(self, document_id: str) -> SyntheticDocument:
        for document in self.documents:
            if document.document_id == document_id:
                return document
        raise KeyError(document_id)

    def texts(self) -> dict[str, str]:
        return {document.document_id: document.text for document in self.documents}

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(document) for document in self.documents])


def document_seed(document_id: str, seed: int) -> int:
    """A stable per-document seed, so a document regenerates without its pack.

    Derived rather than positional: a value provider shared across a pack advances with
    every document, so the same document would produce different values depending on
    where it sat in the run — which is not what ADR-0011 means by reproducible. It lives
    here beside :func:`split_for` because both are per-document derivations that the
    corpus generator, the injector and the public-dataset readers must all agree on.

    Not :func:`hash`: Python randomises string hashing per process, so a pack built with
    it would differ between two runs on the same machine.
    """
    digest = hashlib.sha256(f"{seed}:{document_id}".encode()).hexdigest()
    return int(digest[:8], 16)


def split_for(document_id: str, seed: int) -> str:
    """Deterministic 20/20/60 dev/calibration/test assignment (ADR-0011).

    Public — a public-dataset pack must use the *same* rule as the synthetic corpus, or
    `--split` means two different things depending on which corpus is loaded and
    Increment E's calibration discipline cannot be applied to packs at all.
    """
    digest = hashlib.sha256(f"{seed}:{document_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    for name, upper in SPLITS:
        if bucket < upper:
            return name
    return "test"


def _value_for(placeholder: str, language: str, provider: ValueProvider):  # type: ignore[no-untyped-def]
    if placeholder == "PERSON":
        return provider.person(language)
    if placeholder == "PERSON_SHORT":
        return provider.person_short(language)
    if placeholder == "EMAIL":
        return provider.email(language)
    if placeholder == "PHONE":
        return provider.phone(language)
    if placeholder == "PHONE_DASHED":
        return provider.phone(language, style="dashed")
    if placeholder == "PHONE_COMPACT":
        return provider.phone(language, style="compact")
    if placeholder == "TICKET":
        return provider.ticket()
    if placeholder == "KB":
        return provider.kb_article()
    if placeholder == "MACHINE":
        return provider.machine()
    if placeholder == "VERSION":
        return provider.version()
    if placeholder == "ORDER":
        return provider.order()
    if placeholder == "CHANGE":
        return provider.change()
    if placeholder == "REQUEST":
        return provider.request()
    if placeholder == "ASSET":
        return provider.asset()
    raise CorpusError(f"template uses unknown placeholder {{{placeholder}}}")


def _render(
    spec: TemplateSpec,
    *,
    document_id: str,
    language: str,
    provider: ValueProvider,
    seed: int,
) -> tuple[SyntheticDocument, list[TruthEntity], list[ProtectedToken]]:
    pieces: list[str] = []
    length = 0
    entities: list[TruthEntity] = []
    protected: list[ProtectedToken] = []
    cursor = 0

    for match in PLACEHOLDER_RE.finditer(spec.template):
        literal = spec.template[cursor : match.start()]
        pieces.append(literal)
        length += len(literal)
        cursor = match.end()

        placeholder = match.group(1)
        value = _value_for(placeholder, language, provider)
        start = length
        pieces.append(value.text)
        length += len(value.text)

        if placeholder in PII_PLACEHOLDERS:
            entities.append(
                TruthEntity(
                    document_id=document_id,
                    entity_id=f"{document_id}_e{len(entities):02d}",
                    entity_type=PII_PLACEHOLDERS[placeholder],
                    start=start,
                    end=length,
                    surface=value.text,
                    language=language,
                    difficulty_tier=spec.tier,
                    document_type=spec.document_type,
                    injection_rule=placeholder.lower(),
                    synthetic_value_id=value.value_id,
                )
            )
        elif placeholder in PROTECTED_PLACEHOLDERS:
            protected.append(
                ProtectedToken(
                    document_id=document_id,
                    token=value.text,
                    kind=placeholder.lower(),
                    start=start,
                    end=length,
                )
            )
        else:  # pragma: no cover - _value_for already rejects unknown placeholders
            raise CorpusError(f"placeholder {{{placeholder}}} is neither PII nor protected")

    tail = spec.template[cursor:]
    pieces.append(tail)
    text = "".join(pieces)

    document = SyntheticDocument(
        document_id=document_id,
        language=language,
        document_type=spec.document_type,
        tier=spec.tier,
        split=split_for(document_id, seed),
        text=text,
    )
    return document, entities, protected


def build_corpus(
    *,
    seed: int = 42,
    documents_per_language: int = 34,
    templates: Callable[[str], tuple[TemplateSpec, ...]] = templates_for,
    id_prefix: str = "doc",
    profile: str = "benchmark",
) -> Corpus:
    """Generate a deterministic corpus. Same seed and size give a byte-identical result.

    ``templates`` and ``id_prefix`` exist so a second corpus profile can reuse every
    invariant this function already enforces — span validation, split assignment,
    deterministic value sequencing — rather than growing a parallel generator that
    would drift from it. The incident-notes corpus (ADR-0022) is the second caller;
    its ids are prefixed differently so a document from one corpus can never be
    mistaken for a document from the other in a manifest or a metric row.
    """
    if documents_per_language < 1:
        raise CorpusError("documents_per_language must be at least 1")

    provider = PoolValueProvider(seed)
    documents: list[SyntheticDocument] = []
    entities: list[TruthEntity] = []
    protected: list[ProtectedToken] = []

    index = 0
    for language in LANGUAGES:
        specs = templates(language)
        for position in range(documents_per_language):
            spec = specs[position % len(specs)]
            index += 1
            document, document_entities, document_protected = _render(
                spec,
                document_id=f"{id_prefix}_{index:04d}",
                language=language,
                provider=provider,
                seed=seed,
            )
            documents.append(document)
            entities.extend(document_entities)
            protected.extend(document_protected)

    meta: dict[str, object] = {
        "generator_version": GENERATOR_VERSION,
        "profile": profile,
        "seed": seed,
        "documents_per_language": documents_per_language,
        "languages": list(LANGUAGES),
        "documents": len(documents),
        "entities": len(entities),
        "protected_tokens": len(protected),
    }
    corpus = Corpus(
        documents=tuple(documents),
        entities=tuple(entities),
        protected=tuple(protected),
        meta=meta,
    )
    _validate(corpus)
    return corpus


def _validate(corpus: Corpus) -> None:
    """Every recorded span must slice to the value it claims, in its own document."""
    texts = corpus.texts()
    for entity in corpus.entities:
        text = texts[entity.document_id]
        if text[entity.start : entity.end] != entity.surface:
            raise GroundTruthError(
                f"document {entity.document_id!r}, entity {entity.entity_id!r}: span "
                f"[{entity.start}, {entity.end}) does not match the injected value"
            )
    for token in corpus.protected:
        text = texts[token.document_id]
        if text[token.start : token.end] != token.token:
            raise GroundTruthError(
                f"document {token.document_id!r}: protected span "
                f"[{token.start}, {token.end}) does not match the injected token"
            )


def _frame_of(records: Sequence[Any], record_type: type) -> pd.DataFrame:
    """Rows plus the column names, so an empty table still writes its header.

    A pack whose source carries no identifiers has no protected tokens (MASSIVE is
    exactly that), and a headerless empty CSV cannot be read back — ``load_corpus``
    would fail on a corpus that is perfectly valid. Naming the columns from the
    dataclass keeps the file readable and the schema in one place.
    """
    return pd.DataFrame(
        [asdict(record) for record in records],
        columns=[field.name for field in fields(record_type)],
    )


def write_corpus(corpus: Corpus, directory: str | Path) -> dict[str, str]:
    """Write corpus, manifest, protected tokens and metadata as UTF-8 CSV/JSON."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)

    written = {
        "corpus": _write_csv(_frame_of(corpus.documents, SyntheticDocument), target / CORPUS_FILE),
        "manifest": _write_csv(_frame_of(corpus.entities, TruthEntity), target / MANIFEST_FILE),
        "protected": _write_csv(
            _frame_of(corpus.protected, ProtectedToken), target / PROTECTED_FILE
        ),
    }
    meta_path = target / META_FILE
    meta_path.write_text(
        json.dumps(corpus.meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline=""
    )
    written["meta"] = str(meta_path)
    return written


def _write_csv(frame: pd.DataFrame, path: Path) -> str:
    # lineterminator is pinned so a regenerated corpus is byte-identical on every OS.
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return str(path)


def load_corpus(directory: str | Path) -> Corpus:
    """Load a written corpus and validate every span against its document."""
    source = Path(directory)
    corpus_path = source / CORPUS_FILE
    if not corpus_path.is_file():
        raise CorpusError(f"corpus not found: {corpus_path}")

    documents_frame = pd.read_csv(corpus_path, encoding="utf-8", keep_default_na=False)
    manifest_frame = pd.read_csv(source / MANIFEST_FILE, encoding="utf-8", keep_default_na=False)
    protected_frame = pd.read_csv(source / PROTECTED_FILE, encoding="utf-8", keep_default_na=False)
    meta = json.loads((source / META_FILE).read_text(encoding="utf-8"))

    corpus = Corpus(
        documents=tuple(
            SyntheticDocument(
                document_id=str(row["document_id"]),
                language=str(row["language"]),
                document_type=str(row["document_type"]),
                tier=int(row["tier"]),
                split=str(row["split"]),
                text=str(row["text"]),
            )
            for row in documents_frame.to_dict(orient="records")
        ),
        entities=tuple(
            TruthEntity(
                document_id=str(row["document_id"]),
                entity_id=str(row["entity_id"]),
                entity_type=str(row["entity_type"]),
                start=int(row["start"]),
                end=int(row["end"]),
                surface=str(row["surface"]),
                language=str(row["language"]),
                difficulty_tier=int(row["difficulty_tier"]),
                document_type=str(row["document_type"]),
                injection_rule=str(row["injection_rule"]),
                synthetic_value_id=str(row["synthetic_value_id"]),
            )
            for row in manifest_frame.to_dict(orient="records")
        ),
        protected=tuple(
            ProtectedToken(
                document_id=str(row["document_id"]),
                token=str(row["token"]),
                kind=str(row["kind"]),
                start=int(row["start"]),
                end=int(row["end"]),
            )
            for row in protected_frame.to_dict(orient="records")
        ),
        meta=meta,
    )
    _validate(corpus)
    return corpus

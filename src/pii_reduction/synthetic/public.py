"""Turn a downloaded public corpus into base documents ready for injection.

This module is the seam between "text somebody else wrote" and "a document this
project can measure". It does three things and deliberately not a fourth: it selects
rows, renders them into a document shape, and records the identifiers it substituted.
It never places PII — that is :mod:`pii_reduction.synthetic.injection`, which is the
only code allowed to write a ground-truth span.

Selection is the transformation ``docs/02_PUBLIC_DATA_STRATEGY.md`` requires be
documented, and it is deterministic: a seeded shuffle of the eligible rows rather than
the first *n*. Bitext ships sorted by category, so taking the head would produce a pack
that is entirely about account management and a benchmark that measures one intent.

Nothing here prints or logs source text (``AGENTS.md`` rule 8). Errors name row counts
and file paths.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pii_reduction.synthetic.corpus import ProtectedToken, document_seed
from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.values import PoolValueProvider

__all__ = [
    "ORDER_PLACEHOLDER",
    "BaseDocument",
    "read_bitext",
    "read_massive",
    "substitute_order_numbers",
]

#: Bitext writes its slots as ``{{Order Number}}``. 391 distinct slot names appear
#: across the corpus and most are not identifiers at all — ``{{Person Name}}`` and
#: ``{{Customer Support Phone Number}}`` among them — so only this one is filled, and
#: any row carrying any other placeholder is excluded rather than half-rendered.
ORDER_PLACEHOLDER = "{{Order Number}}"

_PLACEHOLDER_RE = re.compile(r"\{\{(.*?)\}\}")

_BITEXT_COLUMNS = ("instruction", "response")

#: How a row becomes a document. Both layouts use the *same* two fields, so the two
#: English packs differ only in rendering (ADR-0018) — which is the comparison, and
#: also the reason their numbers must never be read as two independent corpora.
BITEXT_LAYOUTS = ("note", "conversation")


@dataclass(frozen=True)
class BaseDocument:
    """Public text, rendered but not yet injected into."""

    document_id: str
    text: str
    language: str
    protected: tuple[ProtectedToken, ...] = ()


def substitute_order_numbers(
    text: str, *, document_id: str, provider: PoolValueProvider
) -> tuple[str, tuple[ProtectedToken, ...]]:
    """Replace every ``{{Order Number}}`` with a synthetic identifier, recording spans.

    The span is recorded as the string is assembled, never by searching the result: a
    document may legitimately carry the same order number twice, and a search would
    then attribute one occurrence's span to the other (ADR-0011).

    These become the pack's protected tokens, which is what makes over-redaction —
    the metric guarding ``AGENTS.md`` rule 5 — measurable on text this project did not
    write. Without them a public pack can only report detection, and a reducer that
    started eating order numbers would show up in no number at all.
    """
    pieces: list[str] = []
    tokens: list[ProtectedToken] = []
    length = 0
    cursor = 0

    for match in re.finditer(re.escape(ORDER_PLACEHOLDER), text):
        literal = text[cursor : match.start()]
        pieces.append(literal)
        length += len(literal)
        cursor = match.end()

        value = provider.order()
        pieces.append(value.text)
        tokens.append(
            ProtectedToken(
                document_id=document_id,
                token=value.text,
                kind="order",
                start=length,
                end=length + len(value.text),
            )
        )
        length += len(value.text)

    pieces.append(text[cursor:])
    return "".join(pieces), tuple(tokens)


def _eligible_bitext(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows whose only placeholder, if any, is the order number."""
    missing = [column for column in _BITEXT_COLUMNS if column not in frame.columns]
    if missing:
        raise CorpusError(
            f"bitext table is missing column(s) {', '.join(missing)}; the pinned "
            "revision in demo/registry.yaml does not match the reader"
        )
    combined = frame["instruction"].astype(str) + "\n" + frame["response"].astype(str)
    keeps = combined.map(
        lambda value: (
            not [name for name in _PLACEHOLDER_RE.findall(value) if name != "Order Number"]
        )
    )
    return frame[keeps]


def _select(frame: pd.DataFrame, *, count: int, seed: int, what: str) -> list[int]:
    """A seeded sample of row positions — reproducible, and not the head of the file."""
    if count < 1:
        raise CorpusError(f"{what}: a pack needs at least one document, asked for {count}")
    if len(frame) < count:
        raise CorpusError(
            f"{what}: only {len(frame)} eligible rows are available but {count} were "
            "requested; lower the pack size or widen the selection rule"
        )
    positions = list(range(len(frame)))
    random.Random(f"select:{seed}:{what}").shuffle(positions)
    return sorted(positions[:count])


def read_bitext(
    path: str | Path,
    *,
    count: int,
    layout: str,
    id_prefix: str,
    seed: int = 42,
) -> list[BaseDocument]:
    """Bitext rows as English support documents, in one of two renderings.

    ``note`` gives the customer message and the agent reply as two paragraphs of free
    text; ``conversation`` gives them as two transcript turns. Bitext's own columns are
    named ``instruction`` and ``response``, so labelling them Customer and Agent
    restates the source rather than inventing structure (ADR-0018).
    """
    if layout not in BITEXT_LAYOUTS:
        raise CorpusError(f"unknown bitext layout {layout!r} (known: {', '.join(BITEXT_LAYOUTS)})")
    frame = _read_table(path)
    eligible = _eligible_bitext(frame)
    # Selection does NOT depend on the layout, so the note pack and the conversation
    # pack contain the *same* source rows. That is what makes the comparison between
    # them a comparison of parsing (ADR-0018) rather than of two different samples.
    positions = _select(eligible, count=count, seed=seed, what="bitext")

    documents: list[BaseDocument] = []
    for index, position in enumerate(positions):
        row = eligible.iloc[position]
        instruction = str(row["instruction"]).strip()
        response = str(row["response"]).strip()
        if layout == "note":
            text = f"{instruction}\n\n{response}"
        else:
            text = f"Customer: {instruction}\nAgent: {response}"

        document_id = f"{id_prefix}_{index:04d}"
        # A provider per document, seeded from the document id, so an order number does
        # not depend on where its row sat in the run — the same rule `inject()` uses.
        provider = PoolValueProvider(seed=document_seed(document_id, seed))
        rendered, protected = substitute_order_numbers(
            text, document_id=document_id, provider=provider
        )
        documents.append(
            BaseDocument(document_id=document_id, text=rendered, language="en", protected=protected)
        )
    return documents


def read_massive(
    path: str | Path,
    *,
    language: str,
    count: int,
    id_prefix: str,
    seed: int = 42,
) -> list[BaseDocument]:
    """MASSIVE utterances, one per document, as they were written.

    They are short (a median of 37 characters), lower case and unpunctuated. That is
    the point: the synthetic corpus's German and Greek are templates this project wrote,
    and a recognizer that has only ever seen well-formed capitalised text has not been
    asked a hard question. No identifiers are substituted — the corpus carries none —
    so this pack measures detection and leakage but not over-redaction.
    """
    frame = _read_table(path)
    if "utt" not in frame.columns:
        raise CorpusError(
            "massive table has no 'utt' column; the pinned revision in "
            "demo/registry.yaml does not match the reader"
        )
    positions = _select(frame, count=count, seed=seed, what=f"massive:{language}")
    return [
        BaseDocument(
            document_id=f"{id_prefix}_{index:04d}",
            text=str(frame.iloc[position]["utt"]).strip(),
            language=language,
        )
        for index, position in enumerate(positions)
    ]


def _read_table(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise CorpusError(f"source file not found: {source}. Fetch the dataset first")
    if source.suffix == ".parquet":
        try:
            return pd.read_parquet(source)
        except ImportError as error:
            raise CorpusError(
                f"reading {source.name} needs pyarrow. Install it with: "
                "pip install -e '.[parquet]' (ADR-0008)"
            ) from error
    return pd.read_csv(source, encoding="utf-8", keep_default_na=False)

"""Inject synthetic PII into text this project did not write.

The Increment A6 generator renders documents *from* templates: it knows where every
entity is because it put it there. Increment D starts from public corpora instead —
Bitext support exchanges and MASSIVE utterances — where the text already exists
and entities have to be placed into it.

Why inject at all rather than benchmark on whatever PII the public data already
contains (``docs/02_PUBLIC_DATA_STRATEGY.md``): real PII cannot safely serve as an open
benchmark, exact ground-truth spans are knowable only if we placed them, and entity
frequency has to be controllable for the slices to mean anything.

Three invariants make the result usable as ground truth:

* **Spans are recorded against the exact emitted string.** Offsets are computed as the
  document is assembled, never by searching for the value afterwards — a search finds
  the wrong occurrence when the same name appears twice, and ADR-0011 forbids any
  normalization that would shift them.
* **Injection is deterministic per document.** Values, position and phrasing all derive
  from ``(seed, document_id)``, so a pack regenerates byte-identically and a single
  document can be rebuilt without replaying the whole pack (ADR-0011).
* **Structure the parser owns is never violated.** Given a parser, insertion points are
  restricted to the regions that parser marks processable. Without that restriction an
  entity dropped at a line start lands *before* a transcript speaker prefix, and the
  line stops parsing as a turn at all — destroying the very structure the conversation
  pack exists to test, and hiding the entity inside a region the pipeline never processes.

The base text is treated as opaque and never edited: injection only *inserts*, so
whatever the source corpus said still reads the same either side of the insertion.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.parsers.base import Parser
from pii_reduction.synthetic.corpus import (
    ProtectedToken,
    SyntheticDocument,
    TruthEntity,
    document_seed,
    split_for,
)
from pii_reduction.synthetic.errors import CorpusError, GroundTruthError
from pii_reduction.synthetic.values import PoolValueProvider, SyntheticValue, ValueProvider

__all__ = ["InjectionPlan", "InjectionResult", "eligible_offsets", "inject"]

#: A sentence boundary followed by whitespace. Injecting mid-word would produce text no
#: human would write, and a recognizer that never has to find a name in ordinary prose
#: is not being tested.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

INJECTABLE_ENTITIES = frozenset({PERSON, EMAIL, PHONE})


@dataclass(frozen=True)
class InjectionPlan:
    """One entity to inject, and the phrasing to wrap it in.

    ``phrases`` render the value into something that reads like the surrounding corpus
    rather than a bare token dropped into prose. Each is a format string with a single
    ``{value}`` placeholder, and the recorded span covers the **value only** — the
    phrase around it is ordinary text a recognizer is entitled to ignore.

    There is deliberately no ``language`` here. The value pool and the manifest label
    must agree, and a per-plan language let them disagree silently: a Greek name could
    be recorded as English, corrupting the per-language table that is currently this
    project's headline result. The language comes from :func:`inject`.
    """

    entity_type: str
    phrases: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.entity_type not in INJECTABLE_ENTITIES:
            raise CorpusError(
                f"injection plan for {self.entity_type!r}: only "
                f"{', '.join(sorted(INJECTABLE_ENTITIES))} have value pools "
                "(ADDRESS stays undetected at v0.1, ADR-0002)"
            )
        if not self.phrases:
            raise CorpusError(f"injection plan for {self.entity_type!r}: needs at least one phrase")
        for phrase in self.phrases:
            if phrase.count("{value}") != 1:
                raise CorpusError(
                    f"injection phrase {phrase!r}: needs exactly one {{value}} placeholder"
                )


@dataclass(frozen=True)
class InjectionResult:
    document: SyntheticDocument
    entities: tuple[TruthEntity, ...]
    #: Protected tokens the caller handed in, with their offsets moved to match the
    #: document that came back. Empty unless the base text carried any.
    protected: tuple[ProtectedToken, ...] = ()


def eligible_offsets(text: str, *, parser: Parser | None = None) -> list[int]:
    """Offsets where an insertion reads naturally and violates no parsed structure.

    Naturally means document start, line starts and sentence ends — a value spliced
    into the middle of a word tells you nothing about a recognizer except that it can
    match a regex.

    ``parser`` is what keeps the result honest on structured text. Restricted to a
    parser's processable regions, an insertion can never precede a transcript speaker
    prefix or a key/value label, so the document still parses the way the source did.
    Without it, the conversation pack would quietly stop containing transcripts.

    Empty text yields the start offset, so a pack of short utterances (MASSIVE) still
    receives entities.
    """
    offsets = {0}
    offsets.update(match.end() for match in _SENTENCE_END_RE.finditer(text))
    offsets.update(index + 1 for index, character in enumerate(text) if character == "\n")
    candidates = sorted(offset for offset in offsets if 0 <= offset <= len(text))
    if parser is None:
        return candidates

    regions = [
        (segment.source_start, segment.source_end)
        for segment in parser.parse(text).processable_segments
        if segment.source_start is not None and segment.source_end is not None
    ]
    # The start of a processable region counts too: it is where a speaker starts
    # talking. Without it a transcript's only candidates are sentence breaks, which live
    # wherever the longest turn is — every name in a two-turn document would land in the
    # agent's reply, and a turn with no internal full stop could receive nothing at all.
    candidates = sorted(set(candidates) | {start for start, _ in regions})
    allowed = [
        offset for offset in candidates if any(start <= offset <= end for start, end in regions)
    ]
    # A document whose parser finds nothing processable receives nothing, rather than
    # having an entity forced into structure the pipeline will never look at.
    return allowed


def _value_for(entity_type: str, language: str, provider: ValueProvider) -> SyntheticValue:
    if entity_type == PERSON:
        return provider.person(language)
    if entity_type == EMAIL:
        return provider.email(language)
    return provider.phone(language)


def inject(
    text: str,
    plans: Sequence[InjectionPlan],
    *,
    document_id: str,
    language: str,
    document_type: str,
    difficulty_tier: int,
    seed: int = 42,
    split: str | None = None,
    parser: Parser | None = None,
    protected: Sequence[ProtectedToken] = (),
) -> InjectionResult:
    """Insert one entity per plan into ``text`` and record exact spans.

    Insertions are applied one at a time; every span already recorded at or after the
    insertion point is shifted by the inserted length. Recomputing beats re-searching:
    the same name may legitimately occur twice, and a search would silently pick the
    wrong occurrence.

    ``split`` defaults to ADR-0011's deterministic 20/20/60 assignment, the same one
    the synthetic corpus uses, so a public pack can be sliced by ``--split`` and
    Increment E's calibration discipline applies to it too.

    ``protected`` carries spans the caller recorded against ``text`` *before* calling —
    the identifiers a public pack substitutes into its base documents, which the
    over-redaction metric needs and which nothing else could keep aligned. They are
    shifted by the same arithmetic as the injected entities and verified the same way,
    because offset arithmetic belongs in one place: a second implementation is a second
    chance to drift, and a drifted protected span silently reports over-redaction that
    did not happen.
    """
    if not isinstance(text, str):
        raise CorpusError(f"inject() requires str, got {type(text).__name__}")
    if any(token.document_id != document_id for token in protected):
        raise CorpusError(
            f"document {document_id}: protected tokens from another document were passed "
            "in; their offsets are measured against a text this call never sees"
        )

    seed_for_document = document_seed(document_id, seed)
    values = PoolValueProvider(seed=seed_for_document)
    chooser = random.Random(seed_for_document)

    result = text
    entities: list[TruthEntity] = []
    kept: list[ProtectedToken] = list(protected)

    for index, plan in enumerate(plans):
        offsets = [
            offset
            for offset in eligible_offsets(result, parser=parser)
            # Never inside a protected token either. An identifier split by an inserted
            # phrase is no longer the token the over-redaction metric looks for, so the
            # pack would report a preservation failure the reducer never committed.
            if not any(token.start < offset < token.end for token in kept)
            # Never inside an entity already placed. Splicing one value into the middle
            # of another produces text no human would write, and leaves the outer span's
            # `end` unshifted — which `_verify` catches, but as an aborted build rather
            # than a sensible result. Today's pools cannot contain a sentence boundary;
            # a Faker-backed provider (`values.ValueProvider`) can.
            if not any(entity.start < offset < entity.end for entity in entities)
        ]
        if not offsets:
            continue
        at = chooser.choice(offsets)
        value = _value_for(plan.entity_type, language, values)
        phrase_index = chooser.randrange(len(plan.phrases))
        prefix, suffix = plan.phrases[phrase_index].split("{value}")

        # Pad so the insertion does not fuse with its neighbours. Without this a
        # sentence-end insertion yields `...0128.I cannot log in`, which is not text
        # anyone would write — and the deterministic PHONE recognizer's boundary guard
        # rejects a number whose neighbour is alphanumeric, so the pack would be
        # measuring the injector rather than the provider.
        lead = "" if at == 0 or result[at - 1].isspace() else " "
        trail = "" if at == len(result) or result[at].isspace() else " "
        rendered = lead + prefix + value.text + suffix + trail

        start = at + len(lead) + len(prefix)
        end = start + len(value.text)
        result = result[:at] + rendered + result[at:]

        entities = [
            entity
            if entity.start < at
            else replace(entity, start=entity.start + len(rendered), end=entity.end + len(rendered))
            for entity in entities
        ]
        kept = [
            token
            if token.start < at
            else replace(token, start=token.start + len(rendered), end=token.end + len(rendered))
            for token in kept
        ]
        entities.append(
            TruthEntity(
                document_id=document_id,
                entity_id=f"{document_id}_e{index:02d}",
                entity_type=plan.entity_type,
                start=start,
                end=end,
                surface=value.text,
                language=language,
                difficulty_tier=difficulty_tier,
                document_type=document_type,
                # The phrase index is part of the rule: `docs/02` expects a per-phrase
                # id so a slice can be taken by phrasing and a single injection can be
                # reproduced from the manifest alone.
                injection_rule=f"{plan.entity_type.lower()}_phrase_{phrase_index:02d}",
                synthetic_value_id=value.value_id,
            )
        )

    document = SyntheticDocument(
        document_id=document_id,
        language=language,
        document_type=document_type,
        tier=difficulty_tier,
        split=split if split is not None else split_for(document_id, seed),
        text=result,
    )
    _verify(document, entities, kept)
    return InjectionResult(document=document, entities=tuple(entities), protected=tuple(kept))


def _verify(
    document: SyntheticDocument,
    entities: Sequence[TruthEntity],
    protected: Sequence[ProtectedToken] = (),
) -> None:
    """Every recorded span must slice back to its own surface.

    Cheap, and it is the invariant the whole pack rests on: a manifest whose offsets
    have drifted turns every metric computed from it into fiction. The message reports
    the document and the offsets and never the expected value, so it stays privacy-safe
    if this is ever pointed at text that is not synthetic (ADR-0011, AGENTS.md rule 8).

    Protected tokens are checked by the same rule and for the same reason: a drifted
    one makes the over-redaction metric report damage that never happened, or miss
    damage that did.
    """
    for entity in entities:
        if document.text[entity.start : entity.end] != entity.surface:
            raise GroundTruthError(
                f"document {document.document_id}: injected span "
                f"[{entity.start}, {entity.end}) does not slice back to the value "
                "recorded for it; the manifest would be wrong"
            )
    for token in protected:
        if document.text[token.start : token.end] != token.token:
            raise GroundTruthError(
                f"document {document.document_id}: protected span "
                f"[{token.start}, {token.end}) does not slice back to the token "
                "recorded for it; over-redaction would be measured against fiction"
            )

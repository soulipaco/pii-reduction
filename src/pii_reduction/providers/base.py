"""Provider protocol and the contract every provider is held to.

``BaseProvider.detect`` is a template method: subclasses implement ``_detect`` and the
base class enforces the provider contract (``docs/10_TESTING_QA.md`` §4) on the way
out — normalized labels, valid offsets, requested entity scope, stable ordering.
A provider that misbehaves fails loudly here rather than corrupting text downstream.

The base also performs *repairs* rather than only checking. A span of a line-bounded
entity type that crosses a line break is split into one span per line
(``BaseProvider._bound_to_line``, ADR-0016 — every fragment is kept, not just the
longest). A PERSON span may additionally be widened over one preceding token, opt-in
per instance (``BaseProvider._extend_left``, ADR-0021); that is the one repair which
does not narrow. Validation runs first, so a genuinely malformed span still raises
rather than being quietly reshaped, and neither repair can invalidate it: splitting
only narrows, and widening moves ``start`` left within a line without touching
``end``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from typing import Protocol, runtime_checkable

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.errors import UnknownEntityLabelError
from pii_reduction.entities.mapping import DropCounter
from pii_reduction.entities.taxonomy import PERSON, line_bounded_labels, require_known
from pii_reduction.patterns import is_identifier_shaped
from pii_reduction.providers.errors import ProviderError

__all__ = [
    "LINE_BOUNDED_ENTITIES",
    "LINE_BREAK_SPLIT_RE",
    "BaseProvider",
    "PIIProvider",
    "extend_person_span_left",
]

#: Entity types whose surface cannot contain a line break, so a span that crosses one
#: is a boundary error to repair rather than a detection to keep or drop.
#:
#: Derived from the taxonomy rather than restated here: ``surface_may_span_lines`` is a
#: static fact about an entity, and duplicating it per layer is how the two drift when
#: a Phase 7 ADDRESS provider lands. ADDRESS is excluded there — a postal address
#: written across several lines is one address, and trimming it would cut a real entity
#: in half.
#:
#: Measured (ADR-0016): handed a multi-line key/value block, spaCy returns a PERSON
#: span covering the name, the line break and the next line's first word. Trimming took
#: English tier-3 PERSON strict recall from 0.333 to 1.000 with no slice regressing.
LINE_BOUNDED_ENTITIES: frozenset[str] = line_bounded_labels()

#: Splits a span surface into line fragments. CR, LF and CRLF only — the same
#: definition `parsers/lines.py` uses and for the same reason: `str.splitlines` also
#: breaks on U+2028 and U+0085, which would change what counts as a line for the
#: multilingual text this project handles. The two are deliberately kept in step; a
#: shared home is warranted if a third consumer appears.
LINE_BREAK_SPLIT_RE = re.compile("\r\n|\r|\n")

#: The token immediately before a span, and the whitespace separating them.
_PRECEDING_TOKEN_RE = re.compile(r"(\S+)([ \t]+)$")

#: A preceding token ending in any of these is a boundary, not a name part: a field
#: label (:), the ano teleia in both codepoints (ADR-0019 mechanism 3), or the end of
#: a sentence. All structural - none is a word in any language.
_BOUNDARY_SUFFIXES = (
    ":",
    "\u00b7",
    "\u0387",
    ".",
    "!",
    "?",
    ";",
    "\u037e",
)


def extend_person_span_left(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a PERSON span over one preceding token, when that is structurally safe.

    ADR-0021. The Greek model sometimes returns only the surname of a two-token name
    (``Γιώργος Δημητρίου`` comes back as ``Δημητρίου``), which strict matching scores
    as a miss *and* a false positive, and which redacts half the name — visible in
    ``fragment_leakage_rate`` and invisible to ``leakage_rate``.

    **This is the mirror of the leading-token trim that was measured and rejected**
    (plan §8 Q4). Trimming can cut the first token of a genuine three-token name,
    leaking a name part — the invisible error. Extending can only swallow a
    neighbouring word, which over-redacts — the visible one. ADR-0016 chose the
    visible error deliberately; this follows that choice rather than reversing it.

    Four structural refusals, no word lists (ADR-0019 requires a structural rule):

    * **across a line break** — ADR-0016 established that a name does not span lines,
      so the previous line's last token is never part of this name;
    * **an identifier-shaped token** — reusing ``is_identifier_shaped``, so this can
      never swallow the ticket and machine ids the over-redaction gate protects;
    * **a token ending in a boundary mark** — ``:`` (a field label), the άνω τελεία in
      both codepoints (ADR-0019 mechanism 3), or sentence-final punctuation. The last
      is why a name opening a sentence does not absorb the previous sentence's final
      word;
    * **an uncased token** — in a cased script a name part is capitalised.

    That last refusal is the one that does not transfer to Arabic, Hebrew, CJK or
    Thai, which is why the repair is enabled per provider instance rather than
    globally, and ships for Greek only.

    ``end`` is never moved, which is what keeps the caller's span validation valid.
    """
    line_start = 0
    for separator in LINE_BREAK_SPLIT_RE.finditer(text, 0, start):
        line_start = separator.end()

    preceding = _PRECEDING_TOKEN_RE.search(text[line_start:start])
    if preceding is None:
        return start, end
    token = preceding.group(1)
    if token.endswith(_BOUNDARY_SUFFIXES):
        return start, end
    if is_identifier_shaped(token):
        return start, end
    if not token[:1].isupper():
        return start, end
    return start - len(token) - len(preceding.group(2)), end


@runtime_checkable
class PIIProvider(Protocol):
    """What the processing layer depends on (``docs/04_PII_ENGINE.md``)."""

    @property
    def name(self) -> str: ...

    def supported_languages(self) -> frozenset[str] | None: ...

    def supported_entities(self) -> frozenset[str]: ...

    def detect(
        self,
        text: str,
        *,
        language: str | None = None,
        entities: Collection[str] | None = None,
    ) -> list[EntityMatch]: ...

    def detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None] | None = None,
        entities: Collection[str] | None = None,
    ) -> list[list[EntityMatch]]: ...


class BaseProvider(ABC):
    """Shared contract enforcement, entity-scope filtering and batching."""

    #: Instance name used in ``EntityMatch.provider`` and in run metrics.
    name: str = ""

    @property
    def drop_counter(self) -> DropCounter:
        """Native labels this provider discarded, by reason.

        Lives on the base class so the pipeline can collect drops from every provider
        without knowing which ones map labels at all — a provider with no mapping
        table simply reports an empty counter. ADR-0004 requires these counts to reach
        observability output; a silent drop is how a provider upgrade loses coverage
        without anyone noticing.

        Created lazily so subclasses are not obliged to call ``super().__init__()``.
        """
        counter: DropCounter | None = getattr(self, "_drop_counter", None)
        if counter is None:
            counter = DropCounter()
            self._drop_counter = counter
        return counter

    #: Opt in to the ADR-0021 PERSON left-extension. See :meth:`_extend_left`.
    extend_person_left: bool = False

    @abstractmethod
    def supported_entities(self) -> frozenset[str]:
        """Normalized labels this provider can produce."""

    def supported_languages(self) -> frozenset[str] | None:
        """``None`` means language-independent."""
        return None

    def _extend_left(
        self, match: EntityMatch, text: str, siblings: Sequence[EntityMatch] = ()
    ) -> list[EntityMatch]:
        """Apply the ADR-0021 PERSON extension when this instance opts in.

        Off by default and per instance, not per provider type: the capitalisation
        test in :func:`extend_person_span_left` assumes a cased script, and applying
        it to every language was measured to cost English and German recall
        (0.962 -> 0.885 and 1.000 -> 0.885). Only the Greek instance enables it.

        **Returns the widened span *and* the original**, in that order, rather than
        replacing one with the other. This is what makes the repair leak-safe, and it
        is not optional: the reconciler resolves overlaps by entity priority and is
        greedy without backtracking, so a span widened into overlap with a
        higher-priority EMAIL or PHONE would be rejected outright and the name would
        survive in cleartext — under-redaction, the invisible error this repair exists
        to avoid. Offering both lets the reconciler take the wide span where it fits
        and fall back to the narrow one where it does not. It costs one extra
        candidate per firing and nothing else: the two overlap, so at most one is ever
        accepted.

        ``siblings`` is every candidate from this same call, so the repair can refuse
        to claim a token another candidate already covers — see the comment at that
        check. It cannot see candidates from *other* providers in the chain, which is
        the other half of why both spans are returned.

        A span whose own surface is identifier-shaped is left alone. The reconciler's
        identifier guard rejects such a span precisely because nothing in it looks like
        a name; widening it over a capitalised word would make the joined surface
        name-like, silently unblocking a candidate the guard was holding back and
        redacting the identifier underneath it.
        """
        if not self.extend_person_left or match.entity_type != PERSON:
            return [match]
        if is_identifier_shaped(text[match.start : match.end]):
            return [match]
        start, _ = extend_person_span_left(text, match.start, match.end)
        if start == match.start:
            return [match]
        if any(
            other is not match and other.start < match.start and other.end > start
            for other in siblings
        ):
            # The token being claimed is already inside another candidate from this
            # same call. Widening over it would put two candidates in conflict that
            # were not before, and the reconciler's length tie-break would hand the
            # overlap to this one — evicting the neighbour and leaking whatever only
            # the neighbour covered. Cross-provider conflicts are invisible here and
            # are handled by returning the narrow span as a fallback below.
            return [match]
        self.drop_counter.record_declared(self.name, "person_extended_left")
        widened = match.model_copy(
            update={"start": start, "metadata": {**match.metadata, "extended": True}}
        )
        return [widened, match]

    @abstractmethod
    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        """Detect candidates. ``entities`` is already narrowed to what this provider supports."""

    def detect(
        self,
        text: str,
        *,
        language: str | None = None,
        entities: Collection[str] | None = None,
    ) -> list[EntityMatch]:
        """Detect entities in ``text``, returning normalized matches sorted by position."""
        if not isinstance(text, str):
            raise ProviderError(
                f"provider {self.name!r}: detect() requires str, got {type(text).__name__}. "
                "Null values are handled by the field processor"
            )

        requested = self._resolve_scope(entities)
        if not requested or not text:
            return []

        detected = self._detect(text, language=language, entities=requested)
        # Validate before repairing: a span that already runs past the end of the text
        # is a provider bug, and it must surface as an actionable ProviderError naming
        # the provider and offsets rather than as an IndexError from the repair code.
        # Line-bounding only ever narrows a span, and the ADR-0021 extension moves
        # `start` left within the same line without touching `end` — so no repair
        # can push a span past the end of the text it was validated against.
        self._validate(detected, text=text, requested=requested)
        matches = [bounded for match in detected for bounded in self._bound_to_line(match, text)]
        matches = [candidate for match in matches for candidate in self._extend_left(match, text)]
        return sorted(matches, key=lambda match: (match.start, match.end, match.entity_type))

    def detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None] | None = None,
        entities: Collection[str] | None = None,
    ) -> list[list[EntityMatch]]:
        """Default: one call per text. Providers with native batching should override."""
        if languages is not None and len(languages) != len(texts):
            raise ProviderError(
                f"provider {self.name!r}: got {len(languages)} languages for {len(texts)} texts"
            )
        resolved = list(languages) if languages is not None else [None] * len(texts)
        return [
            self.detect(text, language=language, entities=entities)
            for text, language in zip(texts, resolved, strict=True)
        ]

    def _bound_to_line(self, match: EntityMatch, text: str) -> list[EntityMatch]:
        """Split a span that crosses a line break into one span per line.

        An NER model handed a multi-line block runs entity boundaries through breaks:
        it returns `Peter Novak` + break + `Mobile` for the PERSON in a key/value
        block. The model is right about the entity and wrong about where it stops, so
        the span is repaired rather than dropped — dropping it would leave the name in
        the output, and keeping it whole destroys the next line's text.

        **Every non-empty fragment is kept, not just the best one.** Choosing one
        fragment is only safe when the name sits entirely on one side of the break,
        and it does not always: a hard-wrapped `Jürgen` + break + `Müller` is one name
        split in two, and keeping either half leaves the other in the output. That
        leak is invisible to `leakage_rate`, which counts an entity leaked only when
        its *exact full* surface survives — half a name never matches. Keeping every
        fragment can over-redact the neighbouring line instead, which is the direction
        this project can measure and gates at 0.000.

        Fragments are counted rather than discarded silently: a provider upgrade that
        starts producing them would otherwise change coverage with no signal
        (ADR-0004's argument for `drop_counter`, applied to spans).
        """
        if match.entity_type not in LINE_BOUNDED_ENTITIES:
            return [match]

        surface = text[match.start : match.end]
        if not any(character in surface for character in ("\n", "\r")):
            return [match]

        spans: list[tuple[int, int]] = []
        cursor = 0
        for separator in LINE_BREAK_SPLIT_RE.finditer(surface):
            spans.append((cursor, separator.start()))
            cursor = separator.end()
        spans.append((cursor, len(surface)))

        fragments: list[EntityMatch] = []
        for relative_start, relative_end in spans:
            start = match.start + relative_start
            end = match.start + relative_end
            while end > start and text[end - 1].isspace():
                end -= 1
            while start < end and text[start].isspace():
                start += 1
            if start < end:
                fragments.append(match.model_copy(update={"start": start, "end": end}))

        if not fragments:
            self.drop_counter.record_declared(self.name, "line_bounded_empty")
            return []
        self.drop_counter.record_declared(self.name, "line_bounded_split")
        return fragments

    def _resolve_scope(self, entities: Collection[str] | None) -> frozenset[str]:
        supported = self.supported_entities()
        if entities is None:
            return supported
        for label in entities:
            try:
                require_known(label, context=f"provider {self.name!r}")
            except UnknownEntityLabelError as exc:
                raise ProviderError(str(exc)) from exc
        return frozenset(entities) & supported

    def _validate(
        self, matches: list[EntityMatch], *, text: str, requested: frozenset[str]
    ) -> None:
        """Enforce the provider contract. Messages carry offsets, never text."""
        for match in matches:
            if match.provider != self.name:
                raise ProviderError(
                    f"provider {self.name!r}: returned a match attributed to {match.provider!r}"
                )
            try:
                require_known(match.entity_type, context=f"provider {self.name!r}")
            except UnknownEntityLabelError as exc:
                raise ProviderError(str(exc)) from exc
            if match.entity_type not in requested:
                raise ProviderError(
                    f"provider {self.name!r}: returned {match.entity_type} which was not "
                    f"requested (requested: {', '.join(sorted(requested))})"
                )
            if not match.is_within(text):
                raise ProviderError(
                    f"provider {self.name!r}: match [{match.start}, {match.end}) exceeds text "
                    f"of length {len(text)}"
                )

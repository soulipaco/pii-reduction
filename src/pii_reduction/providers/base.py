"""Provider protocol and the contract every provider is held to.

``BaseProvider.detect`` is a template method: subclasses implement ``_detect`` and the
base class enforces the provider contract (``docs/10_TESTING_QA.md`` §4) on the way
out — normalized labels, valid offsets, requested entity scope, stable ordering.
A provider that misbehaves fails loudly here rather than corrupting text downstream.

The base also performs *repairs* rather than only checking. A span of a line-bounded
entity type that crosses a line break is split into one span per line
(``BaseProvider._bound_to_line``, ADR-0016 — every fragment is kept, not just the
longest). A PERSON span may then be widened over one preceding token, opt-in per
instance (``BaseProvider._extend_left``, ADR-0021); that is the one repair which does
not narrow. **Last**, a span of a model-inferred entity type is clipped back out of any
HTML, BBCode, URL or entity region it overlaps (``BaseProvider._clip_out_of_markup``,
ADR-0027) — last because the widening step can otherwise pull a span back into a tag,
and because clipping only narrows, so nothing after it is needed.

Validation runs first, so a genuinely malformed span still raises rather than being
quietly reshaped, and no repair can invalidate it: splitting and clipping only narrow,
and widening moves ``start`` left within a line without touching ``end``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from typing import Protocol, runtime_checkable

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.errors import UnknownEntityLabelError
from pii_reduction.entities.mapping import DropCounter
from pii_reduction.entities.taxonomy import (
    PERSON,
    line_bounded_labels,
    markup_guarded_labels,
    require_known,
)
from pii_reduction.patterns import (
    MARKUP_DELIMITER_PATTERN,
    MARKUP_TOKEN_VOCABULARY,
    is_identifier_shaped,
    markup_free_fragments,
    markup_regions,
)
from pii_reduction.providers.errors import ProviderError

__all__ = [
    "LINE_BOUNDED_ENTITIES",
    "LINE_BREAK_SPLIT_RE",
    "MARKUP_GUARDED_ENTITIES",
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

#: Entity types the markup guard may clip (ADR-0027). Derived from the taxonomy for
#: the same reason as :data:`LINE_BOUNDED_ENTITIES`: "does this entity have a grammar
#: of its own?" is a static fact about the entity, and restating it here is how the two
#: definitions drift. EMAIL and PHONE are absent — clipping one would leak.
MARKUP_GUARDED_ENTITIES: frozenset[str] = markup_guarded_labels()

#: Characters trimmed from the edge of a span that a markup region was clipped out of.
#: A fragment left behind by clipping routinely begins or ends on the joiner that held
#: it to the tag, and redacting that joiner damages the syntax the clip just preserved.
_MARKUP_EDGE = " \t\r\n.,;:!?()[]{}\"'`*-\u2013\u2014@/\\&#+=<>"

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

    def _detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None],
        entities: frozenset[str],
    ) -> list[list[EntityMatch]]:
        """Detect candidates for several texts. Default: one ``_detect`` call each.

        The hook a provider with native batching overrides (ADR-0033). It sits *below*
        the repair chain deliberately: everything :meth:`_finalize` does — validation,
        line-bounding, the ADR-0021 extension, the ADR-0027 markup clip, de-duplication
        — is a property of one text and its own spans, so batching must not get a
        second copy of it to drift from.

        ``languages`` is positional-aligned with ``texts`` and already the right
        length; :meth:`detect_batch` checks that before calling.
        """
        return [
            self._detect(text, language=language, entities=entities)
            for text, language in zip(texts, languages, strict=True)
        ]

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
        return self._finalize(detected, text=text, requested=requested)

    def _finalize(
        self, detected: list[EntityMatch], *, text: str, requested: frozenset[str]
    ) -> list[EntityMatch]:
        """Validate and repair one text's raw candidates. Shared by both entry points."""
        # Validate before repairing: a span that already runs past the end of the text
        # is a provider bug, and it must surface as an actionable ProviderError naming
        # the provider and offsets rather than as an IndexError from the repair code.
        # Line-bounding only ever narrows a span, and the ADR-0021 extension moves
        # `start` left within the same line without touching `end` — so no repair
        # can push a span past the end of the text it was validated against.
        self._validate(detected, text=text, requested=requested)
        matches = [bounded for match in detected for bounded in self._bound_to_line(match, text)]
        matches = [candidate for match in matches for candidate in self._extend_left(match, text)]
        # **Last, and that ordering is load-bearing.** The ADR-0021 extension widens a
        # span leftward over one capitalised token, and a token can end in a tag —
        # `Γιώργος</b>` is capitalised, is not identifier-shaped, and would be
        # swallowed whole. Clipping before the extension would therefore be undone by
        # it. Clipping last cannot be undone by anything, and it costs nothing:
        # ADR-0021 offers the widened span *and* the original, so if the widening is
        # clipped back the reconciler sees two identical candidates and treats the
        # second as corroboration (`_find_identical`).
        #
        # `markup_regions` is computed once per call and only when the cheap hint
        # fires, then shared by every candidate: the answer is a property of the text,
        # not of the span.
        regions = markup_regions(text)
        matches = [
            clipped
            for match in matches
            for clipped in self._clip_out_of_markup(match, text, regions)
        ]
        # Exact duplicates are dropped, which clipping-last can now produce: a widened
        # span clipped back to the span it was widened from. Left in, one provider
        # would appear in `supporting_matches` as its own corroboration, which is the
        # one thing that field is not.
        seen: set[tuple[int, int, str]] = set()
        unique: list[EntityMatch] = []
        for candidate in matches:
            key = (candidate.start, candidate.end, candidate.entity_type)
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return sorted(unique, key=lambda match: (match.start, match.end, match.entity_type))

    def detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None] | None = None,
        entities: Collection[str] | None = None,
    ) -> list[list[EntityMatch]]:
        """Detect over several texts at once, output-identical to ``detect`` per text.

        **Identical output is the contract, not an aspiration** (ADR-0033): a provider
        that batches must return exactly what the same texts would have produced one at
        a time. The shared contract suite asserts it for every provider, and
        `tests/test_batched_detection.py` asserts it over three committed corpora for
        the one provider that actually batches.

        Empty and non-``str`` texts take the same route they take in :meth:`detect` —
        an empty text yields no matches, and a non-``str`` is a ``ProviderError`` — so
        a caller cannot get a different answer by changing how many texts it passes.
        """
        if languages is not None and len(languages) != len(texts):
            raise ProviderError(
                f"provider {self.name!r}: got {len(languages)} languages for {len(texts)} texts"
            )
        resolved = list(languages) if languages is not None else [None] * len(texts)
        for text in texts:
            if not isinstance(text, str):
                raise ProviderError(
                    f"provider {self.name!r}: detect_batch() requires str, "
                    f"got {type(text).__name__}. Null values are handled by the field processor"
                )

        requested = self._resolve_scope(entities)
        if not requested:
            return [[] for _ in texts]

        # An empty text is dropped *before* the batch and re-inserted after. The
        # scalar path returns early on one, and a provider's batch API is entitled to
        # its own opinion about a zero-length document; neither should be able to make
        # the two paths disagree.
        indexed = [
            (position, text, language)
            for position, (text, language) in enumerate(zip(texts, resolved, strict=True))
            if text
        ]
        results: list[list[EntityMatch]] = [[] for _ in texts]
        if not indexed:
            return results

        detected = self._detect_batch(
            [text for _, text, _ in indexed],
            languages=[language for _, _, language in indexed],
            entities=requested,
        )
        if len(detected) != len(indexed):
            raise ProviderError(
                f"provider {self.name!r}: _detect_batch returned {len(detected)} results "
                f"for {len(indexed)} texts"
            )
        for (position, text, _), raw in zip(indexed, detected, strict=True):
            results[position] = self._finalize(raw, text=text, requested=requested)
        return results

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

    def _clip_out_of_markup(
        self, match: EntityMatch, text: str, regions: Sequence[tuple[int, int]]
    ) -> list[EntityMatch]:
        """Clip a model-inferred span back out of HTML, BBCode, URLs and entities.

        ADR-0027. An NER model has no notion of markup: handed a quoted HTML fragment
        it reads ``[code]<div`` as running text and returns it as a PERSON with the
        same 0.85 the real names get. Reducing that span destroys the tag — and the
        damage is *inside* a region the parser correctly marked eligible, so neither
        the round-trip invariant nor the over-redaction gate can see it. The reference
        implementation measured the blast radius at 2,687 of 105,279 cells before it
        built this guard, on a corpus where 72% of one ServiceNow journal column
        carries markup (`docs/20_ALTERNATIVE_RECONCILIATION.md`).

        Four decisions, each load-bearing:

        * **Clip, never drop — including when clipping leaves nothing.** ``Grace
          Okafor</div>`` must still lose the name; only the tag is handed back. A span
          lying *wholly* inside a region is discarded only when its own surface
          carries a bracket character, which makes it machine syntax (``code]<div``);
          a plain surface inside a URL path is a name and is kept, because dropping it
          would leak it.
        * **Format-defined entities are exempt** (:data:`MARKUP_GUARDED_ENTITIES`).
          A string matching the email or phone grammar is that thing whatever sits
          beside it, and clipping one is a leak — strictly worse than the
          over-redaction this guard prevents.
        * **Every surviving fragment is kept**, as in :meth:`_bound_to_line` and for
          the same reason: a name split by a tag is a name on both sides of it, and
          keeping only the longest half leaks the other. This diverges from the
          reference implementation, which keeps one fragment; the divergence is
          recorded in ADR-0027.
        * **The plausibility drop is gated on the text containing markup at all**,
          which ``regions`` already answers. On markup-free text this method returns
          the span untouched, which is why no published benchmark number moves.

        **Both plausibility drops apply only to a surface the markup produced** — a
        fragment the clip actually shortened, or a span lying wholly inside a region
        (:meth:`_span_inside_markup`). A surface with fewer than two letters is not a
        name (an emoticon is not, and neither is a lone digit run), and once the angle
        brackets are gone ``div`` and ``href`` read to a model as proper nouns. But
        neither test may be applied to a span markup never touched: the vocabulary
        holds real surnames (``Small``, ``Link``, ``Name``) and an ADDRESS surface is
        legitimately digit-only, so judging an untouched span by either would delete
        a real entity — under-redaction, which is the error this guard must not
        commit. The edge trim still applies to every span in a markup-bearing text; it
        only ever removes punctuation.
        """
        if not regions or match.entity_type not in MARKUP_GUARDED_ENTITIES:
            return [match]

        outside = markup_free_fragments(match.start, match.end, regions)
        if not outside:
            return self._span_inside_markup(match, text)

        fragments: list[EntityMatch] = []
        for start, end in outside:
            # **Before the trim.** Computing it afterwards makes punctuation trimming
            # count as "the markup clipped this", which re-opens the plausibility drops
            # to a span markup never touched: `"Small"` in a cell holding a URL trims
            # to `Small`, hits the tag vocabulary, and the surname is deleted. The
            # architecture review of this increment found exactly that.
            clipped = (start, end) != (match.start, match.end)
            while start < end and text[start] in _MARKUP_EDGE:
                start += 1
            while end > start and text[end - 1] in _MARKUP_EDGE:
                end -= 1
            if start >= end:
                continue
            surface = text[start:end]
            if clipped and sum(1 for character in surface if character.isalpha()) < 2:
                continue
            if clipped and surface.lower() in MARKUP_TOKEN_VOCABULARY:
                continue
            fragments.append(
                match
                if (start, end) == (match.start, match.end)
                else match.model_copy(update={"start": start, "end": end})
            )

        if not fragments:
            # Fragments existed and every one of them failed a plausibility check, so
            # nothing name-like survived outside the markup. Dropping is right here.
            self.drop_counter.record_declared(self.name, "markup_dropped")
            return []
        if fragments != [match]:
            self.drop_counter.record_declared(self.name, "markup_clipped")
        return fragments

    def _span_inside_markup(self, match: EntityMatch, text: str) -> list[EntityMatch]:
        """Decide a span that lies **wholly** inside a markup region.

        **Dropping it blind is a leak**, and the privacy audit of this increment caught
        exactly that: a PERSON span inside a URL path (`…/u/Grace.Okafor`) clips to
        nothing and would have gone out unredacted — the invisible error, produced by
        the guard that exists to prevent the visible one.

        So the surface is judged rather than assumed, on the three tests that can be
        made structurally. It is machine syntax, and discarded, when it carries a
        bracket character (``code]<div`` — the failure this guard was built for), when
        it is a tag or attribute name (``div``), or when it holds fewer than two
        letters (an emoticon). Otherwise it is a name that happens to sit inside
        machine syntax, and it is kept: redacting it damages a URL, which is the
        visible error this project chooses every time it has the choice (ADR-0016,
        ADR-0021, ADR-0023).
        """
        surface = text[match.start : match.end]
        trimmed = surface.strip(_MARKUP_EDGE)
        if (
            MARKUP_DELIMITER_PATTERN.search(surface)
            or sum(1 for character in trimmed if character.isalpha()) < 2
            or trimmed.lower() in MARKUP_TOKEN_VOCABULARY
        ):
            self.drop_counter.record_declared(self.name, "markup_dropped")
            return []
        self.drop_counter.record_declared(self.name, "markup_kept_inside_region")
        return [match]

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

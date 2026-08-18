"""Provider protocol and the contract every provider is held to.

``BaseProvider.detect`` is a template method: subclasses implement ``_detect`` and the
base class enforces the provider contract (``docs/10_TESTING_QA.md`` §4) on the way
out — normalized labels, valid offsets, requested entity scope, stable ordering.
A provider that misbehaves fails loudly here rather than corrupting text downstream.

The base also performs one *repair* rather than only checking: a span of a
line-bounded entity type that crosses a line break is trimmed back to the line
(``BaseProvider._bound_to_line``, ADR-0016). Validation runs first, so a genuinely
malformed span still raises rather than being quietly reshaped, and repair only
ever narrows a span that was already valid.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from typing import Protocol, runtime_checkable

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.errors import UnknownEntityLabelError
from pii_reduction.entities.mapping import DropCounter
from pii_reduction.entities.taxonomy import line_bounded_labels, require_known
from pii_reduction.providers.errors import ProviderError

__all__ = ["LINE_BOUNDED_ENTITIES", "LINE_BREAK_SPLIT_RE", "BaseProvider", "PIIProvider"]

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

    @abstractmethod
    def supported_entities(self) -> frozenset[str]:
        """Normalized labels this provider can produce."""

    def supported_languages(self) -> frozenset[str] | None:
        """``None`` means language-independent."""
        return None

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
        # Repair only ever narrows a span, so the validated spans stay valid.
        self._validate(detected, text=text, requested=requested)
        matches = [bounded for match in detected for bounded in self._bound_to_line(match, text)]
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

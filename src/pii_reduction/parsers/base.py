"""Parser protocol, parse result, and the shared reconstruction implementation.

The contract every parser owes (``docs/03_DATA_CONTRACTS.md`` §17)::

    reconstruct(parse(text)) == text

byte-for-byte, before any transformation. Reconstruction is implemented once, here,
so a new parser cannot get it subtly wrong: parsers only have to emit segments that
tile the source text in order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from pii_reduction.contracts.base import FrozenModel
from pii_reduction.contracts.segments import TextSegment
from pii_reduction.parsers.errors import ParserError

__all__ = ["BaseParser", "ParseResult", "Parser"]


class ParseResult(FrozenModel):
    """Ordered segments of one parsed field, plus how the parse went."""

    parser: str = Field(min_length=1)
    segments: tuple[TextSegment, ...]
    #: Machine-readable reasons a fallback path was taken, e.g. ``no_speaker_prefix``.
    #: Counted in run metrics; never contains text.
    fallbacks: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_ordinals_are_sequential(self) -> Self:
        expected = list(range(len(self.segments)))
        actual = [segment.ordinal for segment in self.segments]
        if actual != expected:
            raise ValueError(f"segment ordinals must be 0..n-1 in order, got {actual}")
        ids = [segment.segment_id for segment in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("segment ids must be unique within a parse result")
        return self

    @property
    def fallback_used(self) -> bool:
        return bool(self.fallbacks)

    @property
    def processable_segments(self) -> tuple[TextSegment, ...]:
        return tuple(segment for segment in self.segments if segment.processable)

    def source_text(self) -> str:
        """The original field text, rebuilt from the segments."""
        return "".join(segment.text for segment in self.segments)


@runtime_checkable
class Parser(Protocol):
    """What the processing layer depends on. Implementations live in this package."""

    @property
    def name(self) -> str: ...

    def parse(self, text: str) -> ParseResult: ...

    def reconstruct(
        self,
        result: ParseResult,
        transformed_segments: Mapping[str, str] | None = None,
    ) -> str: ...


class BaseParser(ABC):
    """Shared reconstruction and input checking."""

    #: Registry name, matching ``config.registries.KNOWN_PARSERS``.
    name: str = ""

    @abstractmethod
    def parse(self, text: str) -> ParseResult:
        """Split ``text`` into ordered segments that tile it exactly."""

    def reconstruct(
        self,
        result: ParseResult,
        transformed_segments: Mapping[str, str] | None = None,
    ) -> str:
        """Reassemble the field, substituting transformed text for processable segments.

        Non-processable structure comes back byte-for-byte
        (``docs/01_ARCHITECTURE.md``, layer 8). Handing this method a replacement for
        a non-processable segment is a programming error, not a silent no-op.
        """
        if transformed_segments is None:
            return result.source_text()

        by_id = {segment.segment_id: segment for segment in result.segments}
        unknown = sorted(set(transformed_segments) - set(by_id))
        if unknown:
            raise ParserError(
                f"parser {self.name!r}: transformed segments {', '.join(unknown)} are not part "
                "of this parse result"
            )
        immutable = sorted(
            segment_id for segment_id in transformed_segments if not by_id[segment_id].processable
        )
        if immutable:
            raise ParserError(
                f"parser {self.name!r}: segments {', '.join(immutable)} are not processable and "
                "must not be transformed"
            )

        return "".join(
            transformed_segments.get(segment.segment_id, segment.text)
            if segment.processable
            else segment.text
            for segment in result.segments
        )

    def _require_text(self, text: str) -> None:
        """Null handling belongs to the caller (``docs/03`` §18: null in, null out)."""
        if not isinstance(text, str):
            raise ParserError(
                f"parser {self.name!r}: parse() requires str, got {type(text).__name__}. "
                "Null values are handled by the field processor, not by parsers"
            )

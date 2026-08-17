"""Parser output contract (``docs/03_DATA_CONTRACTS.md`` §4).

A parser turns one source field into ordered segments. Segments carry the text plus
everything reconstruction needs; ``processable=False`` marks structure that must come
back byte-identical (transcript prefixes, note headers).
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import Field, model_validator

from pii_reduction.contracts.base import FrozenModel

__all__ = ["TextSegment"]


class TextSegment(FrozenModel):
    """One ordered piece of a parsed field.

    ``source_start``/``source_end`` are codepoint offsets into the original field
    when the parser can supply them. They are optional because a parser is allowed
    to reconstruct positionally instead; when present they must be consistent
    (``0 <= source_start <= source_end``, empty segments allowed).
    """

    segment_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    text: str
    processable: bool
    segment_type: str = Field(min_length=1)
    source_start: int | None = None
    source_end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_source_offsets(self) -> Self:
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("source_start and source_end must be set together or both omitted")
        if self.source_start is not None and self.source_end is not None:
            if self.source_start < 0:
                raise ValueError(f"source_start must be >= 0, got {self.source_start}")
            if self.source_end < self.source_start:
                raise ValueError(
                    "source_end must be >= source_start, got "
                    f"source_start={self.source_start} source_end={self.source_end}"
                )
            if self.source_end - self.source_start != len(self.text):
                raise ValueError(
                    "source offsets must span exactly the segment text: "
                    f"{self.source_end - self.source_start} offsets vs {len(self.text)} characters"
                )
        return self

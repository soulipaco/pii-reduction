"""Character-span contract.

Offsets are Python codepoint indices into the exact string that was analysed. No
Unicode normalization happens anywhere in the pipeline (ADR-0011), so a span is
only meaningful against the exact string form it was produced from.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from pii_reduction.contracts.base import FrozenModel
from pii_reduction.contracts.errors import SpanContractError

__all__ = ["Span"]


class Span(FrozenModel):
    """A half-open ``[start, end)`` character range with ``0 <= start < end``.

    The remaining half of the documented invariant (``end <= len(text)``) needs the
    text, so it is checked by :meth:`validate_within` at the boundary where the text
    is available — provider adapters, reducers and the manifest loader.
    """

    start: int
    end: int

    @model_validator(mode="after")
    def _check_offsets(self) -> Self:
        if self.start < 0:
            raise ValueError(f"span start must be >= 0, got {self.start}")
        if self.end <= self.start:
            raise ValueError(f"span end must be > start, got start={self.start} end={self.end}")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start

    def is_within(self, text: str) -> bool:
        return self.end <= len(text)

    def slice_of(self, text: str) -> str:
        """Return the covered substring. Never log or persist the result."""
        self.validate_within(text)
        return text[self.start : self.end]

    def validate_within(self, text: str) -> None:
        """Raise :class:`SpanContractError` if the span runs past the end of ``text``.

        The message reports offsets and lengths only — never the text itself.
        """
        if not self.is_within(text):
            raise SpanContractError(
                f"span [{self.start}, {self.end}) exceeds text of length {len(text)}"
            )

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

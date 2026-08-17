"""Parser errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["ParserError"]


class ParserError(PiiReductionError):
    """A parser was misused or its options are invalid.

    Structural oddities in the *text* are never errors: a malformed line falls back
    to being one processable segment and the fallback is recorded (``docs/06``,
    ``fallback: preserve_line``). Messages here name segment ids and option names,
    never source text.
    """

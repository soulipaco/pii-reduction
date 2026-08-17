"""Source errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["SourceError"]


class SourceError(PiiReductionError):
    """A source could not be read, or its options are invalid.

    Messages name paths, column names and row counts — never cell contents.
    """

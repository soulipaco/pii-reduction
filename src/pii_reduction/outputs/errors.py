"""Output errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["OutputError"]


class OutputError(PiiReductionError):
    """A destination could not be written, or its options are invalid."""

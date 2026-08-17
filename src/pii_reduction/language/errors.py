"""Language resolution errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["LanguageError"]


class LanguageError(PiiReductionError):
    """Language could not be resolved with the configured strategy."""

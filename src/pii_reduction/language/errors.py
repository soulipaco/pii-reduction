"""Language resolution errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["LanguageError", "LanguageNotAvailableError"]


class LanguageError(PiiReductionError):
    """Language could not be resolved with the configured strategy."""


class LanguageNotAvailableError(LanguageError):
    """A detector's optional dependency is not installed.

    Raised with the exact install command. Nothing auto-installs, and no detector
    silently degrades to a default language — an unknown language is reported as
    unknown (``docs/03_DATA_CONTRACTS.md`` §5).
    """

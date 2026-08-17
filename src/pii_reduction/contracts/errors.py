"""Base exception type shared by every layer.

Each layer defines its own subclass (``ConfigurationError``, parser/provider/output
errors) so callers can catch a whole category. Messages must stay privacy-safe:
they may name datasets, columns, offsets, providers and error categories, but never
source text or a matched PII value (``AGENTS.md`` rule 8).
"""

from __future__ import annotations

__all__ = ["PiiReductionError", "SpanContractError"]


class PiiReductionError(Exception):
    """Root of the package's exception hierarchy."""


class SpanContractError(PiiReductionError):
    """A span violates ``0 <= start < end <= len(text)`` for the text it refers to."""

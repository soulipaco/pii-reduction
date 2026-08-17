"""Corpus generation and ground-truth errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["CorpusError", "GroundTruthError"]


class CorpusError(PiiReductionError):
    """A corpus could not be generated or its templates are malformed."""


class GroundTruthError(PiiReductionError):
    """A manifest span does not slice to the value it claims.

    The message reports document id, entity id and offsets — never the expected
    surface string. That keeps the loader privacy-safe even when it is pointed at a
    manifest for non-synthetic data (ADR-0011, and the session-2 privacy review).
    """

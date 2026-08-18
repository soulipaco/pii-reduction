"""Corpus generation and ground-truth errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["CorpusError", "DatasetDownloadError", "GroundTruthError"]


class CorpusError(PiiReductionError):
    """A corpus could not be generated or its templates are malformed."""


class DatasetDownloadError(CorpusError):
    """A public dataset file could not be retrieved, or is not the file we recorded.

    A subclass of :class:`CorpusError` because a failed retrieval is a corpus that
    cannot be built, and every caller already handles that. It has its own name
    because the remedy is different: a checksum mismatch is answered by re-recording
    the retrieval block (ADR-0017), not by fixing a template.
    """


class GroundTruthError(PiiReductionError):
    """A manifest span does not slice to the value it claims.

    The message reports document id, entity id and offsets — never the expected
    surface string. That keeps the loader privacy-safe even when it is pointed at a
    manifest for non-synthetic data (ADR-0011, and the session-2 privacy review).
    """

"""Processing errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["ProcessingError"]


class ProcessingError(PiiReductionError):
    """The run cannot proceed: structural problems with the dataset or its identity.

    Row-level problems are not errors — they follow the configured failure mode and
    are counted. This is for conditions that make the whole run meaningless: a
    missing row-id column, duplicate row identities, a configured column absent from
    the source.
    """

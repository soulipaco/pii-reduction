"""Reduction contract (``docs/03_DATA_CONTRACTS.md`` §8).

One record per replaced span. The original matched value is deliberately absent:
privacy-safe audit mode is the only mode this contract supports.
"""

from __future__ import annotations

from pydantic import Field

from pii_reduction.contracts.labels import NormalizedLabel
from pii_reduction.contracts.spans import Span

__all__ = ["ReductionOperation"]


class ReductionOperation(Span):
    """A single applied replacement, recorded against the pre-reduction offsets."""

    entity_type: NormalizedLabel
    replacement: str
    strategy: str = Field(min_length=1)

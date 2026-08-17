"""Source adapter contract.

A source adapter loads rows and lineage metadata. It never inspects text, decides
which columns are sensitive, or mutates anything (``docs/01_ARCHITECTURE.md`` layer 1).

Adapters are constructed from primitives, not from configuration objects, so this
package never imports ``config``: the pipeline builder translates a validated
``SourceConfig`` into these arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import pandas as pd

__all__ = ["SourceAdapter", "SourceDataset"]


@dataclass(frozen=True)
class SourceDataset:
    """Rows plus the lineage the run record needs."""

    name: str
    frame: pd.DataFrame
    source_type: str
    source_reference: str
    source_version: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.frame)


@runtime_checkable
class SourceAdapter(Protocol):
    @property
    def source_type(self) -> str: ...

    def load(self) -> SourceDataset: ...

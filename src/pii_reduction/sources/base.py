"""Source adapter contract.

A source adapter loads rows and lineage metadata. It never inspects text, decides
which columns are sensitive, or mutates anything (``docs/01_ARCHITECTURE.md`` layer 1).

Adapters are constructed from primitives, not from configuration objects, so this
package never imports ``config``: the pipeline builder translates a validated
``SourceConfig`` into these arguments.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import pandas as pd

__all__ = ["SourceAdapter", "SourceDataset", "SourceSchema"]


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


@dataclass(frozen=True)
class SourceSchema:
    """What a source *has*, answered without reading what it holds.

    Column names only, and the omission is the design. A name is metadata — `docs/09`
    already lists `column` among the fields a log line may carry — while a value is
    not, and a schema call that returned a sample row would be the "show me a few rows
    so I can pick columns" shape ADR-0026 forbids by name, arriving through a side
    door.

    Types are absent for a reason worth stating rather than leaving as a gap: a CSV
    has none, and inferring them means reading rows. An adapter that could answer
    honestly (parquet, Delta) would then be the only one that did, and a caller could
    not tell the difference between "this column is not text" and "this adapter does
    not know". One answer every adapter can give beats a richer one only some can.
    """

    name: str
    source_type: str
    source_reference: str
    columns: tuple[str, ...]

    def has(self, column: str) -> bool:
        return column in self.columns

    def missing(self, columns: Iterable[str]) -> tuple[str, ...]:
        """Which of ``columns`` this source does not have. Sorted, so it reads well."""
        return tuple(sorted(set(columns) - set(self.columns)))


@runtime_checkable
class SourceAdapter(Protocol):
    @property
    def source_type(self) -> str: ...

    def load(self) -> SourceDataset: ...

    def schema(self) -> SourceSchema:
        """The column names, **without materialising the rows**.

        Every adapter must answer this without reading data: a header line for CSV,
        file metadata for parquet, the metastore for a Delta table. That is the whole
        value of the method — a column picker, or a check that a configured column
        exists, should not cost a scan of a production table, and on the Databricks
        path it must not pull rows to the driver at all.

        The property is not merely documented: `tests/test_source_schema.py` pins it
        per adapter through readers that fail if data is touched — an unparseable
        second line and an ignored row limit for CSV, patched row-group readers for
        parquet, and a fake session whose frame raises on any attribute but `schema`
        for Spark, with a companion test proving `load()` *does* trip it.
        """
        ...

"""Local source adapters: in-memory pandas, CSV, parquet."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from pii_reduction.sources.base import SourceDataset
from pii_reduction.sources.errors import SourceError

__all__ = ["CsvSource", "PandasSource", "ParquetSource"]

CSV_OPTIONS = frozenset({"encoding", "delimiter", "quotechar", "nrows"})


class PandasSource:
    """An already-loaded frame. The adapter used by tests, notebooks and Spark parity."""

    source_type = "pandas"

    def __init__(
        self,
        frame: pd.DataFrame,
        *,
        name: str,
        reference: str = "in_memory",
        version: str | None = None,
    ) -> None:
        if not isinstance(frame, pd.DataFrame):
            raise SourceError(f"source {name!r}: expected a DataFrame, got {type(frame).__name__}")
        self._frame = frame
        self._name = name
        self._reference = reference
        self._version = version

    def load(self) -> SourceDataset:
        # Copy so nothing downstream can mutate the caller's frame.
        return SourceDataset(
            name=self._name,
            frame=self._frame.copy(),
            source_type=self.source_type,
            source_reference=self._reference,
            source_version=self._version,
        )


class CsvSource:
    """Delimited text files."""

    source_type = "csv"

    def __init__(
        self, path: str | Path, *, name: str, options: dict[str, Any] | None = None
    ) -> None:
        unknown = sorted(set(options or {}) - CSV_OPTIONS)
        if unknown:
            raise SourceError(
                f"source {name!r}: unknown csv options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(CSV_OPTIONS))})"
            )
        self._path = Path(path)
        self._name = name
        self._options = dict(options or {})

    def load(self) -> SourceDataset:
        if not self._path.is_file():
            raise SourceError(f"source {self._name!r}: file not found: {self._path}")
        try:
            frame = pd.read_csv(
                self._path,
                encoding=self._options.get("encoding", "utf-8"),
                sep=self._options.get("delimiter", ","),
                quotechar=self._options.get("quotechar", '"'),
                nrows=self._options.get("nrows"),
            )
        except UnicodeDecodeError as exc:
            raise SourceError(
                f"source {self._name!r}: {self._path} is not valid "
                f"{self._options.get('encoding', 'utf-8')}"
            ) from exc
        except pd.errors.ParserError as exc:
            raise SourceError(f"source {self._name!r}: could not parse {self._path}") from exc
        return SourceDataset(
            name=self._name,
            frame=frame,
            source_type=self.source_type,
            source_reference=str(self._path),
        )


class ParquetSource:
    """Columnar files. Requires the ``parquet`` extra (pyarrow)."""

    source_type = "parquet"

    def __init__(
        self, path: str | Path, *, name: str, options: dict[str, Any] | None = None
    ) -> None:
        if options:
            raise SourceError(
                f"source {name!r}: unknown parquet options {', '.join(sorted(options))}"
            )
        self._path = Path(path)
        self._name = name

    def load(self) -> SourceDataset:
        if not self._path.exists():
            raise SourceError(f"source {self._name!r}: file not found: {self._path}")
        try:
            frame = pd.read_parquet(self._path)
        except ImportError as exc:
            raise SourceError(
                f"source {self._name!r}: reading parquet needs pyarrow. "
                "Install it with: pip install 'pii-reduction[parquet]'"
            ) from exc
        return SourceDataset(
            name=self._name,
            frame=frame,
            source_type=self.source_type,
            source_reference=str(self._path),
        )

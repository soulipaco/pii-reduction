"""Local source adapters: in-memory pandas, CSV, parquet."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from pii_reduction.sources.base import SourceDataset, SourceSchema
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

    def schema(self) -> SourceSchema:
        # Already in memory, so there is nothing to avoid reading.
        return SourceSchema(
            name=self._name,
            source_type=self.source_type,
            source_reference=self._reference,
            columns=tuple(str(column) for column in self._frame.columns),
        )

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

    def schema(self) -> SourceSchema:
        """The header line, and nothing after it.

        ``nrows=0`` rather than the configured value: a source narrowed to a sample
        still *has* every column, and answering "which columns exist" from a slice
        would make the answer depend on a performance setting.
        """
        header = self._read(nrows=0)
        return SourceSchema(
            name=self._name,
            source_type=self.source_type,
            source_reference=str(self._path),
            columns=tuple(str(column) for column in header.columns),
        )

    def _read(self, *, nrows: int | None) -> pd.DataFrame:
        """One reader for both callers, and the sharing is the point.

        ``CSV_OPTIONS`` is a mutable set. With two copies of this, adding ``header``
        or ``skiprows`` to the set and to ``load()`` alone would make ``schema()``
        report columns the run never sees — silently, which is the failure class this
        whole module is guarding against elsewhere.
        """
        if not self._path.is_file():
            raise SourceError(f"source {self._name!r}: file not found: {self._path}")
        encoding = self._options.get("encoding", "utf-8")
        try:
            return pd.read_csv(
                self._path,
                encoding=encoding,
                sep=self._options.get("delimiter", ","),
                quotechar=self._options.get("quotechar", '"'),
                nrows=nrows,
            )
        except UnicodeDecodeError as exc:
            raise SourceError(
                f"source {self._name!r}: {self._path} is not valid {encoding}"
            ) from exc
        except pd.errors.EmptyDataError as exc:
            # A subclass of ValueError, not ParserError, so it escaped `SourceError`
            # entirely and reached the user as a pandas traceback. Pre-existing in
            # `load()`; caught here once for both callers.
            raise SourceError(
                f"source {self._name!r}: {self._path} is empty — no header row to read"
            ) from exc
        except pd.errors.ParserError as exc:
            raise SourceError(f"source {self._name!r}: could not parse {self._path}") from exc

    def load(self) -> SourceDataset:
        frame = self._read(nrows=self._options.get("nrows"))
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

    def schema(self) -> SourceSchema:
        """The file's own schema block. No row group is opened.

        ``pandas.read_parquet(columns=[])`` would also avoid the data but goes through
        the whole engine dispatch to do it; the footer is what the question is actually
        about, and reading it directly says so.

        **A parquet footer also carries per-column min/max statistics — real values.**
        Only ``.names`` is taken, and that is a rule rather than an accident: anything
        here that later reports types or statistics would put actual column extrema on
        a display surface, which `docs/09` classes unsafe. See ADR-0031.
        """
        if not self._path.exists():
            raise SourceError(f"source {self._name!r}: file not found: {self._path}")
        try:
            import pyarrow.dataset as dataset
        except ImportError as exc:
            raise SourceError(
                f"source {self._name!r}: reading parquet needs pyarrow. "
                "Install it with: pip install 'pii-reduction[parquet]'"
            ) from exc
        try:
            # `pyarrow.dataset` rather than `parquet.read_schema`, because `load()`
            # uses `pd.read_parquet`, which accepts a **partitioned directory** — and
            # `read_schema` does not. A pre-flight check that refuses a source the run
            # reads happily is worse than no check: it reports a broken dataset that
            # works. Still footer-only; no row group is opened either way.
            fields = dataset.dataset(self._path, format="parquet").schema.names
        except Exception as exc:
            raise SourceError(
                f"source {self._name!r}: could not read the parquet schema at {self._path}"
            ) from exc
        return SourceSchema(
            name=self._name,
            source_type=self.source_type,
            source_reference=str(self._path),
            columns=tuple(str(field) for field in fields),
        )

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

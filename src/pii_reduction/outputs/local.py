"""Local output adapters: in-memory pandas, CSV, parquet, plus run-metrics JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from pii_reduction.outputs.errors import OutputError

__all__ = ["CsvOutput", "PandasOutput", "ParquetOutput", "write_json"]

MODES = frozenset({"overwrite", "error"})


class PandasOutput:
    """Keeps the frame in memory. Useful in notebooks and tests."""

    destination_type = "pandas"

    def __init__(self) -> None:
        self.frames: dict[str, pd.DataFrame] = {}

    def write(self, frame: pd.DataFrame, *, name: str) -> str:
        self.frames[name] = frame.copy()
        return f"memory://{name}"


class _FileOutput:
    destination_type = ""
    suffix = ""

    def __init__(self, path: str | Path, *, mode: str = "overwrite") -> None:
        if mode not in MODES:
            raise OutputError(
                f"destination mode {mode!r} is not supported (known: {', '.join(sorted(MODES))})"
            )
        self._path = Path(path)
        self._mode = mode

    def _target(self, name: str) -> Path:
        # A path with our suffix is a file; anything else is treated as a directory.
        if self._path.suffix == self.suffix:
            target = self._path
        else:
            target = self._path / f"{name}{self.suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and self._mode == "error":
            raise OutputError(f"destination already exists and mode is 'error': {target}")
        return target


class CsvOutput(_FileOutput):
    destination_type = "csv"
    suffix = ".csv"

    def write(self, frame: pd.DataFrame, *, name: str) -> str:
        target = self._target(name)
        frame.to_csv(target, index=False, encoding="utf-8")
        return str(target)


class ParquetOutput(_FileOutput):
    """Requires the ``parquet`` extra (pyarrow).

    **The dependency is checked when the adapter is constructed, not when it writes.**
    The pipeline builds its output adapter before it reads a row, so a missing engine
    fails in the first second rather than after the whole corpus has been detected and
    reduced. The reference implementation compared in `docs/20` lost an eighteen-minute
    cluster run to exactly this, which is more evidence than the check costs.
    """

    destination_type = "parquet"
    suffix = ".parquet"

    def __init__(self, path: str | Path, *, mode: str = "overwrite") -> None:
        super().__init__(path, mode=mode)
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise OutputError(
                "writing parquet needs pyarrow. Install it with: "
                "pip install 'pii-reduction[parquet]'"
            ) from exc

    def write(self, frame: pd.DataFrame, *, name: str) -> str:
        target = self._target(name)
        try:
            frame.to_parquet(target, index=False)
        except ImportError as exc:
            # Kept as well as the constructor check: `to_parquet` can resolve a
            # different engine than the import above, and a write-time failure still
            # needs to say what to install rather than surfacing pandas' own message.
            raise OutputError(
                "writing parquet needs pyarrow. Install it with: "
                "pip install 'pii-reduction[parquet]'"
            ) from exc
        return str(target)


def write_json(path: str | Path, payload: dict[str, Any]) -> str:
    """Persist run metrics. Only metadata is ever written here — never source text."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return str(target)

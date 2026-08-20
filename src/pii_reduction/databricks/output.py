"""Delta table output: the standard ``OutputAdapter`` over ``saveAsTable``.

Delta is the required output format on Databricks (`AGENTS.md` Databricks rules;
`docs/07` table design). Row grain is preserved and reduced columns are appended by
the pipeline before this adapter ever sees the frame — writing is all this does.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from pii_reduction.databricks.errors import DatabricksError, error_label
from pii_reduction.databricks.source import require_table_name

__all__ = ["DeltaTableOutput"]

_KNOWN_MODES = frozenset({"overwrite", "append", "errorifexists"})

#: What this project calls a mode, and what the client actually accepts.
#:
#: Databricks Connect **rejects** ``errorifexists`` outright —
#: ``[UNSUPPORTED_OPERATION] errorifexists is not supported`` — while accepting
#: Spark's older alias ``error``, which behaves identically: a second write to an
#: existing table raises. Measured against the workspace on 16.4 (session 10), where
#: it broke the first real end-to-end run of the CLI: the shipped default is
#: ``errorifexists``, so *every* config-driven Delta write failed, and the parity
#: test never saw it because it passes ``mode="overwrite"`` explicitly.
#:
#: The translation lives here rather than in the configuration vocabulary on purpose
#: — the same shape as ADR-0004's per-model label mapping inside provider adapters.
#: ``errorifexists`` is Spark's documented name, `docs/06` publishes it, and the local
#: file adapters use their own spelling too — adapting a name to what a client will
#: take is exactly an adapter's job.
_SPARK_MODES = {"errorifexists": "error", "overwrite": "overwrite", "append": "append"}


class DeltaTableOutput:
    """Write a pandas frame as a Delta table under a fully-qualified prefix.

    ``prefix`` is ``catalog.schema`` and each write appends its ``name``:
    ``prefix.name``. One adapter therefore serves the reduced table, the audit table
    and the run-metrics table of a run, which keeps them in one schema by
    construction (`docs/07` lakehouse layout).
    """

    destination_type = "delta_table"

    def __init__(self, spark: Any, prefix: str, *, mode: str = "errorifexists") -> None:
        if mode not in _KNOWN_MODES:
            raise DatabricksError(
                f"unknown write mode {mode!r} (known: {', '.join(sorted(_KNOWN_MODES))}). "
                "The default refuses to touch an existing table; overwriting is a "
                "deliberate choice, not a fallback"
            )
        parts = prefix.split(".")
        if len(parts) != 2 or not all(parts):
            raise DatabricksError(
                f"prefix {prefix!r} must be catalog.schema — the table name is appended per write"
            )
        self._spark = spark
        self._prefix = prefix
        self._mode = mode

    def write(self, frame: pd.DataFrame, *, name: str) -> str:
        table = require_table_name(f"{self._prefix}.{name}")
        try:
            spark_frame = self._spark.createDataFrame(frame)
            spark_frame.write.format("delta").mode(_SPARK_MODES[self._mode]).saveAsTable(table)
        except Exception as error:
            raise DatabricksError(f"could not write {table} ({error_label(error)})") from error
        return table

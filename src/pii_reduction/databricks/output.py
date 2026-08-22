"""Delta table output: the standard ``OutputAdapter`` over ``saveAsTable``.

Delta is the required output format on Databricks (`AGENTS.md` Databricks rules;
`docs/07` table design). Row grain is preserved and reduced columns are appended by
the pipeline before this adapter ever sees the frame — writing is all this does.

Two of the things it does are translations from what this project calls something to
what a Delta client will accept: the write mode (``errorifexists`` → ``error``) and
**column mapping for column names Delta refuses** (``docs/20`` item A2). Both are an
adapter's job, in the same sense as ADR-0004's per-model label mapping: the
configuration vocabulary stays what `docs/06` publishes, and the client-specific
spelling stops here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from pii_reduction.databricks.errors import DatabricksError, error_label
from pii_reduction.databricks.source import require_table_name

__all__ = ["DeltaTableOutput", "needs_column_mapping"]

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

#: Characters Delta refuses in a column name unless column mapping is on.
#:
#: The Delta protocol rejects ``' ,;{}()\n\t='`` in a column name, and a **ServiceNow
#: export puts a space in almost every one of them** — ``Short description``,
#: ``Assigned to``, ``Comments and Work notes``. The reduction then derives its output
#: column from that name (``<column><output_suffix>``), so the sibling carries the
#: space too. Without the options below the very first real-data write fails with
#: ``DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES``.
_DELTA_INVALID_IN_COLUMN_NAME = frozenset(" ,;{}()\n\t=")

#: Enabling column mapping is what makes such a name legal. **Renaming is the
#: alternative and it is worse**: configuration addresses columns by their real
#: names and the reduced sibling is derived from that name, so a rename would ripple
#: into the dataset config and into the output contract that consumers read.
#:
#: Set **only when a column actually needs it.** Column mapping raises the table's
#: reader/writer protocol version, which older readers cannot open — a cost worth
#: paying to make a write possible and not worth paying on a table whose names are
#: already legal. Whether it was needed is visible in the write result rather than
#: silently applied.
_COLUMN_MAPPING_OPTIONS = {
    "delta.columnMapping.mode": "name",
    "delta.minReaderVersion": "2",
    "delta.minWriterVersion": "5",
}


def needs_column_mapping(columns: Iterable[object]) -> bool:
    """Does any column name carry a character Delta refuses without column mapping?

    Public because the runbook's failure mode is worth checking before a run rather
    than after eighteen minutes of compute, and because the decision belongs in one
    place: the writer applies it, a test pins it, and nothing has to re-derive the
    character set.
    """
    return any(
        any(character in _DELTA_INVALID_IN_COLUMN_NAME for character in str(column))
        for column in columns
    )


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
            writer = spark_frame.write.format("delta").mode(_SPARK_MODES[self._mode])
            if needs_column_mapping(frame.columns):
                for option, value in _COLUMN_MAPPING_OPTIONS.items():
                    writer = writer.option(option, value)
            writer.saveAsTable(table)
        except Exception as error:
            raise DatabricksError(f"could not write {table} ({error_label(error)})") from error
        return table

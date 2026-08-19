"""Spark table source: a Unity Catalog table as a ``SourceDataset``.

Implements the same :class:`~pii_reduction.sources.base.SourceAdapter` protocol as
the local CSV/parquet adapters, which is the point — ``pipeline.process`` receives a
``SourceDataset`` and never learns where the rows came from.
"""

from __future__ import annotations

import re
from typing import Any

from pii_reduction.databricks.errors import DatabricksError
from pii_reduction.observability.logging import get_logger, safe_fields
from pii_reduction.sources.base import SourceDataset

__all__ = ["SparkTableSource", "require_table_name"]

logger = get_logger("databricks")

#: Three dot-separated identifiers, each a plain name. Backtick-quoted or injected
#: SQL never gets through, because the table name is interpolated into queries.
#: ``\Z`` rather than ``$``: the dollar anchor tolerates one trailing newline.
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2}\Z")


def require_table_name(table: str) -> str:
    """A fully-qualified ``catalog.schema.table`` name, validated.

    Fully qualified deliberately: a bare table name silently lands in whatever the
    session's current catalog and schema happen to be, and "which table did the run
    actually touch" must never depend on session state (`docs/07`).
    """
    if not _TABLE_RE.match(table):
        raise DatabricksError(
            f"table name {table!r} must be fully qualified catalog.schema.table with "
            "plain identifiers. Names come from configuration or environment, never "
            "hard-coded (AGENTS.md)"
        )
    return table


class SparkTableSource:
    """Read a table through the session into the standard ``SourceDataset``.

    The frame is materialised with ``toPandas()``: the driver-side runner processes
    on the driver, and the distributed runner takes a Spark ``DataFrame`` directly
    (:func:`~pii_reduction.databricks.runner.distributed_frame`) rather than going
    through this adapter — pulling rows to the driver only to ship them back out
    would defeat it.
    """

    source_type = "spark_table"

    def __init__(self, spark: Any, table: str, *, name: str | None = None) -> None:
        self._spark = spark
        self._table = require_table_name(table)
        self._name = name or self._table

    def load(self) -> SourceDataset:
        try:
            frame = self._spark.read.table(self._table).toPandas()
        except Exception as error:
            # Connect exceptions carry the workspace URL in their message; wrap so
            # OUR message names only the table and the exception class. The original
            # stays chained, so a full traceback still shows the host — a host is
            # not a credential (it lives in the user's own profile), and suppressing
            # the cause would cost the debugging context.
            raise DatabricksError(
                f"source {self._name!r}: could not read {self._table} ({error.__class__.__name__})"
            ) from error
        return SourceDataset(
            name=self._name,
            frame=frame,
            source_type=self.source_type,
            source_reference=self._table,
            source_version=self._table_version(),
        )

    def _table_version(self) -> str | None:
        """The table's Delta version, as ``delta_v<N>``, when it has one.

        ``RunMetadata.source_version`` is optional provenance, not a gate, so this
        is best-effort by design: a non-Delta table, a permissions gap, or a
        session that cannot run the query yields ``None`` rather than failing a
        read that already succeeded. The table name was validated by
        :func:`require_table_name`, so interpolating it into SQL is safe.
        """
        try:
            rows = self._spark.sql(f"DESCRIBE HISTORY {self._table} LIMIT 1").collect()
        except Exception as error:
            # Category only (AGENTS.md rule 8): a Connect message can carry the
            # workspace URL, and this path must never fail or leak on its way to
            # returning "no version".
            logger.info(
                "table version unavailable %s",
                safe_fields(dataset=self._name, error_category=type(error).__name__),
            )
            return None
        if not rows:
            return None
        version = getattr(rows[0], "version", None)
        return None if version is None else f"delta_v{version}"

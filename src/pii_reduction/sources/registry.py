"""Source construction by type name (primitives in, adapter out)."""

from __future__ import annotations

from typing import Any

from pii_reduction.sources.base import SourceAdapter
from pii_reduction.sources.errors import SourceError
from pii_reduction.sources.local import CsvSource, ParquetSource

__all__ = ["BUILT_ELSEWHERE", "available_source_types", "build_source"]

#: Types configuration may name that this registry deliberately cannot build, and
#: where each is built instead. They need a live Spark session, and a ``sources/``
#: module that took one would put a Databricks dependency on the runtime path — the
#: inversion `docs/01_ARCHITECTURE.md` forbids and three tests pin. Naming them here
#: costs nothing (these are strings, not imports) and buys an error that says what to
#: do; a bare "not registered" would read as "unsupported", which is wrong.
#:
#: `tests/test_sources_outputs.py` asserts this mapping covers exactly
#: ``config.registries.DATABRICKS_SOURCE_TYPES``, so the two cannot drift.
BUILT_ELSEWHERE = {
    "spark_table": (
        "reads a Unity Catalog table through a Spark session, which configuration "
        "cannot supply. Run this dataset through the Databricks driver path — "
        "`pii-reduction-databricks run <dataset>`, or "
        "`pii_reduction.databricks.run_driver(spark, config)` — which builds the "
        "adapter from the table this config names (ADR-0025)"
    )
}


def available_source_types() -> frozenset[str]:
    """What *this* registry can build. Configuration may name more (see above)."""
    return frozenset({CsvSource.source_type, ParquetSource.source_type})


def build_source(
    source_type: str,
    *,
    name: str,
    path: str | None = None,
    options: dict[str, Any] | None = None,
) -> SourceAdapter:
    """Build a local source adapter.

    ``path`` is optional only so that a table-typed configuration — which carries a
    ``table`` and no ``path`` — reaches the refusal below with its real message
    instead of an ``AttributeError`` at the call site.
    """
    elsewhere = BUILT_ELSEWHERE.get(source_type)
    if elsewhere is not None:
        raise SourceError(f"source type {source_type!r} {elsewhere}")
    if source_type == CsvSource.source_type:
        return CsvSource(_require_path(source_type, path), name=name, options=options)
    if source_type == ParquetSource.source_type:
        return ParquetSource(_require_path(source_type, path), name=name, options=options)
    raise SourceError(
        f"source type {source_type!r} is not registered "
        f"(available: {', '.join(sorted(available_source_types()))})"
    )


def _require_path(source_type: str, path: str | None) -> str:
    if not path:
        raise SourceError(f"source type {source_type!r} requires a path")
    return path

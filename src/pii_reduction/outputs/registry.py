"""Destination construction by type name (primitives in, adapter out)."""

from __future__ import annotations

from pii_reduction.outputs.base import OutputAdapter
from pii_reduction.outputs.errors import OutputError
from pii_reduction.outputs.local import CsvOutput, ParquetOutput

__all__ = ["BUILT_ELSEWHERE", "available_destination_types", "build_output"]

#: The destination half of ``sources.registry.BUILT_ELSEWHERE`` — same reason, same
#: pinning test against ``config.registries.DATABRICKS_DESTINATION_TYPES``.
BUILT_ELSEWHERE = {
    "delta_table": (
        "writes Delta tables through a Spark session, which configuration cannot "
        "supply. Run this dataset through the Databricks driver path — "
        "`pii-reduction-databricks run <dataset>`, or "
        "`pii_reduction.databricks.run_driver(spark, config)` — which writes under "
        "the catalog.schema this config names (ADR-0025)"
    )
}


def available_destination_types() -> frozenset[str]:
    """What *this* registry can build. Configuration may name more (see above)."""
    return frozenset({CsvOutput.destination_type, ParquetOutput.destination_type})


def build_output(
    destination_type: str, *, path: str | None = None, mode: str = "overwrite"
) -> OutputAdapter:
    """Build a local output adapter.

    ``path`` is optional for the same reason as in ``build_source``: a table-typed
    destination carries a catalog and schema, and must reach the refusal below.
    """
    elsewhere = BUILT_ELSEWHERE.get(destination_type)
    if elsewhere is not None:
        raise OutputError(f"destination type {destination_type!r} {elsewhere}")
    if destination_type not in available_destination_types():
        raise OutputError(
            f"destination type {destination_type!r} is not registered "
            f"(available: {', '.join(sorted(available_destination_types()))})"
        )
    if not path:
        raise OutputError(f"destination type {destination_type!r} requires a path")
    if destination_type == CsvOutput.destination_type:
        return CsvOutput(path, mode=mode)
    return ParquetOutput(path, mode=mode)

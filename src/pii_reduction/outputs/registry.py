"""Destination construction by type name (primitives in, adapter out)."""

from __future__ import annotations

from pii_reduction.outputs.base import OutputAdapter
from pii_reduction.outputs.errors import OutputError
from pii_reduction.outputs.local import CsvOutput, ParquetOutput

__all__ = ["available_destination_types", "build_output"]


def available_destination_types() -> frozenset[str]:
    return frozenset({CsvOutput.destination_type, ParquetOutput.destination_type})


def build_output(destination_type: str, *, path: str, mode: str = "overwrite") -> OutputAdapter:
    if destination_type == CsvOutput.destination_type:
        return CsvOutput(path, mode=mode)
    if destination_type == ParquetOutput.destination_type:
        return ParquetOutput(path, mode=mode)
    raise OutputError(
        f"destination type {destination_type!r} is not registered "
        f"(available: {', '.join(sorted(available_destination_types()))})"
    )

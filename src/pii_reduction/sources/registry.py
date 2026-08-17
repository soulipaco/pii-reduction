"""Source construction by type name (primitives in, adapter out)."""

from __future__ import annotations

from typing import Any

from pii_reduction.sources.base import SourceAdapter
from pii_reduction.sources.errors import SourceError
from pii_reduction.sources.local import CsvSource, ParquetSource

__all__ = ["available_source_types", "build_source"]


def available_source_types() -> frozenset[str]:
    return frozenset({CsvSource.source_type, ParquetSource.source_type})


def build_source(
    source_type: str,
    *,
    name: str,
    path: str,
    options: dict[str, Any] | None = None,
) -> SourceAdapter:
    if source_type == CsvSource.source_type:
        return CsvSource(path, name=name, options=options)
    if source_type == ParquetSource.source_type:
        return ParquetSource(path, name=name, options=options)
    raise SourceError(
        f"source type {source_type!r} is not registered "
        f"(available: {', '.join(sorted(available_source_types()))})"
    )

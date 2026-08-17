"""Source adapters: rows in, lineage attached, no text inspection."""

from pii_reduction.sources.base import SourceAdapter, SourceDataset
from pii_reduction.sources.errors import SourceError
from pii_reduction.sources.local import CsvSource, PandasSource, ParquetSource
from pii_reduction.sources.registry import available_source_types, build_source

__all__ = [
    "CsvSource",
    "PandasSource",
    "ParquetSource",
    "SourceAdapter",
    "SourceDataset",
    "SourceError",
    "available_source_types",
    "build_source",
]

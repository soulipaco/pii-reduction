"""Output adapters: row grain preserved, reduced columns appended."""

from pii_reduction.outputs.base import OutputAdapter
from pii_reduction.outputs.errors import OutputError
from pii_reduction.outputs.local import CsvOutput, PandasOutput, ParquetOutput, write_json
from pii_reduction.outputs.registry import available_destination_types, build_output

__all__ = [
    "CsvOutput",
    "OutputAdapter",
    "OutputError",
    "PandasOutput",
    "ParquetOutput",
    "available_destination_types",
    "build_output",
    "write_json",
]

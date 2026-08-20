"""Source and output adapters, plus language resolution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.config.registries import (
    DATABRICKS_DESTINATION_TYPES,
    DATABRICKS_SOURCE_TYPES,
    KNOWN_DESTINATION_TYPES,
    KNOWN_SOURCE_TYPES,
)
from pii_reduction.contracts.language import UNKNOWN_LANGUAGE
from pii_reduction.language import (
    ColumnLanguageResolver,
    LanguageError,
    StaticLanguageResolver,
)
from pii_reduction.outputs import (
    CsvOutput,
    OutputError,
    PandasOutput,
    ParquetOutput,
    available_destination_types,
    build_output,
    write_json,
)
from pii_reduction.outputs.registry import BUILT_ELSEWHERE as DESTINATIONS_BUILT_ELSEWHERE
from pii_reduction.sources import (
    CsvSource,
    PandasSource,
    ParquetSource,
    SourceError,
    available_source_types,
    build_source,
)
from pii_reduction.sources.registry import BUILT_ELSEWHERE as SOURCES_BUILT_ELSEWHERE
from tests.pipeline_fixtures import build_frame, write_dataset_csv

pytestmark = pytest.mark.unit


class TestRegistries:
    """Configuration may name more types than these registries can build (ADR-0025).

    The gap is exactly the Databricks adapters: they need a live Spark session, and a
    `sources/`/`outputs/` module that took one would put a Databricks dependency on
    the runtime path. These tests pin the gap to that exact set, so a type can never
    go quietly missing from a registry and be explained away as "Databricks".
    """

    def test_the_local_source_registry_covers_every_non_databricks_type(self) -> None:
        assert available_source_types() == KNOWN_SOURCE_TYPES - DATABRICKS_SOURCE_TYPES

    def test_the_local_destination_registry_covers_every_non_databricks_type(self) -> None:
        assert (
            available_destination_types() == KNOWN_DESTINATION_TYPES - DATABRICKS_DESTINATION_TYPES
        )

    def test_the_source_guidance_map_covers_exactly_the_databricks_types(self) -> None:
        assert set(SOURCES_BUILT_ELSEWHERE) == DATABRICKS_SOURCE_TYPES

    def test_the_destination_guidance_map_covers_exactly_the_databricks_types(self) -> None:
        assert set(DESTINATIONS_BUILT_ELSEWHERE) == DATABRICKS_DESTINATION_TYPES

    def test_unknown_source_type_is_actionable(self) -> None:
        with pytest.raises(SourceError) as exc_info:
            build_source("excel", name="demo", path="x.xlsx")
        assert "not registered" in str(exc_info.value)

    def test_unknown_destination_type_is_actionable(self) -> None:
        with pytest.raises(OutputError) as exc_info:
            build_output("excel", path="x")
        assert "not registered" in str(exc_info.value)

    def test_a_databricks_source_says_where_it_is_built_instead(self) -> None:
        # "not registered" would read as "unsupported", which is wrong and would send
        # someone to implement an adapter that already exists.
        with pytest.raises(SourceError) as exc_info:
            build_source("spark_table", name="demo")
        message = str(exc_info.value)
        assert "not registered" not in message
        assert "run_driver" in message and "spark_table" in message

    def test_a_databricks_destination_says_where_it_is_built_instead(self) -> None:
        with pytest.raises(OutputError) as exc_info:
            build_output("delta_table")
        message = str(exc_info.value)
        assert "not registered" not in message
        assert "run_driver" in message and "delta_table" in message

    def test_a_path_source_still_requires_its_path(self) -> None:
        with pytest.raises(SourceError, match="requires a path"):
            build_source("csv", name="demo")


class TestSources:
    def test_pandas_source_copies_the_frame(self) -> None:
        frame = build_frame()
        loaded = PandasSource(frame, name="demo").load()
        loaded.frame.loc[0, "body"] = "mutated"
        assert frame.loc[0, "body"] != "mutated"

    def test_pandas_source_reports_lineage(self) -> None:
        loaded = PandasSource(build_frame(), name="demo", version="v1").load()
        assert (loaded.name, loaded.source_type, loaded.source_version) == (
            "demo",
            "pandas",
            "v1",
        )
        assert loaded.row_count == 20

    def test_csv_source_reads_utf8_including_greek(self, tmp_path: Path) -> None:
        path = write_dataset_csv(tmp_path / "demo.csv")
        loaded = CsvSource(path, name="demo").load()
        assert loaded.row_count == 20
        assert any("Το email" in str(value) for value in loaded.frame["body"])

    def test_csv_source_missing_file_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(SourceError) as exc_info:
            CsvSource(tmp_path / "nope.csv", name="demo").load()
        assert "nope.csv" in str(exc_info.value)

    def test_csv_source_rejects_unknown_options(self) -> None:
        with pytest.raises(SourceError) as exc_info:
            CsvSource("x.csv", name="demo", options={"separator": ";"})
        assert "separator" in str(exc_info.value)

    def test_csv_source_honours_the_delimiter(self, tmp_path: Path) -> None:
        path = tmp_path / "semi.csv"
        path.write_text("row_id;body\n1;hello\n", encoding="utf-8")
        loaded = CsvSource(path, name="demo", options={"delimiter": ";"}).load()
        assert list(loaded.frame.columns) == ["row_id", "body"]

    def test_parquet_round_trip(self, tmp_path: Path) -> None:
        target = ParquetOutput(tmp_path).write(build_frame(), name="demo")
        loaded = ParquetSource(target, name="demo").load()
        assert loaded.row_count == 20


class TestOutputs:
    def test_pandas_output_keeps_a_copy(self) -> None:
        adapter = PandasOutput()
        adapter.write(build_frame(), name="demo")
        assert len(adapter.frames["demo"]) == 20

    def test_csv_output_writes_into_a_directory(self, tmp_path: Path) -> None:
        target = Path(CsvOutput(tmp_path / "out").write(build_frame(), name="demo"))
        assert target.name == "demo.csv"
        assert len(pd.read_csv(target)) == 20

    def test_csv_output_accepts_an_explicit_file_path(self, tmp_path: Path) -> None:
        target = Path(CsvOutput(tmp_path / "out" / "custom.csv").write(build_frame(), name="demo"))
        assert target.name == "custom.csv"

    def test_error_mode_refuses_to_overwrite(self, tmp_path: Path) -> None:
        adapter = CsvOutput(tmp_path / "out", mode="error")
        adapter.write(build_frame(), name="demo")
        with pytest.raises(OutputError) as exc_info:
            adapter.write(build_frame(), name="demo")
        assert "already exists" in str(exc_info.value)

    def test_overwrite_mode_replaces(self, tmp_path: Path) -> None:
        adapter = CsvOutput(tmp_path / "out")
        adapter.write(build_frame(), name="demo")
        adapter.write(build_frame().head(3), name="demo")
        assert len(pd.read_csv(tmp_path / "out" / "demo.csv")) == 3

    def test_unknown_mode_is_actionable(self, tmp_path: Path) -> None:
        with pytest.raises(OutputError):
            CsvOutput(tmp_path, mode="append")

    def test_write_json_is_utf8_and_stable(self, tmp_path: Path) -> None:
        target = Path(write_json(tmp_path / "metrics.json", {"b": 1, "a": "Ελλάδα"}))
        content = target.read_text(encoding="utf-8")
        assert content.index('"a"') < content.index('"b"')
        assert "Ελλάδα" in content


class TestLanguageResolution:
    def test_static_resolver_reports_the_configured_language(self) -> None:
        resolver = StaticLanguageResolver("de", supported=("en", "de", "el"))
        result = resolver.resolve("beliebiger Text")
        assert (result.language, result.supported, result.detector) == ("de", True, "static")

    def test_static_resolver_flags_an_unsupported_language(self) -> None:
        resolver = StaticLanguageResolver("fr", supported=("en", "de", "el"))
        result = resolver.resolve("texte")
        assert result.supported is False
        assert result.fallback_used is True
        assert result.reason == "unsupported_language"

    def test_column_resolver_reads_the_row(self) -> None:
        resolver = ColumnLanguageResolver("language", supported=("en", "de", "el"))
        assert resolver.resolve("text", row={"language": "EL"}).language == "el"

    def test_column_resolver_treats_a_missing_value_as_unknown(self) -> None:
        resolver = ColumnLanguageResolver("language", supported=("en",))
        result = resolver.resolve("text", row={"language": None})
        assert result.language == UNKNOWN_LANGUAGE
        assert result.fallback_used is True
        assert result.supported is False

    def test_column_resolver_requires_the_column(self) -> None:
        resolver = ColumnLanguageResolver("language", supported=("en",))
        with pytest.raises(LanguageError) as exc_info:
            resolver.resolve("text", row={"other": "en"})
        assert "language" in str(exc_info.value)

    def test_static_resolver_requires_a_language(self) -> None:
        with pytest.raises(LanguageError):
            StaticLanguageResolver("", supported=("en",))

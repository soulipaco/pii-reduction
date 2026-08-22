"""`SourceAdapter.schema()`: the columns, without reading the rows.

Pickup item 5 — "a schema-only path would let a column picker read the source's
columns without reading the source", and the plan is explicit that it is an engine
change, deliberately not improvised in the service.

**The property under test is the negative one.** Any adapter can return column names
by loading everything and looking at the frame; the value is entirely in not doing
that. On a Unity Catalog table the difference is a metastore lookup against a full
scan pulled to the driver, which is the difference between a picker somebody uses and
one nobody does. So the tests below do not merely check the names — they check that
the data was never touched, through readers that fail if it is.

Default tier: a header line, a parquet footer and a fake Spark session need no models.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from pii_reduction.cli import main
from pii_reduction.databricks.source import SparkTableSource
from pii_reduction.sources.base import SourceAdapter, SourceSchema
from pii_reduction.sources.errors import SourceError
from pii_reduction.sources.local import CsvSource, PandasSource, ParquetSource

pytestmark = pytest.mark.unit

COLUMNS = ("document_id", "text", "language", "machine_name")


def _write_csv(path: Path, rows: int = 3) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for index in range(rows):
            writer.writerow([f"d{index}", "Grace Okafor called", "en", f"DEMO-PC-69{index}0"])
    return path


class TestEveryAdapterAnswers:
    def test_pandas(self) -> None:
        frame = pd.DataFrame({column: ["x"] for column in COLUMNS})
        schema = PandasSource(frame, name="mem").schema()
        assert schema.columns == COLUMNS
        assert schema.source_type == "pandas"

    def test_csv(self, tmp_path: Path) -> None:
        schema = CsvSource(_write_csv(tmp_path / "rows.csv"), name="csv").schema()
        assert schema.columns == COLUMNS
        assert schema.source_reference.endswith("rows.csv")

    def test_parquet(self, tmp_path: Path) -> None:
        path = tmp_path / "rows.parquet"
        pd.DataFrame({column: ["x"] for column in COLUMNS}).to_parquet(path)
        assert ParquetSource(path, name="pq").schema().columns == COLUMNS

    def test_parquet_directory(self, tmp_path: Path) -> None:
        """`load()` accepts a partitioned directory, so `schema()` must too.

        Found by the privacy audit: the first version used `parquet.read_schema`,
        which takes a file. A pre-flight check that refuses a source the run reads
        happily is worse than no check — it reports a broken dataset that works.
        """
        root = tmp_path / "partitioned"
        root.mkdir()
        frame = pd.DataFrame({column: ["x", "y"] for column in COLUMNS})
        frame.iloc[:1].to_parquet(root / "part-0.parquet")
        frame.iloc[1:].to_parquet(root / "part-1.parquet")

        source = ParquetSource(root, name="pq")
        assert source.schema().columns == COLUMNS
        assert tuple(source.load().frame.columns) == COLUMNS

    def test_spark_table(self) -> None:
        assert _FakeSpark().source().schema().columns == COLUMNS

    def test_the_protocol_requires_it(self) -> None:
        # A new adapter that forgets `schema` stops satisfying `SourceAdapter`, which
        # is what keeps the contract from being optional in practice.
        assert isinstance(PandasSource(pd.DataFrame({"a": []}), name="m"), SourceAdapter)

        class Halfway:
            source_type = "halfway"

            def load(self) -> None: ...

        assert not isinstance(Halfway(), SourceAdapter)


class TestItDoesNotReadTheData:
    """The whole point, asserted rather than documented."""

    def test_csv_reads_the_header_and_stops(self, tmp_path: Path) -> None:
        # A file whose *second* line cannot be parsed as the header promises. `load`
        # is not asked for it; `schema` must not care.
        path = tmp_path / "rows.csv"
        path.write_text(
            'document_id,text\nd0,unclosed "quote and, commas everywhere\n', encoding="utf-8"
        )
        assert CsvSource(path, name="csv").schema().columns == ("document_id", "text")

    def test_csv_ignores_a_configured_row_limit(self, tmp_path: Path) -> None:
        # A source narrowed to a sample still *has* every column; answering from the
        # slice would make the schema depend on a performance setting.
        path = _write_csv(tmp_path / "rows.csv")
        assert CsvSource(path, name="csv", options={"nrows": 1}).schema().columns == COLUMNS

    def test_parquet_never_opens_a_row_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Swap the footer read for a full read and this test fails.

        The column assertions alone would not — `pd.read_parquet(path).columns` returns
        the same tuple — which is what the architecture review pointed out about the
        docstring claiming every adapter was pinned this way.
        """
        import pyarrow.parquet as parquet

        path = tmp_path / "rows.parquet"
        pd.DataFrame({column: ["x", "y"] for column in COLUMNS}).to_parquet(path)

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("schema() read parquet data")

        monkeypatch.setattr(parquet, "read_table", refuse)
        monkeypatch.setattr(parquet.ParquetFile, "read_row_group", refuse)
        monkeypatch.setattr(pd, "read_parquet", refuse)

        assert ParquetSource(path, name="pq").schema().columns == COLUMNS

    def test_spark_never_executes_an_action(self) -> None:
        """`load()` calls `toPandas()`, which pulls the whole table to the driver.

        A schema call that did the same would make a column picker cost a full scan of
        a production table — not a performance note, a reason nobody would use it.
        """
        spark = _FakeSpark()
        spark.source().schema()
        assert spark.actions == [], f"schema() executed {spark.actions}"
        assert spark.reader.table_calls == ["cat.sch.tickets"]

    def test_spark_load_still_does_read(self) -> None:
        # The contrast, so the test above is measuring something.
        spark = _FakeSpark()
        spark.source().load()
        assert spark.actions == ["toPandas"]


class TestItAnswersUsefully:
    def test_missing_reports_what_a_config_asked_for_and_the_source_lacks(self) -> None:
        schema = SourceSchema(
            name="d", source_type="csv", source_reference="x.csv", columns=("a", "b")
        )
        assert schema.missing(["b", "c", "a"]) == ("c",)
        assert schema.missing([]) == ()
        assert schema.has("a") and not schema.has("z")

    def test_a_missing_file_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(SourceError, match="file not found"):
            CsvSource(tmp_path / "absent.csv", name="csv").schema()


#: Every CLI test passes `--configs` rather than relying on the process working
#: directory, which `tests/test_cli_run.py` already does and this file at first did
#: not — from another cwd the command failed and one of these tests *passed anyway*.
CONFIGS = str(Path(__file__).resolve().parents[1] / "configs")


def _configs_with(
    tmp_path: Path,
    *,
    row_id: str = "document_id",
    columns: tuple[str, ...] = ("text",),
    output_column: str | None = None,
) -> Path:
    """A configuration tree over a CSV whose columns this file controls.

    One builder for every precondition `describe` checks, so a fourth check is a
    keyword rather than a fourth near-identical fixture.
    """
    import shutil

    configs = tmp_path / "configs"
    shutil.copytree(Path(CONFIGS), configs)
    source = _write_csv(tmp_path / "rows.csv")

    block = [
        "dataset:",
        "  name: gap",
        f"  row_id: {row_id}",
        "source:",
        "  type: csv",
        f"  path: {source.as_posix()}",
        "destination:",
        "  type: csv",
        f"  path: {(tmp_path / 'out.csv').as_posix()}",
        "columns:",
    ]
    for column in columns:
        block += [f"  {column}:", "    parser: plain_text", "    entities: [EMAIL, PHONE]"]
        if output_column is not None:
            block.append(f"    output_column: {output_column}")
    block.append("")
    (configs / "datasets" / "gap.yaml").write_text(chr(10).join(block), encoding="utf-8")
    return configs


def _configs_naming_a_column_the_source_lacks(tmp_path: Path) -> Path:
    return _configs_with(tmp_path, columns=("text", "absent_column"))


class TestTheCliFrontDoor:
    def test_it_lists_the_columns_and_marks_the_configured_ones(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["describe", "benchmark_plain", "--configs", CONFIGS]) == 0
        out = capsys.readouterr().out
        assert "source=csv" in out
        assert "text · processed" in out
        assert "document_id · row_id" in out

    def test_it_prints_the_column_names_and_nothing_else(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A **positive** assertion about the output's shape, not a denylist.

        The first version checked that four substrings from the corpus were absent, and
        it did not assert the exit code — so any failure path produced empty output and
        the test passed while proving nothing. Demonstrated by the privacy audit, from
        a different working directory. Asserting the exact line set cannot pass
        vacuously, and it catches a leak this denylist would have missed: a sample of
        the short categorical columns, or a dtype summary.
        """
        assert main(["describe", "benchmark_plain", "--configs", CONFIGS]) == 0
        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert lines, "describe printed nothing; the assertions below would be vacuous"

        header, *rows = lines
        assert header.startswith("dataset=") and " source=csv " in f" {header} "
        corpus = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "corpus"
        columns = CsvSource(corpus / "corpus.csv", name="corpus").schema().columns
        # One line per column, each beginning with that column's name and carrying
        # only marks this file computed from the configuration.
        assert len(rows) == len(columns)
        for line, column in zip(rows, columns, strict=True):
            body = line.strip()
            assert body.split(" · ")[0] == column
            for mark in body.split(" · ")[1:]:
                assert mark in {"processed", "row_id"}, mark
        assert captured.err == ""

    def test_a_missing_configured_column_fails_before_the_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The reason the command exists: today this is a failure met after the load."""
        configs = _configs_naming_a_column_the_source_lacks(tmp_path)
        assert main(["describe", "gap", "--configs", str(configs)]) == 1
        assert "not present in the source" in capsys.readouterr().err

    def test_a_missing_row_id_column_fails_before_the_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The gap the architecture review found.

        `Pipeline._validate_source` raises on a missing row id *after the load*, and
        three documents claimed this command moved that earlier. It checked only the
        processed columns, so a typo in `row_id` got exit 0 here and died after the
        table was read.
        """
        configs = _configs_with(tmp_path, row_id="ticekt_id")
        assert main(["describe", "gap", "--configs", str(configs)]) == 1
        assert "row id column 'ticekt_id' is not present" in capsys.readouterr().err

    def test_an_output_column_that_already_exists_fails_before_the_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The third precondition `_validate_source` enforces, and answerable without
        # reading a row like the other two.
        configs = _configs_with(tmp_path, output_column="language")
        assert main(["describe", "gap", "--configs", str(configs)]) == 1
        assert "output column(s) already exist" in capsys.readouterr().err

    def test_a_databricks_source_is_refused_with_the_front_door_that_can_answer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["describe", "databricks_table_example", "--configs", CONFIGS]) == 2
        message = capsys.readouterr().err
        # It must not name a subcommand that does not exist: `pii-reduction-databricks`
        # registers `run` and nothing else, and the first version of this test pinned
        # the inaccuracy by asserting only the console-script name.
        assert "No command describes one yet" in message
        assert "pii-reduction-databricks run" in message


class _FakeReader:
    def __init__(self, owner: _FakeSpark) -> None:
        self._owner = owner
        self.table_calls: list[str] = []

    def table(self, name: str) -> _FakeFrame:
        self.table_calls.append(name)
        return _FakeFrame(self._owner)


class _FakeFrame:
    def __init__(self, owner: _FakeSpark) -> None:
        self._owner = owner

    @property
    def schema(self) -> _FakeSchema:
        return _FakeSchema()

    def toPandas(self) -> pd.DataFrame:  # noqa: N802 - Spark's own spelling
        self._owner.actions.append("toPandas")
        return pd.DataFrame({column: [] for column in COLUMNS})

    def __getattr__(self, name: str) -> Any:
        # Any other attribute access is an action this test wants to hear about,
        # rather than a silent success that proves nothing.
        raise AssertionError(f"schema() reached for {name!r} on the frame")


class _FakeSchema:
    def fieldNames(self) -> list[str]:  # noqa: N802 - Spark's own spelling
        return list(COLUMNS)


class _FakeSpark:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.reader = _FakeReader(self)

    @property
    def read(self) -> _FakeReader:
        return self.reader

    def source(self) -> SparkTableSource:
        return SparkTableSource(self, "cat.sch.tickets")

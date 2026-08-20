"""The Databricks surface, tested without a workspace and without pyspark.

`AGENTS.md`'s "one implementation, two runtimes" is only checkable if the Databricks
path's logic is testable off-Databricks. The partition function is deliberately plain
``Iterator[pd.DataFrame] -> Iterator[pd.DataFrame]``, so its batching and
worker-level-init semantics — the anti-pattern `docs/07` exists to prevent is
per-row model construction — get real assertions here in the default tier.

Everything needing a session or credentials lives in ``test_databricks_parity.py``
under the ``databricks`` marker, which never runs in CI (ADR-0009).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.config.loader import load_resolved_dataset
from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.databricks import (
    DatabricksError,
    DeltaTableOutput,
    SparkTableSource,
    distributed_frame,
    partition_processor,
)
from pii_reduction.databricks.source import require_table_name
from pii_reduction.outputs.base import OutputAdapter
from pii_reduction.processing.pipeline import RUN_ID_COLUMN, STATUS_COLUMN
from pii_reduction.sources.base import SourceAdapter
from pii_reduction.synthetic.corpus import load_corpus

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def resolved_config() -> ResolvedDataset:
    return load_resolved_dataset(REPO_ROOT / "configs", "benchmark_plain")


class TestProtocolConformance:
    """The Spark adapters satisfy `sources/` and `outputs/` without declaring it.

    Neither declares conformance — these are `Protocol`s, not base classes, so
    nothing type-checks the adapters against them. (The reason is *not* that an
    import would be illegal: `databricks/ -> sources/` is the permitted inward
    direction and `source.py` already imports `SourceDataset` from the very module
    that defines `SourceAdapter`. What keeps Spark off the runtime path is where
    these adapters *live*, not what they import — `docs/01_ARCHITECTURE.md`.)

    Structural conformance is exactly what drifts silently when a protocol gains a
    member, so without these two assertions the only thing holding the claim up is
    the prose that makes it. Their reach stops there: `isinstance` on a
    `runtime_checkable` Protocol checks that members are *present*, never that their
    signatures match, and since neither adapter declares conformance no type checker
    covers that gap either.
    """

    def test_spark_table_source_is_a_source_adapter(self) -> None:
        assert isinstance(SparkTableSource(None, "cat.sch.tbl"), SourceAdapter)

    def test_delta_table_output_is_an_output_adapter(self) -> None:
        assert isinstance(DeltaTableOutput(None, "cat.sch"), OutputAdapter)


class TestTableNames:
    """Names come from config/env and are interpolated into SQL — validated hard."""

    def test_fully_qualified_names_pass(self) -> None:
        assert require_table_name("workspace.demo.table_1") == "workspace.demo.table_1"

    @pytest.mark.parametrize(
        "bad",
        [
            "table",  # bare: would land in whatever the session's schema is
            "schema.table",  # two parts: same problem one level up
            "c.s.t; DROP TABLE x",  # injection-shaped
            "c.s.`t`",  # quoting tricks
            "c..t",
            "",
        ],
    )
    def test_everything_else_is_refused(self, bad: str) -> None:
        with pytest.raises(DatabricksError, match="fully qualified"):
            require_table_name(bad)

    def test_the_output_prefix_is_two_parts(self) -> None:
        with pytest.raises(DatabricksError, match=r"catalog\.schema"):
            DeltaTableOutput(object(), "workspace.demo.table")

    def test_unknown_write_mode_is_refused(self) -> None:
        # The default refuses to touch an existing table; overwrite is opt-in.
        with pytest.raises(DatabricksError, match="unknown write mode"):
            DeltaTableOutput(object(), "workspace.demo", mode="replaceWhere")


class TestPartitionProcessor:
    """The mapInPandas inner function, driven by plain iterators."""

    def payload(self) -> dict[str, object]:
        return resolved_config().model_dump(mode="json")

    def corpus_batches(self, sizes: tuple[int, ...]) -> list[pd.DataFrame]:
        corpus = load_corpus(REPO_ROOT / "tests" / "fixtures" / "corpus")
        frame = corpus.to_frame()
        frame = frame[frame["document_type"] == "plain"].reset_index(drop=True)
        batches: list[pd.DataFrame] = []
        cursor = 0
        for size in sizes:
            batches.append(frame.iloc[cursor : cursor + size].copy())
            cursor += size
        return batches

    def test_batches_come_back_reduced_with_the_pipeline_columns(self) -> None:
        cache: dict[str, object] = {}
        process = partition_processor(self.payload(), "run_a", pipeline_cache=cache)  # type: ignore[arg-type]
        batches = self.corpus_batches((5, 7))
        results = list(process(iter(batches)))
        assert len(results) == 2
        for source, result in zip(batches, results, strict=True):
            assert len(result) == len(source), "row grain must be preserved"
            assert "text_pii_redacted" in result.columns
            assert STATUS_COLUMN in result.columns
            assert RUN_ID_COLUMN in result.columns
            # Non-destructive: the source column survives unchanged (AGENTS.md rule 4).
            assert result["text"].tolist() == source["text"].tolist()

    def test_the_pipeline_is_built_once_per_worker_not_per_batch(self) -> None:
        """The anti-pattern docs/07 names, asserted rather than hoped.

        One cache entry after many batches means one pipeline construction — on a
        real worker that is one model load for the whole worker lifetime, never one
        per row or per batch.
        """
        cache: dict[str, object] = {}
        process = partition_processor(self.payload(), "run_a", pipeline_cache=cache)  # type: ignore[arg-type]
        list(process(iter(self.corpus_batches((3, 3, 3, 3)))))
        assert len(cache) == 1

        # A second partition on the same worker reuses the same pipeline object.
        pipeline_before = next(iter(cache.values()))
        list(process(iter(self.corpus_batches((4,)))))
        assert next(iter(cache.values())) is pipeline_before

    def test_the_reduction_matches_the_local_pipeline_exactly(self) -> None:
        """Parity at the function level: partition output == local pipeline output.

        The workspace parity test asserts this same equality end-to-end through
        Delta; this one asserts it with no I/O in the way, so a divergence is
        attributable to adapters rather than to the function.
        """
        from pii_reduction.processing.pipeline import build_pipeline
        from pii_reduction.sources.local import PandasSource

        batches = self.corpus_batches((12,))
        cache: dict[str, object] = {}
        process = partition_processor(self.payload(), "run_a", pipeline_cache=cache)  # type: ignore[arg-type]
        distributed = pd.concat(process(iter(batches)), ignore_index=True)

        local_pipeline = build_pipeline(resolved_config())
        local = local_pipeline.process(PandasSource(batches[0], name="parity").load()).frame

        assert distributed["text_pii_redacted"].tolist() == local["text_pii_redacted"].tolist()


class TestRunIdentity:
    """One logical distributed run must stamp ONE run id (docs/01 idempotency)."""

    def test_the_driver_generated_run_id_reaches_every_row(self) -> None:
        cache: dict[str, object] = {}
        config = resolved_config()
        process = partition_processor(
            config.model_dump(mode="json"),
            "run_fixed",
            pipeline_cache=cache,  # type: ignore[arg-type]
        )
        corpus = load_corpus(REPO_ROOT / "tests" / "fixtures" / "corpus")
        frame = corpus.to_frame()
        frame = frame[frame["document_type"] == "plain"].head(6).reset_index(drop=True)
        results = pd.concat(process(iter([frame.iloc[:3], frame.iloc[3:]])), ignore_index=True)
        assert set(results[RUN_ID_COLUMN]) == {"run_fixed"}

    def test_a_new_run_does_not_reuse_a_warm_workers_old_identity(self) -> None:
        # The warm-worker failure: a cached pipeline keyed on config alone would
        # stamp the previous job's id onto a new one.
        cache: dict[str, object] = {}
        payload = resolved_config().model_dump(mode="json")
        corpus = load_corpus(REPO_ROOT / "tests" / "fixtures" / "corpus")
        frame = corpus.to_frame()
        batch = frame[frame["document_type"] == "plain"].head(3).reset_index(drop=True)

        run_one = partition_processor(payload, "run_one", pipeline_cache=cache)  # type: ignore[arg-type]
        run_two = partition_processor(payload, "run_two", pipeline_cache=cache)  # type: ignore[arg-type]
        first: pd.DataFrame = pd.concat(run_one(iter([batch])))
        second: pd.DataFrame = pd.concat(run_two(iter([batch])))
        assert set(first[RUN_ID_COLUMN]) == {"run_one"}
        assert set(second[RUN_ID_COLUMN]) == {"run_two"}
        assert len(cache) == 2, "each run builds its own pipeline; within a run it is cached"


class FakeField:
    def __init__(self, name: str) -> None:
        self.name = name
        self.dataType = self

    def simpleString(self) -> str:  # noqa: N802 - mirrors the pyspark method name
        return "string"


class FakeSparkFrame:
    """Just enough of a Spark DataFrame for `distributed_frame`: schema + capture."""

    def __init__(self, columns: list[str]) -> None:
        self.schema = [FakeField(name) for name in columns]
        self.captured_schema: str | None = None

    def mapInPandas(self, func, schema):  # type: ignore[no-untyped-def]  # noqa: N802
        self.captured_schema = schema
        return self


class TestDeclaredSchemaCannotDrift:
    def test_the_declared_columns_are_what_process_actually_appends(self) -> None:
        """The mirror `distributed_frame` maintains, asserted in the default tier.

        `mapInPandas` matches string labels by NAME, so a wrong declaration works
        today — and would swap two string columns silently under positional
        matching. This test pins name AND order against the real pipeline output,
        which is the drift the docstring promises cannot happen.
        """
        from pii_reduction.processing.pipeline import build_pipeline
        from pii_reduction.sources.local import PandasSource

        config = resolved_config()
        corpus = load_corpus(REPO_ROOT / "tests" / "fixtures" / "corpus")
        frame = corpus.to_frame()
        batch = frame[frame["document_type"] == "plain"].head(2).reset_index(drop=True)

        fake = FakeSparkFrame(list(batch.columns))
        run = distributed_frame(fake, config, run_id="run_schema")
        assert run.run_id == "run_schema"
        declared = [part.split("`")[1] for part in (fake.captured_schema or "").split(", ")]

        processed = build_pipeline(config).process(PandasSource(batch, name="x").load()).frame
        assert declared == list(processed.columns), (
            "distributed_frame's declared schema no longer mirrors what "
            "Pipeline.process appends — fix the mirror, not this test"
        )


class TestSourceWithoutASession:
    def test_a_bad_table_name_fails_before_any_connection(self) -> None:
        with pytest.raises(DatabricksError, match="fully qualified"):
            SparkTableSource(object(), "just_a_table")


class _HistoryRow:
    def __init__(self, version: object) -> None:
        self.version = version


class _FakeQuery:
    def __init__(self, rows: list[object] | None, error: Exception | None = None) -> None:
        self._rows = rows or []
        self._error = error

    def collect(self) -> list[object]:
        if self._error is not None:
            raise self._error
        return self._rows


class _FakeRead:
    """`spark.read.table(name).toPandas()` — the read half of the source."""

    def table(self, _name: str) -> _FakeRead:
        return self

    def toPandas(self) -> pd.DataFrame:  # noqa: N802 - Spark's casing
        # Shaped like the benchmark_plain contract so `run_driver` fakes can
        # process it; the source-version tests only count rows. Synthetic values,
        # RFC 2606 domain (ADR-0003).
        return pd.DataFrame(
            {
                "document_id": ["doc_0001"],
                "language": ["en"],
                "text": ["Contact maria.rossi@example.com about the ticket."],
            }
        )


class _FakeSpark:
    def __init__(self, history: _FakeQuery) -> None:
        self.read = _FakeRead()
        self._history = history
        self.queries: list[str] = []

    def sql(self, query: str) -> _FakeQuery:
        self.queries.append(query)
        return self._history


class _FakeWriter:
    """`createDataFrame(f).write.format("delta").mode(m).saveAsTable(t)` — capture."""

    def __init__(
        self,
        sink: dict[str, pd.DataFrame],
        frame: pd.DataFrame,
        modes: dict[str, str] | None = None,
    ) -> None:
        self._sink = sink
        self._frame = frame
        self._modes = modes
        self._mode = ""

    def format(self, _fmt: str) -> _FakeWriter:
        return self

    def mode(self, mode: str) -> _FakeWriter:
        self._mode = mode
        return self

    def saveAsTable(self, table: str) -> None:  # noqa: N802 - Spark's casing
        self._sink[table] = self._frame
        if self._modes is not None:
            self._modes[table] = self._mode


class _FakeSessionFrame:
    def __init__(
        self,
        sink: dict[str, pd.DataFrame],
        frame: pd.DataFrame,
        modes: dict[str, str] | None = None,
    ) -> None:
        self.write = _FakeWriter(sink, frame, modes)


class _FakeWritableSpark(_FakeSpark):
    """A fake session that can also write, for driving `run_driver` end to end."""

    def __init__(self, history: _FakeQuery) -> None:
        super().__init__(history)
        self.tables: dict[str, pd.DataFrame] = {}

    def createDataFrame(self, frame: pd.DataFrame) -> _FakeSessionFrame:  # noqa: N802
        return _FakeSessionFrame(self.tables, frame)


class TestRunDriverProjection:
    """ADR-0024: `reduced_only_prefix` writes the projection to its own prefix.

    Fake-session unit tests, like the runner's init-once semantics; the parity
    test asserts the projection against the real workspace on its next run.
    """

    def _run(self, reduced_only_prefix: str | None):  # type: ignore[no-untyped-def]
        from pii_reduction.databricks.runner import run_driver

        spark = _FakeWritableSpark(_FakeQuery([_HistoryRow(3)]))
        result = run_driver(
            spark,
            resolved_config(),
            source_table="cat.raw.src",
            destination_prefix="cat.operator",
            reduced_only_prefix=reduced_only_prefix,
        )
        return spark, result

    def test_without_the_prefix_no_projection_table_is_written(self) -> None:
        spark, result = self._run(None)
        assert result.reduced_only_table is None
        assert not any(name.endswith("_reduced_only") for name in spark.tables)

    def test_the_projection_lands_at_its_own_prefix_without_the_raw_column(self) -> None:
        spark, result = self._run("cat.consumers")
        assert result.reduced_only_table is not None
        assert result.reduced_only_table.startswith("cat.consumers.")

        projected = spark.tables[result.reduced_only_table]
        full = spark.tables[result.reduced_table]
        configured = [policy.column for policy in resolved_config().columns]
        assert configured, "fixture must configure at least one column"
        for column in configured:
            assert column in full.columns
            assert column not in projected.columns
        assert len(projected) == len(full)


class TestSourceVersionCapture:
    """`source_version` provenance (docs/17 D2): best-effort, never load-breaking.

    Unit-tested against a fake session like the runner's init-once semantics; the
    databricks-marked parity test exercises it against a real Delta table the next
    time it runs against the workspace.
    """

    def test_a_delta_table_version_is_recorded(self) -> None:
        spark = _FakeSpark(_FakeQuery([_HistoryRow(12)]))
        dataset = SparkTableSource(spark, "cat.sch.tbl").load()
        assert dataset.source_version == "delta_v12"
        assert any("DESCRIBE HISTORY cat.sch.tbl" in query for query in spark.queries)

    def test_a_failing_history_query_does_not_fail_the_read(self) -> None:
        # A non-Delta table or a permissions gap must cost the provenance field,
        # never the read that already succeeded.
        spark = _FakeSpark(_FakeQuery(None, error=RuntimeError("not a Delta table")))
        dataset = SparkTableSource(spark, "cat.sch.tbl").load()
        assert dataset.source_version is None
        assert len(dataset.frame) == 1

    def test_empty_history_yields_no_version(self) -> None:
        dataset = SparkTableSource(_FakeSpark(_FakeQuery([])), "cat.sch.tbl").load()
        assert dataset.source_version is None

    def test_a_history_row_without_a_version_yields_none(self) -> None:
        spark = _FakeSpark(_FakeQuery([object()]))
        dataset = SparkTableSource(spark, "cat.sch.tbl").load()
        assert dataset.source_version is None


def table_config(**overrides: object) -> ResolvedDataset:
    """`benchmark_plain`, re-pointed at Unity Catalog objects (ADR-0025).

    Built by copy rather than by loading `databricks_table_example.yaml` on purpose:
    that file uses language `mode: detect`, and building its pipeline would need the
    `language` extra, which the default tier does not have (ADR-0009). The example
    file is validated by `TestTheShippedExample` below, which resolves it without
    building anything.
    """
    from pii_reduction.config.models import DeltaTableDestination, SparkTableSource

    base = resolved_config()
    source = SparkTableSource(type="spark_table", table="cat.raw.tickets")
    destination = DeltaTableDestination.model_validate(
        {"type": "delta_table", "catalog": "cat", "schema": "reduced", **overrides}
    )
    return base.model_copy(update={"source": source, "destination": destination})


class TestConfigNamedTables:
    """P2's exit criterion: a dataset YAML names a UC table end to end.

    Fake sessions throughout — no workspace, no Spark, default tier. The parity test
    asserts the same wiring against the real workspace on its next run.
    """

    def _spark(self) -> _FakeWritableSpark:
        return _FakeWritableSpark(_FakeQuery([_HistoryRow(7)]))

    def test_run_driver_takes_both_names_from_configuration(self) -> None:
        from pii_reduction.databricks.runner import run_driver

        spark = self._spark()
        result = run_driver(spark, table_config())

        assert result.reduced_table == "cat.reduced.benchmark_corpus_plain_reduced"
        assert result.audit_table == "cat.reduced.benchmark_corpus_plain_pii_audit"
        assert result.metrics_table == "cat.reduced.benchmark_corpus_plain_run_metrics"
        # The configured table is what was read, not a default or a session guess.
        assert any("cat.raw.tickets" in query for query in spark.queries)

    def test_an_explicit_argument_still_wins(self) -> None:
        # What lets one committed config be pointed at a throwaway schema — the
        # parity test depends on exactly this.
        from pii_reduction.databricks.runner import run_driver

        spark = self._spark()
        result = run_driver(
            spark,
            table_config(),
            source_table="cat.other.src",
            destination_prefix="cat.scratch",
        )
        assert result.reduced_table.startswith("cat.scratch.")
        assert any("cat.other.src" in query for query in spark.queries)

    def test_the_configured_write_mode_is_used(self) -> None:
        from pii_reduction.databricks.output import DeltaTableOutput
        from pii_reduction.databricks.runner import _resolve_destination

        prefix, mode = _resolve_destination(table_config(mode="overwrite"), None, None)
        assert (prefix, mode) == ("cat.reduced", "overwrite")
        # An unconfigured destination keeps the fail-safe default rather than
        # inheriting a mode from somewhere.
        assert _resolve_destination(resolved_config(), "cat.scratch", None)[1] == "errorifexists"
        assert DeltaTableOutput(object(), prefix, mode=mode) is not None

    def test_a_configured_projection_applies_on_databricks_too(self) -> None:
        """ADR-0024's projection is a property of the artifact, not of the runtime."""
        from pii_reduction.databricks.runner import run_driver

        spark = self._spark()
        result = run_driver(spark, table_config(projection="reduced_only"))
        written = spark.tables[result.reduced_table]
        configured = [policy.column for policy in resolved_config().columns]
        for column in configured:
            assert column not in written.columns
        assert "text_pii_redacted" in written.columns

    def test_a_file_source_is_read_locally_and_still_writes_delta(self) -> None:
        """A `csv` source is not an error on the Databricks path (2026-08-21).

        On compute the local adapter's "filesystem path" includes a Unity Catalog
        volume, so this is what makes runbook §6 — upload a file, reduce it, land it
        in Delta — actually run. Refusing it meant the Databricks front door could not
        execute the config that section publishes, which only surfaced when the CLI
        was run as a job.
        """
        from pii_reduction.databricks.runner import run_driver

        spark = self._spark()
        # `benchmark_plain` reads the committed corpus CSV from disk.
        result = run_driver(spark, resolved_config(), destination_prefix="cat.scratch")

        assert result.rows > 0
        assert result.reduced_table == "cat.scratch.benchmark_corpus_plain_reduced"
        # Read through the file adapter, so no table was queried for its version.
        assert not any("DESCRIBE HISTORY" in query for query in spark.queries)
        written = spark.tables[result.reduced_table]
        assert "text_pii_redacted" in written.columns

    def test_a_config_without_a_destination_prefix_says_what_to_add(self) -> None:
        from pii_reduction.databricks.runner import run_driver

        with pytest.raises(DatabricksError) as exc_info:
            run_driver(self._spark(), resolved_config(), source_table="cat.raw.src")
        message = str(exc_info.value)
        assert "delta_table" in message and "destination_prefix=" in message


class TestTheShippedExample:
    def test_the_example_dataset_resolves(self) -> None:
        """`configs/datasets/databricks_table_example.yaml` is what the runbook copies.

        Resolution only — no pipeline is built, so this stays inside the default
        tier's no-model, no-Spark budget while still failing if the example drifts
        out of the config contract.
        """
        config = load_resolved_dataset(REPO_ROOT / "configs", "databricks_table_example")
        assert config.source.type == "spark_table"
        assert config.destination.type == "delta_table"
        assert config.destination.prefix.count(".") == 1
        # The chain, not just the entity list: `entities` declares scope while
        # `provider_chain` decides capability, and the project default chain cannot
        # detect PERSON. An example that lists PERSON under `deterministic_only`
        # would redact emails, report success, and leave every name in the text.
        assert config.columns[0].provider_chain == "deterministic_presidio"
        assert "PERSON" in config.columns[0].entities
        # And the copyable example must not teach writing back into the source schema.
        assert config.destination.prefix != config.source.table.rsplit(".", 1)[0]


class TestDatabricksCli:
    """The front door, wired against a fake session (no workspace, no Spark)."""

    def _main(self, argv: list[str], spark: object) -> int:
        from pii_reduction.databricks.cli import main

        return main(argv, session_factory=lambda _profile=None: spark)

    def test_run_reports_metadata_only(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pii_reduction.databricks.cli as cli_module

        spark = _FakeWritableSpark(_FakeQuery([_HistoryRow(1)]))
        config = table_config()
        # The CLI's job under test is argument wiring, so the config load is the one
        # thing stubbed: a real dataset file cannot both name a UC table and stay
        # inside the default tier's no-model budget (see `table_config`).
        monkeypatch.setattr(cli_module, "load_resolved_dataset", lambda *_a, **_k: config)
        code = self._main(["run", "any_dataset"], spark)

        assert code == 0
        captured = capsys.readouterr()
        assert "cat.reduced.benchmark_corpus_plain_reduced" in captured.out
        # AGENTS.md rule 8: no source text and no detected value on either stream.
        source_text = spark.tables["cat.reduced.benchmark_corpus_plain_reduced"].iloc[0]
        assert str(source_text["text"]) not in captured.out
        assert str(source_text["text"]) not in captured.err
        assert "@" not in captured.out

    def test_a_missing_dataset_exits_two_with_a_readable_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spark = _FakeWritableSpark(_FakeQuery([]))
        code = self._main(
            ["run", "no_such_dataset", "--configs", str(REPO_ROOT / "configs")], spark
        )
        assert code == 2
        assert "not found" in capsys.readouterr().err


class TestDestructiveWritesAreRefused:
    """AGENTS.md rule 4 at the table level, not just the column level."""

    @pytest.mark.parametrize("suffix", ["reduced", "pii_audit", "run_metrics"])
    def test_a_run_cannot_write_over_the_table_it_reads(self, suffix: str) -> None:
        from pii_reduction.databricks.runner import run_driver

        spark = _FakeWritableSpark(_FakeQuery([_HistoryRow(2)]))
        source = f"cat.reduced.benchmark_corpus_plain_{suffix}"
        with pytest.raises(DatabricksError, match="write over the table it reads"):
            run_driver(
                spark,
                table_config(mode="overwrite"),
                source_table=source,
                destination_prefix="cat.reduced",
            )
        # Refused before anything was read or written, not part-way through.
        assert spark.tables == {}

    def test_the_projection_target_is_checked_too(self) -> None:
        from pii_reduction.databricks.runner import run_driver

        spark = _FakeWritableSpark(_FakeQuery([_HistoryRow(2)]))
        with pytest.raises(DatabricksError, match="write over the table it reads"):
            run_driver(
                spark,
                table_config(),
                source_table="cat.consumers.benchmark_corpus_plain_reduced_only",
                destination_prefix="cat.operator",
                reduced_only_prefix="cat.consumers",
            )


class TestUnexpectedFailuresStayQuiet:
    def test_a_third_party_exception_reaches_stderr_as_its_class_only(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A Connect failure quotes the workspace URL and profile in its message.

        The core CLI lets an unexpected exception keep its traceback, which is right
        for a local run. This front door's output lands in a job log, so the message
        is replaced by the exception class (AGENTS.md rules 1 and 8).
        """
        from pii_reduction.databricks.cli import main

        secret_shaped = "cannot reach https://example-workspace.invalid with profile FIELD_TEAM"

        def explode(_profile: str | None = None) -> object:
            raise RuntimeError(secret_shaped)

        # A dataset that resolves, so the run reaches the session factory: the
        # config load happens first and would otherwise fail before the crossing
        # under test.
        code = main(
            ["run", "databricks_table_example", "--configs", str(REPO_ROOT / "configs")],
            session_factory=explode,
        )
        captured = capsys.readouterr()
        assert code == 2
        assert "RuntimeError" in captured.err
        assert secret_shaped not in captured.err
        assert "example-workspace" not in captured.err
        assert captured.out == ""


class TestTableNameShapesAgree:
    """The config pattern and the SQL-boundary validator must accept the same names.

    Two validators exist on purpose — one fails a typo at config load with a readable
    message, the other guards SQL interpolation — but if they disagreed, a name could
    pass configuration and then be refused at the first query, or worse, the reverse.
    """

    @pytest.mark.parametrize(
        "table",
        ["workspace.demo.table_1", "cat.sch.tbl", "_a._b._c"],
    )
    def test_both_accept_the_same_good_names(self, table: str) -> None:
        from pii_reduction.config.models import SparkTableSource as SparkTableSourceConfig

        assert require_table_name(table) == table
        assert SparkTableSourceConfig(type="spark_table", table=table).table == table

    @pytest.mark.parametrize(
        "bad",
        [
            "table",
            "schema.table",
            "c.s.t; DROP TABLE x",
            "c.s.`t`",
            "c..t",
            "",
            "cat.sch.tbl\n",  # the trailing-newline case `\Z` exists for
        ],
    )
    def test_both_refuse_the_same_bad_names(self, bad: str) -> None:
        from pydantic import ValidationError

        from pii_reduction.config.models import SparkTableSource as SparkTableSourceConfig

        with pytest.raises(DatabricksError):
            require_table_name(bad)
        with pytest.raises(ValidationError):
            SparkTableSourceConfig(type="spark_table", table=bad)


class TestTheLocalPipelineRefusesTableTypes:
    """The routing that turns a table-typed config into guidance, not a crash.

    `Pipeline.load`/`write` read `path` with `getattr` precisely so these configs
    reach the registry's message. Without these tests, reverting to direct attribute
    access would break nothing in the suite — `run_driver` never calls either method.
    """

    def test_load_names_the_driver_path(self) -> None:
        from pii_reduction.processing.pipeline import build_pipeline
        from pii_reduction.sources.errors import SourceError

        with pytest.raises(SourceError, match="run_driver"):
            build_pipeline(table_config()).load()

    def test_write_names_the_driver_path(self) -> None:
        from pii_reduction.outputs.errors import OutputError
        from pii_reduction.processing.pipeline import build_pipeline
        from pii_reduction.sources.local import PandasSource

        pipeline = build_pipeline(table_config())
        frame = load_corpus(REPO_ROOT / "tests" / "fixtures" / "corpus").to_frame()
        batch = frame[frame["document_type"] == "plain"].head(2).reset_index(drop=True)
        outcome = pipeline.process(PandasSource(batch, name="x").load())
        with pytest.raises(OutputError, match="run_driver"):
            pipeline.write(outcome)


class TestDriverRunStatus:
    def test_a_clean_run_reports_success_and_no_failed_fields(self) -> None:
        from pii_reduction.databricks.runner import run_driver

        result = run_driver(_FakeWritableSpark(_FakeQuery([_HistoryRow(1)])), table_config())
        assert result.status == "success"
        assert result.fields_failed == 0

    def test_the_cli_exits_one_when_fields_failed(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scheduler must not read a partial reduction as green (ADR-0025 rung 3)."""
        import pii_reduction.databricks.cli as cli_module
        from pii_reduction.databricks.runner import DriverRunResult

        failed = DriverRunResult(
            run_id="r",
            config_hash="c" * 16,
            rows=3,
            reduced_table="cat.reduced.d_reduced",
            audit_table="cat.reduced.d_pii_audit",
            metrics_table="cat.reduced.d_run_metrics",
            status="partial_failure",
            fields_failed=2,
        )
        monkeypatch.setattr(cli_module, "load_resolved_dataset", lambda *_a, **_k: table_config())
        monkeypatch.setattr(cli_module, "run_driver", lambda *_a, **_k: failed)
        code = cli_module.main(["run", "d"], session_factory=lambda _p=None: object())

        assert code == 1
        assert "fields_failed=2" in capsys.readouterr().out


class TestReducedOnlyPrefixOnTheCli:
    def test_the_flag_reaches_the_runner(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pii_reduction.databricks.cli as cli_module

        spark = _FakeWritableSpark(_FakeQuery([_HistoryRow(1)]))
        monkeypatch.setattr(cli_module, "load_resolved_dataset", lambda *_a, **_k: table_config())
        code = cli_module.main(
            ["run", "d", "--reduced-only-prefix", "cat.consumers"],
            session_factory=lambda _p=None: spark,
        )

        assert code == 0
        out = capsys.readouterr().out
        assert "reduced_only: cat.consumers.benchmark_corpus_plain_reduced_only" in out
        projected = spark.tables["cat.consumers.benchmark_corpus_plain_reduced_only"]
        assert "text" not in projected.columns


class TestAuditSchemaIsPinnedToALiteral:
    """The audit table's metadata-only guarantee, pinned where CI can see it.

    The parity test compares the written table against `AUDIT_COLUMNS` — but the
    writer *builds* the frame from `AUDIT_COLUMNS`, so both sides move together and
    adding a raw-text field would keep it green. It is also `databricks`-marked, so
    it never runs in CI. This is the literal, in the default tier: adding a column
    that could carry a value has to be a deliberate edit here, with rule 8 in view.
    """

    def test_the_column_set_is_exactly_this(self) -> None:
        from pii_reduction.processing.field_processor import AUDIT_COLUMNS

        assert AUDIT_COLUMNS == (
            "run_id",
            "row_id",
            "column_name",
            "segment_id",
            "segment_start",
            "entity_type",
            "start",
            "end",
            "score",
            "provider",
            "recognizer",
            "language",
            "resolution_rule",
        ), (
            "the audit schema changed. Every column here is metadata about a span; "
            "none carries the matched text, and none may (AGENTS.md rule 8, "
            "SECURITY.md). Update this literal only with that in mind."
        )


class TestAuthRoutes:
    """Which credentials the session accepts (session 10).

    A profile is the nicest route and is not available everywhere: some
    organisations block the Databricks CLI outright, leaving a personal access token
    or a service principal as the only option. Refusing those would make the whole
    Databricks surface unusable in exactly the environments it was built for.

    The decision is separated from session construction so it can be tested here, in
    the default tier, with no Databricks Connect installed and no real credential
    anywhere. Values below are obvious fakes.
    """

    AUTH_VARS = (
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_RUNTIME_VERSION",
    )

    @pytest.fixture(autouse=True)
    def _clear_auth_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The developer machine may have any of these set; the routes must be decided
        # by the test, not by the environment it runs in.
        for name in self.AUTH_VARS:
            monkeypatch.delenv(name, raising=False)

    def test_an_explicit_profile_wins(self) -> None:
        from pii_reduction.databricks.session import resolve_auth_route

        assert resolve_auth_route("my-profile") == ("profile", "my-profile")

    def test_the_profile_environment_variable_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "from-env")
        assert resolve_auth_route() == ("profile", "from-env")

    def test_a_host_and_token_authenticate_without_any_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The route for workspaces where policy blocks the CLI."""
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_HOST", "https://example.invalid")
        monkeypatch.setenv("DATABRICKS_TOKEN", "not-a-real-token")
        assert resolve_auth_route() == ("env_token", None)

    def test_a_service_principal_authenticates_without_any_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_HOST", "https://example.invalid")
        monkeypatch.setenv("DATABRICKS_CLIENT_ID", "not-a-real-id")
        monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "not-a-real-secret")
        assert resolve_auth_route() == ("env_oauth", None)

    def test_running_on_databricks_needs_no_credential_of_ours(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_RUNTIME_VERSION", "16.4")
        assert resolve_auth_route() == ("ambient", None)

    def test_on_compute_an_inherited_profile_does_not_displace_ambient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale variable must not route a notebook through Connect.

        The process already has a session there, and taking the profile route would
        also set a serverless compute override the runtime never asked for.
        """
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_RUNTIME_VERSION", "16.4")
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "inherited-from-somewhere")
        assert resolve_auth_route() == ("ambient", None)

    def test_but_an_explicit_profile_argument_still_wins_on_compute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An argument is someone saying what they want; ambient is only a default.
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_RUNTIME_VERSION", "16.4")
        assert resolve_auth_route("deliberate") == ("profile", "deliberate")

    def test_a_host_without_a_secret_is_not_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Half-configured must fail with the instructions, not proceed and fail
        # somewhere less legible.
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_HOST", "https://example.invalid")
        with pytest.raises(DatabricksError, match="no Databricks credentials found"):
            resolve_auth_route()

    def test_the_refusal_names_every_route_and_no_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pii_reduction.databricks.session import resolve_auth_route

        monkeypatch.setenv("DATABRICKS_TOKEN", "not-a-real-token")  # no host: not enough
        with pytest.raises(DatabricksError) as exc_info:
            resolve_auth_route()
        message = str(exc_info.value)
        for name in ("DATABRICKS_CONFIG_PROFILE", "DATABRICKS_HOST", "DATABRICKS_TOKEN"):
            assert name in message, "the refusal must name the variable to set"
        # It names variables, never their contents (AGENTS.md rule 1).
        assert "not-a-real-token" not in message

    def test_there_is_no_way_to_pass_a_secret_as_an_argument(self) -> None:
        """The signature is the control: a token parameter would invite committing one."""
        import inspect

        from pii_reduction.databricks.session import get_session

        parameters = set(inspect.signature(get_session).parameters)
        assert parameters == {"profile", "serverless"}


class TestWriteModeReachesSparkAsAnAcceptedName:
    """`errorifexists` must reach Spark as `error` (session 10, measured).

    Databricks Connect rejects `errorifexists` outright —
    `[UNSUPPORTED_OPERATION] errorifexists is not supported` — and it is the shipped
    default, so before this translation every config-driven Delta write failed on the
    workspace. Nothing caught it: the parity test passes `mode="overwrite"`
    explicitly, so the default path had no coverage at all until the first real
    end-to-end CLI run hit it.
    """

    class _Recorder:
        def __init__(self) -> None:
            self.tables: dict[str, pd.DataFrame] = {}
            self.modes: dict[str, str] = {}

        def createDataFrame(self, frame: pd.DataFrame):  # type: ignore[no-untyped-def]  # noqa: N802
            return _FakeSessionFrame(self.tables, frame, self.modes)

    def _written_mode(self, configured: str) -> str:
        from pii_reduction.databricks.output import DeltaTableOutput

        spark = self._Recorder()
        DeltaTableOutput(spark, "cat.sch", mode=configured).write(
            pd.DataFrame({"a": ["x"]}), name="t"
        )
        return spark.modes["cat.sch.t"]

    def test_errorifexists_is_translated(self) -> None:
        assert self._written_mode("errorifexists") == "error"

    @pytest.mark.parametrize("mode", ["overwrite", "append"])
    def test_the_others_pass_through(self, mode: str) -> None:
        assert self._written_mode(mode) == mode

    def test_every_accepted_mode_has_a_translation(self) -> None:
        # A mode the config layer accepts but the writer cannot translate would fail
        # at the workspace boundary, which is exactly how this was found.
        from pii_reduction.databricks.output import _KNOWN_MODES, _SPARK_MODES

        assert set(_SPARK_MODES) == set(_KNOWN_MODES)
        # `errorifexists` is the one name Connect refuses; nothing may send it.
        assert "errorifexists" not in set(_SPARK_MODES.values())


class TestErrorLabelsCarryTheConditionAndNothingElse:
    """`ClassName: CONDITION` — the token that makes a failure diagnosable.

    This session lost an afternoon to `could not write <table> (PySparkValueError)`
    whose real cause was `[UNSUPPORTED_OPERATION] errorifexists is not supported`.
    The condition is a fixed identifier and carries no data; the message can quote a
    workspace URL or a cell value, so it still never appears.
    """

    class _ConditionError(Exception):
        def getCondition(self) -> str:  # noqa: N802 - Spark's casing
            return "TABLE_OR_VIEW_ALREADY_EXISTS"

    class _LegacyClassError(Exception):
        def getErrorClass(self) -> str:  # noqa: N802 - Spark's casing
            return "UNSUPPORTED_OPERATION"

    class _HostileGetterError(Exception):
        def getCondition(self) -> str:  # noqa: N802 - Spark's casing
            raise RuntimeError("getter itself fails")

    def test_a_condition_is_included(self) -> None:
        from pii_reduction.databricks.errors import error_label

        label = error_label(self._ConditionError("workspace https://example.invalid said no"))
        assert label == "_ConditionError: TABLE_OR_VIEW_ALREADY_EXISTS"
        # The message is what can carry a host or a cell value; it must not appear.
        assert "example.invalid" not in label

    def test_the_older_getter_is_used_too(self) -> None:
        from pii_reduction.databricks.errors import error_label

        assert (
            error_label(self._LegacyClassError("x")) == "_LegacyClassError: UNSUPPORTED_OPERATION"
        )

    def test_a_plain_exception_degrades_to_its_class(self) -> None:
        from pii_reduction.databricks.errors import error_label

        assert error_label(ValueError("sensitive text")) == "ValueError"

    def test_a_failing_getter_never_becomes_a_second_failure(self) -> None:
        from pii_reduction.databricks.errors import error_label

        assert error_label(self._HostileGetterError("x")) == "_HostileGetterError"


class TestConfigModesAndWriterModesCannotDrift:
    def test_the_config_vocabulary_matches_what_the_writer_accepts(self) -> None:
        """A mode config accepts but the writer cannot deliver is this session's bug class."""
        from typing import get_args

        from pii_reduction.config.models import DeltaTableDestination
        from pii_reduction.databricks.output import _KNOWN_MODES

        annotation = DeltaTableDestination.model_fields["mode"].annotation
        assert set(get_args(annotation)) == _KNOWN_MODES


class TestTheEntryPointRaisesRatherThanReturns:
    """A Databricks wheel task ignores a returned exit code (measured 2026-08-21).

    The job called the entry point as a function, the CLI returned 2 after printing
    an error, and the run was recorded as SUCCESS — a scheduler would have seen green
    over a failed reduction. `console_scripts` hides this locally by wrapping in
    `sys.exit`, so only a real job run could surface it.
    """

    def test_a_failure_exit_code_becomes_a_systemexit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pii_reduction.databricks.cli as cli_module

        monkeypatch.setattr(cli_module, "main", lambda *_a, **_k: 2)
        with pytest.raises(SystemExit) as exc_info:
            cli_module.cli()
        assert exc_info.value.code == 2

    def test_success_returns_without_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`SystemExit(0)` would fail the job too — Databricks runs it under IPython.

        Measured the same day: raising unconditionally marked a task failed after it
        had read 25 rows from a volume and written three Delta tables.
        """
        import pii_reduction.databricks.cli as cli_module

        monkeypatch.setattr(cli_module, "main", lambda *_a, **_k: 0)
        cli_module.cli()  # must simply return; raising would fail the job

    def test_the_console_script_points_at_the_raising_wrapper(self) -> None:
        # The wheel task names this entry point; pointing it back at `main` would
        # silently restore the green-on-failure behaviour.
        import tomllib

        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            scripts = tomllib.load(handle)["project"]["scripts"]
        assert scripts["pii-reduction-databricks"].endswith(":cli")

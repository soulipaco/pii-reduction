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

    def __init__(self, sink: dict[str, pd.DataFrame], frame: pd.DataFrame) -> None:
        self._sink = sink
        self._frame = frame

    def format(self, _fmt: str) -> _FakeWriter:
        return self

    def mode(self, _mode: str) -> _FakeWriter:
        return self

    def saveAsTable(self, table: str) -> None:  # noqa: N802 - Spark's casing
        self._sink[table] = self._frame


class _FakeSessionFrame:
    def __init__(self, sink: dict[str, pd.DataFrame], frame: pd.DataFrame) -> None:
        self.write = _FakeWriter(sink, frame)


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

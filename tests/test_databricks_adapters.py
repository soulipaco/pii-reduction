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

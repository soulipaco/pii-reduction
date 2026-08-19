"""Local-vs-Databricks parity on the committed corpus (Increment F's exit).

``databricks``-marked: needs the ``databricks`` extra in its own venv and an
authenticated CLI profile in ``DATABRICKS_CONFIG_PROFILE``. Never runs in CI
(ADR-0009) — no workflow installs the extra and the marker is excluded.

The claim under test is `AGENTS.md`'s "one implementation, two runtimes": rows in
through Spark, the same ``Pipeline.process``, Delta out — and the reduced output is
**byte-identical** to the local run, asserted as a hash over the reduced column in
document order.

Everything created lives under one throwaway schema which is dropped afterwards; the
tests leave the workspace as they found it.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from pii_reduction.config.loader import load_resolved_dataset
from pii_reduction.synthetic.corpus import load_corpus

pytestmark = pytest.mark.databricks

REPO_ROOT = Path(__file__).resolve().parents[1]
#: Configurable per AGENTS.md ("Unity Catalog object names should be configurable");
#: `workspace` is the generic default catalog on serverless workspaces, not a
#: workspace-identifying value.
SCHEMA = os.environ.get("PII_PARITY_SCHEMA", "workspace.pii_reduction_parity")


@pytest.fixture(scope="module")
def spark() -> Any:
    if not os.environ.get("DATABRICKS_CONFIG_PROFILE"):
        pytest.skip("set DATABRICKS_CONFIG_PROFILE to run workspace tests")
    from pii_reduction.databricks import get_session

    session = get_session()
    catalog, schema = SCHEMA.split(".")
    existing = session.sql(f"SHOW SCHEMAS IN {catalog} LIKE '{schema}'").count()
    if existing:
        # Never adopt-and-destroy a schema someone else made: teardown drops CASCADE,
        # and "the tests leave the workspace as they found it" must stay true.
        pytest.skip(f"schema {SCHEMA} already exists; set PII_PARITY_SCHEMA to a fresh name")
    session.sql(f"CREATE SCHEMA {SCHEMA}")
    yield session
    session.sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


@pytest.fixture(scope="module")
def corpus_frame() -> pd.DataFrame:
    corpus = load_corpus(REPO_ROOT / "tests" / "fixtures" / "corpus")
    frame = corpus.to_frame()
    return frame[frame["document_type"] == "plain"].reset_index(drop=True)


def reduced_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values("document_id")["text_pii_redacted"]
    return hashlib.sha256("\x1f".join(ordered.tolist()).encode()).hexdigest()


class TestDriverPathParity:
    def test_delta_round_trip_reduces_identically_to_local(
        self, spark: Any, corpus_frame: pd.DataFrame
    ) -> None:
        """The exit criterion: output-hash equality on the shared fixture."""
        from pii_reduction.databricks import SparkTableSource, run_driver
        from pii_reduction.processing.pipeline import build_pipeline
        from pii_reduction.sources.local import PandasSource

        config = load_resolved_dataset(REPO_ROOT / "configs", "benchmark_plain")

        # Rows go up as a Delta table first, so the read side exercises the real
        # source adapter rather than a frame that never left the driver.
        spark.createDataFrame(corpus_frame).write.format("delta").mode("overwrite").saveAsTable(
            f"{SCHEMA}.corpus"
        )

        result = run_driver(
            spark,
            config,
            source_table=f"{SCHEMA}.corpus",
            destination_prefix=SCHEMA,
            mode="overwrite",
        )
        assert result.rows == len(corpus_frame)

        remote = SparkTableSource(spark, result.reduced_table).load().frame
        local_pipeline = build_pipeline(config)
        local = local_pipeline.process(PandasSource(corpus_frame, name="local").load()).frame

        assert reduced_hash(remote) == reduced_hash(local), (
            "the Databricks round trip and the local run reduced the same corpus "
            "differently — the two-runtimes claim is broken"
        )

    def test_audit_and_metrics_tables_exist_and_are_metadata_only(
        self, spark: Any, corpus_frame: pd.DataFrame
    ) -> None:
        """The audit table carries spans and providers, never surfaces (AGENTS.md 8)."""
        config = load_resolved_dataset(REPO_ROOT / "configs", "benchmark_plain")
        from pii_reduction.processing.field_processor import AUDIT_COLUMNS

        audit = spark.read.table(f"{SCHEMA}.{config.dataset.name}_pii_audit").toPandas()
        assert len(audit) > 0
        # Exact set, not a denylist: a future field carrying raw text under a NEW
        # name must fail here, which "no column called surface" cannot promise
        # (AGENTS.md rule 8, SECURITY.md "audit table storing raw entity values").
        assert set(audit.columns) == set(AUDIT_COLUMNS)

        metrics = spark.read.table(f"{SCHEMA}.{config.dataset.name}_run_metrics").toPandas()
        assert metrics.loc[0, "run_rows_read"] == len(corpus_frame)
        assert str(metrics.loc[0, "run_config_hash"])
        # Session-9 provenance (docs/17 D2): the driver path reads a real Delta
        # table this test created, so the source version must resolve.
        assert str(metrics.loc[0, "run_source_version"]).startswith("delta_v")


class TestDistributedPath:
    def test_map_in_pandas_or_the_recorded_incident(
        self, spark: Any, corpus_frame: pd.DataFrame
    ) -> None:
        """Passes on a workspace with working Python sandboxes; reports the known
        incident otherwise.

        The development workspace's serverless channel cannot start Python worker
        sandboxes (ISOLATION_STARTUP_FAILURE, plan §8 F). That is Databricks
        infrastructure, not this code — the partition function itself is proven in
        the default tier — so the incident is *reported* as a skip with the error
        class, and the day the sandbox works this test starts asserting real
        distributed parity with no code change.
        """
        from pii_reduction.databricks import distributed_frame
        from pii_reduction.processing.pipeline import build_pipeline
        from pii_reduction.sources.local import PandasSource

        config = load_resolved_dataset(REPO_ROOT / "configs", "benchmark_plain")
        source = spark.createDataFrame(corpus_frame[["document_id", "language", "text"]])

        run = distributed_frame(source, config)
        try:
            distributed = run.frame.toPandas()
        except Exception as error:
            message = str(error)
            if "ISOLATION_STARTUP_FAILURE" in message or "SANDBOX" in message.upper():
                pytest.skip(
                    "serverless Python sandbox unavailable on this workspace "
                    "(ISOLATION_STARTUP_FAILURE) — known incident, see plan §8 F"
                )
            raise

        local_pipeline = build_pipeline(config)
        local = local_pipeline.process(PandasSource(corpus_frame, name="local").load()).frame
        assert reduced_hash(distributed) == reduced_hash(local)

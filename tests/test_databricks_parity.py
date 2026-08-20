"""Local-vs-Databricks parity on the committed corpus (Increment F's exit).

``databricks``-marked: needs the ``databricks`` extra in its own venv and any one of
the supported credential routes — a CLI profile, ``DATABRICKS_HOST`` plus a token or
service principal, or ambient credentials when running on Databricks compute. Never
runs in CI (ADR-0009) — no workflow installs the extra and the marker is excluded.

The claim under test is `AGENTS.md`'s "one implementation, two runtimes": rows in
through Spark, the same ``Pipeline.process``, Delta out — and the reduced output is
**byte-identical** to the local run, asserted as a hash over the reduced column in
document order.

Everything created lives under one throwaway schema which is dropped afterwards; the
tests leave the workspace as they found it. **That schema is created and dropped in
whatever workspace the session belongs to** — set ``PII_PARITY_SCHEMA`` to name it,
which is required outright when running on Databricks compute, where there is no
credential to act as the opt-in.
"""

from __future__ import annotations

import hashlib
import os
import re
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
#: The volume the Volumes test creates inside that throwaway schema.
VOLUME = os.environ.get("PII_PARITY_VOLUME", "pii_reduction_files")

#: Both names are interpolated into CREATE and DROP statements, and both come from
#: the environment. SECURITY.md asks for exactly this check where object identifiers
#: are configurable, and the library already applies it at its own SQL boundary
#: (`databricks.source.require_table_name`); a test that issues `DROP ... CASCADE`
#: has no business being the laxer of the two.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")


def _require_identifiers() -> None:
    parts = SCHEMA.split(".")
    if len(parts) != 2 or not all(_IDENTIFIER.match(part) for part in parts):
        pytest.skip(f"PII_PARITY_SCHEMA must be catalog.schema with plain identifiers: {SCHEMA!r}")
    if not _IDENTIFIER.match(VOLUME):
        pytest.skip(f"PII_PARITY_VOLUME must be a plain identifier: {VOLUME!r}")


def _workspace_session() -> Any:
    """The session these tests run against, from whatever credentials exist.

    Prefers a session that is **already running**: on Databricks compute — a notebook
    or a job — the runtime has built one, and constructing a second through Connect
    would be both wrong and unnecessary. Falls back to
    :func:`~pii_reduction.databricks.get_session`, which accepts a CLI profile,
    ``DATABRICKS_HOST`` plus a token or service principal, or ambient compute
    credentials.

    Gating on ``DATABRICKS_CONFIG_PROFILE`` alone (as this fixture used to) made a
    CLI profile the only way in, so these tests were unrunnable both from a notebook
    and in any organisation whose policy blocks the Databricks CLI — which is a
    supported way to use this project, not an edge case.
    """
    active = _active_workspace_session()
    if active is not None:
        return active
    from pii_reduction.databricks import get_session

    return get_session()


def _active_workspace_session() -> Any | None:
    """The session this process already has, if any."""
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        return None
    return SparkSession.getActiveSession()


@pytest.fixture(scope="module")
def spark() -> Any:
    from pii_reduction.databricks.errors import DatabricksError
    from pii_reduction.databricks.session import resolve_auth_route

    _require_identifiers()
    # An already-running session is itself proof of credentials, and it is what a
    # notebook or job has. Asking `resolve_auth_route` first would make this depend
    # on DATABRICKS_RUNTIME_VERSION being set, which is not something to rest on for
    # serverless compute.
    existing = _active_workspace_session()
    route = "ambient"
    if existing is None:
        try:
            # Decides only whether credentials are *present*; it opens no connection,
            # so a machine with none skips here rather than timing out later.
            route, _profile = resolve_auth_route()
        except DatabricksError as error:
            pytest.skip(str(error))

    if route == "ambient" and not os.environ.get("PII_PARITY_SCHEMA"):
        # On compute there is no credential to withhold, so the marker would be the
        # only thing between `pytest -m databricks` in a notebook and CREATE/DROP in
        # whatever workspace that session belongs to. Naming the schema is the
        # operator's deliberate gesture; without it, refuse to touch anything.
        pytest.skip(
            "running on Databricks compute: set PII_PARITY_SCHEMA explicitly to name "
            "the throwaway catalog.schema these tests may create and drop"
        )

    session = existing if existing is not None else _workspace_session()
    catalog, schema = SCHEMA.split(".")
    existing = session.sql(f"SHOW SCHEMAS IN {catalog} LIKE '{schema}'").count()
    if existing:
        # Never adopt-and-destroy a schema someone else made: teardown drops CASCADE,
        # and "the tests leave the workspace as they found it" must stay true.
        pytest.skip(f"schema {SCHEMA} already exists; set PII_PARITY_SCHEMA to a fresh name")
    session.sql(f"CREATE SCHEMA {SCHEMA}")
    yield session
    # The volume is dropped explicitly before the schema: whether CASCADE removes a
    # managed volume and its files has never been exercised here, and the teardown
    # promise above is not worth resting on an assumption.
    session.sql(f"DROP VOLUME IF EXISTS {SCHEMA}.{VOLUME}")
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
            # Same schema deliberately — the parity fixture owns exactly one; what
            # matters is that the projection table exists and drops the raw column.
            reduced_only_prefix=SCHEMA,
            mode="overwrite",
        )
        assert result.rows == len(corpus_frame)

        # ADR-0024: the projection carries the reduced column, never the raw one.
        assert result.reduced_only_table is not None
        projected = spark.read.table(result.reduced_only_table).toPandas()
        assert "text" not in projected.columns
        assert "text_pii_redacted" in projected.columns
        assert len(projected) == len(corpus_frame)

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


class TestVolumeIngestion:
    """A `/Volumes/...` file read through the ordinary CSV source (plan §8 P3).

    The claim under test is that a Unity Catalog volume needs **no new adapter**: a
    volume path is a filesystem path, so `CsvSource` reads it unchanged. That is only
    true where the volume is actually mounted — on Databricks compute — because the
    FUSE mount is server-side. From a local Databricks Connect client there is no
    `/Volumes` on the machine, so the read is skipped with that stated rather than
    asserted; run this test from a notebook or job on the workspace to make it assert.
    """

    def test_a_volume_csv_loads_through_the_plain_csv_source(
        self, spark: Any, corpus_frame: pd.DataFrame
    ) -> None:
        from pii_reduction.sources.local import CsvSource

        if not Path("/Volumes").exists():
            # Checked before the volume is created: a client without the mount
            # leaves no volume and no file behind. (The throwaway schema itself is
            # the fixture's, and its teardown removes it either way.)
            pytest.skip(
                "no /Volumes mount on this machine: the volume FUSE mount is "
                "server-side, so this assertion holds when the process runs on "
                "Databricks compute (notebook or job), not from a local Connect "
                "client. Run this test there to assert it."
            )

        catalog, schema = SCHEMA.split(".")
        spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{VOLUME}")
        volume_path = f"/Volumes/{catalog}/{schema}/{VOLUME}/corpus.csv"

        # Written as one ordinary file, not a Spark output directory: the claim is
        # that `CsvSource` needs no volume awareness, and it takes a file path.
        # Synthetic corpus only — the committed fixture, never real data (rule 2).
        corpus_frame.to_csv(volume_path, index=False, encoding="utf-8")

        dataset = CsvSource(volume_path, name="volume_corpus").load()
        assert dataset.row_count == len(corpus_frame)
        assert dataset.source_type == "csv"
        assert dataset.source_reference == volume_path

"""Run the local pipeline on Databricks — same ``build_pipeline``, same ``process``.

Two paths, one pipeline:

* **Driver path** (:func:`run_driver`): rows come in through Spark, the pipeline runs
  on the driver exactly as it does locally, and reduced/audit/metrics land as Delta.
  This is the path a serverless-only workspace can execute today.
* **Distributed path** (:func:`distributed_frame`): ``mapInPandas`` with
  **worker-level pipeline construction** — the pipeline is built once per worker
  process and reused across batches, never per row (`AGENTS.md` "avoid
  one-model-load-per-row"; `docs/07` anti-pattern section). The partition function
  itself (:func:`partition_processor`) is plain
  ``Iterator[pd.DataFrame] -> Iterator[pd.DataFrame]`` so its batching and init-once
  semantics are unit-tested in the default tier with no Spark anywhere.

The distributed path additionally requires the package to be importable on the
workers and the workers to start at all; the development workspace's serverless
channel currently fails the latter (ISOLATION_STARTUP_FAILURE — plan §8 F records
the incident and a databricks-marked test watches it).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pandas as pd

from pii_reduction.config.fingerprint import config_fingerprint
from pii_reduction.config.registries import DATABRICKS_DESTINATION_TYPES
from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.contracts.results import ProcessingStatus
from pii_reduction.databricks.errors import DatabricksError
from pii_reduction.databricks.output import DeltaTableOutput
from pii_reduction.databricks.source import SparkTableSource
from pii_reduction.processing.field_processor import AUDIT_COLUMNS
from pii_reduction.processing.pipeline import (
    RUN_ID_COLUMN,
    STATUS_COLUMN,
    Pipeline,
    build_pipeline,
)
from pii_reduction.sources.base import SourceDataset

__all__ = [
    "APPENDED_COLUMNS",
    "DistributedRun",
    "DriverRunResult",
    "distributed_frame",
    "partition_processor",
    "run_driver",
]


@dataclass(frozen=True)
class DriverRunResult:
    """What one driver-path run produced and where it landed."""

    run_id: str
    config_hash: str
    rows: int
    reduced_table: str
    audit_table: str
    metrics_table: str
    #: The reduced-only projection (ADR-0024), written only when the caller gave
    #: `reduced_only_prefix` — the artifact meant for a different grant boundary.
    reduced_only_table: str | None = None
    #: The run's own verdict, carried out of the driver so a *caller* can fail on it.
    #: Without these two a scheduled job (ADR-0025 rung 3) would see a completed
    #: write and report green, while `pii_status` inside the table said otherwise —
    #: the local CLI has exited 1 on this since R6 and the deployment target must
    #: not be the weaker signal.
    status: str = ProcessingStatus.SUCCESS.value
    fields_failed: int = 0


def _resolve_source_table(config: ResolvedDataset, source_table: str | None) -> str | None:
    """The table to read, or ``None`` when this dataset reads a file instead.

    Explicit argument first, then what the dataset config names (ADR-0025). The
    argument survives because tests and one-off runs legitimately point the same
    config at a throwaway table; configuration is the path a runbook uses.

    **A file source is not an error here.** A `csv` or `parquet` source is read by the
    ordinary local adapter, which on Databricks compute includes a Unity Catalog
    volume — a volume path is a filesystem path, which is the whole of runbook §6's
    claim. Refusing it made the Databricks front door unable to run the very config
    that section publishes; found by running the CLI as a job on 2026-08-21.
    """
    if source_table is not None:
        return source_table
    table = getattr(config.source, "table", None)
    return None if table is None else str(table)


def _resolve_destination(
    config: ResolvedDataset, destination_prefix: str | None, mode: str | None
) -> tuple[str, str]:
    """The ``catalog.schema`` to write under, and the write mode, in that order."""
    destination = config.destination
    configured_prefix = getattr(destination, "prefix", None)
    prefix = destination_prefix if destination_prefix is not None else configured_prefix
    if prefix is None:
        raise DatabricksError(
            f"dataset {config.dataset.name!r}: no destination prefix. Either pass "
            "destination_prefix=, or give the dataset a 'delta_table' destination "
            "with a catalog and schema (this dataset's destination type is "
            f"{destination.type!r}; see configs/datasets/databricks_table_example.yaml)"
        )
    if mode is not None:
        return str(prefix), mode
    # Only a Databricks destination's mode may reach the Delta writer. A local
    # `mode: overwrite` means "replace a file", which is cheap and reversible; the
    # same word against a Delta table replaces a governed dataset. Inheriting it
    # across that boundary would make a destructive write the *default* for any
    # config whose destination was written for local runs — refused here, so an
    # unconfigured run keeps `errorifexists` and overwriting stays deliberate.
    if destination.type in DATABRICKS_DESTINATION_TYPES:
        return str(prefix), str(destination.mode)
    return str(prefix), "errorifexists"


def _refuse_writing_over_the_source(
    table: str, prefix: str, base: str, reduced_only_prefix: str | None
) -> None:
    """Refuse a run whose output table is the table it reads (AGENTS.md rule 4).

    The driver reads with ``toPandas()`` and writes afterwards, so a target equal to
    the source under ``mode: overwrite`` would replace the original text with the
    reduced frame — destructive, and invisible until someone looks for the raw column.
    ``errorifexists`` already fails this closed by default; this refuses it under
    every mode, because "the default protects you" is not the same as "it cannot
    happen". Names only in the message — they are configuration values, not data.
    """
    targets = {f"{prefix}.{base}_{suffix}" for suffix in ("reduced", "pii_audit", "run_metrics")}
    if reduced_only_prefix is not None:
        targets.add(f"{reduced_only_prefix}.{base}_reduced_only")
    if table in targets:
        raise DatabricksError(
            f"dataset {base!r} would write over the table it reads ({table}): the "
            "reduced output must land somewhere other than the source. Give the "
            "destination a different catalog.schema, or rename the dataset"
        )


def run_driver(
    spark: Any,
    config: ResolvedDataset,
    *,
    source_table: str | None = None,
    destination_prefix: str | None = None,
    reduced_only_prefix: str | None = None,
    run_id: str | None = None,
    mode: str | None = None,
) -> DriverRunResult:
    """Read from a table, run the pipeline on the driver, write Delta tables.

    The pipeline call is byte-for-byte the local one — that is the parity claim, and
    the parity test holds an output-hash equality over it. Table names are built from
    the caller's configuration; nothing here knows a workspace.

    **Sources.** A ``spark_table`` source is read through Spark. A ``csv`` or
    ``parquet`` source is read by the ordinary local adapter — on Databricks compute
    that includes a Unity Catalog volume, so "upload a file and reduce it" needs no
    volume-aware code. The destination is Delta either way.

    **Where the names come from (ADR-0025).** ``source_table``, ``destination_prefix``
    and ``mode`` all default to what the dataset configuration names — a
    ``spark_table`` source and a ``delta_table`` destination — so a dataset YAML can
    name a Unity Catalog table end to end and a runbook needs no Python. An explicit
    argument still wins, which is what keeps the parity test able to point the
    committed config at a throwaway schema.

    ``reduced_only_prefix`` (ADR-0024) additionally writes the reduced-only
    projection — the frame without the configured raw text columns — to a
    *separate* ``catalog.schema``, which is what makes `docs/09`'s
    "reduced schema → broader analytics consumers" grant model realisable: the
    projection can live in a schema those consumers can read while the full
    frame, audit and metrics stay behind the operator boundary.
    """
    table = _resolve_source_table(config, source_table)
    prefix, write_mode = _resolve_destination(config, destination_prefix, mode)
    base = config.dataset.name
    if table is not None:
        _refuse_writing_over_the_source(table, prefix, base, reduced_only_prefix)

    pipeline = build_pipeline(config, run_id=run_id)
    # A table goes through Spark; a file goes through the same local adapter the
    # local runtime uses, which is what makes a `/Volumes/...` path work with no
    # volume-aware code anywhere (runbook §6).
    dataset = (
        SparkTableSource(spark, table, name=config.dataset.name).load()
        if table is not None
        else pipeline.load()
    )
    outcome = pipeline.process(dataset)

    output = DeltaTableOutput(spark, prefix, mode=write_mode)
    # `destination.projection` shapes the dataset artifact wherever it is written, so
    # a config that asks for reduced_only gets it on Databricks too — the local
    # `Pipeline.write` applies the same rule (ADR-0024). `reduced_only_prefix` is a
    # separate question: a second copy, for a different grant boundary.
    dataset_frame = (
        pipeline.reduced_only_projection(outcome.frame)
        if getattr(config.destination, "projection", "full") == "reduced_only"
        else outcome.frame
    )
    reduced = output.write(dataset_frame, name=f"{base}_reduced")
    reduced_only: str | None = None
    if reduced_only_prefix is not None:
        reduced_only = DeltaTableOutput(spark, reduced_only_prefix, mode=write_mode).write(
            pipeline.reduced_only_projection(outcome.frame), name=f"{base}_reduced_only"
        )
    audit = output.write(
        # Column set pinned whether or not anything was detected: an audit table
        # whose schema depends on the detection outcome breaks `append` reruns and
        # every reader downstream.
        pd.DataFrame(list(outcome.audit), columns=list(AUDIT_COLUMNS)),
        name=f"{base}_pii_audit",
    )
    metrics = output.write(
        # Flat names (`run_rows_read`), not dotted (`run.rows_read`): docs/07's
        # run-metrics schema is flat, and dotted columns force backticks into every
        # SQL query that ever reads the table.
        pd.json_normalize(outcome.metrics_payload(), sep="_"),
        name=f"{base}_run_metrics",
    )
    return DriverRunResult(
        run_id=outcome.run.run_id,
        config_hash=outcome.run.config_hash,
        rows=len(outcome.frame),
        reduced_table=reduced,
        audit_table=audit,
        metrics_table=metrics,
        reduced_only_table=reduced_only,
        status=outcome.run.status.value,
        fields_failed=outcome.run.fields_failed,
    )


#: Worker-level cache: one pipeline per (worker process, run, config). ``mapInPandas``
#: calls the partition function once per partition, and a worker handles many
#: partitions over a job — building the pipeline (and any NLP models behind it) once
#: per worker is the entire point of this cache (`docs/07` worker-level init).
_WORKER_PIPELINES: dict[str, Pipeline] = {}


def partition_processor(
    config_payload: dict[str, Any],
    run_id: str,
    *,
    pipeline_cache: dict[str, Pipeline] | None = None,
) -> Callable[[Iterator[pd.DataFrame]], Iterator[pd.DataFrame]]:
    """Build the ``Iterator[pd.DataFrame] -> Iterator[pd.DataFrame]`` function.

    ``config_payload`` is a plain ``ResolvedDataset.model_dump()`` dict rather than a
    pickled object: the payload crosses the driver-to-worker boundary, and a plain
    dict survives client/server library-version skew that a pickled pydantic instance
    would not.

    ``run_id`` is generated on the **driver**, once per logical run, and is part of
    the cache key. Without it every worker would mint its own id — one distributed
    run would stamp different ``pii_run_id`` values per partition — and a warm
    worker's cached pipeline would stamp a *previous* job's id onto a new one
    (`docs/01_ARCHITECTURE.md` idempotency strategy).

    ``pipeline_cache`` is injectable for the unit tests that assert init-once
    semantics; workers use the module-level cache.
    """
    cache = _WORKER_PIPELINES if pipeline_cache is None else pipeline_cache

    def process_partition(batches: Iterator[pd.DataFrame]) -> Iterator[pd.DataFrame]:
        config = ResolvedDataset.model_validate(config_payload)
        key = f"{run_id}:{config_fingerprint(config)}"
        pipeline = cache.get(key)
        if pipeline is None:
            pipeline = build_pipeline(config, run_id=run_id)
            cache[key] = pipeline
        for batch in batches:
            outcome = pipeline.process(
                SourceDataset(
                    name=config.dataset.name,
                    frame=batch,
                    source_type="spark_partition",
                    source_reference="mapInPandas",
                )
            )
            yield outcome.frame

    return process_partition


#: Columns ``Pipeline.process`` appends after the configured output columns, in
#: order. Declared once and asserted against the pipeline's actual output by a
#: default-tier test — order matters, because a positional mismatch between this
#: declaration and the pandas result would swap two string columns silently.
APPENDED_COLUMNS = (RUN_ID_COLUMN, STATUS_COLUMN)


@dataclass(frozen=True)
class DistributedRun:
    """The distributed plan: a transformed Spark frame, not yet materialised."""

    frame: Any
    output_schema: str
    run_id: str = ""


def distributed_frame(
    spark_frame: Any,
    config: ResolvedDataset,
    *,
    run_id: str | None = None,
) -> DistributedRun:
    """Wrap ``mapInPandas`` around :func:`partition_processor`.

    Returns the transformed (lazy) frame plus the run id stamped on every row; the
    caller decides where the frame lands.

    **This path ignores ``destination.projection``** (ADR-0024): it returns the
    processed frame, and the caller decides what to write. ``run_driver`` and the
    local ``Pipeline.write`` both apply the projection because both own the write;
    this function does not, so a config asking for ``reduced_only`` still gets every
    column here.

    **This path produces the reduced frame only.** Per-partition audit rows and run
    metrics are computed inside each worker's ``process`` call and discarded —
    fanning them out of ``mapInPandas`` alongside the data is a second output
    channel, a real design problem deliberately out of scope for v1 and recorded in
    plan §8 F. A run that needs the audit and metrics Delta tables uses
    :func:`run_driver`.
    """
    added = [policy.output_column for policy in config.columns]
    schema = ", ".join(
        [f"`{field.name}` {field.dataType.simpleString()}" for field in spark_frame.schema]
        + [f"`{name}` string" for name in [*added, *APPENDED_COLUMNS]]
    )
    chosen_run_id = run_id or uuid.uuid4().hex
    payload = config.model_dump(mode="json")
    transformed = spark_frame.mapInPandas(partition_processor(payload, chosen_run_id), schema)
    return DistributedRun(frame=transformed, output_schema=schema, run_id=chosen_run_id)

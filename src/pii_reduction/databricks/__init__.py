"""Databricks execution surface (Increment F, roadmap Phase 6).

The rule this package exists to satisfy is `AGENTS.md`'s "one implementation, two
runtimes": local and Databricks execution call the **same** ``build_pipeline`` and
``pipeline.process``. Everything here is adapter — where rows come from, where they
land, and where the per-partition function runs. No entity logic lives in this
package, and nothing outside it may import ``pyspark`` or ``databricks.connect``
(`docs/01_ARCHITECTURE.md`; ``tests/test_package.py`` imports this package in a
subprocess and asserts no optional runtime module was loaded).

Two execution paths, both shipped:

* :func:`~pii_reduction.databricks.runner.run_driver` — read a table through Spark,
  run the pipeline on the driver, write reduced/audit/metrics back as Delta. Works on
  any compute that can run SQL, including serverless-only workspaces.
* :func:`~pii_reduction.databricks.runner.distributed_frame` — the ``mapInPandas``
  path with worker-level pipeline construction. The partition function is plain
  ``Iterator[pd.DataFrame] -> Iterator[pd.DataFrame]`` and is unit-tested without
  Spark; the Spark wiring around it needs workers that can start a Python sandbox,
  which the development workspace's serverless channel currently cannot
  (ISOLATION_STARTUP_FAILURE, recorded in plan §8 F).

Requires the ``databricks`` extra in its own environment — Databricks Connect
couples client and server versions, so it deliberately does not share the core venv
(ADR-0006). Importing this package without the extra raises an actionable error at
first use, not at import (`docs/07` model-lifecycle rule applied to sessions).

Catalog, schema and table names come from configuration or environment only. Never
hard-code a workspace value (`AGENTS.md` hard rule; the privacy hook enforces it).
"""

from pii_reduction.databricks.errors import DatabricksError
from pii_reduction.databricks.output import DeltaTableOutput
from pii_reduction.databricks.runner import (
    DistributedRun,
    DriverRunResult,
    distributed_frame,
    partition_processor,
    run_driver,
)
from pii_reduction.databricks.session import get_session
from pii_reduction.databricks.source import SparkTableSource

__all__ = [
    "DatabricksError",
    "DeltaTableOutput",
    "DistributedRun",
    "DriverRunResult",
    "SparkTableSource",
    "distributed_frame",
    "get_session",
    "partition_processor",
    "run_driver",
]

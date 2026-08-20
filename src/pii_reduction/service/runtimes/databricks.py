"""The Databricks runtime — the one file in the service layer that may import the
Databricks surface.

`tests/test_package.py::test_nothing_outside_the_databricks_surface_imports_it`
exempts this exact relative path and asserts that it exists, so the exemption cannot
quietly widen into a blanket allowance if the file is renamed. Two things the
exemption does **not** cover, deliberately:

* `pyspark` and `databricks.connect` are still forbidden here — the Spark-name guard
  has no exemption at all. A session arrives from
  `pii_reduction.databricks.session.get_session`, which is the seam
  `pii-reduction-databricks` already uses, so this module never names Spark.
* Nothing else under `service/` may import this module's dependencies. Even a
  ``TYPE_CHECKING`` annotation naming ``DriverRunResult`` in another file would fail
  the guard, which walks the AST rather than the runtime imports — which is why the
  conversion to :class:`RunSummary` happens here and not in the store.

Requires the `databricks` extra, which lives in its own virtual environment
(ADR-0006). The service must therefore be started with this runtime only where that
environment is the one running it; :func:`databricks_runtime` fails at the first
session call rather than at import, which is what keeps `pii_reduction.service`
importable in a core install.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.databricks.runner import run_driver
from pii_reduction.databricks.session import get_session
from pii_reduction.service.models import RunSummary

__all__ = ["databricks_runtime"]


def databricks_runtime(
    profile: str | None = None,
    *,
    session_factory: Callable[..., Any] = get_session,
) -> Callable[[ResolvedDataset], RunSummary]:
    """Build the runtime callable.

    ``session_factory`` is injected for the same reason `databricks/cli.py` injects
    it: the wiring is then testable in the default tier against a fake session, with
    no workspace and no Spark.

    **No table or prefix is passed.** `run_driver` resolves both from the dataset
    configuration (ADR-0025), and the service must not offer the override arguments —
    a caller-named source or destination is the confused deputy `docs/09` forbids.
    """

    def run(config: ResolvedDataset) -> RunSummary:
        spark = session_factory(profile)
        result = run_driver(spark, config)
        outputs = {
            "reduced": result.reduced_table,
            "audit": result.audit_table,
            "metrics": result.metrics_table,
        }
        if result.reduced_only_table is not None:
            outputs["reduced_only"] = result.reduced_only_table
        return RunSummary(
            engine_run_id=result.run_id,
            config_hash=result.config_hash,
            status=result.status,
            rows_read=result.rows,
            rows_written=result.rows,
            # The driver result reports rows and failed fields; it does not carry
            # per-field or per-entity totals. `None` says so, where `0` would read as
            # "nothing was detected".
            fields_processed=None,
            fields_failed=result.fields_failed,
            entities_detected=None,
            entities_reduced=None,
            outputs=outputs,
        )

    return run

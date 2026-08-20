"""Execution runtimes the service can trigger: local, and the Databricks driver path.

One module per runtime, and the Databricks one is **not** imported here. That is the
whole reason this is a package rather than a module: `service/runtimes/databricks.py`
is the only file outside `databricks/` permitted to import the Databricks surface
(ADR-0026, pinned by `tests/test_package.py`), and importing it from this
``__init__`` would make every `pii_reduction.service` import reach for an optional
runtime that a core install does not have.

A runtime is a plain callable — ``ResolvedDataset -> RunSummary``. It converts the
engine's result to the service's own metadata model **at the boundary**, so the run
store never holds a ``ProcessingOutcome`` (which carries the source and reduced text)
or a ``DriverRunResult`` (whose type belongs to the Databricks surface).
"""

from __future__ import annotations

from collections.abc import Callable

from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.service.models import RunSummary

__all__ = ["Runtime"]

#: What the run trigger needs from an execution surface. A plain callable rather than
#: a ``Protocol``: there is exactly one method, nothing declares conformance
#: explicitly, and two names for one concept is how a type stops being read.
Runtime = Callable[[ResolvedDataset], RunSummary]

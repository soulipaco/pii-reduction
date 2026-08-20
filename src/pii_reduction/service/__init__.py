"""Rung 4: the service layer (ADR-0025's ladder, shaped by ADR-0026).

A thin HTTP API over the engine. It does three things — builds and validates a
dataset configuration, triggers a run, and reports run metadata — and it owns **no**
reduction logic: no detection, no reconciliation, no reduction, and no module here may
even import `providers/`, `reducers/`, `parsers/`, `language/`, `entities/`,
`evaluation/`, `sources/` or `outputs/`. A service that cannot name a provider cannot
quietly reimplement one, and a capability it needs that the engine lacks becomes a
change to the engine (`docs/01_ARCHITECTURE.md`, *Package dependency direction*).

The engine never learns this package exists: nothing in `pii_reduction` outside
`service/` may import it, which `tests/test_package.py` pins statically. That is
ADR-0025's rung rule, made checkable.

**`api` is deliberately not imported here.** It names FastAPI at module scope —
route decorators run at import time, so it cannot defer the way the Presidio adapter
defers its engine — and re-exporting it would make `pii_reduction.service`
un-importable in a core install. Import it explicitly:

```python
from pii_reduction.service.api import create_app
```

The same applies to `runtimes.databricks`, the one file permitted to import the
Databricks surface.
"""

from __future__ import annotations

from pii_reduction.service.builder import BuiltConfig, build_dataset_config
from pii_reduction.service.catalog import describe_dataset, list_dataset_names, load_dataset
from pii_reduction.service.errors import (
    InvalidRequestError,
    RunNotFoundError,
    RuntimeUnavailableError,
    ServiceError,
    UnknownDatasetError,
    UnknownTemplateError,
)
from pii_reduction.service.runs import RunStore
from pii_reduction.service.templates import DatasetTemplate, load_templates

__all__ = [
    "BuiltConfig",
    "DatasetTemplate",
    "InvalidRequestError",
    "RunNotFoundError",
    "RunStore",
    "RuntimeUnavailableError",
    "ServiceError",
    "UnknownDatasetError",
    "UnknownTemplateError",
    "build_dataset_config",
    "describe_dataset",
    "list_dataset_names",
    "load_dataset",
    "load_templates",
]

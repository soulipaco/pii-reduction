"""Databricks adapter errors."""

from __future__ import annotations

from typing import Any

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["DatabricksError", "require_spark_session"]

_INSTALL_HINT = (
    "Databricks Connect is not installed in this environment. It couples client and "
    "server versions, so it lives in its own venv rather than the core one "
    "(ADR-0006):\n"
    "  uv venv .venv-dbx --python 3.12\n"
    '  VIRTUAL_ENV=.venv-dbx uv pip install -e ".[databricks]"\n'
    "and authenticate with whichever route your workspace permits: a CLI profile, "
    "DATABRICKS_HOST plus a token or service principal, or nothing at all when "
    "running on Databricks compute — never a hard-coded host (AGENTS.md rule 1)."
)


class DatabricksError(PiiReductionError):
    """A Databricks session, table, or write could not be handled."""


def require_spark_session() -> Any:
    """Import ``DatabricksSession`` lazily, with an actionable error when absent.

    Lazy so that importing :mod:`pii_reduction.databricks` never drags ``pyspark``
    into a core environment — ``tests/test_package.py`` asserts exactly that in a
    subprocess, and this function is the single crossing point.
    """
    try:
        from databricks.connect import DatabricksSession
    except ImportError as error:  # pragma: no cover - exercised only without the extra
        raise DatabricksError(_INSTALL_HINT) from error
    return DatabricksSession

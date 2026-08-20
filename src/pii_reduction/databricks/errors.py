"""Databricks adapter errors."""

from __future__ import annotations

from typing import Any

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["DatabricksError", "error_label", "require_spark_session"]


def error_label(error: Exception) -> str:
    """``ClassName: CONDITION`` when Spark offers a condition, else the class alone.

    The class name alone is privacy-safe but nearly useless: this session lost an
    afternoon to ``could not write <table> (PySparkValueError)`` whose real cause was
    ``[UNSUPPORTED_OPERATION] errorifexists is not supported``. Spark's *condition* —
    ``UNSUPPORTED_OPERATION``, ``TABLE_OR_VIEW_ALREADY_EXISTS`` — is a fixed
    identifier from a published list, carries no data by construction, and is the one
    token that turns such an investigation into a one-line read.

    The message itself is still never included: Connect messages can quote the
    workspace URL, and a Spark analysis error can quote a value (`AGENTS.md` rules 1
    and 8). Anything unexpected from the getter is swallowed — a diagnostic aid must
    not become a second failure.
    """
    for attribute in ("getCondition", "getErrorClass"):
        getter = getattr(error, attribute, None)
        if not callable(getter):
            continue
        try:
            condition = getter()
        except Exception:
            continue
        if isinstance(condition, str) and condition:
            return f"{error.__class__.__name__}: {condition}"
    return error.__class__.__name__


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

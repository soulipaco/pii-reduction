"""Session construction: profile and environment only, never a hard-coded host."""

from __future__ import annotations

import os
from typing import Any

from pii_reduction.databricks.errors import DatabricksError, require_spark_session

__all__ = ["get_session"]

PROFILE_ENV = "DATABRICKS_CONFIG_PROFILE"
SERVERLESS_ENV = "DATABRICKS_SERVERLESS_COMPUTE_ID"


def get_session(profile: str | None = None, *, serverless: bool = True) -> Any:
    """A ``DatabricksSession`` from a named CLI profile.

    ``profile`` falls back to ``DATABRICKS_CONFIG_PROFILE``; there is deliberately no
    host or token parameter — credentials come from the CLI's auth store, and a
    function signature that accepted them would invite committing one
    (`AGENTS.md` rule 1).

    ``serverless=True`` targets serverless compute, which is the only compute a
    serverless-only workspace has. The environment variable route is used rather
    than a builder API so the same code works across the Connect client generations
    the dedicated venv may hold (15.x and 16.x behave differently here).
    """
    chosen = profile or os.environ.get(PROFILE_ENV)
    if not chosen:
        raise DatabricksError(
            "no Databricks profile named: pass profile= or set "
            f"{PROFILE_ENV}. Profiles are listed by `databricks auth profiles`"
        )
    os.environ[PROFILE_ENV] = chosen
    if serverless:
        os.environ.setdefault(SERVERLESS_ENV, "auto")
    session_builder = require_spark_session().builder
    return session_builder.getOrCreate()

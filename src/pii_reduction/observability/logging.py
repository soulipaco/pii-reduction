"""Privacy-safe logging helpers.

``AGENTS.md`` rule 8: logs may carry dataset name, row id, parser, provider,
language, entity counts, timing and error categories — never source text or a
detected value. The library therefore logs *fields*, never free text, and the helper
below is the only way this package builds a log record.

Nothing here configures the root logger: applications own logging configuration. The
library only attaches a ``NullHandler`` so importing it is silent.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["LOGGER_NAME", "get_logger", "safe_fields"]

LOGGER_NAME = "pii_reduction"

#: Field names that may appear in a log record. Anything else is dropped rather
#: than trusted, so a future caller cannot quietly start logging text.
ALLOWED_FIELDS = frozenset(
    {
        "dataset",
        "row_id",
        "run_id",
        "column",
        "output_column",
        "parser",
        "provider",
        "providers",
        "reducer",
        "language",
        "status",
        "error_category",
        "entities_detected",
        "entities_reduced",
        "rows",
        #: Run records recovered from a durable journal at service startup. Its own
        #: key rather than `rows_read`, which means rows of *source data* everywhere
        #: else — an operator aggregating throughput must not silently mix the two.
        "runs_recovered",
        "rows_read",
        "rows_written",
        "fields_processed",
        "fields_failed",
        "fallbacks",
        "duration_ms",
        "destination",
        "config_hash",
    }
)

logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


def safe_fields(**fields: Any) -> str:
    """Render allowed fields as ``key=value`` pairs, dropping anything unlisted."""
    parts = []
    for key in sorted(fields):
        if key not in ALLOWED_FIELDS:
            continue
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)

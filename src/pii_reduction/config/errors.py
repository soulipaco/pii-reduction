"""Configuration errors.

``docs/06_CONFIGURATION_CONTRACT.md`` is explicit that these must be actionable:
``KeyError: parser`` is a bug report, ``dataset 'demo_chat', column 'transcript':
parser 'conversation_v9' is not registered`` is a fix.
"""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["ConfigurationError", "config_context"]


class ConfigurationError(PiiReductionError):
    """Configuration is missing, malformed, or references something that does not exist."""


def config_context(
    *,
    path: str | None = None,
    dataset: str | None = None,
    column: str | None = None,
) -> str:
    """Build the ``file 'x', dataset 'y', column 'z': `` prefix used by every message."""
    parts = []
    if path is not None:
        parts.append(f"file {path!r}")
    if dataset is not None:
        parts.append(f"dataset {dataset!r}")
    if column is not None:
        parts.append(f"column {column!r}")
    return f"{', '.join(parts)}: " if parts else ""

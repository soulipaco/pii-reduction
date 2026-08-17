"""Provider errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["ProviderError", "ProviderNotAvailableError"]


class ProviderError(PiiReductionError):
    """A provider is misconfigured or violated the detection contract."""


class ProviderNotAvailableError(ProviderError):
    """A provider's optional dependency or model is not installed.

    Raised with the exact install command; nothing ever auto-downloads a model
    (``docs/07_DATABRICKS_RUNTIME.md`` model-lifecycle rule, ADR-0008).
    """

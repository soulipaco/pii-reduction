"""Shared model configuration for the core contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["FrozenModel"]


class FrozenModel(BaseModel):
    """Immutable, strictly-validated base for every core contract object.

    ``extra="forbid"`` matters here: a provider adapter that invents a field name
    should fail loudly rather than smuggle provider-specific state through the
    normalized contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

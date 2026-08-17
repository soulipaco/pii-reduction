"""Taxonomy errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["LabelMappingError", "UnknownEntityLabelError"]


class UnknownEntityLabelError(PiiReductionError):
    """A label is not part of the normalized taxonomy."""


class LabelMappingError(PiiReductionError):
    """A provider label-mapping table is inconsistent or targets an unknown label."""

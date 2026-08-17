"""Reduction strategies: redact, mask, deterministic pseudonymization."""

from pii_reduction.reducers.base import BaseReducer, Reducer, ReductionResult
from pii_reduction.reducers.errors import PseudonymizationKeyError, ReducerError
from pii_reduction.reducers.mask import MaskReducer
from pii_reduction.reducers.pseudonymize import PseudonymizeReducer
from pii_reduction.reducers.redact import RedactReducer
from pii_reduction.reducers.registry import available_reducers, build_reducer

__all__ = [
    "BaseReducer",
    "MaskReducer",
    "PseudonymizationKeyError",
    "PseudonymizeReducer",
    "RedactReducer",
    "Reducer",
    "ReducerError",
    "ReductionResult",
    "available_reducers",
    "build_reducer",
]

"""Reducer errors."""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = ["PseudonymizationKeyError", "ReducerError"]


class ReducerError(PiiReductionError):
    """A reducer is misconfigured or was given unresolved spans."""


class PseudonymizationKeyError(ReducerError):
    """The pseudonymization key is missing.

    The key is read from the environment and never from configuration or a default
    (``docs/06_CONFIGURATION_CONTRACT.md``: "Do not place secret keys in YAML").
    The message names the variable; it never reports whether a value looked valid.
    """

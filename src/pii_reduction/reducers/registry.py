"""Reducer construction by configured name.

A test pins this to ``config.registries.KNOWN_REDUCERS``, so a strategy cannot be
configurable without being constructible.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pii_reduction.reducers.base import BaseReducer
from pii_reduction.reducers.errors import ReducerError
from pii_reduction.reducers.mask import MaskReducer
from pii_reduction.reducers.pseudonymize import PseudonymizeReducer
from pii_reduction.reducers.redact import RedactReducer

__all__ = ["available_reducers", "build_reducer"]


def available_reducers() -> frozenset[str]:
    return frozenset({RedactReducer.name, MaskReducer.name, PseudonymizeReducer.name})


def build_reducer(
    name: str,
    options: dict[str, Any] | None = None,
    *,
    replacements: Mapping[str, str] | None = None,
    scope_value: str | None = None,
) -> BaseReducer:
    """Construct a reducer by registry name.

    ``replacements`` (effective entity configuration) is used by ``redact``;
    ``scope_value`` (dataset or project name) is used by ``pseudonymize``. Passing
    both is harmless — each strategy takes what it needs.
    """
    if name == RedactReducer.name:
        return RedactReducer(options, replacements=replacements)
    if name == MaskReducer.name:
        return MaskReducer(options)
    if name == PseudonymizeReducer.name:
        return PseudonymizeReducer(options, scope_value=scope_value)
    raise ReducerError(
        f"reducer {name!r} is not registered (known: {', '.join(sorted(available_reducers()))})"
    )

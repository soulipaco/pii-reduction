"""Redaction: replace the span with its entity label.

The default portfolio behavior (``docs/04_PII_ENGINE.md``): safe, obvious in demos,
trivial to validate, and the only strategy that never needs the matched value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.entities.taxonomy import TAXONOMY, default_replacement, is_known
from pii_reduction.reducers.base import BaseReducer
from pii_reduction.reducers.errors import ReducerError

__all__ = ["RedactReducer"]


class RedactReducer(BaseReducer):
    """``Maria Rossi`` becomes ``<PERSON>``."""

    name = "redact"

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        *,
        replacements: Mapping[str, str] | None = None,
    ) -> None:
        if options:
            raise ReducerError(
                f"reducer {self.name!r}: unknown options {', '.join(sorted(options))} "
                "(replacements are configured under 'entities', not here)"
            )
        self._replacements = dict(replacements or {})
        for label in self._replacements:
            if not is_known(label):
                raise ReducerError(
                    f"reducer {self.name!r}: replacement configured for unknown entity "
                    f"{label!r} (known: {', '.join(sorted(TAXONOMY))})"
                )

    def _replacement(self, entity: ResolvedEntity, surface: str) -> str:
        configured = self._replacements.get(entity.entity_type)
        if configured is not None:
            return configured
        if is_known(entity.entity_type):
            return default_replacement(entity.entity_type)
        return f"<{entity.entity_type}>"

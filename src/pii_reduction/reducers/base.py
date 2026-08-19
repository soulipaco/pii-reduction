"""Reducer protocol and the shared right-to-left replacement loop.

Detection decides *what* is sensitive; a reducer decides how it is rendered
(``docs/01_ARCHITECTURE.md`` layer 7). Keeping them apart is what lets redaction,
masking and pseudonymization be swapped by configuration without touching detection.

The signature is deliberately ``reduce(text, entities)`` rather than
``replacement_for(entity)``: masking and pseudonymization need the matched surface
string, and only a reducer that receives the text can produce ``ma***@example.com``
or a stable token. The surface is given to ``_replacement`` and goes nowhere else —
``ReductionOperation`` records offsets, label, replacement and strategy, never the
original value (``docs/03_DATA_CONTRACTS.md`` §8).

Replacements are applied from the highest offset down, so earlier spans keep their
original coordinates while the string is rewritten (``docs/04_PII_ENGINE.md``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pii_reduction.contracts.base import FrozenModel
from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.contracts.reduction import ReductionOperation
from pii_reduction.reducers.errors import ReducerError

__all__ = ["BaseReducer", "Reducer", "ReductionResult"]


class ReductionResult(FrozenModel):
    """Reduced text plus the audit trail of what was replaced."""

    text: str
    operations: tuple[ReductionOperation, ...] = ()

    @property
    def entity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for operation in self.operations:
            counts[operation.entity_type] = counts.get(operation.entity_type, 0) + 1
        return counts


@runtime_checkable
class Reducer(Protocol):
    @property
    def name(self) -> str: ...

    def reduce(self, text: str, entities: Sequence[ResolvedEntity]) -> ReductionResult: ...


class BaseReducer(ABC):
    """Shared span replacement. Subclasses only decide what a span becomes."""

    #: Registry name, matching ``config.registries.KNOWN_REDUCERS``.
    name: str = ""

    #: Non-secret identifier of the key a keyed reducer derives its output from,
    #: for run provenance (``RunMetadata.pseudonymization_key_id``). ``None`` for
    #: unkeyed reducers. Declared on the base so the pipeline reads a contract
    #: attribute rather than duck-typing one reducer's internals — a future keyed
    #: reducer that skips it loses provenance visibly (the field stays null), not
    #: by attribute-name accident.
    key_id: str | None = None

    @abstractmethod
    def _replacement(self, entity: ResolvedEntity, surface: str) -> str:
        """Rendering for one approved span. ``surface`` is the matched text."""

    def reduce(self, text: str, entities: Sequence[ResolvedEntity]) -> ReductionResult:
        """Apply every approved span, right to left, and record the operations."""
        if not isinstance(text, str):
            raise ReducerError(
                f"reducer {self.name!r}: reduce() requires str, got {type(text).__name__}"
            )

        ordered = sorted(entities, key=lambda entity: (entity.start, entity.end))
        self._check_spans(ordered, text=text)

        reduced = text
        operations: list[ReductionOperation] = []
        for entity in reversed(ordered):
            surface = text[entity.start : entity.end]
            replacement = self._replacement(entity, surface)
            reduced = reduced[: entity.start] + replacement + reduced[entity.end :]
            operations.append(
                ReductionOperation(
                    start=entity.start,
                    end=entity.end,
                    entity_type=entity.entity_type,
                    replacement=replacement,
                    strategy=self.name,
                )
            )

        operations.reverse()
        return ReductionResult(text=reduced, operations=tuple(operations))

    def _check_spans(self, ordered: Sequence[ResolvedEntity], *, text: str) -> None:
        previous: ResolvedEntity | None = None
        for entity in ordered:
            if not entity.is_within(text):
                raise ReducerError(
                    f"reducer {self.name!r}: span [{entity.start}, {entity.end}) exceeds text "
                    f"of length {len(text)}"
                )
            if previous is not None and entity.start < previous.end:
                raise ReducerError(
                    f"reducer {self.name!r}: spans [{previous.start}, {previous.end}) and "
                    f"[{entity.start}, {entity.end}) overlap; reconcile candidates before "
                    "reducing"
                )
            previous = entity

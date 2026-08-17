"""Entity contracts (``docs/03_DATA_CONTRACTS.md`` §6 and §7).

``EntityMatch`` is what every provider returns after normalizing its own labels
(ADR-0004): provider-native strings such as ``PER`` or ``EMAIL_ADDRESS`` never reach
this object. ``ResolvedEntity`` is what the reconciler produces, carrying the
provenance of the decision.

Neither object stores the matched text. The surface string is available from the
source text when genuinely needed; keeping it out of the contract is what makes
audit tables and logs privacy-safe by default (``AGENTS.md`` rule 8).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from pii_reduction.contracts.labels import NormalizedLabel
from pii_reduction.contracts.spans import Span

__all__ = ["EntityMatch", "ResolvedEntity"]


class EntityMatch(Span):
    """A candidate entity span from one provider.

    ``score`` semantics are provider-defined and are never comparable across
    providers (``docs/04_PII_ENGINE.md``; ADR-0005). ``None`` means the provider
    does not express confidence at all.
    """

    entity_type: NormalizedLabel
    score: float | None = None
    provider: str = Field(min_length=1)
    recognizer: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResolvedEntity(Span):
    """A span accepted by the reconciler, with the evidence behind it."""

    entity_type: NormalizedLabel
    score: float | None = None
    selected_provider: str = Field(min_length=1)
    supporting_matches: tuple[EntityMatch, ...] = ()
    resolution_rule: str = Field(min_length=1)

    @classmethod
    def from_match(cls, match: EntityMatch, *, resolution_rule: str) -> ResolvedEntity:
        """Promote a single winning match, keeping it as its own supporting evidence."""
        return cls(
            start=match.start,
            end=match.end,
            entity_type=match.entity_type,
            score=match.score,
            selected_provider=match.provider,
            supporting_matches=(match,),
            resolution_rule=resolution_rule,
        )

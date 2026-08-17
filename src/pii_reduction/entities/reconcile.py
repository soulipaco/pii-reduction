"""Deterministic overlap resolution (``docs/04_PII_ENGINE.md``).

Overlaps are inevitable once more than one recognizer runs: ``john.smith@example.com``
is one EMAIL to a pattern matcher and two PERSON fragments to an NER model. Mutating
text from unresolved candidates would corrupt it, so every candidate passes through
here first.

The algorithm is the documented seven steps: drop invalid spans, apply per-provider
per-entity minimum scores, order by entity priority then score then span length then
provider order, accept greedily while non-overlapping, and record what was rejected
and why. Scores are never compared *across* providers (ADR-0005) — entity priority
and provider order decide those cases, and score only breaks ties within one provider.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from pii_reduction.contracts.entities import EntityMatch, ResolvedEntity
from pii_reduction.entities.taxonomy import TAXONOMY, default_priority

__all__ = [
    "DEFAULT_POLICY_NAME",
    "ReconciliationPolicy",
    "ReconciliationResult",
    "RejectedMatch",
    "reconcile",
]

DEFAULT_POLICY_NAME = "priority_score_length"

REASON_BELOW_THRESHOLD = "below_threshold"
REASON_OVERLAP = "overlap"
REASON_OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class RejectedMatch:
    """A candidate that lost, for debug metrics. Carries no text."""

    entity_type: str
    start: int
    end: int
    provider: str
    reason: str


@dataclass(frozen=True)
class ReconciliationPolicy:
    """Configurable resolution policy.

    ``priorities`` come from the effective entity configuration (taxonomy defaults
    unless a project overrides them). ``provider_order`` is the chain order: earlier
    providers win ties. ``thresholds`` are per provider and per entity — never global
    (ADR-0005).
    """

    priorities: Mapping[str, int] = field(default_factory=dict)
    provider_order: tuple[str, ...] = ()
    thresholds: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    entities: frozenset[str] | None = None
    name: str = DEFAULT_POLICY_NAME

    def priority_of(self, entity_type: str) -> int:
        if entity_type in self.priorities:
            return self.priorities[entity_type]
        if entity_type in TAXONOMY:
            return default_priority(entity_type)
        return 0

    def provider_rank(self, provider: str) -> int:
        try:
            return self.provider_order.index(provider)
        except ValueError:
            return len(self.provider_order)

    def threshold_for(self, provider: str, entity_type: str) -> float | None:
        return self.thresholds.get(provider, {}).get(entity_type)


@dataclass(frozen=True)
class ReconciliationResult:
    entities: tuple[ResolvedEntity, ...] = ()
    rejected: tuple[RejectedMatch, ...] = ()

    def rejection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.rejected:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts


def reconcile(
    matches: Iterable[EntityMatch],
    *,
    policy: ReconciliationPolicy | None = None,
) -> ReconciliationResult:
    """Resolve candidate matches into non-overlapping approved spans."""
    active = policy or ReconciliationPolicy()

    survivors: list[EntityMatch] = []
    rejected: list[RejectedMatch] = []
    for match in matches:
        if active.entities is not None and match.entity_type not in active.entities:
            rejected.append(_reject(match, REASON_OUT_OF_SCOPE))
            continue
        threshold = active.threshold_for(match.provider, match.entity_type)
        if threshold is not None and match.score is not None and match.score < threshold:
            rejected.append(_reject(match, REASON_BELOW_THRESHOLD))
            continue
        survivors.append(match)

    ordered = sorted(survivors, key=lambda match: _sort_key(match, active))

    accepted: list[tuple[EntityMatch, list[EntityMatch]]] = []
    for candidate in ordered:
        duplicate = _find_identical(accepted, candidate)
        if duplicate is not None:
            duplicate.append(candidate)
            continue
        if any(candidate.overlaps(winner) for winner, _ in accepted):
            rejected.append(_reject(candidate, REASON_OVERLAP))
            continue
        accepted.append((candidate, [candidate]))

    resolved = tuple(
        sorted(
            (
                ResolvedEntity(
                    start=winner.start,
                    end=winner.end,
                    entity_type=winner.entity_type,
                    score=winner.score,
                    selected_provider=winner.provider,
                    supporting_matches=tuple(supporting),
                    resolution_rule=active.name,
                )
                for winner, supporting in accepted
            ),
            key=lambda entity: (entity.start, entity.end),
        )
    )
    return ReconciliationResult(entities=resolved, rejected=tuple(rejected))


def _sort_key(match: EntityMatch, policy: ReconciliationPolicy) -> tuple[int, float, int, int, int]:
    """Highest entity priority first, then score, then longer span, then chain order."""
    return (
        -policy.priority_of(match.entity_type),
        -(match.score if match.score is not None else -1.0),
        -(match.end - match.start),
        policy.provider_rank(match.provider),
        match.start,
    )


def _find_identical(
    accepted: Sequence[tuple[EntityMatch, list[EntityMatch]]], candidate: EntityMatch
) -> list[EntityMatch] | None:
    """A second provider agreeing exactly is corroboration, not a conflict."""
    for winner, supporting in accepted:
        if (winner.start, winner.end, winner.entity_type) == (
            candidate.start,
            candidate.end,
            candidate.entity_type,
        ):
            return supporting
    return None


def _reject(match: EntityMatch, reason: str) -> RejectedMatch:
    return RejectedMatch(
        entity_type=match.entity_type,
        start=match.start,
        end=match.end,
        provider=match.provider,
        reason=reason,
    )

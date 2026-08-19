"""Referential consistency of deterministic pseudonymization, measured.

Pseudonymization's pitch is linkage without identity: the same value always maps
to the same token, and distinct values map to distinct tokens, so counts, joins
and group-bys on reduced data have the same cardinality structure as on the
originals. Until session 9 that property was implemented and asserted but never
measured (`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md`, D5); this module is the
measurement.

Inputs are ``(entity_type, value, token)`` observations gathered by a caller
that can pair a ground-truth value with the token that replaced it (the corpus
measurement pairs manifest entities with reduced-text tokens positionally).
Values are held in memory only and never leave this function — the result
carries counts and rates, no surfaces and no tokens.

Deliberately **not** re-exported from ``evaluation/__init__`` and deliberately
not a ``*Metric`` peer of the benchmark's rows: ``run_benchmark`` cannot compute
it (the pipeline outcome does not retain per-operation replacements), so it is a
test-tier measurement driven by ``tests/test_referential_consistency.py``, which
pins the published numbers. Promote it to the benchmark surface only if a caller
outside the tests appears.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["ConsistencyResult", "referential_consistency"]


@dataclass(frozen=True)
class ConsistencyResult:
    """Counts only — no value and no token survives into this object."""

    entity_type: str
    #: Observations seen (occurrences, not distinct values).
    occurrences: int
    distinct_values: int
    distinct_tokens: int
    #: Values that were seen with more than one token — broken consistency.
    inconsistent_values: int
    #: Tokens that covered more than one value — merged identities.
    merged_tokens: int

    @property
    def consistency_rate(self) -> float:
        """Fraction of distinct values whose occurrences all share one token."""
        if self.distinct_values == 0:
            return 0.0
        return (self.distinct_values - self.inconsistent_values) / self.distinct_values

    @property
    def distinctness_rate(self) -> float:
        """Fraction of distinct tokens that stand for exactly one value."""
        if self.distinct_tokens == 0:
            return 0.0
        return (self.distinct_tokens - self.merged_tokens) / self.distinct_tokens


def referential_consistency(
    observations: Iterable[tuple[str, str, str]],
) -> tuple[ConsistencyResult, ...]:
    """Measure value↔token structure per entity type.

    ``observations`` are ``(entity_type, value, token)`` triples, one per entity
    occurrence. Both failure directions are counted separately because they harm
    differently: an *inconsistent value* (one value, several tokens) silently
    splits one subject across join keys; a *merged token* (several values, one
    token) silently fuses two subjects — the failure the reducer's in-process
    collision check exists to catch, which no cross-process check can
    (``reducers/pseudonymize.py``).
    """
    value_tokens: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    token_values: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    occurrences: dict[str, int] = defaultdict(int)

    for entity_type, value, token in observations:
        occurrences[entity_type] += 1
        value_tokens[entity_type][value].add(token)
        token_values[entity_type][token].add(value)

    results = []
    for entity_type in sorted(occurrences):
        values = value_tokens[entity_type]
        tokens = token_values[entity_type]
        results.append(
            ConsistencyResult(
                entity_type=entity_type,
                occurrences=occurrences[entity_type],
                distinct_values=len(values),
                distinct_tokens=len(tokens),
                inconsistent_values=sum(1 for seen in values.values() if len(seen) > 1),
                merged_tokens=sum(1 for seen in tokens.values() if len(seen) > 1),
            )
        )
    return tuple(results)

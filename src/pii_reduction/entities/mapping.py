"""Label-normalization machinery shared by provider adapters (ADR-0004).

The *tables* live with their providers — ``EMAIL_ADDRESS -> EMAIL`` is a fact about
Presidio, ``PER -> PERSON`` is a fact about German spaCy — so provider-native label
strings never leave ``providers/``. What lives here is the mechanism they all use:
validate the table against the taxonomy once, translate labels, and count everything
that gets dropped so silent coverage loss shows up in run metrics instead of
disappearing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from pii_reduction.entities.errors import LabelMappingError
from pii_reduction.entities.taxonomy import is_known, known_labels

__all__ = ["DropCounter", "LabelMapping"]


@dataclass
class DropCounter:
    """Counts native labels a provider discarded, split by reason.

    ``declared`` are labels the adapter deliberately drops (Presidio's ``URL``,
    which produces partial-match noise; ``LOCATION``, which is not ADDRESS —
    ADR-0002/ADR-0004). ``unmapped`` are labels nobody accounted for, which is the
    signal that a provider version changed under us.
    """

    declared: Counter[str] = field(default_factory=Counter)
    unmapped: Counter[str] = field(default_factory=Counter)

    def record_declared(self, provider: str, native_label: str) -> None:
        self.declared[f"{provider}:{native_label}"] += 1

    def record_unmapped(self, provider: str, native_label: str) -> None:
        self.unmapped[f"{provider}:{native_label}"] += 1

    def as_dict(self) -> dict[str, int]:
        """Flat counts for run metrics: ``{"presidio:URL": 3, ...}``."""
        return {**dict(self.declared), **dict(self.unmapped)}

    @property
    def total(self) -> int:
        return sum(self.declared.values()) + sum(self.unmapped.values())


@dataclass(frozen=True)
class LabelMapping:
    """A provider's native-label table, validated against the taxonomy.

    ``table`` maps native label to normalized label. ``dropped`` lists native labels
    the adapter intentionally discards. A label in neither is *unmapped*: it is
    dropped too, but counted separately.
    """

    provider: str
    table: Mapping[str, str]
    dropped: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.provider:
            raise LabelMappingError("label mapping requires a provider name")
        unknown = sorted({v for v in self.table.values() if not is_known(v)})
        if unknown:
            raise LabelMappingError(
                f"provider {self.provider!r}: mapping targets are not in the taxonomy: "
                f"{', '.join(unknown)} (known: {', '.join(sorted(known_labels()))})"
            )
        both = sorted(set(self.table) & set(self.dropped))
        if both:
            raise LabelMappingError(
                f"provider {self.provider!r}: native labels are both mapped and dropped: "
                f"{', '.join(both)}"
            )

    def normalize(self, native_label: str, *, counter: DropCounter | None = None) -> str | None:
        """Translate one native label; ``None`` means the label is dropped."""
        normalized = self.table.get(native_label)
        if normalized is not None:
            return normalized
        if counter is not None:
            if native_label in self.dropped:
                counter.record_declared(self.provider, native_label)
            else:
                counter.record_unmapped(self.provider, native_label)
        return None

    def supported_entities(self) -> frozenset[str]:
        """Normalized labels this provider can produce."""
        return frozenset(self.table.values())

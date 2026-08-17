"""Masking: keep some structure, remove the identifying part.

Useful when downstream readers need to see *that* there was an email, or need the
last digits to reconcile a case, without seeing who it was
(``docs/04_PII_ENGINE.md``; rules per entity per ``docs/06``).

Masking is not redaction with extra steps, and two consequences deserve to be
explicit:

* **A masked value is still partly the original.** ``ma***@example.com`` keeps the
  domain and two characters. Masking is a de-identification aid, not a guarantee,
  and the benchmark's leakage metric has to be read per strategy (ADR-0013).
* **Masked output can look like PII again.** ``ma***@example.com`` still matches the
  EMAIL pattern, so re-running detection over reduced text finds it a second time.
  Reduction is idempotent in the sense that matters — running the *pipeline* twice
  on the same source gives the same output — but the redactor must not be pointed at
  its own output (``docs/10_TESTING_QA.md`` §10).
"""

from __future__ import annotations

from typing import Any

from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.entities.taxonomy import ADDRESS, EMAIL, PERSON, PHONE, TAXONOMY, is_known
from pii_reduction.reducers.base import BaseReducer
from pii_reduction.reducers.errors import ReducerError

__all__ = ["MASK_RULES", "MaskReducer"]

RULE_FULL = "full"
RULE_LAST4 = "last4"
RULE_PARTIAL_EMAIL = "partial_email"

MASK_RULES = frozenset({RULE_FULL, RULE_LAST4, RULE_PARTIAL_EMAIL})

DEFAULT_RULES: dict[str, str] = {
    EMAIL: RULE_PARTIAL_EMAIL,
    PHONE: RULE_LAST4,
    PERSON: RULE_FULL,
    ADDRESS: RULE_FULL,
}

DEFAULT_OPTIONS: dict[str, Any] = {
    "rules": DEFAULT_RULES,
    "mask_char": "*",
    #: Characters kept by ``last4``.
    "keep_last": 4,
    #: Characters of the local part kept by ``partial_email``.
    "keep_local": 2,
}


class MaskReducer(BaseReducer):
    """Per-entity masking rules."""

    name = "mask"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ReducerError(
                f"reducer {self.name!r}: unknown options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        rules = dict(DEFAULT_RULES)
        configured = merged["rules"]
        if not isinstance(configured, dict):
            raise ReducerError(
                f"reducer {self.name!r}: rules must be a mapping of entity to rule, "
                "e.g. {EMAIL: partial_email}"
            )
        for label, rule in configured.items():
            if not is_known(label):
                raise ReducerError(
                    f"reducer {self.name!r}: rule configured for unknown entity {label!r} "
                    f"(known: {', '.join(sorted(TAXONOMY))})"
                )
            if rule not in MASK_RULES:
                raise ReducerError(
                    f"reducer {self.name!r}: entity {label}: mask rule {rule!r} is not "
                    f"supported (known: {', '.join(sorted(MASK_RULES))})"
                )
            rules[label] = rule

        mask_char = merged["mask_char"]
        if not isinstance(mask_char, str) or len(mask_char) != 1:
            raise ReducerError(f"reducer {self.name!r}: mask_char must be a single character")

        self.options = merged
        self._rules = rules
        self._mask_char = mask_char
        self._keep_last = int(merged["keep_last"])
        self._keep_local = int(merged["keep_local"])
        if self._keep_last < 0 or self._keep_local < 0:
            raise ReducerError(f"reducer {self.name!r}: keep_last and keep_local must be >= 0")

    def _replacement(self, entity: ResolvedEntity, surface: str) -> str:
        rule = self._rules.get(entity.entity_type, RULE_FULL)
        if rule == RULE_PARTIAL_EMAIL:
            return self._partial_email(surface)
        if rule == RULE_LAST4:
            return self._last_n(surface, self._keep_last)
        return self._full(surface)

    def _full(self, surface: str) -> str:
        """Mask every character, preserving whitespace so line shape survives."""
        return "".join(
            character if character.isspace() else self._mask_char for character in surface
        )

    def _last_n(self, surface: str, keep: int) -> str:
        if keep <= 0:
            return self._full(surface)
        head, tail = surface[: max(len(surface) - keep, 0)], surface[max(len(surface) - keep, 0) :]
        return self._full(head) + tail

    def _partial_email(self, surface: str) -> str:
        """``maria.rossi@example.com`` becomes ``ma***@example.com``."""
        local, separator, domain = surface.partition("@")
        if not separator:
            return self._full(surface)
        kept = local[: self._keep_local]
        return f"{kept}{self._mask_char * 3}@{domain}"

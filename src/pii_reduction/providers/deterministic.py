"""Deterministic EMAIL and PHONE recognizers.

Structured entities are where pattern matching genuinely belongs; names and addresses
are not (``AGENTS.md`` rule 6). This provider is the whole v0.1 detection baseline and
needs no model, which is what lets the entire test suite run without an NLP install.

Score semantics are fixed by construction (ADR-0005), not learned:

* EMAIL → ``1.0``. An anchored structural match either holds or does not.
* PHONE → ``1.0`` when ``phonenumbers`` validates the number for one of the
  configured regions, ``0.85`` when the text is only a possible number for that
  region. The two tiers are what let the reconciler and the benchmark tell a real
  ``+30 210 ...`` from a digit run that merely has a plausible length.

Leniency defaults to ``valid`` on measured evidence: at ``possible`` leniency
``PhoneNumberMatcher`` reported ``6915`` from ``DEMO-PC-6915``, ``12345`` from
``Order 12345``, and fragments of ``2026-04-03 09:15:04`` as numbers. Those are
precisely the negative fixtures of ``docs/10_TESTING_QA.md`` §6, so shipping
``possible`` as the default would have inflated over-redaction from the first
benchmark run. ``possible`` remains available per dataset, and the 0.85 tier with it.
"""

from __future__ import annotations

from typing import Any

import phonenumbers
from phonenumbers import Leniency

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.taxonomy import EMAIL, PHONE
from pii_reduction.patterns import EMAIL_PATTERN
from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.errors import ProviderError

__all__ = ["DeterministicProvider"]

SCORE_EMAIL = 1.0
SCORE_PHONE_VALID = 1.0
SCORE_PHONE_POSSIBLE = 0.85

RECOGNIZER_EMAIL = "email_pattern"
RECOGNIZER_PHONE = "phonenumbers_matcher"

_LENIENCY = {"valid": Leniency.VALID, "possible": Leniency.POSSIBLE}

DEFAULT_OPTIONS: dict[str, Any] = {
    #: Regions used to interpret nationally-formatted numbers. International
    #: (``+``-prefixed) numbers are found regardless, via the region-less pass.
    "regions": ["GR", "DE", "GB", "US"],
    #: ``possible`` also reports correctly-shaped but unvalidated numbers at 0.85 —
    #: and, measurably, plain identifiers such as ``Order 12345``. See the module
    #: docstring; opt in per dataset when recall matters more than precision.
    "leniency": "valid",
}


class DeterministicProvider(BaseProvider):
    """Pattern- and library-based recognizers for EMAIL and PHONE."""

    name = "deterministic"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ProviderError(
                f"provider {self.name!r}: unknown options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        regions = merged["regions"]
        if not regions or not all(isinstance(r, str) and len(r) == 2 for r in regions):
            raise ProviderError(
                f"provider {self.name!r}: regions must be a non-empty list of two-letter "
                "region codes, e.g. ['GR', 'DE']"
            )
        if merged["leniency"] not in _LENIENCY:
            raise ProviderError(
                f"provider {self.name!r}: leniency {merged['leniency']!r} is not supported "
                f"(known: {', '.join(sorted(_LENIENCY))})"
            )

        self.options = merged
        self._regions: tuple[str, ...] = tuple(str(region).upper() for region in regions)
        self._leniency = _LENIENCY[merged["leniency"]]

    def supported_entities(self) -> frozenset[str]:
        return frozenset({EMAIL, PHONE})

    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        if EMAIL in entities:
            matches.extend(self._detect_emails(text, language=language))
        if PHONE in entities:
            matches.extend(self._detect_phones(text, language=language))
        return matches

    def _detect_emails(self, text: str, *, language: str | None) -> list[EntityMatch]:
        return [
            EntityMatch(
                start=found.start(),
                end=found.end(),
                entity_type=EMAIL,
                score=SCORE_EMAIL,
                provider=self.name,
                recognizer=RECOGNIZER_EMAIL,
                language=language,
            )
            for found in EMAIL_PATTERN.finditer(text)
        ]

    def _detect_phones(self, text: str, *, language: str | None) -> list[EntityMatch]:
        """Match once per configured region plus a region-less pass, then dedupe.

        ``PhoneNumberMatcher`` takes a single default region, so a corpus mixing
        Greek and German national formats needs one pass each. The region-less pass
        catches ``+``-prefixed numbers. The same span found by several regions is
        kept once, at the strongest score.
        """
        best: dict[tuple[int, int], tuple[float, str | None]] = {}
        for region in (None, *self._regions):
            for found in phonenumbers.PhoneNumberMatcher(text, region, leniency=self._leniency):
                span = (found.start, found.end)
                if not _has_clean_boundaries(text, *span):
                    continue
                score = (
                    SCORE_PHONE_VALID
                    if phonenumbers.is_valid_number(found.number)
                    else SCORE_PHONE_POSSIBLE
                )
                current = best.get(span)
                if current is None or score > current[0]:
                    best[span] = (score, region)

        return [
            EntityMatch(
                start=start,
                end=end,
                entity_type=PHONE,
                score=score,
                provider=self.name,
                recognizer=RECOGNIZER_PHONE,
                language=language,
                metadata={"region": region} if region else {},
            )
            for (start, end), (score, region) in best.items()
        ]


def _has_clean_boundaries(text: str, start: int, end: int) -> bool:
    """Reject digit runs embedded in identifiers such as ``INC00128492``.

    ``phonenumbers`` will happily match a numeric substring of a ticket or asset id.
    Requiring the characters either side of the match to be non-alphanumeric keeps
    the over-redaction baseline honest (``docs/10_TESTING_QA.md`` §6).
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return not (before.isalnum() or after.isalnum())

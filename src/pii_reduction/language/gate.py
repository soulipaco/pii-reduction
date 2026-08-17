"""The short-text policy that decides whether detection may be attempted at all.

Kept separate from the detector, and free of any optional dependency, for two
reasons: the policy is the part with the interesting edge cases, and it must be
testable in the default model-free test tier (ADR-0009).

The policy exists because confidence alone cannot gate short text (ADR-0012). Measured
on ``lingua`` restricted to en/de/el: ``Thanks`` scores ``en`` 0.89, ``Resolved``
``en`` 0.96, and — the case that settles it — ``maria@example.com`` on its own scores
``en`` 0.95. An email address is not English. Any threshold high enough to reject it
would also reject genuine short German and Greek text, so the gate is structural
rather than probabilistic: strip the things that are not prose, count what is left,
and refuse to guess when there is too little of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from pii_reduction.patterns import DIGIT_RUN_PATTERN, EMAIL_PATTERN, URL_PATTERN

__all__ = [
    "REASON_BELOW_MIN_ALPHA",
    "REASON_BELOW_MIN_CHARS",
    "REASON_BELOW_MIN_CONFIDENCE",
    "ShortTextGate",
    "eligible_alpha_count",
]

REASON_BELOW_MIN_CHARS = "below_min_chars"
REASON_BELOW_MIN_ALPHA = "below_min_alpha_chars"
REASON_BELOW_MIN_CONFIDENCE = "below_min_confidence"


def eligible_alpha_count(text: str) -> int:
    """Count alphabetic characters after removing what is not prose.

    Emails and URLs go first (they are structure that happens to be made of letters),
    then digit runs. What remains is the evidence a language claim can rest on. The
    same patterns feed the deterministic EMAIL recognizer, so the gate and the
    recognizer cannot disagree about where an address starts and ends.
    """
    stripped = EMAIL_PATTERN.sub(" ", text)
    stripped = URL_PATTERN.sub(" ", stripped)
    stripped = DIGIT_RUN_PATTERN.sub(" ", stripped)
    return sum(1 for character in stripped if character.isalpha())


@dataclass(frozen=True)
class ShortTextGate:
    """Whether there is enough prose to justify a language claim (ADR-0012)."""

    min_chars: int = 20
    min_alpha_chars: int = 12
    min_confidence: float = 0.70

    def rejection_reason(self, text: str) -> str | None:
        """``None`` when detection may proceed, else the reason to record."""
        if len(text.strip()) < self.min_chars:
            return REASON_BELOW_MIN_CHARS
        if eligible_alpha_count(text) < self.min_alpha_chars:
            return REASON_BELOW_MIN_ALPHA
        return None

    def accepts_confidence(self, confidence: float) -> bool:
        return confidence >= self.min_confidence

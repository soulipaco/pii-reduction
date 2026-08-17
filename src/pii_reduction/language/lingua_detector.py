"""Lingua-backed language detection.

`lingua` was chosen over `langdetect` and fastText on measured accuracy and licence
(ADR-0012): on the same short strings `langdetect` returned ``Danke``→``da``,
``Call me``→``it`` and ``Resolved``→``no``, while fastText's LID model is CC BY-SA and
cannot be a dependency of an MIT project (ADR-0007).

The detector is restricted to the configured languages. That is not an optimization:
an unrestricted detector asked about ``Ευχαριστώ`` can return any of a hundred
languages, and the pipeline has provider chains for three. Restricting turns "which
language is this?" into the answerable "which of ours is this, if any?".

Everything the detector is *not* allowed to guess about is decided by
:class:`~pii_reduction.language.gate.ShortTextGate` before it is called.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pii_reduction.contracts.language import UNKNOWN_LANGUAGE, LanguageResult
from pii_reduction.language.base import REASON_UNSUPPORTED, BaseLanguageResolver
from pii_reduction.language.errors import LanguageError, LanguageNotAvailableError
from pii_reduction.language.gate import REASON_BELOW_MIN_CONFIDENCE, ShortTextGate

__all__ = ["DETECTOR_NAME", "LinguaDetector", "reset_detector_cache"]

DETECTOR_NAME = "lingua"

INSTALL_HINT = "install the extra: pip install 'pii-reduction[language]'"

#: Detectors by language set. Building one loads lingua's models, so it is done once
#: per process (or per Spark worker), like the Presidio engine.
_DETECTOR_CACHE: dict[tuple[str, ...], Any] = {}


def reset_detector_cache() -> None:
    """Drop cached detectors. For tests; a running pipeline should never need this."""
    _DETECTOR_CACHE.clear()


def _build_detector(languages: tuple[str, ...]) -> Any:
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise LanguageNotAvailableError(
            f"language detector {DETECTOR_NAME!r} requires lingua. {INSTALL_HINT}"
        ) from exc

    by_iso: Mapping[str, Any] = {
        language.iso_code_639_1.name.lower(): language for language in Language.all()
    }
    unknown = sorted(set(languages) - set(by_iso))
    if unknown:
        raise LanguageError(
            f"language detector {DETECTOR_NAME!r}: lingua does not support {', '.join(unknown)}"
        )
    selected = [by_iso[language] for language in languages]
    if len(selected) < 2:
        raise LanguageError(
            f"language detector {DETECTOR_NAME!r}: at least two supported languages are "
            "needed to detect between them; use mode 'static' for a single language"
        )
    return LanguageDetectorBuilder.from_languages(*selected).build()


def _detector_for(languages: tuple[str, ...]) -> Any:
    key = tuple(sorted(languages))
    detector = _DETECTOR_CACHE.get(key)
    if detector is None:
        detector = _build_detector(key)
        _DETECTOR_CACHE[key] = detector
    return detector


class LinguaDetector(BaseLanguageResolver):
    """Detects among the configured languages, or reports ``und`` and says why."""

    detector = DETECTOR_NAME

    def __init__(
        self,
        *,
        supported: tuple[str, ...],
        unknown_language: str = UNKNOWN_LANGUAGE,
        gate: ShortTextGate | None = None,
    ) -> None:
        super().__init__(supported=supported, unknown_language=unknown_language)
        if not supported:
            raise LanguageError("language detection requires at least one supported language")
        self._languages = tuple(sorted(supported))
        self.gate = gate or ShortTextGate()

    def detector_instance(self) -> Any:
        """The cached lingua detector. Builds on first use, once per process."""
        return _detector_for(self._languages)

    def resolve(self, text: str, *, row: Mapping[str, Any] | None = None) -> LanguageResult:
        rejection = self.gate.rejection_reason(text)
        if rejection is not None:
            return self._und(rejection)

        values = self.detector_instance().compute_language_confidence_values(text)
        if not values:  # pragma: no cover - lingua always returns the configured set
            return self._und(REASON_BELOW_MIN_CONFIDENCE)

        best = values[0]
        confidence = float(best.value)
        if not self.gate.accepts_confidence(confidence):
            return self._und(REASON_BELOW_MIN_CONFIDENCE, confidence=confidence)

        language = best.language.iso_code_639_1.name.lower()
        supported = language in self._supported
        return LanguageResult(
            language=language,
            confidence=confidence,
            detector=self.detector,
            supported=supported,
            fallback_used=not supported,
            reason=None if supported else REASON_UNSUPPORTED,
        )

    def _und(self, reason: str, *, confidence: float | None = None) -> LanguageResult:
        """Explicit "no usable claim", with the reason recorded (never a fake default)."""
        return LanguageResult(
            language=self._unknown,
            confidence=confidence,
            detector=self.detector,
            supported=False,
            fallback_used=True,
            reason=reason,
        )

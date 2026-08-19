"""Language resolver construction by configured mode (primitives in, resolver out)."""

from __future__ import annotations

from pii_reduction.contracts.language import UNKNOWN_LANGUAGE
from pii_reduction.language.base import (
    BaseLanguageResolver,
    ColumnLanguageResolver,
    StaticLanguageResolver,
)
from pii_reduction.language.errors import LanguageError
from pii_reduction.language.gate import ShortTextGate
from pii_reduction.language.lingua_detector import DETECTOR_NAME, LinguaDetector

__all__ = ["DETECTOR_DISTRIBUTIONS", "available_detectors", "build_resolver"]

#: Distributions whose installed versions describe a detector, for run provenance
#: (``RunMetadata.language_detector_version``). Lives with the language package
#: for the same reason ``providers.registry.PROVIDER_DISTRIBUTIONS`` lives with
#: the providers: the pipeline must not know which library backs a detector.
DETECTOR_DISTRIBUTIONS: dict[str, tuple[str, ...]] = {
    DETECTOR_NAME: ("lingua-language-detector",),
}

MODE_DETECT = "detect"
MODE_STATIC = "static"
MODE_COLUMN = "column"

MODES = frozenset({MODE_DETECT, MODE_STATIC, MODE_COLUMN})


def available_detectors() -> frozenset[str]:
    """Detector names that can actually be built. ``none`` means static/column mode."""
    return frozenset({DETECTOR_NAME, "none"})


def build_resolver(
    mode: str,
    *,
    supported: tuple[str, ...],
    detector: str = DETECTOR_NAME,
    static_language: str | None = None,
    language_column: str | None = None,
    unknown_language: str = UNKNOWN_LANGUAGE,
    gate: ShortTextGate | None = None,
) -> BaseLanguageResolver:
    """Construct the resolver for a column's language policy."""
    if mode not in MODES:
        raise LanguageError(
            f"language mode {mode!r} is not supported (known: {', '.join(sorted(MODES))})"
        )
    if mode == MODE_STATIC:
        return StaticLanguageResolver(
            static_language or "", supported=supported, unknown_language=unknown_language
        )
    if mode == MODE_COLUMN:
        return ColumnLanguageResolver(
            language_column or "", supported=supported, unknown_language=unknown_language
        )
    if detector != DETECTOR_NAME:
        raise LanguageError(
            f"language detector {detector!r} is not implemented "
            f"(available: {', '.join(sorted(available_detectors()))})"
        )
    return LinguaDetector(supported=supported, unknown_language=unknown_language, gate=gate)

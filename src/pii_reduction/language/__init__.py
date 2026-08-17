"""Language resolution: explicit, column-driven, or detected."""

from pii_reduction.language.base import (
    BaseLanguageResolver,
    ColumnLanguageResolver,
    LanguageResolver,
    StaticLanguageResolver,
)
from pii_reduction.language.errors import LanguageError, LanguageNotAvailableError
from pii_reduction.language.gate import ShortTextGate, eligible_alpha_count
from pii_reduction.language.lingua_detector import LinguaDetector
from pii_reduction.language.registry import available_detectors, build_resolver

__all__ = [
    "BaseLanguageResolver",
    "ColumnLanguageResolver",
    "LanguageError",
    "LanguageNotAvailableError",
    "LanguageResolver",
    "LinguaDetector",
    "ShortTextGate",
    "StaticLanguageResolver",
    "available_detectors",
    "build_resolver",
    "eligible_alpha_count",
]

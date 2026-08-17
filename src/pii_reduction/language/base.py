"""Language resolution: explicit and column-driven modes.

Detection proper (lingua, plus the short-text gate of ADR-0012) arrives in Increment
C. What exists now is the boundary it will plug into, and the two modes that need no
model: a fixed language for the whole dataset, and a language carried in a source
column — which is what the seeded synthetic corpus provides.

Resolvers are built from primitives, not from ``LanguageSettings``, so this package
does not import ``config``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from pii_reduction.contracts.language import UNKNOWN_LANGUAGE, LanguageResult
from pii_reduction.language.errors import LanguageError

__all__ = [
    "ColumnLanguageResolver",
    "LanguageResolver",
    "StaticLanguageResolver",
]

REASON_UNSUPPORTED = "unsupported_language"
REASON_MISSING = "missing_language_value"


@runtime_checkable
class LanguageResolver(Protocol):
    @property
    def detector(self) -> str: ...

    def resolve(self, text: str, *, row: Mapping[str, Any] | None = None) -> LanguageResult: ...


class BaseLanguageResolver(ABC):
    detector: str = ""

    def __init__(self, *, supported: tuple[str, ...], unknown_language: str = UNKNOWN_LANGUAGE):
        self._supported = frozenset(supported)
        self._unknown = unknown_language

    @abstractmethod
    def resolve(self, text: str, *, row: Mapping[str, Any] | None = None) -> LanguageResult: ...

    def _result(self, language: str | None, *, reason: str | None = None) -> LanguageResult:
        if not language:
            return LanguageResult(
                language=self._unknown,
                detector=self.detector,
                supported=False,
                fallback_used=True,
                reason=reason or REASON_MISSING,
            )
        normalized = language.strip().lower()
        supported = normalized in self._supported
        return LanguageResult(
            language=normalized,
            confidence=1.0 if supported else None,
            detector=self.detector,
            supported=supported,
            fallback_used=not supported,
            reason=None if supported else REASON_UNSUPPORTED,
        )


class StaticLanguageResolver(BaseLanguageResolver):
    """Every row is the configured language. No text is inspected."""

    detector = "static"

    def __init__(
        self,
        language: str,
        *,
        supported: tuple[str, ...],
        unknown_language: str = UNKNOWN_LANGUAGE,
    ) -> None:
        super().__init__(supported=supported, unknown_language=unknown_language)
        if not language:
            raise LanguageError("static language resolution requires a language code")
        self._language = language

    def resolve(self, text: str, *, row: Mapping[str, Any] | None = None) -> LanguageResult:
        return self._result(self._language)


class ColumnLanguageResolver(BaseLanguageResolver):
    """The language is carried by a source column."""

    detector = "column"

    def __init__(
        self,
        column: str,
        *,
        supported: tuple[str, ...],
        unknown_language: str = UNKNOWN_LANGUAGE,
    ) -> None:
        super().__init__(supported=supported, unknown_language=unknown_language)
        if not column:
            raise LanguageError("column language resolution requires a column name")
        self.column = column

    def resolve(self, text: str, *, row: Mapping[str, Any] | None = None) -> LanguageResult:
        if row is None or self.column not in row:
            raise LanguageError(f"language column {self.column!r} is not present in the source row")
        value = row[self.column]
        if value is None or (isinstance(value, float) and value != value):  # NaN
            return self._result(None)
        return self._result(str(value))

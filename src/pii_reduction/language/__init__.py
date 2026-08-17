"""Language resolution. Detection with lingua arrives in Increment C."""

from pii_reduction.language.base import (
    ColumnLanguageResolver,
    LanguageResolver,
    StaticLanguageResolver,
)
from pii_reduction.language.errors import LanguageError

__all__ = [
    "ColumnLanguageResolver",
    "LanguageError",
    "LanguageResolver",
    "StaticLanguageResolver",
]

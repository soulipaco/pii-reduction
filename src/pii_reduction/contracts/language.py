"""Language resolution contract (``docs/03_DATA_CONTRACTS.md`` §5).

Unknown language is represented explicitly (``UNKNOWN_LANGUAGE``) rather than as a
fake default. The field name is ``supported``; ``docs/01_ARCHITECTURE.md`` once
showed ``is_supported`` and was corrected in session 2.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from pii_reduction.contracts.base import FrozenModel

__all__ = ["UNKNOWN_LANGUAGE", "LanguageResult"]

UNKNOWN_LANGUAGE = "und"


class LanguageResult(FrozenModel):
    """The resolved language of a segment or field, with provenance."""

    language: str = Field(min_length=2)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    detector: str = Field(min_length=1)
    supported: bool
    fallback_used: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _check_unknown_is_not_supported(self) -> Self:
        if self.language == UNKNOWN_LANGUAGE and self.supported:
            raise ValueError(f"language {UNKNOWN_LANGUAGE!r} cannot be marked supported")
        return self

    @property
    def is_unknown(self) -> bool:
        return self.language == UNKNOWN_LANGUAGE

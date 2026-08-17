"""Provider protocol and the contract every provider is held to.

``BaseProvider.detect`` is a template method: subclasses implement ``_detect`` and the
base class enforces the provider contract (``docs/10_TESTING_QA.md`` §4) on the way
out — normalized labels, valid offsets, requested entity scope, stable ordering.
A provider that misbehaves fails loudly here rather than corrupting text downstream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from typing import Protocol, runtime_checkable

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.errors import UnknownEntityLabelError
from pii_reduction.entities.mapping import DropCounter
from pii_reduction.entities.taxonomy import require_known
from pii_reduction.providers.errors import ProviderError

__all__ = ["BaseProvider", "PIIProvider"]


@runtime_checkable
class PIIProvider(Protocol):
    """What the processing layer depends on (``docs/04_PII_ENGINE.md``)."""

    @property
    def name(self) -> str: ...

    def supported_languages(self) -> frozenset[str] | None: ...

    def supported_entities(self) -> frozenset[str]: ...

    def detect(
        self,
        text: str,
        *,
        language: str | None = None,
        entities: Collection[str] | None = None,
    ) -> list[EntityMatch]: ...

    def detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None] | None = None,
        entities: Collection[str] | None = None,
    ) -> list[list[EntityMatch]]: ...


class BaseProvider(ABC):
    """Shared contract enforcement, entity-scope filtering and batching."""

    #: Instance name used in ``EntityMatch.provider`` and in run metrics.
    name: str = ""

    @property
    def drop_counter(self) -> DropCounter:
        """Native labels this provider discarded, by reason.

        Lives on the base class so the pipeline can collect drops from every provider
        without knowing which ones map labels at all — a provider with no mapping
        table simply reports an empty counter. ADR-0004 requires these counts to reach
        observability output; a silent drop is how a provider upgrade loses coverage
        without anyone noticing.

        Created lazily so subclasses are not obliged to call ``super().__init__()``.
        """
        counter: DropCounter | None = getattr(self, "_drop_counter", None)
        if counter is None:
            counter = DropCounter()
            self._drop_counter = counter
        return counter

    @abstractmethod
    def supported_entities(self) -> frozenset[str]:
        """Normalized labels this provider can produce."""

    def supported_languages(self) -> frozenset[str] | None:
        """``None`` means language-independent."""
        return None

    @abstractmethod
    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        """Detect candidates. ``entities`` is already narrowed to what this provider supports."""

    def detect(
        self,
        text: str,
        *,
        language: str | None = None,
        entities: Collection[str] | None = None,
    ) -> list[EntityMatch]:
        """Detect entities in ``text``, returning normalized matches sorted by position."""
        if not isinstance(text, str):
            raise ProviderError(
                f"provider {self.name!r}: detect() requires str, got {type(text).__name__}. "
                "Null values are handled by the field processor"
            )

        requested = self._resolve_scope(entities)
        if not requested or not text:
            return []

        matches = self._detect(text, language=language, entities=requested)
        self._validate(matches, text=text, requested=requested)
        return sorted(matches, key=lambda match: (match.start, match.end, match.entity_type))

    def detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None] | None = None,
        entities: Collection[str] | None = None,
    ) -> list[list[EntityMatch]]:
        """Default: one call per text. Providers with native batching should override."""
        if languages is not None and len(languages) != len(texts):
            raise ProviderError(
                f"provider {self.name!r}: got {len(languages)} languages for {len(texts)} texts"
            )
        resolved = list(languages) if languages is not None else [None] * len(texts)
        return [
            self.detect(text, language=language, entities=entities)
            for text, language in zip(texts, resolved, strict=True)
        ]

    def _resolve_scope(self, entities: Collection[str] | None) -> frozenset[str]:
        supported = self.supported_entities()
        if entities is None:
            return supported
        for label in entities:
            try:
                require_known(label, context=f"provider {self.name!r}")
            except UnknownEntityLabelError as exc:
                raise ProviderError(str(exc)) from exc
        return frozenset(entities) & supported

    def _validate(
        self, matches: list[EntityMatch], *, text: str, requested: frozenset[str]
    ) -> None:
        """Enforce the provider contract. Messages carry offsets, never text."""
        for match in matches:
            if match.provider != self.name:
                raise ProviderError(
                    f"provider {self.name!r}: returned a match attributed to {match.provider!r}"
                )
            try:
                require_known(match.entity_type, context=f"provider {self.name!r}")
            except UnknownEntityLabelError as exc:
                raise ProviderError(str(exc)) from exc
            if match.entity_type not in requested:
                raise ProviderError(
                    f"provider {self.name!r}: returned {match.entity_type} which was not "
                    f"requested (requested: {', '.join(sorted(requested))})"
                )
            if not match.is_within(text):
                raise ProviderError(
                    f"provider {self.name!r}: match [{match.start}, {match.end}) exceeds text "
                    f"of length {len(text)}"
                )

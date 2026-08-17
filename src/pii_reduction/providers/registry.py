"""Provider construction by configured type.

``config.registries.KNOWN_PROVIDER_TYPES`` lists what configuration accepts; this
lists what exists today. A configured-but-unbuilt type gets an error naming the
increment that will implement it, rather than a ``KeyError`` at run time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.deterministic import DeterministicProvider
from pii_reduction.providers.errors import ProviderError
from pii_reduction.providers.presidio_provider import PresidioProvider

__all__ = ["PENDING_PROVIDER_TYPES", "available_provider_types", "build_provider"]

_PROVIDERS: dict[str, Callable[[dict[str, Any] | None], BaseProvider]] = {
    DeterministicProvider.name: DeterministicProvider,
    PresidioProvider.name: PresidioProvider,
}

#: Accepted by configuration, not yet implemented, with where they arrive.
#: Empty today; transformer and GLiNER providers are roadmap Phase 7.
PENDING_PROVIDER_TYPES: dict[str, str] = {}


def available_provider_types() -> frozenset[str]:
    return frozenset(_PROVIDERS)


def build_provider(
    provider_type: str,
    options: dict[str, Any] | None = None,
    *,
    name: str | None = None,
) -> BaseProvider:
    """Construct a provider by type; ``name`` overrides the instance name in metrics."""
    factory = _PROVIDERS.get(provider_type)
    if factory is None:
        pending = PENDING_PROVIDER_TYPES.get(provider_type)
        if pending is not None:
            raise ProviderError(
                f"provider type {provider_type!r} is not implemented yet; it arrives in {pending}"
            )
        raise ProviderError(
            f"provider type {provider_type!r} is not registered "
            f"(available: {', '.join(sorted(_PROVIDERS))})"
        )
    provider = factory(options)
    if name is not None:
        provider.name = name
    return provider

"""Provider construction by configured type.

``config.registries.KNOWN_PROVIDER_TYPES`` lists what configuration accepts; this
lists what exists today. A configured-but-unbuilt type gets an error naming the
increment that will implement it, rather than a ``KeyError`` at run time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.deterministic import DeterministicProvider
from pii_reduction.providers.errors import ProviderError
from pii_reduction.providers.presidio_provider import PresidioProvider

__all__ = [
    "PENDING_PROVIDER_TYPES",
    "PROVIDER_DISTRIBUTIONS",
    "available_provider_types",
    "build_provider",
    "provider_distributions",
]

_PROVIDERS: dict[str, Callable[[dict[str, Any] | None], BaseProvider]] = {
    DeterministicProvider.name: DeterministicProvider,
    PresidioProvider.name: PresidioProvider,
}

#: Distributions whose installed versions describe a provider type's detection
#: behaviour, for run provenance (``RunMetadata.provider_versions``). This lives
#: with the providers because it is provider knowledge — the pipeline must not
#: know which libraries back an adapter (ADR-0004's boundary, applied to
#: provenance). spaCy *model* packages are per-instance configuration
#: (``options.models``) and are added at the call site, not here. A test pins
#: these keys to :func:`available_provider_types`.
PROVIDER_DISTRIBUTIONS: dict[str, tuple[str, ...]] = {
    DeterministicProvider.name: ("phonenumbers",),
    PresidioProvider.name: ("presidio-analyzer", "spacy"),
}


def provider_distributions(provider_type: str, options: Mapping[str, Any]) -> tuple[str, ...]:
    """The distributions describing one configured provider: type-level + models.

    Lives here, not in ``processing/``, because both halves are provider
    knowledge: which libraries back an adapter (the table above) and which option
    carries its model packages (``options["models"]``, a Presidio-instance
    setting). The pipeline passes settings through without interpreting them.
    """
    base = PROVIDER_DISTRIBUTIONS.get(provider_type, ())
    models = options.get("models")
    if isinstance(models, dict):
        return base + tuple(sorted({str(model) for model in models.values()}))
    return base


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

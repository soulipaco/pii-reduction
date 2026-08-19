"""Version capture for run provenance.

``RunMetadata.provider_versions`` must let a reader answer "which detector stack
produced this run". The integration workflow pins spaCy model versions precisely
because a model bump can move a gate — so the run record has to capture what CI
already knows matters (`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md`, D2).

Lookups go through ``importlib.metadata``, which reads installed package metadata
without importing the package: recording a version never loads a model, never
imports an optional dependency, and therefore never trips the model-free default
tier. spaCy models are ordinary distributions (``en_core_web_md`` has package
metadata like any wheel), so model versions resolve the same way.
"""

from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata

__all__ = ["describe_versions", "distribution_version"]


def distribution_version(name: str) -> str | None:
    """The installed version of a distribution, or ``None`` when it is absent."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def describe_versions(type_name: str, distributions: Iterable[str]) -> str:
    """``"presidio (presidio-analyzer 2.2.364, spacy 3.8.15)"`` — or the bare name.

    Degrades to exactly the pre-provenance value (the bare type name) when nothing
    resolves, so a machine without an optional extra records what it always
    recorded rather than an error — and the degraded form is itself information:
    a run whose record says only ``presidio`` ran on a machine that could not
    have loaded the models.
    """
    parts = [
        f"{name} {version}" for name in distributions if (version := distribution_version(name))
    ]
    return f"{type_name} ({', '.join(parts)})" if parts else type_name

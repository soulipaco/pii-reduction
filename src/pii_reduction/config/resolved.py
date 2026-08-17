"""Fully-resolved configuration: what the pipeline actually runs on.

Nothing here is optional. Every fallback has already been applied by
:func:`pii_reduction.config.loader.resolve_dataset`, so downstream code never has to
re-implement the layering rules — and a benchmark result can be traced to one
concrete object via its fingerprint.
"""

from __future__ import annotations

from pydantic import Field

from pii_reduction.config.models import (
    ChainSettings,
    ConfigModel,
    DatasetIdentity,
    DestinationConfig,
    FailureMode,
    LanguageSettings,
    ObservabilitySettings,
    ProjectIdentity,
    ProviderSettings,
    ReducerSettings,
    SourceConfig,
    ValidationSettings,
)

__all__ = ["EffectiveEntity", "ResolvedColumnPolicy", "ResolvedDataset"]


class EffectiveEntity(ConfigModel):
    """Taxonomy default after project-level overrides."""

    label: str = Field(min_length=1)
    replacement: str = Field(min_length=1)
    priority: int


class ResolvedColumnPolicy(ConfigModel):
    """Everything needed to process one column of one dataset."""

    column: str = Field(min_length=1)
    parser: str = Field(min_length=1)
    parser_options: dict[str, object] = Field(default_factory=dict)
    output_column: str = Field(min_length=1)
    entities: tuple[str, ...] = Field(min_length=1)
    language: LanguageSettings
    provider_chain: str = Field(min_length=1)
    providers: tuple[str, ...] = Field(min_length=1)
    overlap_policy: str = Field(min_length=1)
    reducer: str = Field(min_length=1)
    failure_mode: FailureMode
    preserve_original: bool


class ResolvedDataset(ConfigModel):
    """One dataset, ready to run."""

    project: ProjectIdentity
    dataset: DatasetIdentity
    source: SourceConfig
    destination: DestinationConfig
    columns: tuple[ResolvedColumnPolicy, ...] = Field(min_length=1)
    entities: dict[str, EffectiveEntity]
    providers: dict[str, ProviderSettings]
    chains: dict[str, ChainSettings]
    reducers: dict[str, ReducerSettings]
    observability: ObservabilitySettings
    validation: ValidationSettings

    def column(self, name: str) -> ResolvedColumnPolicy:
        for policy in self.columns:
            if policy.column == name:
                return policy
        raise KeyError(name)

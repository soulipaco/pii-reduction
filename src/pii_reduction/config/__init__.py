"""Typed configuration: models, layered loading, validation, and fingerprinting."""

from pii_reduction.config.errors import ConfigurationError
from pii_reduction.config.fingerprint import config_fingerprint, fingerprint_material
from pii_reduction.config.loader import (
    load_dataset_config,
    load_project_config,
    load_resolved_dataset,
    load_yaml_mapping,
    resolve_dataset,
)
from pii_reduction.config.models import (
    ChainSettings,
    ColumnConfig,
    DatasetConfig,
    DatasetIdentity,
    EntityOverride,
    FailureMode,
    LanguageMode,
    LanguageOverrides,
    LanguageSettings,
    ObservabilitySettings,
    ProcessingOverrides,
    ProcessingSettings,
    ProjectConfig,
    ProjectIdentity,
    ProviderSettings,
    ReducerSettings,
    ValidationSettings,
)
from pii_reduction.config.resolved import (
    EffectiveEntity,
    ResolvedColumnPolicy,
    ResolvedDataset,
)

# Re-exported so a caller that must *enumerate* entity labels can do so through the
# configuration layer. `loader` already depends on `entities.taxonomy`, so this adds
# no package edge — and it is what keeps the service layer's import allowlist
# workable without letting it reach into `entities/` directly
# (`docs/01_ARCHITECTURE.md`, *Package dependency direction*).
from pii_reduction.entities.taxonomy import TAXONOMY, known_labels

__all__ = [
    "TAXONOMY",
    "ChainSettings",
    "ColumnConfig",
    "ConfigurationError",
    "DatasetConfig",
    "DatasetIdentity",
    "EffectiveEntity",
    "EntityOverride",
    "FailureMode",
    "LanguageMode",
    "LanguageOverrides",
    "LanguageSettings",
    "ObservabilitySettings",
    "ProcessingOverrides",
    "ProcessingSettings",
    "ProjectConfig",
    "ProjectIdentity",
    "ProviderSettings",
    "ReducerSettings",
    "ResolvedColumnPolicy",
    "ResolvedDataset",
    "ValidationSettings",
    "config_fingerprint",
    "fingerprint_material",
    "known_labels",
    "load_dataset_config",
    "load_project_config",
    "load_resolved_dataset",
    "load_yaml_mapping",
    "resolve_dataset",
]

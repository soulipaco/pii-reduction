"""Layered configuration loading, merging and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from pii_reduction.config import (
    ConfigurationError,
    FailureMode,
    LanguageMode,
    load_project_config,
    load_resolved_dataset,
    load_yaml_mapping,
)
from tests.conftest import MINIMAL_DATASET_YAML, MINIMAL_PROJECT_YAML, write_configs

pytestmark = pytest.mark.unit


def resolve(tmp_path: Path, *, project: str | None = None, dataset: str | None = None):  # type: ignore[no-untyped-def]
    configs = write_configs(
        tmp_path,
        project_yaml=project or MINIMAL_PROJECT_YAML,
        dataset_yaml=dataset or MINIMAL_DATASET_YAML,
    )
    return load_resolved_dataset(configs, "demo_smoke")


class TestShippedProjectConfig:
    def test_the_shipped_default_is_fail_closed(self) -> None:
        """ADR-0023: `configs/project.yaml` must not re-open the fail-open default.

        `preserve_original_and_record_error` writes raw source text into the reduced
        column on any error; it is an explicit per-dataset opt-in, never the shipped
        project default.
        """
        repo_root = Path(__file__).resolve().parents[1]
        shipped = load_yaml_mapping(repo_root / "configs" / "project.yaml")
        assert shipped["processing"]["failure_mode"] == "quarantine_row"


class TestYamlLoading:
    def test_missing_file_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            load_yaml_mapping(tmp_path / "nope.yaml")
        assert "nope.yaml" in str(exc_info.value)

    def test_empty_file_is_an_empty_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        assert load_yaml_mapping(path) == {}

    def test_non_mapping_top_level_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ConfigurationError) as exc_info:
            load_yaml_mapping(path)
        assert "mapping" in str(exc_info.value)

    def test_invalid_yaml_is_reported_as_a_configuration_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("project: [unclosed\n", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_yaml_mapping(path)


class TestSideFiles:
    def test_providers_file_contributes_providers_and_chains(self, tmp_path: Path) -> None:
        project_yaml = """
project:
  name: test-project
processing:
  default_provider_chain: hybrid
language:
  mode: static
  detector: none
  static_language: en
"""
        configs = write_configs(
            tmp_path,
            project_yaml=project_yaml,
            side_files={
                "providers.yaml": """
providers:
  deterministic:
    type: deterministic
    entities: [EMAIL, PHONE]
  presidio_en:
    type: presidio
    languages: [en]
    entities: [PERSON]
    thresholds:
      PERSON: 0.5
chains:
  hybrid:
    providers: [deterministic, presidio_en]
""",
                "languages.yaml": "languages:\n  en:\n    chain: hybrid\n",
                "entities.yaml": "entities:\n  PERSON:\n    replacement: '[redacted person]'\n",
            },
        )
        project = load_project_config(configs)
        assert set(project.providers) == {"deterministic", "presidio_en"}
        assert project.chains["hybrid"].providers == ("deterministic", "presidio_en")
        assert project.languages["en"].chain == "hybrid"
        assert project.entities["PERSON"].replacement == "[redacted person]"

    def test_side_file_may_not_redefine_a_project_section(self, tmp_path: Path) -> None:
        configs = write_configs(
            tmp_path,
            side_files={"providers.yaml": "providers:\n  other:\n    type: deterministic\n"},
        )
        with pytest.raises(ConfigurationError) as exc_info:
            load_project_config(configs)
        assert "already" in str(exc_info.value)

    def test_side_file_rejects_keys_it_does_not_own(self, tmp_path: Path) -> None:
        configs = write_configs(tmp_path, side_files={"languages.yaml": "processing:\n  seed: 1\n"})
        with pytest.raises(ConfigurationError) as exc_info:
            load_project_config(configs)
        assert "allowed: languages" in str(exc_info.value)


class TestActionableValidation:
    def test_unknown_parser_names_the_dataset_and_column(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace("parser: plain_text", "parser: conversation_v9")
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        message = str(exc_info.value)
        assert "dataset 'demo_smoke'" in message
        assert "column 'body'" in message
        assert "'conversation_v9' is not registered" in message
        assert "plain_text" in message  # the message lists what *is* available

    def test_unknown_entity_label_is_actionable(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace("entities: [EMAIL, PHONE]", "entities: [EMAIL, SSN]")
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        message = str(exc_info.value)
        assert "SSN" in message
        assert "column 'body'" in message

    def test_no_processable_column_is_an_error(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace(
            "  body:\n    parser: plain_text\n    entities: [EMAIL, PHONE]\n",
            "  body:\n    process: false\n",
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        assert "no columns are configured for processing" in str(exc_info.value)

    def test_column_without_entities_is_rejected_rather_than_defaulted(
        self, tmp_path: Path
    ) -> None:
        dataset = MINIMAL_DATASET_YAML.replace("    entities: [EMAIL, PHONE]\n", "")
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        assert "no entities configured" in str(exc_info.value)

    def test_unknown_provider_chain_lists_the_defined_chains(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace(
            "    entities: [EMAIL, PHONE]\n",
            "    entities: [EMAIL, PHONE]\n    provider_chain: nlp_heavy\n",
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        message = str(exc_info.value)
        assert "'nlp_heavy' is not defined" in message
        assert "deterministic_only" in message

    def test_chain_referencing_an_undefined_provider_is_rejected(self, tmp_path: Path) -> None:
        project = MINIMAL_PROJECT_YAML.replace(
            "    providers: [deterministic]", "    providers: [deterministic, presidio_en]"
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, project=project)
        assert "presidio_en" in str(exc_info.value)

    def test_unknown_source_type_is_reported_before_schema_errors(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace("  type: csv", "  type: excel", 1)
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        message = str(exc_info.value)
        assert "source type 'excel' is not registered" in message
        assert "csv" in message

    def test_unknown_key_is_a_typo_not_an_extension_point(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace("    parser: plain_text", "    parsers: plain_text")
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        assert "parsers" in str(exc_info.value)

    def test_global_threshold_is_rejected_with_the_reason(self, tmp_path: Path) -> None:
        project = MINIMAL_PROJECT_YAML.replace(
            "    entities: [EMAIL, PHONE]", "    entities: [EMAIL, PHONE]\n    threshold: 0.5"
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, project=project)
        message = str(exc_info.value)
        assert "'threshold' is not supported" in message
        assert "thresholds" in message

    def test_static_language_mode_requires_a_language(self, tmp_path: Path) -> None:
        project = MINIMAL_PROJECT_YAML.replace("  static_language: en", "")
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, project=project)
        assert "requires 'static_language'" in str(exc_info.value)

    def test_column_language_mode_requires_a_column(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace(
            "    entities: [EMAIL, PHONE]\n",
            "    entities: [EMAIL, PHONE]\n    language:\n      mode: column\n",
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        assert "requires 'language_column'" in str(exc_info.value)

    def test_detect_mode_without_a_detector_is_rejected(self, tmp_path: Path) -> None:
        project = MINIMAL_PROJECT_YAML.replace("  mode: static", "  mode: detect")
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, project=project)
        assert "requires a detector" in str(exc_info.value)

    def test_output_column_may_not_overwrite_the_source_column(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace(
            "    entities: [EMAIL, PHONE]\n",
            "    entities: [EMAIL, PHONE]\n    output_column: body\n",
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        assert "preserve_original" in str(exc_info.value)

    def test_two_columns_may_not_share_one_output_column(self, tmp_path: Path) -> None:
        dataset = (
            MINIMAL_DATASET_YAML
            + """  summary:
    parser: plain_text
    entities: [EMAIL]
    output_column: body_pii_redacted
"""
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, dataset=dataset)
        assert "both write to output column" in str(exc_info.value)

    def test_raw_text_logging_is_refused_outside_local(self, tmp_path: Path) -> None:
        project = (
            MINIMAL_PROJECT_YAML.replace("  environment: local", "  environment: databricks")
            + "\nobservability:\n  log_raw_text: true\n"
        )
        with pytest.raises(ConfigurationError) as exc_info:
            resolve(tmp_path, project=project)
        assert "log_raw_text" in str(exc_info.value)

    def test_unknown_dataset_lists_what_is_available(self, tmp_path: Path) -> None:
        configs = write_configs(tmp_path)
        with pytest.raises(ConfigurationError) as exc_info:
            load_resolved_dataset(configs, "demo_missing")
        message = str(exc_info.value)
        assert "demo_missing" in message
        assert "demo_smoke" in message


class TestLayeredMerge:
    def test_defaults_flow_from_the_project_layer(self, tmp_path: Path) -> None:
        resolved = resolve(tmp_path)
        policy = resolved.column("body")
        assert policy.parser == "plain_text"
        assert policy.reducer == "redact"
        assert policy.provider_chain == "deterministic_only"
        assert policy.providers == ("deterministic",)
        # ADR-0023: the unconfigured default is fail-closed.
        assert policy.failure_mode is FailureMode.QUARANTINE_ROW
        assert policy.language.mode is LanguageMode.STATIC
        assert policy.language.static_language == "en"

    def test_output_column_is_derived_from_the_suffix(self, tmp_path: Path) -> None:
        resolved = resolve(tmp_path)
        assert resolved.column("body").output_column == "body_pii_redacted"

    def test_dataset_layer_overrides_the_project_layer(self, tmp_path: Path) -> None:
        dataset = (
            MINIMAL_DATASET_YAML
            + "\nprocessing:\n  output_suffix: _redacted\n  failure_mode: fail_fast\n"
        )
        resolved = resolve(tmp_path, dataset=dataset)
        policy = resolved.column("body")
        assert policy.output_column == "body_redacted"
        assert policy.failure_mode is FailureMode.FAIL_FAST

    def test_column_layer_overrides_the_dataset_layer(self, tmp_path: Path) -> None:
        dataset = (
            MINIMAL_DATASET_YAML.replace(
                "    entities: [EMAIL, PHONE]\n",
                "    entities: [EMAIL, PHONE]\n    language:\n      static_language: de\n",
            )
            + "\nlanguage:\n  static_language: el\n"
        )
        resolved = resolve(tmp_path, dataset=dataset)
        assert resolved.column("body").language.static_language == "de"

    def test_dataset_language_override_applies_when_the_column_is_silent(
        self, tmp_path: Path
    ) -> None:
        dataset = MINIMAL_DATASET_YAML + "\nlanguage:\n  static_language: el\n"
        resolved = resolve(tmp_path, dataset=dataset)
        assert resolved.column("body").language.static_language == "el"

    def test_entity_overrides_apply_over_taxonomy_defaults(self, tmp_path: Path) -> None:
        configs = write_configs(
            tmp_path,
            side_files={
                "entities.yaml": "entities:\n  EMAIL:\n    replacement: '[email]'\n    priority: 42\n"
            },
        )
        resolved = load_resolved_dataset(configs, "demo_smoke")
        assert resolved.entities["EMAIL"].replacement == "[email]"
        assert resolved.entities["EMAIL"].priority == 42
        # Untouched labels keep their taxonomy defaults.
        assert resolved.entities["PERSON"].replacement == "<PERSON>"

    def test_entities_are_normalized_to_a_sorted_tuple(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace(
            "entities: [EMAIL, PHONE]", "entities: [PHONE, EMAIL, PHONE]"
        )
        resolved = resolve(tmp_path, dataset=dataset)
        assert resolved.column("body").entities == ("EMAIL", "PHONE")

    def test_columns_with_process_false_are_left_out(self, tmp_path: Path) -> None:
        dataset = (
            MINIMAL_DATASET_YAML
            + """  notes:
    process: false
"""
        )
        resolved = resolve(tmp_path, dataset=dataset)
        assert [policy.column for policy in resolved.columns] == ["body"]

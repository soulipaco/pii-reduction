"""Configuration fingerprint stability and secret exclusion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_reduction.config import config_fingerprint, fingerprint_material, load_resolved_dataset
from tests.conftest import MINIMAL_DATASET_YAML, MINIMAL_PROJECT_YAML, write_configs

pytestmark = pytest.mark.unit


def fingerprint_of(root: Path, *, project: str | None = None, dataset: str | None = None) -> str:
    configs = write_configs(
        root,
        project_yaml=project or MINIMAL_PROJECT_YAML,
        dataset_yaml=dataset or MINIMAL_DATASET_YAML,
    )
    return config_fingerprint(load_resolved_dataset(configs, "demo_smoke"))


class TestStability:
    def test_same_configuration_hashes_the_same_twice(self, tmp_path: Path) -> None:
        first = fingerprint_of(tmp_path / "a")
        second = fingerprint_of(tmp_path / "b")
        assert first == second
        assert len(first) == 64

    def test_key_order_in_yaml_does_not_change_the_hash(self, tmp_path: Path) -> None:
        reordered = """
dataset:
  row_id: row_id
  name: demo_smoke

destination:
  path: data/output/
  type: parquet

source:
  path: data/input/demo.csv
  type: csv

columns:
  body:
    entities: [PHONE, EMAIL]
    parser: plain_text
"""
        assert fingerprint_of(tmp_path / "a") == fingerprint_of(tmp_path / "b", dataset=reordered)

    def test_a_changed_setting_changes_the_hash(self, tmp_path: Path) -> None:
        changed = MINIMAL_PROJECT_YAML.replace(
            "output_suffix: _pii_redacted", "output_suffix: _red"
        )
        assert fingerprint_of(tmp_path / "a") != fingerprint_of(tmp_path / "b", project=changed)

    def test_a_changed_entity_scope_changes_the_hash(self, tmp_path: Path) -> None:
        changed = MINIMAL_DATASET_YAML.replace("entities: [EMAIL, PHONE]", "entities: [EMAIL]")
        assert fingerprint_of(tmp_path / "a") != fingerprint_of(tmp_path / "b", dataset=changed)


class TestSecretExclusion:
    def test_secret_bearing_keys_are_absent_from_the_hash_material(self, tmp_path: Path) -> None:
        dataset = MINIMAL_DATASET_YAML.replace(
            "  path: data/input/demo.csv",
            "  path: data/input/demo.csv\n  options:\n"
            "    encoding: utf-8\n    auth_token: placeholder-value\n",
        )
        configs = write_configs(tmp_path, dataset_yaml=dataset)
        resolved = load_resolved_dataset(configs, "demo_smoke")
        material = json.dumps(fingerprint_material(resolved))
        assert "auth_token" not in material
        assert "placeholder-value" not in material
        assert "utf-8" in material  # non-secret options still take part

    def test_changing_a_secret_bearing_value_does_not_change_the_hash(self, tmp_path: Path) -> None:
        def dataset_with(value: str) -> str:
            return MINIMAL_DATASET_YAML.replace(
                "  path: data/input/demo.csv",
                f"  path: data/input/demo.csv\n  options:\n    auth_token: {value}\n",
            )

        first = fingerprint_of(tmp_path / "a", dataset=dataset_with("placeholder-one"))
        second = fingerprint_of(tmp_path / "b", dataset=dataset_with("placeholder-two"))
        assert first == second

    def test_changing_a_non_secret_option_does_change_the_hash(self, tmp_path: Path) -> None:
        def dataset_with(delimiter: str) -> str:
            return MINIMAL_DATASET_YAML.replace(
                "  path: data/input/demo.csv",
                f"  path: data/input/demo.csv\n  options:\n    delimiter: '{delimiter}'\n",
            )

        first = fingerprint_of(tmp_path / "a", dataset=dataset_with(","))
        second = fingerprint_of(tmp_path / "b", dataset=dataset_with(";"))
        assert first != second

"""Shared test helpers.

Every fixture value in this suite is synthetic. Email addresses use RFC 2606
reserved domains (``example.com``/``.org``/``.net``) per ADR-0003; ``.test`` appears
only in tests that explicitly document recognizer behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

MINIMAL_PROJECT_YAML = """
project:
  name: test-project
  environment: local
  seed: 42

processing:
  default_parser: plain_text
  default_reducer: redact
  default_provider_chain: deterministic_only
  output_suffix: _pii_redacted

language:
  mode: static
  detector: none
  static_language: en

providers:
  deterministic:
    type: deterministic
    entities: [EMAIL, PHONE]

chains:
  deterministic_only:
    providers: [deterministic]
"""

MINIMAL_DATASET_YAML = """
dataset:
  name: demo_smoke
  row_id: row_id

source:
  type: csv
  path: data/input/demo.csv

destination:
  type: parquet
  path: data/output/

columns:
  body:
    parser: plain_text
    entities: [EMAIL, PHONE]
"""


def write_configs(
    root: Path,
    *,
    project_yaml: str = MINIMAL_PROJECT_YAML,
    dataset_yaml: str = MINIMAL_DATASET_YAML,
    dataset_name: str = "demo_smoke",
    side_files: dict[str, str] | None = None,
) -> Path:
    """Write a ``configs/`` tree and return its path."""
    configs = root / "configs"
    (configs / "datasets").mkdir(parents=True, exist_ok=True)
    (configs / "project.yaml").write_text(project_yaml, encoding="utf-8")
    (configs / "datasets" / f"{dataset_name}.yaml").write_text(dataset_yaml, encoding="utf-8")
    for filename, content in (side_files or {}).items():
        (configs / filename).write_text(content, encoding="utf-8")
    return configs


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    """A valid minimal configuration tree."""
    return write_configs(tmp_path)

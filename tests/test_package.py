"""Packaging and layering guards.

These are cheap structural tests for two promises that are easy to break silently:
the core package installs and runs without any NLP extra (ADR-0008), and
``contracts`` stays the dependency hub nothing else leaks into
(``docs/01_ARCHITECTURE.md``).
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import pii_reduction

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "src" / "pii_reduction" / "contracts"

# Provider/runtime extras only. Faker is a `dev` extra and legitimately present in a
# developer environment (it also registers a pytest plugin, so it is always imported).
OPTIONAL_MODULES = ("presidio_analyzer", "spacy", "lingua", "pyspark", "databricks")


def test_version_matches_pyproject() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    assert pii_reduction.__version__ == pyproject["project"]["version"]


def test_core_layers_import_without_any_provider_extra() -> None:
    """A fresh interpreter must not pull in a provider extra.

    Checked in a subprocess rather than against this process's ``sys.modules``:
    collecting the integration tests imports Presidio, so an in-process check would
    pass or fail depending on test ordering. ``pii_reduction.providers`` is included
    deliberately — the Presidio adapter must be importable without the extra
    installed, and only reach for it when an engine is actually built.
    """
    code = (
        "import sys, pii_reduction.config, pii_reduction.contracts, "
        "pii_reduction.entities, pii_reduction.providers, pii_reduction.parsers, "
        "pii_reduction.reducers, pii_reduction.processing, pii_reduction.databricks\n"
        "loaded = {name.split('.')[0] for name in sys.modules}\n"
        f"print(','.join(sorted(loaded & set({list(OPTIONAL_MODULES)!r}))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"core import loaded: {result.stdout.strip()}"


def test_contracts_package_imports_nothing_else_from_the_project() -> None:
    """``contracts`` is the hub: it may import itself and third-party libraries only."""
    offenders: list[str] = []
    for path in sorted(CONTRACTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for module in imported:
                if module.startswith("pii_reduction") and not module.startswith(
                    "pii_reduction.contracts"
                ):
                    offenders.append(f"{path.name} imports {module}")
    assert offenders == []


def test_license_is_mit() -> None:
    # ADR-0007. The Greek spaCy models are CC BY-NC-SA and must never become a dependency.
    licence_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in licence_text

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    extras = pyproject["project"]["optional-dependencies"]
    all_requirements = " ".join(
        requirement for requirements in extras.values() for requirement in requirements
    )
    assert "el_core_news" not in all_requirements

"""Packaging and layering guards.

Cheap structural tests for three promises that are easy to break silently, each one
invisible to the ordinary suite because breaking it changes no behaviour:

* the core package installs and runs without any NLP extra (ADR-0008),
* ``contracts`` stays the dependency hub nothing else leaks into,
* Spark stays inside the ``databricks/`` execution surface, and that surface stays
  unimported by everything else (``docs/01_ARCHITECTURE.md``, ADR-0006).
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
PACKAGE_DIR = REPO_ROOT / "src" / "pii_reduction"
DATABRICKS_DIR = PACKAGE_DIR / "databricks"

# Roots that only the Databricks execution surface may name. ``databricks`` covers
# ``databricks.connect``; ``pii_reduction.databricks`` does not start with it.
SPARK_ROOTS = ("pyspark", "databricks")

# Provider/runtime extras only. Faker is a `dev` extra and legitimately present in a
# developer environment (it also registers a pytest plugin, so it is always imported).
OPTIONAL_MODULES = ("presidio_analyzer", "spacy", "lingua", "pyspark", "databricks")


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    """Every module an import in ``path`` could name, at any nesting depth.

    Three deliberate choices, each one a hole that was open before it was made:

    * ``ast.walk`` rather than a scan of top-level statements — a function-local
      ``from pyspark.sql import ...`` is exactly how an optional runtime dependency
      sneaks past an import-time check.
    * ``from X import y`` is reported as ``X.y``, never as a bare ``X``, because
      ``y`` may itself be a submodule. `cli.py` shows the shape in its innocent form
      (``from pii_reduction import __version__``); with ``y = databricks`` the same
      shape is a layering violation, and a caller reading only ``node.module`` would
      see nothing but ``pii_reduction``. Reporting the joined name and *not* the
      prefix is what lets a caller judge ``import X`` and ``from X import y``
      differently — the contracts guard must reject the first and allow the second.
    * relative imports are resolved against the file's package, so ``from . import
      databricks`` is reported as the absolute name it actually binds rather than as
      a bare ``databricks`` that would look like the *vendor* package.

    Two limits it cannot cover, stated rather than implied: a dynamic
    ``importlib.import_module("pyspark")`` produces no import node at all, and an
    ``if TYPE_CHECKING:`` import is reported even though it is erased at runtime.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # `from . import x` / `from ..pkg import x`
                # Computed here rather than once per file so the helper stays usable
                # on paths outside the package (`demo/` holds runnable entry points).
                package_parts = path.parent.relative_to(PACKAGE_DIR.parent).parts
                base = ".".join(package_parts[: len(package_parts) - (node.level - 1)])
                prefix = f"{base}.{node.module}" if node.module else base
            elif node.module:
                prefix = node.module
            else:  # pragma: no cover - unreachable: level 0 always has a module
                continue
            found.extend((node.lineno, f"{prefix}.{alias.name}") for alias in node.names)
    return found


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
    """``contracts`` is the hub: it may import itself and third-party libraries only.

    ``rglob``, not ``glob``: a future ``contracts/`` subpackage must not fall out of
    the guard silently.
    """
    offenders: list[str] = []
    for path in sorted(CONTRACTS_DIR.rglob("*.py")):
        for lineno, module in _imported_modules(path):
            # `import pii_reduction` is deliberately *not* exempt: a plain import of
            # the root package from inside the hub is a partially-initialized cycle,
            # and it is the one shape a bare-prefix exemption used to hide.
            if module.startswith("pii_reduction") and not module.startswith(
                "pii_reduction.contracts"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == [], f"contracts is no longer the hub: {offenders}"


def test_only_the_databricks_surface_names_spark() -> None:
    """`pyspark`/`databricks.connect` are confined to `databricks/` (ADR-0006).

    The subprocess test above proves the optional runtime is not imported *eagerly*.
    It cannot prove exclusivity: it imports eight packages, so a module-level import
    in `evaluation/`, `synthetic/`, `cli.py` or `benchmark.py` would never be loaded,
    and a function-local import anywhere would not be loaded at all. This asserts the
    boundary `docs/01_ARCHITECTURE.md` actually claims — statically, over every
    source file, at every nesting depth.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if path.is_relative_to(DATABRICKS_DIR):
            continue
        for lineno, module in _imported_modules(path):
            if module.split(".")[0] in SPARK_ROOTS:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == [], f"Spark imported outside the Databricks surface: {offenders}"


def test_nothing_outside_the_databricks_surface_imports_it() -> None:
    """`databricks/` is an execution surface: it imports inward, nothing imports it.

    Pinning the direction is what lets the package be deleted without touching
    behaviour, and stops a runtime-path module reaching for a Spark-backed adapter.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if path.is_relative_to(DATABRICKS_DIR):
            continue
        for lineno, module in _imported_modules(path):
            if module == "pii_reduction.databricks" or module.startswith(
                "pii_reduction.databricks."
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == [], f"the Databricks surface is imported by: {offenders}"


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

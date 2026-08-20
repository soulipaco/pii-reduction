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
SERVICE_DIR = PACKAGE_DIR / "service"

#: The single file outside `databricks/` permitted to import the Databricks surface
#: (ADR-0026). An **exact relative path**, not a filename: matching `databricks.py`
#: by name would exempt any future file called that, anywhere in the package.
DATABRICKS_IMPORT_EXEMPTION = SERVICE_DIR / "runtimes" / "databricks.py"
#: The same fact as the line above, as the case-sensitive string the guard
#: compares. Derived rather than repeated, so the two cannot drift.
EXEMPT_RELATIVE_PATH = DATABRICKS_IMPORT_EXEMPTION.relative_to(REPO_ROOT).as_posix()

#: Packages the service layer may not name. It is rung 4: it assembles configurations
#: the engine validates and triggers entry points the engine owns, so a service that
#: cannot name a provider or a reducer cannot quietly reimplement one
#: (`docs/01_ARCHITECTURE.md`; ADR-0025's "the service layer owns no reduction logic",
#: made checkable). A naming rule, not runtime isolation — `processing/` imports all
#: of these, so the service *process* still loads them.
ENGINE_INTERNALS_CLOSED_TO_THE_SERVICE = (
    "pii_reduction.providers",
    "pii_reduction.reducers",
    "pii_reduction.parsers",
    "pii_reduction.language",
    "pii_reduction.entities",
    "pii_reduction.evaluation",
    "pii_reduction.sources",
    "pii_reduction.outputs",
    "pii_reduction.synthetic",
)

#: `processing/` is reachable, but only through the front door. `build_pipeline` and
#: `Pipeline` are what a run trigger needs; `field_processor` is the per-field
#: parse → detect → reconcile → reduce orchestrator, and a service reaching for it is
#: reaching for the engine's inside.
PROCESSING_MODULE_OPEN_TO_THE_SERVICE = "pii_reduction.processing.pipeline"

# Roots that only the Databricks execution surface may name. ``databricks`` covers
# ``databricks.connect``; ``pii_reduction.databricks`` does not start with it.
SPARK_ROOTS = ("pyspark", "databricks")

# Provider/runtime extras only. Faker is a `dev` extra and legitimately present in a
# developer environment (it also registers a pytest plugin, so it is always imported).
#: `fastapi` is here although it is also a `dev` dependency, and *because* it is:
#: the dev venv has it installed, so without it in this list the subprocess guard
#: would be blind to `service/__init__.py` gaining a convenience re-export of `api`
#: — the one change that would make `pii_reduction.service` un-importable in a core
#: install (ADR-0026).
OPTIONAL_MODULES = (
    "presidio_analyzer",
    "spacy",
    "lingua",
    "pyspark",
    "databricks",
    "fastapi",
)


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
        "pii_reduction.reducers, pii_reduction.processing, pii_reduction.databricks, "
        # `pii_reduction.service` is included for the same reason `providers` is: the
        # package must import in a core install, which is only true while
        # `service/__init__.py` stays clear of `api` (fastapi at module scope) and of
        # `runtimes.databricks`.
        "pii_reduction.service\n"
        "loaded = {name.split('.')[0] for name in sys.modules}\n"
        f"print(','.join(sorted(loaded & set({list(OPTIONAL_MODULES)!r}))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"core import loaded: {result.stdout.strip()}"


def test_importing_the_service_does_not_load_the_databricks_surface() -> None:
    """The optional runtime stays optional until somebody asks for it.

    `OPTIONAL_MODULES` cannot see this: importing `pii_reduction.databricks.runner`
    loads a module whose root package is `pii_reduction`, and the vendor `databricks`
    distribution is never touched — the surface is importable with no Spark at all,
    which is the property the lazy-session design rests on. So the check has to name
    `pii_reduction.databricks` directly.

    What it protects: `service/cli.py` imports the Databricks runtime *conditionally*,
    under `--databricks`. A convenience re-export in `service/__init__.py` or
    `service/runtimes/__init__.py` would make that conditional a lie, and nothing else
    would notice.
    """
    code = (
        "import sys, pii_reduction.service\n"
        "loaded = [n for n in sys.modules if n.startswith('pii_reduction.databricks')]\n"
        "print(','.join(sorted(loaded)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", (
        f"importing pii_reduction.service loaded the Databricks surface: {result.stdout.strip()}"
    )


def test_the_config_layer_only_reaches_the_taxonomy() -> None:
    """`config/` is the service layer's sanctioned relay, so its own edges are pinned.

    The service allowlist works by leaving `config/` open, which makes `config/` one
    convenience re-export away from being routed around — `known_labels` and
    `TAXONOMY` are exactly such re-exports, added deliberately in session 11. This
    bounds what a future one may relay: `config/` may reach `contracts/` and
    `entities/` (the taxonomy is a configuration vocabulary) and nothing else.
    """
    allowed = ("pii_reduction.config", "pii_reduction.contracts", "pii_reduction.entities")
    offenders: list[str] = []
    for path in sorted((PACKAGE_DIR / "config").rglob("*.py")):
        for lineno, module in _imported_modules(path):
            if not module.startswith("pii_reduction"):
                continue
            if any(module == name or module.startswith(f"{name}.") for name in allowed):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == [], f"the configuration layer reached outside its bounds: {offenders}"


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
    """`databricks/` is an execution surface: it imports inward, and almost nothing
    imports it.

    Pinning the direction is what stops a **runtime-path** module reaching for a
    Spark-backed adapter. The original rule said "nothing", which was a proxy for
    that: rung 4 is not on the engine path, and ADR-0026 exempts exactly one file so
    the service can offer the driver path. The exemption is narrow by construction —
    an exact relative path, asserted to exist — and
    `test_only_the_databricks_surface_names_spark` above is **not** exempted, so the
    one file that may import this surface still may not name `pyspark` or
    `databricks.connect`.
    """
    assert DATABRICKS_IMPORT_EXEMPTION.is_file(), (
        f"the exemption names {DATABRICKS_IMPORT_EXEMPTION.relative_to(REPO_ROOT)}, which "
        "does not exist. A renamed file silently turns a named exemption into a blanket "
        "one — point the exemption at the new path, or remove it"
    )
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        # Compared as a POSIX string rather than by `Path.__eq__`: `WindowsPath`
        # equality is case-insensitive, so a file named `Databricks.py` would be
        # exempt on a developer machine and rejected on CI.
        relative = path.relative_to(REPO_ROOT).as_posix()
        if path.is_relative_to(DATABRICKS_DIR) or relative == EXEMPT_RELATIVE_PATH:
            continue
        for lineno, module in _imported_modules(path):
            if module == "pii_reduction.databricks" or module.startswith(
                "pii_reduction.databricks."
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == [], f"the Databricks surface is imported by: {offenders}"


def test_nothing_outside_the_service_layer_imports_it() -> None:
    """The engine never learns that a service layer exists (ADR-0025's rung rule).

    The literal form of "each rung may only depend on the ones below it". It is what
    lets `service/` be deleted without touching behaviour, and — more usefully — what
    stops a convenience import in `cli.py` or `processing/` quietly making the engine
    depend on its own front end.

    It is also why `pii-reduction-service` is a third console script rather than a
    `pii-reduction serve` subcommand: the subcommand would need `cli.py` to import
    this package, and a function-local import would not help, because
    `_imported_modules` walks the AST.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if path.is_relative_to(SERVICE_DIR):
            continue
        for lineno, module in _imported_modules(path):
            if module == "pii_reduction.service" or module.startswith("pii_reduction.service."):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == [], f"the service layer is imported by: {offenders}"


def test_the_service_layer_cannot_name_the_engines_internals() -> None:
    """Makes "the service layer owns no reduction logic" a checkable property.

    Direction guards cannot say this: they stop `service/` being *imported*, not
    `service/` containing detection. An import allowlist can. What is left to it is
    `config/`, `processing/` (`build_pipeline`), `contracts/`, `observability/`, and
    the one Databricks file — enough to assemble a configuration, run it and report
    on it, and not enough to reimplement any of it. A capability the service needs
    that the engine lacks becomes a change to the engine.
    """
    offenders: list[str] = []
    for path in sorted(SERVICE_DIR.rglob("*.py")):
        for lineno, module in _imported_modules(path):
            closed_by = [
                closed
                for closed in ENGINE_INTERNALS_CLOSED_TO_THE_SERVICE
                if module == closed or module.startswith(f"{closed}.")
            ]
            open_module = PROCESSING_MODULE_OPEN_TO_THE_SERVICE
            processing_reached = module == "pii_reduction.processing" or module.startswith(
                "pii_reduction.processing."
            )
            # `==` or `<open>.` — a prefix test alone would silently open a future
            # `processing/pipeline_internals.py`. The bare package is closed too,
            # because `processing/__init__.py` re-exports `FieldProcessor`.
            through_the_front_door = module == open_module or module.startswith(f"{open_module}.")
            if processing_reached and not through_the_front_door:
                closed_by.append("pii_reduction.processing (except .pipeline)")
            for closed in closed_by:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module} (closed: {closed})"
                )
    assert offenders == [], (
        "the service layer reached into the engine's internals; route it through "
        f"`config/`, or change the engine: {offenders}"
    )


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

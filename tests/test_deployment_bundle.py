"""The deployment skeleton, checked for the one property it actually promises.

P4's requirement is "zero hard-coded workspace values". That is a claim a test can
hold, and it is the claim worth holding: a bundle that quietly grows a host, a
catalog literal, a personal workspace path or a cluster id is how a workspace ends up
named in a public repository (`AGENTS.md` Databricks rules, rule 1).

**Every deployment file is scanned, discovered rather than listed** — including
`resources/README.md`, because prose is the likeliest place a real host lands: someone
pastes the curl command that worked. An added `resources/*.yml` is deployed by the
bundle's own `include:`, so it must be covered the moment it exists rather than the
moment someone remembers to add it here.

What these tests deliberately do **not** claim: that the bundle deploys, or that the
job runs. Neither has ever happened — see `resources/README.md`. Parsing YAML is not
validation, and calling it that would be exactly the kind of overstatement the
runbook's own status block exists to avoid.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE = REPO_ROOT / "databricks.yml"
RESOURCES = REPO_ROOT / "resources"
JOB = RESOURCES / "pii_reduction_job.yml"


def deployment_files() -> list[Path]:
    """Everything the bundle deploys, plus the prose that explains it."""
    return [BUNDLE, *sorted(RESOURCES.glob("*.yml")), *sorted(RESOURCES.glob("*.md"))]


#: Shapes that identify a workspace, an account, or a person. A committed deployment
#: file may contain none of them; every such value belongs to a variable, an
#: environment variable, or the dataset config under review.
FORBIDDEN = (
    # Schemeless too: `host: dbc-x.cloud.databricks.com` is a host without `https://`.
    (
        re.compile(r"[\w.-]+\.(?:cloud\.databricks\.com|azuredatabricks\.net)", re.I),
        "a workspace host",
    ),
    (re.compile(r"\badb-\d{4,}", re.I), "a workspace id"),
    (re.compile(r"\bdapi[0-9a-f]{8,}", re.I), "a personal access token"),
    (re.compile(r"\bdose[0-9a-f]{8,}", re.I), "an OAuth secret"),
    (re.compile(r"\b(?:client_secret|token|password)\s*[:=]\s*[\"']?\w{8,}", re.I), "a secret"),
    (re.compile(r"\b\d{4}-\d{6}-[a-z0-9]{8}\b"), "a cluster id"),
    (
        re.compile(r"\b(?:warehouse_id|existing_cluster_id|instance_pool_id)\b", re.I),
        "a pinned resource",
    ),
    # `/Users/<person>@<company>/...` is AGENTS.md rule 1's own example, and what the
    # bundle CLI writes by default into `workspace.root_path`.
    (re.compile(r"/Users/"), "a personal workspace path"),
    # Any real-looking address: a notification recipient is personal data.
    (re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I), "an email address"),
)


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name} must be a YAML mapping"
    return loaded


class TestNoWorkspaceValues:
    def test_every_deployment_file_is_covered(self) -> None:
        # The guard is only as good as its file list, and the list is discovered.
        names = {path.name for path in deployment_files()}
        assert {"databricks.yml", "pii_reduction_job.yml", "README.md"} <= names

    @pytest.mark.parametrize("path", deployment_files(), ids=lambda p: p.name)
    def test_the_file_names_no_workspace_and_no_person(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        for pattern, what in FORBIDDEN:
            match = pattern.search(text)
            assert match is None, (
                f"{path.name} contains {what} ({match.group(0)!r}). Deployment files "
                "name variables; values come from the environment at deploy time, or "
                "from the dataset config under review (AGENTS.md)"
            )

    def test_no_workspace_block_pins_a_host(self) -> None:
        """The CLI resolves the workspace from the profile it is authenticated with.

        Checked at the root as well as per target: a top-level ``workspace:`` mapping
        is valid bundle syntax and would be missed by walking targets alone.
        """
        bundle = _load(BUNDLE)
        assert "host" not in bundle.get("workspace", {}), "the bundle root pins a host"
        for name, target in bundle["targets"].items():
            assert "host" not in target.get("workspace", {}), f"target {name!r} pins a host"

    def test_no_variable_carries_a_value_that_could_name_a_workspace(self) -> None:
        """Only the two path-ish variables may have defaults, and neither is a table.

        A `catalog`/`schema` variable with a default is the shape this guards
        against: it reads as harmless and silently decides where a deploy writes.
        """
        variables = _load(BUNDLE)["variables"]
        assert set(variables) == {"dataset", "configs_path"}, (
            "a new bundle variable appeared. Destinations belong to the dataset "
            "config, not to deploy-time overrides — see resources/README.md"
        )
        assert variables["dataset"]["default"] == "databricks_table_example"
        # A bundle substitution, not a literal path and not a relative one: resolved
        # at deploy time, so it commits nothing about a workspace.
        assert variables["configs_path"]["default"] == "${workspace.file_path}/configs"


class TestTheJobRunsTheShippedEntryPoint:
    def _task(self) -> dict[str, Any]:
        job = _load(JOB)["resources"]["jobs"]["pii_reduction"]
        tasks: list[dict[str, Any]] = job["tasks"]
        assert len(tasks) == 1, "one task, one entry point"
        return tasks[0]

    def test_it_calls_the_console_script_this_repository_ships(self) -> None:
        task = self._task()["python_wheel_task"]
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            scripts = tomllib.load(handle)["project"]["scripts"]
        assert task["entry_point"] in scripts, (
            "the job's entry point is not a console script this package defines — "
            "a job that calls something else is a second implementation"
        )
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            distribution = tomllib.load(handle)["project"]["name"]
        assert task["package_name"] == distribution.replace("-", "_")

    def test_it_names_a_dataset_and_never_a_destination(self) -> None:
        """What a scheduled job touches must be reviewable in git.

        Parameters name a dataset config; the config names the tables. Any override
        flag here would move that decision into a job definition someone can edit in
        a browser — including `--reduced-only-prefix`, which decides where the
        broader-grant artifact lands (ADR-0024).
        """
        parameters = self._task()["python_wheel_task"]["parameters"]
        assert parameters[:2] == ["run", "${var.dataset}"]
        joined = " ".join(parameters)
        for flag in (
            "--source-table",
            "--destination-prefix",
            "--reduced-only-prefix",
            "--mode",
            "--profile",
        ):
            assert flag not in joined, f"{flag} belongs in the dataset config, not the job"

    def test_the_default_dataset_exists(self) -> None:
        dataset = _load(BUNDLE)["variables"]["dataset"]["default"]
        assert (REPO_ROOT / "configs" / "datasets" / f"{dataset}.yaml").is_file()

    def test_no_notebook_task(self) -> None:
        # AGENTS.md rule 3: a scheduled notebook is the usual way logic escapes the
        # package.
        assert "notebook_task" not in JOB.read_text(encoding="utf-8")

    def test_it_does_not_arrive_scheduled(self) -> None:
        """A skeleton that ships scheduled runs before anyone has read it."""
        job = _load(JOB)["resources"]["jobs"]["pii_reduction"]
        assert "schedule" not in job
        assert "continuous" not in job

    def test_the_parameters_are_accepted_by_the_shipped_parser(self) -> None:
        """The regression this file exists to catch, and previously could not.

        Renaming `--configs` in the CLI would leave every other test here green and
        break every scheduled run. Substituting the bundle variables and parsing the
        list with the real parser is what makes that a test failure instead of a
        production one.
        """
        from pii_reduction.databricks.cli import _build_parser

        variables = _load(BUNDLE)["variables"]
        substitutions = {
            "${var.dataset}": variables["dataset"]["default"],
            "${var.configs_path}": "configs",  # the substitution's deploy-time value
        }
        raw = self._task()["python_wheel_task"]["parameters"]
        argv = [substitutions.get(item, item) for item in raw]

        args = _build_parser().parse_args(argv)
        assert args.command == "run"
        assert args.dataset == variables["dataset"]["default"]
        assert str(args.configs) == "configs"

    def test_every_task_names_an_environment_that_exists(self) -> None:
        # A typo here is a deploy-time failure that no other test would see.
        job = _load(JOB)["resources"]["jobs"]["pii_reduction"]
        declared = {environment["environment_key"] for environment in job["environments"]}
        for task in job["tasks"]:
            assert task["environment_key"] in declared

    def test_it_configures_no_credential(self) -> None:
        """The job authenticates as itself on compute; nothing else belongs here."""
        job = _load(JOB)["resources"]["jobs"]["pii_reduction"]
        for key in ("run_as", "git_source"):
            assert key not in job
        assert "spark_conf" not in self._task()

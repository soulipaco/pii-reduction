"""Run provenance: real versions in `RunMetadata` (docs/17 D2, session 9).

The integration workflow pins model versions because a bump can move a gate; these
tests hold the run record to the same standard. Everything here is default-tier:
version lookups go through ``importlib.metadata`` and never import an optional
dependency, so the assertions are written to hold both on a machine with every
extra installed and on the model-free CI push tier.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from pii_reduction.observability.versions import describe_versions, distribution_version
from pii_reduction.processing.pipeline import build_pipeline
from pii_reduction.providers.registry import (
    PROVIDER_DISTRIBUTIONS,
    available_provider_types,
    provider_distributions,
)
from pii_reduction.reducers.pseudonymize import DEFAULT_KEY_ENV
from pii_reduction.sources import PandasSource, SourceDataset
from tests.pipeline_fixtures import PROJECT_YAML, build_frame
from tests.test_pipeline import make_config

pytestmark = pytest.mark.unit

TEST_KEY = "test-key-not-a-real-secret-0123456789"


@pytest.fixture
def dataset() -> SourceDataset:
    return PandasSource(build_frame(), name="demo_smoke").load()


class TestVersionHelpers:
    def test_distribution_version_resolves_an_installed_package(self) -> None:
        # pydantic is a core dependency and is always present.
        version = distribution_version("pydantic")
        assert version is not None and version[0].isdigit()

    def test_distribution_version_is_none_for_a_missing_package(self) -> None:
        assert distribution_version("not-a-real-distribution-xyz") is None

    def test_describe_versions_composes_installed_versions(self) -> None:
        described = describe_versions("example", ("pydantic",))
        assert described.startswith("example (pydantic ")

    def test_describe_versions_degrades_to_the_bare_type_name(self) -> None:
        # The degraded form is exactly the pre-provenance value, so a machine
        # without an extra records what it always recorded.
        assert describe_versions("presidio", ("not-a-real-distribution-xyz",)) == "presidio"


class TestProviderDistributions:
    def test_every_provider_type_declares_its_distributions(self) -> None:
        # The mapping lives with the providers (ADR-0004's boundary applied to
        # provenance); this pins it to what can actually be built.
        assert set(PROVIDER_DISTRIBUTIONS) == set(available_provider_types())

    def test_configured_models_join_the_distribution_list(self) -> None:
        distributions = provider_distributions(
            "presidio", {"models": {"en": "en_core_web_md", "el": "xx_ent_wiki_sm"}}
        )
        assert (
            distributions[: len(PROVIDER_DISTRIBUTIONS["presidio"])]
            == PROVIDER_DISTRIBUTIONS["presidio"]
        )
        assert "en_core_web_md" in distributions and "xx_ent_wiki_sm" in distributions

    def test_a_provider_without_models_gets_the_type_level_list_only(self) -> None:
        assert provider_distributions("deterministic", {}) == ("phonenumbers",)


class TestRunMetadataVersions:
    def test_provider_versions_carry_real_library_versions(
        self, tmp_path: Path, dataset: SourceDataset
    ) -> None:
        # phonenumbers is a core dependency, so the deterministic provider's
        # entry must always resolve to a concrete version.
        outcome = build_pipeline(make_config(tmp_path)).process(dataset)
        recorded = outcome.run.provider_versions["deterministic"]
        assert recorded.startswith("deterministic (phonenumbers ")

    def test_detector_version_is_none_without_detection(
        self, tmp_path: Path, dataset: SourceDataset
    ) -> None:
        # The fixture resolves language from a column; no detector runs, so no
        # detector version is claimed.
        outcome = build_pipeline(make_config(tmp_path)).process(dataset)
        assert outcome.run.language_detector_version is None

    def test_detector_version_is_recorded_for_detect_mode(self, tmp_path: Path) -> None:
        """Wiring only: zero rows are processed, so lingua is never imported.

        The value is `"lingua (lingua-language-detector X)"` where the extra is
        installed and the bare `"lingua"` where it is not — both start the same,
        which keeps this default-tier assertion machine-independent.
        """
        marker = "  mode: column\n  detector: none\n  language_column: language\n"
        assert marker in PROJECT_YAML
        project = PROJECT_YAML.replace(marker, "  mode: detect\n  detector: lingua\n")
        pipeline = build_pipeline(make_config(tmp_path, project_yaml=project))
        empty = PandasSource(build_frame().iloc[0:0], name="demo_smoke").load()
        outcome = pipeline.process(empty)
        version = outcome.run.language_detector_version
        assert version is not None and version.startswith("lingua")


class TestPseudonymizationKeyId:
    def test_a_pseudonymizing_run_records_a_key_id(
        self, tmp_path: Path, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEFAULT_KEY_ENV, TEST_KEY)
        project = PROJECT_YAML.replace("default_reducer: redact", "default_reducer: pseudonymize")
        outcome = build_pipeline(make_config(tmp_path, project_yaml=project)).process(dataset)

        expected = hmac.new(TEST_KEY.encode(), b"pii-reduction-key-id", hashlib.sha256).hexdigest()[
            :8
        ]
        assert outcome.run.pseudonymization_key_id == expected

    def test_the_key_id_is_not_the_key_and_reveals_nothing_of_it(
        self, tmp_path: Path, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEFAULT_KEY_ENV, TEST_KEY)
        project = PROJECT_YAML.replace("default_reducer: redact", "default_reducer: pseudonymize")
        outcome = build_pipeline(make_config(tmp_path, project_yaml=project)).process(dataset)

        key_id = outcome.run.pseudonymization_key_id
        assert key_id is not None
        assert len(key_id) == 8
        assert key_id not in TEST_KEY and TEST_KEY not in key_id

    def test_key_rotation_changes_the_recorded_id(
        self, tmp_path: Path, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The point of the field: a rotation is a visible provenance change
        # instead of a silent break in referential consistency.
        project = PROJECT_YAML.replace("default_reducer: redact", "default_reducer: pseudonymize")
        monkeypatch.setenv(DEFAULT_KEY_ENV, "test-key-one-0123456789abcdefghij")
        first = build_pipeline(make_config(tmp_path / "a", project_yaml=project)).process(dataset)
        monkeypatch.setenv(DEFAULT_KEY_ENV, "test-key-two-0123456789abcdefghij")
        second = build_pipeline(make_config(tmp_path / "b", project_yaml=project)).process(dataset)
        assert first.run.pseudonymization_key_id != second.run.pseudonymization_key_id

    def test_a_redacting_run_records_no_key_id(
        self, tmp_path: Path, dataset: SourceDataset
    ) -> None:
        outcome = build_pipeline(make_config(tmp_path)).process(dataset)
        assert outcome.run.pseudonymization_key_id is None

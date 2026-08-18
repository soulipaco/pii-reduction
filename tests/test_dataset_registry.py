"""The public-dataset registry is a licence gate, so its refusals are the tests.

``docs/02_PUBLIC_DATA_STRATEGY.md`` requires a provenance record per dataset. What
makes that more than paperwork is that a pack cannot be built without one, and that
the shipped registry is itself checked — an entry that quietly loses its licence field
should fail here rather than at publication time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.registry import (
    ALLOWED_LICENCES,
    load_registry,
    require_publishable,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "demo" / "registry.yaml"

VALID = {
    "name": "Example corpus",
    "source_url": "https://example.com/dataset",
    "license": "MIT",
    "redistribution_allowed": True,
    "contains_real_pii": False,
    "retrieval_method": "huggingface",
    "version": "1.0",
    "document_type": "plain",
    "languages": ["en"],
}


def write(tmp_path: Path, entry: dict[str, object], key: str = "example") -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "datasets": {key: entry}}), encoding="utf-8")
    return path


class TestTheShippedRegistry:
    def test_it_loads_and_every_entry_validates(self) -> None:
        entries = load_registry(REGISTRY)
        assert set(entries) == {"bitext_customer_support", "massive"}

    def test_every_entry_is_publishable(self) -> None:
        # Nothing should be in `datasets:` that a pack cannot be built from — a source
        # that fails the gate belongs under `rejected:` with its reason.
        for key, entry in load_registry(REGISTRY).items():
            assert entry.publishable, f"{key} is listed but not publishable"

    def test_no_entry_carries_real_pii(self) -> None:
        assert all(entry.contains_real_pii is False for entry in load_registry(REGISTRY).values())

    def test_the_share_alike_source_is_flagged_as_such(self) -> None:
        # CDLA-Sharing-1.0 is permitted but its obligation travels to derived packs,
        # which is the decision point ADR-0010 recorded.
        bitext = load_registry(REGISTRY)["bitext_customer_support"]
        assert bitext.license == "CDLA-Sharing-1.0"
        assert bitext.share_alike is True

    def test_the_rejected_dataset_stays_recorded_with_its_reason(self) -> None:
        # So a later session does not re-litigate a corpus already ruled out.
        raw = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        rejected = raw["rejected"]["kaggle_customer_support_twitter"]
        assert rejected["contains_real_pii"] is True
        assert "reason" in rejected

    def test_the_registry_covers_all_three_languages(self) -> None:
        languages = {
            language for entry in load_registry(REGISTRY).values() for language in entry.languages
        }
        assert {"en", "de", "el"} <= languages

    def test_multiwoz_is_rejected_for_carrying_real_pii(self) -> None:
        """The finding that justifies the whole registry (session-5 privacy audit).

        MultiWOZ's dialogues are fictional but the entities in them are a scrape of
        real Cambridge venue listings, read aloud by the wizard and therefore present
        in the published text. `contains_real_pii: false` was wrong, and the gate
        would have waved through hundreds of real dialable UK numbers.
        """
        raw = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        assert "multiwoz_22" not in raw["datasets"]
        rejected = raw["rejected"]["multiwoz_22"]
        assert rejected["contains_real_pii"] is True
        assert "ADR-0010" in rejected["reason"]

    def test_a_provenance_claim_is_not_self_certifying(self) -> None:
        # These assertions check the registry agrees with itself; they cannot check it
        # agrees with the world. MultiWOZ passed every one of them while being wrong.
        # Kept as a marker so nobody mistakes a green suite for a licence review.
        for entry in load_registry(REGISTRY).values():
            assert entry.contains_real_pii is False


class TestValidation:
    def test_a_missing_file_is_actionable(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusError, match="registry not found"):
            load_registry(tmp_path / "absent.yaml")

    @pytest.mark.parametrize("field", sorted(VALID))
    def test_every_required_field_is_required(self, tmp_path: Path, field: str) -> None:
        entry = {key: value for key, value in VALID.items() if key != field}
        with pytest.raises(CorpusError, match=f"missing required field.*{field}"):
            load_registry(write(tmp_path, entry))

    def test_a_restrictive_licence_is_refused_at_load(self, tmp_path: Path) -> None:
        # The el_core_news_lg lesson (ADR-0007), applied to corpora: a non-commercial
        # source poisons everything derived from it.
        path = write(tmp_path, {**VALID, "license": "CC-BY-NC-SA-4.0"})
        with pytest.raises(CorpusError, match="not on the permitted list"):
            load_registry(path)

    def test_an_unknown_retrieval_method_is_refused(self, tmp_path: Path) -> None:
        path = write(tmp_path, {**VALID, "retrieval_method": "email_from_a_colleague"})
        with pytest.raises(CorpusError, match="retrieval_method"):
            load_registry(path)

    def test_languages_must_be_a_non_empty_list(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusError, match="non-empty list"):
            load_registry(write(tmp_path, {**VALID, "languages": []}))

    def test_an_empty_registry_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "datasets": {}}), encoding="utf-8")
        with pytest.raises(CorpusError, match="no 'datasets' mapping"):
            load_registry(path)


class TestTheGate:
    def test_an_unregistered_dataset_cannot_be_used(self, tmp_path: Path) -> None:
        # The failure this exists to prevent: building a pack from a corpus whose
        # licence nobody ever checked.
        path = write(tmp_path, VALID)
        with pytest.raises(CorpusError, match="no registry entry"):
            require_publishable("something_someone_downloaded", path=path)

    def test_real_pii_is_refused_whatever_the_licence_says(self, tmp_path: Path) -> None:
        path = write(tmp_path, {**VALID, "contains_real_pii": True})
        with pytest.raises(CorpusError, match="real personal data"):
            require_publishable("example", path=path)

    def test_possible_real_pii_is_refused_too(self, tmp_path: Path) -> None:
        # docs/02 allows `possible`; for building a pack that is not good enough.
        path = write(tmp_path, {**VALID, "contains_real_pii": "possible"})
        with pytest.raises(CorpusError, match="real personal data"):
            require_publishable("example", path=path)

    def test_a_non_redistributable_source_is_refused(self, tmp_path: Path) -> None:
        path = write(tmp_path, {**VALID, "redistribution_allowed": False})
        with pytest.raises(CorpusError, match="redistribution is not permitted"):
            require_publishable("example", path=path)

    @pytest.mark.parametrize("value", ["unknown", "yes", "", 0, 1])
    def test_redistribution_must_be_a_real_boolean(self, tmp_path: Path, value: object) -> None:
        # `bool("unknown")` is True, and docs/02 documents `unknown` as a legal value —
        # so a coercing read turns "nobody checked" into "yes, publish it".
        path = write(tmp_path, {**VALID, "redistribution_allowed": value})
        with pytest.raises(CorpusError, match="must be true or false"):
            load_registry(path)

    def test_share_alike_must_be_a_real_boolean(self, tmp_path: Path) -> None:
        path = write(tmp_path, {**VALID, "share_alike": "no"})
        with pytest.raises(CorpusError, match="must be true or false"):
            load_registry(path)

    def test_a_clean_entry_passes(self, tmp_path: Path) -> None:
        entry = require_publishable("example", path=write(tmp_path, VALID))
        assert entry.key == "example"
        assert entry.publishable

    @pytest.mark.parametrize("licence", sorted(ALLOWED_LICENCES))
    def test_every_permitted_licence_actually_passes(self, tmp_path: Path, licence: str) -> None:
        path = write(tmp_path, {**VALID, "license": licence})
        assert require_publishable("example", path=path).license == licence

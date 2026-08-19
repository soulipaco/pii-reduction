"""Label promotion: the option, and the scope the shipped configuration gives it.

Default tier deliberately. Constructing a ``PresidioProvider`` imports no optional
runtime — the engine is built lazily — so the validation rules and, more importantly,
the *scoping* of promotion in ``configs/providers.yaml`` are guarded on every push.
The detection behaviour promotion produces needs the models and lives in
``test_providers_presidio.py`` under the integration marker.

The scoping guard is the one that matters. ADR-0020 measured promotion applied to
every language: English PERSON precision 0.833 -> 0.694, German 0.963 -> 0.839, and
over-redaction off its 0.000 gate. Nothing in the type system stops someone adding
``promote`` to the ``presidio`` instance and reproducing exactly that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from pii_reduction.entities.mapping import DropCounter
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.providers import build_provider
from pii_reduction.providers.errors import ProviderError
from pii_reduction.providers.presidio_provider import (
    DROPPED_LABELS,
    NATIVE_LABELS,
    PROMOTABLE_LABELS,
    PresidioProvider,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_YAML = REPO_ROOT / "configs" / "providers.yaml"


@pytest.fixture(scope="module")
def shipped() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(PROVIDERS_YAML.read_text(encoding="utf-8"))
    return loaded


class TestPromoteOption:
    def test_promotion_is_off_by_default(self) -> None:
        provider = PresidioProvider()
        assert provider.supported_entities() == {PERSON, EMAIL, PHONE}
        assert provider._mapping.table.get("LOCATION") is None

    def test_a_promoted_label_maps_to_person(self) -> None:
        provider = PresidioProvider({"promote": ["LOCATION"]})
        assert provider._mapping.table["LOCATION"] == PERSON

    def test_a_promoted_label_leaves_the_drop_set(self) -> None:
        # LOCATION ships in DROPPED_LABELS. If promotion left it there, drop_counter
        # would report a configured behaviour as an unbidden arrival on every hit —
        # and LabelMapping refuses a label that is in both, so this would not even
        # construct.
        assert "LOCATION" in DROPPED_LABELS
        provider = PresidioProvider({"promote": ["LOCATION"]})
        assert "LOCATION" not in provider._mapping.dropped

    def test_an_unpromotable_label_is_refused(self) -> None:
        # Promoting URL or DATE_TIME is a category error, not a coverage choice.
        with pytest.raises(ProviderError) as exc_info:
            PresidioProvider({"promote": ["URL"]})
        message = str(exc_info.value)
        assert "URL" in message
        assert "LOCATION" in message, "the error must name what *is* promotable"

    def test_an_already_mapped_label_is_refused(self) -> None:
        # Refused by the promotable check rather than by a rule of its own: the two
        # sets are disjoint (asserted below), so a separate "already mapped" branch
        # would be unreachable. Pinned here because that holds only while they stay
        # disjoint.
        with pytest.raises(ProviderError, match="cannot promote PERSON"):
            PresidioProvider({"promote": ["PERSON"]})

    def test_a_bare_string_is_refused_rather_than_iterated(self) -> None:
        # "LOCATION" would otherwise iterate as characters and fail with a confusing
        # message about the label 'L'.
        with pytest.raises(ProviderError, match="not a string"):
            PresidioProvider({"promote": "LOCATION"})

    def test_promotable_labels_are_the_ones_a_name_can_hide_under(self) -> None:
        assert {"LOCATION", "ORGANIZATION", "NRP"} == PROMOTABLE_LABELS
        # Disjoint from the labels already mapped — this is what makes a separate
        # "already mapped" validation rule unnecessary rather than merely absent.
        assert not PROMOTABLE_LABELS & set(NATIVE_LABELS)


class TestDropAttribution:
    """A drop must name the instance that made it, not the class default."""

    def test_a_renamed_instance_attributes_its_own_drops(self) -> None:
        # `build_provider` assigns `name` after construction. With one Presidio
        # instance that was invisible; with two, the Greek instance's drops would file
        # under `presidio` and `pipeline` merges the counters, so they would silently
        # sum into the English instance's key — losing the signal ADR-0004 keeps drop
        # counts for.
        provider = build_provider(
            "presidio",
            {"models": {"el": "xx_ent_wiki_sm"}, "promote": ["LOCATION"]},
            name="presidio_el",
        )
        # `build_provider` is typed to the base class; the rename it performs is the
        # whole point of this test, so narrow rather than cast.
        assert isinstance(provider, PresidioProvider)
        assert provider._mapping.provider == "presidio_el"

        counter = DropCounter()
        provider._mapping.normalize("NRP", counter=counter)
        assert dict(counter.declared) == {"presidio_el:NRP": 1}

    def test_the_default_name_is_still_used_when_nothing_renames_it(self) -> None:
        assert PresidioProvider()._mapping.provider == "presidio"


class TestShippedScope:
    """ADR-0020: promotion is enabled for Greek and for nothing else."""

    def test_the_general_presidio_instance_does_not_promote(self, shipped: dict[str, Any]) -> None:
        options = shipped["providers"]["presidio"].get("options", {})
        assert not options.get("promote"), (
            "promotion on the general instance costs en PERSON precision 0.833 -> 0.694 "
            "and de 0.963 -> 0.839, and takes over-redaction off 0.000 (ADR-0020)"
        )

    def test_the_general_presidio_instance_does_not_serve_greek(
        self, shipped: dict[str, Any]
    ) -> None:
        # Two instances serving el would be a second opinion on the same text rather
        # than a routing split, and `language_scopes` would send Greek to both.
        assert "el" not in shipped["providers"]["presidio"]["languages"]

    def test_greek_is_served_by_the_promoting_instance(self, shipped: dict[str, Any]) -> None:
        greek = shipped["providers"]["presidio_el"]
        assert greek["languages"] == ["el"]
        assert greek["options"]["promote"] == ["LOCATION", "ORGANIZATION"]

    def test_nrp_is_not_enabled(self, shipped: dict[str, Any]) -> None:
        # Promotable, but MISC does not map to it, so it never fires. Enabling it
        # would ship a path nothing measures.
        assert "NRP" not in shipped["providers"]["presidio_el"]["options"]["promote"]

    def test_both_instances_keep_the_same_thresholds_and_calibration(
        self, shipped: dict[str, Any]
    ) -> None:
        # `ReconciliationPolicy.thresholds` is keyed per provider *name*, so divergent
        # values would quietly filter Greek differently from en/de with no error
        # anywhere. Not worth a config-inheritance mechanism for one duplicated pair —
        # worth an assertion that they have not drifted.
        general, greek = shipped["providers"]["presidio"], shipped["providers"]["presidio_el"]
        assert greek["thresholds"] == general["thresholds"]
        assert greek["calibration"] == general["calibration"]

    def test_greek_keeps_the_mit_licensed_model(self, shipped: dict[str, Any]) -> None:
        # ADR-0007 survives the split: the promoting instance is where a well-meaning
        # accuracy fix would reach for el_core_news_*.
        assert shipped["providers"]["presidio_el"]["options"]["models"] == {"el": "xx_ent_wiki_sm"}

    def test_the_hybrid_chain_runs_both_instances(self, shipped: dict[str, Any]) -> None:
        chain = shipped["chains"]["deterministic_presidio"]["providers"]
        assert list(chain) == ["deterministic", "presidio", "presidio_el"]

    def test_the_deterministic_chain_is_untouched(self, shipped: dict[str, Any]) -> None:
        # The whole point of keeping the split inside the chain: `with_chain` does not
        # override a language route, so a project-level route would apply Presidio to
        # Greek during the deterministic benchmark and corrupt that baseline.
        assert list(shipped["chains"]["deterministic_only"]["providers"]) == ["deterministic"]

    def test_no_project_level_language_route_was_added(self) -> None:
        project = yaml.safe_load(
            (REPO_ROOT / "configs" / "project.yaml").read_text(encoding="utf-8")
        )
        assert not project.get("languages"), (
            "promotion is scoped by provider language, not by a `languages:` route — "
            "benchmark.with_chain overrides a column's chain but not a route (ADR-0020)"
        )

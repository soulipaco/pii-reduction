"""The demo packs' regression gates: a new gate set per pack, on its own corpus.

These cannot run in CI. Building a pack needs a download and CI is deliberately offline
(ADR-0017), so nothing else would notice if one of these files rotted into something the
loader cannot read. That is what these tests are for: they check the **files**, not the
numbers — the numbers need the pack, and the pack needs the network.

The other half of the job is keeping the two gate sets apart. A pack that scores well is
never a reason to loosen a floor guarding the committed synthetic corpus (plan §8 Q3).
"""

from __future__ import annotations

import pytest

from pii_reduction.cli import DEFAULT_SEED
from pii_reduction.evaluation.gates import load_gate_file
from pii_reduction.synthetic.packs import PACKS
from pii_reduction.synthetic.registry import load_registry
from tests.test_benchmark import REPO_ROOT
from tests.test_benchmark_gates import read_yaml

pytestmark = pytest.mark.unit

PACK_GATE_DIR = REPO_ROOT / "configs" / "pack_gates"

#: Gate files that describe a size variant of a pack rather than a PackSpec of their
#: own. Enumerated explicitly so the loader coverage below cannot silently skip a
#: file that exists on disk but matches no spec name.
VARIANT_GATE_FILES = {"support_tickets_10k": "bitext_customer_support"}


class TestThePackGateFiles:
    """A pack's gates are a new gate set on its own corpus, never a replacement.

    They cannot run in CI: building a pack needs a download and CI is deliberately
    offline (ADR-0017). So nothing else would notice if one of these files rotted into
    something the loader cannot read, which is what these tests are for. They check the
    files, not the numbers — the numbers need the pack, and the pack needs the network.
    """

    @pytest.mark.parametrize("pack", sorted(PACKS) + sorted(VARIANT_GATE_FILES))
    @pytest.mark.parametrize("gate_set", ["deterministic_only", "deterministic_presidio"])
    def test_every_pack_gate_file_loads_for_every_chain(self, pack: str, gate_set: str) -> None:
        gates = load_gate_file(PACK_GATE_DIR / f"{pack}.yaml", gate_set)
        assert gates
        assert all(gate.min_support is not None for gate in gates), (
            "every gate must record the support it was measured over"
        )

    @pytest.mark.parametrize("pack", sorted(PACKS))
    def test_the_provenance_names_the_bytes_it_was_measured_on(self, pack: str) -> None:
        # A pack is rebuilt rather than committed, so the source revision is the only
        # thing that makes its published numbers reproducible.
        measured = read_yaml(PACK_GATE_DIR / f"{pack}.yaml")["measured"]
        assert {"pack", "source", "source_revision", "seed", "splits", "strategy"} <= set(measured)
        assert measured["seed"] == DEFAULT_SEED
        assert len(measured["source_revision"]) == 40

    @pytest.mark.parametrize("pack", sorted(PACKS))
    def test_the_recorded_revision_is_the_one_the_registry_would_fetch(self, pack: str) -> None:
        # Drift here means the floors were measured on a corpus nobody can rebuild.
        entry = load_registry(REPO_ROOT / "demo" / "registry.yaml")[PACKS[pack].dataset]
        measured = read_yaml(PACK_GATE_DIR / f"{pack}.yaml")["measured"]
        assert measured["source_revision"] == entry.require_retrieval().revision

    def test_no_gate_file_exists_without_coverage_here(self) -> None:
        # A file on disk that neither PACKS nor VARIANT_GATE_FILES names would be
        # loaded by nobody and could rot unnoticed — the exact failure this module
        # exists to catch.
        on_disk = {path.stem for path in PACK_GATE_DIR.glob("*.yaml")}
        covered = set(PACKS) | set(VARIANT_GATE_FILES)
        assert on_disk == covered, f"uncovered gate files: {sorted(on_disk ^ covered)}"

    def test_the_10k_variant_pins_the_same_source_revision(self) -> None:
        # A variant is the same corpus at a different size; if its pin drifts from the
        # registry's, its floors were measured on bytes nobody can rebuild.
        entry = load_registry(REPO_ROOT / "demo" / "registry.yaml")["bitext_customer_support"]
        measured = read_yaml(PACK_GATE_DIR / "support_tickets_10k.yaml")["measured"]
        assert measured["source_revision"] == entry.require_retrieval().revision
        assert measured["seed"] == DEFAULT_SEED

    def test_no_variant_gate_file_carries_a_wall_clock_gate(self) -> None:
        # ADR-0009, stated at the exact place a throughput floor would be tempting:
        # the 10k report publishes rows/s beside these floors, and the floor must
        # never follow the number into the gate file.
        for variant in VARIANT_GATE_FILES:
            for gate_set in ("deterministic_only", "deterministic_presidio"):
                for gate in load_gate_file(PACK_GATE_DIR / f"{variant}.yaml", gate_set):
                    assert "rows" not in gate.metric and "second" not in gate.metric

    def test_a_pack_with_no_protected_tokens_has_no_over_redaction_gate(self) -> None:
        """A gate that measures nothing must never be green (ADR-0009).

        MASSIVE carries no identifiers, so that pack's over-redaction support is zero.
        The gate is deliberately absent rather than present and vacuous.
        """
        for gate_set in ("deterministic_only", "deterministic_presidio"):
            gates = load_gate_file(PACK_GATE_DIR / "multilingual_utterances.yaml", gate_set)
            assert not [gate for gate in gates if gate.metric == "over_redaction_rate"]

    def test_each_file_declares_which_pack_it_measures(self) -> None:
        for pack in PACKS:
            measured = read_yaml(PACK_GATE_DIR / f"{pack}.yaml")["measured"]
            assert str(measured["pack"]).startswith(pack)

    def test_no_workflow_gates_on_a_pack(self) -> None:
        """Plan §8 Q3, made mechanical, in both directions.

        A pack cannot be built without a download, so wiring one into a workflow would
        make CI depend on HuggingFace being up — and the same edit is how a pack's
        floors would come to stand in for the synthetic ones that guard the committed
        regression corpus. The workflows may name `configs/benchmark_gates.yaml` and
        nothing else under `configs/`.
        """
        for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
            text = workflow.read_text(encoding="utf-8")
            assert "pack_gates" not in text
            assert "build-pack" not in text

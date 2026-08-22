"""ADR-0032: the speaker prefix stays preserved by default, and the opt-in is measured.

Every claim ADR-0032 rules on is pinned here rather than left in prose, because six
sessions of prose is what left the question open.

The **default tier** covers the mechanism and the model-free half:

- flipping `preserve_prefix` moves all 90 unreachable incident entities into scope, so
  ADR-0028's number and ADR-0022's tier-4 0.000 have the same single cause;
- the model-free chain's detection numbers are *identical* either way, so the option
  buys nothing without a model;
- structurally, the author's name lands in a processable segment while the timestamp
  and the separator stay byte-identical.

The **integration tier** pins the two hybrid tables the ADR publishes. Those are the
numbers the decision actually rests on, and they need the models.

Configs are copied to `tmp_path` and edited there. Nothing in `configs/` changes, and
no gate reads anything asserted here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pii_reduction.benchmark import BenchmarkOutcome, run_benchmark
from pii_reduction.parsers.transcript import TranscriptParser

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIGS = REPO_ROOT / "configs"
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "corpus"
INCIDENTS_DIR = REPO_ROOT / "tests" / "fixtures" / "incidents"

#: The shipped transcript config, and the one edit ADR-0032 measures.
PRESERVE_TRUE = "preserve_prefix: true"
PRESERVE_FALSE = "preserve_prefix: false"


def configs_with_prefix_offered(destination: Path) -> Path:
    """A copy of the shipped configuration with `preserve_prefix: false`.

    One boolean, in one file. Copying the whole tree rather than writing a fixture
    config keeps the comparison honest: every other setting is the one that ships.
    """
    shutil.copytree(SHIPPED_CONFIGS, destination)
    transcript = destination / "datasets" / "benchmark_transcript.yaml"
    original = transcript.read_text(encoding="utf-8")
    assert PRESERVE_TRUE in original, "the shipped transcript config no longer preserves"
    transcript.write_text(original.replace(PRESERVE_TRUE, PRESERVE_FALSE), encoding="utf-8")
    return destination


class TestTheStructuralClaim:
    """What the option does to the text, with no model involved.

    Synthetic committed fixture text only — `tests/fixtures/incidents` is generated
    from a seed (ADR-0022).
    """

    LINE = "2026-04-03 09:12:04 - Peter Novak: Alert confirmed on DEMO-PC-6907.\n"

    def test_preserved_the_author_is_structure_and_no_provider_is_offered_it(self) -> None:
        result = TranscriptParser({"preserve_prefix": True}).parse(self.LINE)
        offered = "".join(segment.text for segment in result.processable_segments)
        assert "Peter Novak" not in offered
        assert "2026-04-03 09:12:04 - Peter Novak:" in [
            segment.text for segment in result.segments if not segment.processable
        ]

    def test_offered_the_author_is_body_and_so_is_the_timestamp(self) -> None:
        result = TranscriptParser({"preserve_prefix": False}).parse(self.LINE)
        offered = "".join(segment.text for segment in result.processable_segments)
        assert "Peter Novak" in offered
        # ADR-0032 states this out loud: the timestamp survives because no shipped
        # entity policy detects it, *not* because the parser still protects it.
        assert "2026-04-03 09:12:04" in offered

    @pytest.mark.parametrize("preserve", [True, False])
    def test_reconstruction_stays_byte_exact_either_way(self, preserve: bool) -> None:
        parser = TranscriptParser({"preserve_prefix": preserve})
        assert parser.reconstruct(parser.parse(self.LINE)) == self.LINE


class TestTheMechanism:
    """Model-free: the whole unreachable share is the speaker prefixes, and only that."""

    def test_offering_the_prefix_makes_every_unreachable_entity_reachable(
        self, tmp_path: Path
    ) -> None:
        preserved = run_benchmark(corpus_dir=INCIDENTS_DIR, configs_dir=SHIPPED_CONFIGS)
        offered = run_benchmark(
            corpus_dir=INCIDENTS_DIR,
            configs_dir=configs_with_prefix_offered(tmp_path / "configs"),
        )
        assert (preserved.reachability.unreachable, preserved.reachability.total) == (90, 315)
        assert (offered.reachability.unreachable, offered.reachability.total) == (0, 315)

    def test_without_a_model_the_option_buys_nothing(self, tmp_path: Path) -> None:
        """ADR-0032: on the deterministic chain the flip moves no detection number.

        The model-free chain detects no PERSON at all, so making the author reachable
        changes what was *offered* and nothing about what was *found*. This is why the
        ADR does not present the option as a free improvement.
        """
        preserved = run_benchmark(corpus_dir=INCIDENTS_DIR, configs_dir=SHIPPED_CONFIGS)
        offered = run_benchmark(
            corpus_dir=INCIDENTS_DIR,
            configs_dir=configs_with_prefix_offered(tmp_path / "configs"),
        )
        assert offered.strict.f1 == pytest.approx(preserved.strict.f1, abs=0.0005)
        assert offered.leakage.rate == pytest.approx(preserved.leakage.rate, abs=0.0005)
        assert offered.over_redaction.rate == pytest.approx(
            preserved.over_redaction.rate, abs=0.0005
        )


@pytest.mark.integration
class TestTheDecisionRestsOnThese:
    """The two hybrid tables in ADR-0032, pinned so the ruling cannot drift from them.

    Tolerances are loose enough to survive a patch-level model bump and tight enough
    that the *direction* of each trade is the assertion. The exact figures are in the
    ADR; what a test can defend is that offering the prefix helps where the author is a
    person and costs where the speaker is a role.
    """

    @staticmethod
    def _both(corpus: Path, tmp_path: Path) -> tuple[BenchmarkOutcome, BenchmarkOutcome]:
        preserved = run_benchmark(
            corpus_dir=corpus,
            configs_dir=SHIPPED_CONFIGS,
            provider_chain="deterministic_presidio",
            benchmark_run_id="prefix_preserved",
        )
        offered = run_benchmark(
            corpus_dir=corpus,
            configs_dir=configs_with_prefix_offered(tmp_path / "configs"),
            provider_chain="deterministic_presidio",
            benchmark_run_id="prefix_offered",
        )
        return preserved, offered

    def test_where_the_author_is_a_person_it_pays(self, tmp_path: Path) -> None:
        preserved, offered = self._both(INCIDENTS_DIR, tmp_path)
        assert preserved.strict.f1 == pytest.approx(0.761, abs=0.02)
        assert offered.strict.f1 == pytest.approx(0.844, abs=0.02)
        assert preserved.leakage.rate == pytest.approx(0.289, abs=0.02)
        assert offered.leakage.rate == pytest.approx(0.114, abs=0.02)
        # The trade the ADR rules on, as a relation rather than as two constants.
        assert offered.strict.f1 > preserved.strict.f1
        assert offered.leakage.rate < preserved.leakage.rate

    def test_where_the_speaker_is_a_role_it_costs(self, tmp_path: Path) -> None:
        preserved, offered = self._both(CORPUS_DIR, tmp_path)
        assert preserved.strict.f1 == pytest.approx(0.910, abs=0.02)
        assert offered.strict.f1 == pytest.approx(0.902, abs=0.02)
        # Recall does not move: this corpus's speakers are roles, so none of them is
        # ground truth and the whole delta is false positives.
        assert offered.strict.recall == pytest.approx(preserved.strict.recall, abs=0.0005)
        assert offered.strict.precision < preserved.strict.precision

    def test_and_over_redaction_cannot_see_the_cost(self, tmp_path: Path) -> None:
        """The second reason the default is *preserve*.

        Two Greek words are destroyed by the flip and `over_redaction_rate` stays
        0.000 through it, because it counts protected identifier tokens and neither
        word is one. The error the opt-in introduces is the kind this repository's
        instrumentation is worst at seeing.
        """
        preserved, offered = self._both(CORPUS_DIR, tmp_path)
        assert preserved.over_redaction.rate == pytest.approx(0.000, abs=0.0005)
        assert offered.over_redaction.rate == pytest.approx(0.000, abs=0.0005)

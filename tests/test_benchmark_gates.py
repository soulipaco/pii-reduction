"""Benchmark regression gates: the comparison, the file format, and the shipped file.

Most of these tests build metric rows by hand, because the interesting behaviour of a
gate is what it does when the benchmark does *not* look the way it expected — a slice
that disappeared, a metric that was renamed, a corpus that shrank. Those cases must
fail loudly; a gate that silently measures nothing is worse than no gate at all.

The last class runs the real deterministic benchmark against the real shipped gate
file. It stays in the default tier because that chain needs no NLP model. The hybrid
chain's gate set is checked in ``test_benchmark_presidio.py`` (integration).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from pii_reduction.benchmark import BenchmarkOutcome
from pii_reduction.cli import DEFAULT_DOCUMENTS_PER_LANGUAGE, DEFAULT_SEED, main
from pii_reduction.evaluation.gates import (
    DISPLAY_TOLERANCE,
    SUPPORTED_VERSION,
    Gate,
    GateConfigurationError,
    evaluate_gates,
    load_gate_file,
)
from pii_reduction.evaluation.report import MetricRow
from tests.test_benchmark import CONFIGS_DIR, CORPUS_DIR, GATE_FILE, REPO_ROOT

pytestmark = pytest.mark.unit

PROVIDERS_FILE = CONFIGS_DIR / "providers.yaml"


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping for assertions.

    Deliberately not ``config.loader.load_yaml_mapping``: that reader belongs to the
    pipeline configuration contract, and these files (the gate file, a CI workflow)
    are not part of it. ``gates.py`` reads the gate file with its own loader for the
    same reason, so the test reads it the same way production does.
    """
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def row(
    metric: str,
    value: float,
    *,
    support: int = 100,
    entity_type: str = "*",
    language: str = "*",
    document_type: str = "*",
    difficulty_tier: str = "*",
) -> MetricRow:
    return MetricRow(
        benchmark_run_id="test",
        provider="deterministic_only",
        language=language,
        entity_type=entity_type,
        document_type=document_type,
        difficulty_tier=difficulty_tier,
        strategy="redact",
        metric_name=metric,
        metric_value=value,
        support=support,
    )


class TestGateDefinition:
    def test_a_gate_with_no_bound_is_refused(self) -> None:
        with pytest.raises(GateConfigurationError, match="asserts nothing"):
            Gate(name="empty", metric="strict_f1")

    def test_a_gate_whose_min_exceeds_its_max_is_refused(self) -> None:
        with pytest.raises(GateConfigurationError, match="above max"):
            Gate(name="inverted", metric="strict_f1", minimum=0.9, maximum=0.5)

    def test_the_slice_description_names_only_non_aggregate_dimensions(self) -> None:
        assert Gate(name="a", metric="strict_f1", minimum=0.5).slice_description == "overall"
        sliced = Gate(
            name="b",
            metric="strict_recall",
            entity_type="PERSON",
            language="en",
            difficulty_tier="3",
            minimum=0.3,
        )
        assert sliced.slice_description == "entity_type=PERSON, language=en, difficulty_tier=3"


class TestComparison:
    def test_a_value_at_the_floor_passes(self) -> None:
        report = evaluate_gates(
            [row("strict_f1", 0.723)],
            [Gate(name="f1", metric="strict_f1", minimum=0.723)],
            gate_set="s",
        )
        assert report.passed

    def test_a_value_below_the_floor_fails_and_says_by_how_much(self) -> None:
        report = evaluate_gates(
            [row("strict_f1", 0.700)],
            [Gate(name="f1", metric="strict_f1", minimum=0.723)],
            gate_set="s",
        )
        assert not report.passed
        assert "0.700 is below the floor of 0.723" in report.failures[0].reason

    def test_a_value_above_the_ceiling_fails(self) -> None:
        report = evaluate_gates(
            [row("over_redaction_rate", 0.02)],
            [Gate(name="over", metric="over_redaction_rate", maximum=0.0)],
            gate_set="s",
        )
        assert not report.passed
        assert "above the ceiling" in report.failures[0].reason

    def test_representation_noise_does_not_fail_a_perfect_score(self) -> None:
        # A floor of 1.000 must not fail because the metric arrived as 0.9999999.
        report = evaluate_gates(
            [row("strict_recall", 1.0 - DISPLAY_TOLERANCE / 2)],
            [Gate(name="recall", metric="strict_recall", minimum=1.0)],
            gate_set="s",
        )
        assert report.passed

    def test_the_tolerance_is_far_smaller_than_one_missed_entity(self) -> None:
        # The smallest gated slice has 6 ground-truth entities, so a real regression
        # moves the metric by at least 1/6. The tolerance must not be able to absorb
        # one, or the gates would be decorative.
        assert DISPLAY_TOLERANCE < 1 / 6 / 10


class TestGatesThatMeasureNothing:
    def test_a_gate_matching_no_row_fails(self) -> None:
        report = evaluate_gates(
            [row("strict_f1", 1.0)],
            [Gate(name="renamed", metric="f1_strict", minimum=0.5)],
            gate_set="s",
        )
        assert not report.passed
        assert "no benchmark row matched" in report.failures[0].reason

    def test_a_gate_for_a_vanished_slice_fails(self) -> None:
        report = evaluate_gates(
            [row("strict_recall", 1.0, entity_type="EMAIL")],
            [
                Gate(
                    name="gone",
                    metric="strict_recall",
                    entity_type="PERSON",
                    language="el",
                    minimum=0.2,
                )
            ],
            gate_set="s",
        )
        assert not report.passed

    def test_an_ambiguous_gate_fails(self) -> None:
        report = evaluate_gates(
            [row("strict_f1", 1.0), row("strict_f1", 0.1)],
            [Gate(name="ambiguous", metric="strict_f1", minimum=0.5)],
            gate_set="s",
        )
        assert not report.passed
        assert "must identify exactly one row" in report.failures[0].reason

    def test_an_empty_gate_set_is_refused(self) -> None:
        with pytest.raises(GateConfigurationError, match="no gates"):
            evaluate_gates([row("strict_f1", 1.0)], [], gate_set="s")

    def test_a_shrunken_slice_fails_even_when_the_value_holds(self) -> None:
        # 1.000 over 3 entities is not the claim 1.000 over 51 entities makes.
        report = evaluate_gates(
            [row("strict_recall", 1.0, support=3, entity_type="EMAIL")],
            [
                Gate(
                    name="email",
                    metric="strict_recall",
                    entity_type="EMAIL",
                    minimum=1.0,
                    min_support=51,
                )
            ],
            gate_set="s",
        )
        assert not report.passed
        assert "support fell to 3" in report.failures[0].reason

    def test_a_grown_slice_is_fine(self) -> None:
        report = evaluate_gates(
            [row("strict_recall", 1.0, support=200, entity_type="EMAIL")],
            [
                Gate(
                    name="email",
                    metric="strict_recall",
                    entity_type="EMAIL",
                    minimum=1.0,
                    min_support=51,
                )
            ],
            gate_set="s",
        )
        assert report.passed


class TestReportRendering:
    def test_passing_gates_are_listed_too(self) -> None:
        report = evaluate_gates(
            [row("strict_f1", 0.9)],
            [Gate(name="f1", metric="strict_f1", minimum=0.5)],
            gate_set="deterministic_only",
        )
        rendered = report.render()
        assert "[PASS] f1" in rendered
        assert "1/1 gates passed" in rendered
        assert "deterministic_only" in rendered

    def test_a_failure_is_counted_and_explained(self) -> None:
        report = evaluate_gates(
            [row("strict_f1", 0.1)],
            [Gate(name="f1", metric="strict_f1", minimum=0.5)],
            gate_set="s",
        )
        rendered = report.render()
        assert "[FAIL] f1" in rendered
        assert "1 FAILED" in rendered


class TestGateFileFormat:
    def write(self, tmp_path: Path, data: object) -> Path:
        path = tmp_path / "gates.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    def test_a_missing_file_is_an_actionable_error(self, tmp_path: Path) -> None:
        with pytest.raises(GateConfigurationError, match="not found"):
            load_gate_file(tmp_path / "absent.yaml", "deterministic_only")

    def test_an_unknown_gate_set_lists_the_known_ones(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            {
                "version": SUPPORTED_VERSION,
                "gate_sets": {"a": {"gates": [{"name": "g", "metric": "strict_f1", "min": 0.1}]}},
            },
        )
        with pytest.raises(GateConfigurationError, match="defined: a"):
            load_gate_file(path, "b")

    def test_a_gate_set_with_no_gates_is_refused(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path, {"version": SUPPORTED_VERSION, "gate_sets": {"a": {"gates": []}}}
        )
        with pytest.raises(GateConfigurationError, match="defines no gates"):
            load_gate_file(path, "a")

    def test_an_unknown_key_is_refused_rather_than_ignored(self, tmp_path: Path) -> None:
        # A typo like `minimum:` instead of `min:` would otherwise produce a gate with
        # no bound at all, which is the silent failure this whole module exists to stop.
        path = self.write(
            tmp_path,
            {
                "version": SUPPORTED_VERSION,
                "gate_sets": {
                    "a": {"gates": [{"name": "g", "metric": "strict_f1", "minimum": 0.9}]}
                },
            },
        )
        with pytest.raises(GateConfigurationError, match="unknown keys minimum"):
            load_gate_file(path, "a")

    def test_duplicate_gate_names_are_refused(self, tmp_path: Path) -> None:
        gate = {"name": "g", "metric": "strict_f1", "min": 0.1}
        path = self.write(
            tmp_path,
            {"version": SUPPORTED_VERSION, "gate_sets": {"a": {"gates": [gate, dict(gate)]}}},
        )
        with pytest.raises(GateConfigurationError, match="duplicate gate names: g"):
            load_gate_file(path, "a")

    def test_a_tier_written_as_an_integer_is_accepted(self, tmp_path: Path) -> None:
        # Tiers are integers in YAML and strings in the report grain; the file should
        # not have to know that.
        path = self.write(
            tmp_path,
            {
                "version": SUPPORTED_VERSION,
                "gate_sets": {
                    "a": {
                        "gates": [
                            {
                                "name": "g",
                                "metric": "strict_recall",
                                "difficulty_tier": 3,
                                "min": 0.1,
                            }
                        ]
                    }
                },
            },
        )
        assert load_gate_file(path, "a")[0].difficulty_tier == "3"

    def test_an_unknown_top_level_key_is_refused(self, tmp_path: Path) -> None:
        # Same argument as the per-gate check, one level up: `gate_setts:` next to a
        # valid `gate_sets:` would otherwise be accepted in silence.
        path = self.write(
            tmp_path,
            {
                "version": SUPPORTED_VERSION,
                "gate_sets": {"a": {"gates": [{"name": "g", "metric": "strict_f1", "min": 0.1}]}},
                "measurd": {},
            },
        )
        with pytest.raises(GateConfigurationError, match="unknown top-level keys measurd"):
            load_gate_file(path, "a")

    def test_an_unknown_gate_set_key_is_refused(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            {
                "version": SUPPORTED_VERSION,
                "gate_sets": {
                    "a": {
                        "descriptionn": "typo",
                        "gates": [{"name": "g", "metric": "strict_f1", "min": 0.1}],
                    }
                },
            },
        )
        with pytest.raises(GateConfigurationError, match="unknown keys descriptionn"):
            load_gate_file(path, "a")

    def test_an_unsupported_schema_version_is_refused(self, tmp_path: Path) -> None:
        # A version key nobody validates promises a compatibility the loader does not
        # provide, so the loader validates it.
        path = self.write(
            tmp_path,
            {
                "version": 99,
                "gate_sets": {"a": {"gates": [{"name": "g", "metric": "strict_f1", "min": 0.1}]}},
            },
        )
        with pytest.raises(GateConfigurationError, match="version 99 is not supported"):
            load_gate_file(path, "a")

    def test_a_missing_schema_version_is_refused(self, tmp_path: Path) -> None:
        path = self.write(
            tmp_path,
            {"gate_sets": {"a": {"gates": [{"name": "g", "metric": "strict_f1", "min": 0.1}]}}},
        )
        with pytest.raises(GateConfigurationError, match="version None is not supported"):
            load_gate_file(path, "a")

    def test_invalid_yaml_names_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "gates.yaml"
        path.write_text("gate_sets: [unclosed\n", encoding="utf-8")
        with pytest.raises(GateConfigurationError, match="invalid YAML"):
            load_gate_file(path, "a")


class TestTheShippedGateFile:
    def test_every_configured_chain_has_a_gate_set(self) -> None:
        # A chain without gates is a chain nothing protects. Adding one to
        # providers.yaml must not be possible without deciding its floors.
        chains = set(read_yaml(PROVIDERS_FILE)["chains"])
        gate_sets = set(read_yaml(GATE_FILE)["gate_sets"])
        assert chains == gate_sets

    def test_the_measurement_provenance_is_recorded(self) -> None:
        measured = read_yaml(GATE_FILE)["measured"]
        expected = {
            "corpus",
            "seed",
            "documents_per_language",
            # AGENTS.md requires the splits behind a published result to be recorded.
            "splits",
            "strategy",
            "date",
            "commit",
            "versions",
        }
        assert expected <= set(measured)
        assert {"en_core_web_md", "de_core_news_md", "xx_ent_wiki_sm"} <= set(measured["versions"])

    def test_the_recorded_corpus_parameters_are_the_ones_that_built_it(self) -> None:
        # Provenance that does not match the CLI defaults would send a reader
        # regenerating a different corpus than the gates were measured on.
        measured = read_yaml(GATE_FILE)["measured"]
        assert measured["seed"] == DEFAULT_SEED
        assert measured["documents_per_language"] == DEFAULT_DOCUMENTS_PER_LANGUAGE

    def test_the_file_declares_the_schema_version_the_loader_supports(self) -> None:
        assert read_yaml(GATE_FILE)["version"] == SUPPORTED_VERSION

    def test_the_model_version_agrees_across_all_three_places_that_record_it(self) -> None:
        # The gate file says which models the numbers were measured on, the workflow
        # says which to install, and the checksum file pins the exact artifacts. Drift
        # between them means CI would silently judge one set of models by another
        # set's floors.
        versions = read_yaml(GATE_FILE)["measured"]["versions"]
        models = ("en_core_web_md", "de_core_news_md", "xx_ent_wiki_sm")
        measured = {versions[model] for model in models}
        assert len(measured) == 1, f"models measured at differing versions: {sorted(measured)}"
        version = measured.pop()

        workflow = read_yaml(REPO_ROOT / ".github" / "workflows" / "integration.yml")
        assert workflow["env"]["SPACY_MODEL_VERSION"] == version

        checksums = (REPO_ROOT / ".github" / "spacy-models.sha256").read_text(encoding="utf-8")
        for model in models:
            assert f"{model}-{version}-py3-none-any.whl" in checksums

    @pytest.mark.parametrize("gate_set", ["deterministic_only", "deterministic_presidio"])
    def test_each_gate_set_loads_and_every_gate_carries_support(self, gate_set: str) -> None:
        gates = load_gate_file(GATE_FILE, gate_set)
        assert gates
        assert all(gate.min_support is not None for gate in gates), (
            "every shipped gate must record the support it was measured over"
        )

    def test_the_deterministic_gates_pass_on_the_committed_corpus(self) -> None:
        from pii_reduction.benchmark import run_benchmark

        outcome: BenchmarkOutcome = run_benchmark(
            corpus_dir=CORPUS_DIR,
            configs_dir=CONFIGS_DIR,
            provider_chain="deterministic_only",
            benchmark_run_id="benchmark_gates",
        )
        report = evaluate_gates(
            outcome.rows,
            load_gate_file(GATE_FILE, "deterministic_only"),
            gate_set="deterministic_only",
        )
        assert report.passed, report.render()

    def test_a_tightened_gate_fails_the_run(self) -> None:
        # The gates are only worth having if they can fail. Rather than break a real
        # assertion, tighten one past the measured value and confirm it is caught.
        from pii_reduction.benchmark import run_benchmark

        outcome = run_benchmark(
            corpus_dir=CORPUS_DIR,
            configs_dir=CONFIGS_DIR,
            provider_chain="deterministic_only",
            benchmark_run_id="benchmark_gates_broken",
        )
        impossible = Gate(name="impossible", metric="strict_f1", minimum=0.99, min_support=180)
        report = evaluate_gates(outcome.rows, [impossible], gate_set="deterministic_only")
        assert not report.passed
        assert "below the floor" in report.failures[0].reason


class TestCliIntegration:
    def test_the_benchmark_command_reports_gates_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--gates",
                str(GATE_FILE),
            ]
        )
        captured = capsys.readouterr().out
        assert exit_code == 0
        assert "benchmark gates: deterministic_only" in captured
        assert "gates passed" in captured

    def test_a_failing_gate_exits_non_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # CI depends on the exit code, not on the text; assert the contract CI reads.
        path = tmp_path / "gates.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": SUPPORTED_VERSION,
                    "measured": {"strategy": "redact"},
                    "gate_sets": {
                        "deterministic_only": {
                            "gates": [{"name": "impossible", "metric": "strict_f1", "min": 0.99}]
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--gates",
                str(path),
            ]
        )
        assert exit_code == 1
        assert "[FAIL] impossible" in capsys.readouterr().out

    def test_a_malformed_gate_file_is_distinguishable_from_a_failed_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Exit 2, not 1. A typo in the gate file and a real regression are different
        # events, and whoever reads the CI log should not have to guess which it was.
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--gates",
                str(tmp_path / "absent.yaml"),
            ]
        )
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "gate file not found" in captured.err
        assert "Traceback" not in captured.err

    def test_gates_cannot_be_checked_against_a_single_split(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The shipped floors are whole-corpus numbers. Scoring one split against them
        # compares numbers that were never comparable, so the combination is refused
        # rather than quietly answering a different question.
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--split",
                "dev",
                "--gates",
                str(GATE_FILE),
            ]
        )
        assert exit_code == 2
        assert "cannot be combined with --split" in capsys.readouterr().err

    def test_gates_refuse_a_strategy_they_were_not_measured_on(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Every shipped gate file records `measured.strategy: redact`, and leakage is
        # defined per strategy (ADR-0013 §5): a mask run's leakage_rate judged against
        # redact floors would compare two different metrics under one name — and PASS,
        # since masking covers the full surface just as redaction does. The guard is
        # data-level like the chain guard: it compares the run's actual strategy to the
        # file's recorded one, so a config-level `reducer: mask` cannot slip past a
        # flag-only check.
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--strategy",
                "mask",
                "--gates",
                str(GATE_FILE),
            ]
        )
        assert exit_code == 2
        assert "measured under strategy 'redact'" in capsys.readouterr().err

    def test_a_matching_strategy_passes_the_guard(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Explicitly asking for the measured strategy is not an error — the guard
        # compares strategies, it does not forbid the flag.
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--strategy",
                "redact",
                "--gates",
                str(GATE_FILE),
            ]
        )
        assert exit_code == 0
        assert "gates passed" in capsys.readouterr().out

    def test_a_gate_file_without_a_measured_strategy_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Comparing against an unknown baseline is the silent wrongness the gates
        # module exists to prevent, so the record is required rather than assumed.
        path = tmp_path / "gates.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": SUPPORTED_VERSION,
                    "gate_sets": {
                        "deterministic_only": {
                            "gates": [{"name": "g", "metric": "strict_f1", "min": 0.1}]
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        exit_code = main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--gates",
                str(path),
            ]
        )
        assert exit_code == 2
        assert "measured.strategy" in capsys.readouterr().err

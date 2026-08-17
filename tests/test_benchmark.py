"""The A6 exit gate: the whole slice, end to end, over the committed corpus.

The gate is deliberately a *sanity* threshold, not a quality claim. Deterministic
recognizers on synthetic text should find effectively every email and phone number;
if they do not, either the corpus or the provider has a bug, and this is the cheapest
place to notice. PERSON is asserted to report zero with its true support — the honest
baseline the plan asks for, not a filtered table (plan §5, A6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pii_reduction.benchmark import BenchmarkOutcome, run_benchmark, summarise
from pii_reduction.cli import main
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.evaluation import TruthSpan, detection_metrics_by
from pii_reduction.synthetic import load_corpus

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "corpus"
CONFIGS_DIR = REPO_ROOT / "configs"

#: The A6 gate. Locked here rather than invented in CI config (ADR-0009).
MIN_STRICT_RECALL = 0.95


@pytest.fixture(scope="module")
def outcome() -> BenchmarkOutcome:
    return run_benchmark(
        corpus_dir=CORPUS_DIR, configs_dir=CONFIGS_DIR, benchmark_run_id="benchmark_test"
    )


class TestExitGate:
    def test_email_strict_recall_meets_the_gate(self, outcome: BenchmarkOutcome) -> None:
        by_entity = detection_metrics_by(
            _truths(), outcome.predictions, dimensions=("entity_type",)
        )
        metric = by_entity[(EMAIL,)]
        assert metric.support > 0
        assert metric.recall >= MIN_STRICT_RECALL, f"EMAIL recall {metric.recall:.3f}"

    def test_phone_strict_recall_meets_the_gate(self, outcome: BenchmarkOutcome) -> None:
        by_entity = detection_metrics_by(
            _truths(), outcome.predictions, dimensions=("entity_type",)
        )
        metric = by_entity[(PHONE,)]
        assert metric.support > 0
        assert metric.recall >= MIN_STRICT_RECALL, f"PHONE recall {metric.recall:.3f}"

    def test_person_reports_zero_with_its_real_support(self, outcome: BenchmarkOutcome) -> None:
        # No shipped provider detects PERSON before Increment B. The gap is reported,
        # not hidden: support must be the true count, recall exactly zero.
        by_entity = detection_metrics_by(
            _truths(), outcome.predictions, dimensions=("entity_type",)
        )
        metric = by_entity[(PERSON,)]
        assert metric.support > 0
        assert metric.recall == 0.0
        assert metric.true_positives == 0

    def test_precision_is_perfect_on_synthetic_text(self, outcome: BenchmarkOutcome) -> None:
        # Every predicted span should be a real injected entity; a false positive
        # here means the recognizers are matching something they should not.
        assert outcome.strict.false_positives == 0

    def test_nothing_non_pii_was_touched(self, outcome: BenchmarkOutcome) -> None:
        assert outcome.over_redaction.total > 0
        assert outcome.over_redaction.rate == 0.0, outcome.over_redaction.modified_kinds


class TestReportedNumbers:
    def test_every_language_and_tier_appears_in_the_table(self, outcome: BenchmarkOutcome) -> None:
        languages = {row.language for row in outcome.rows}
        tiers = {row.difficulty_tier for row in outcome.rows}
        assert {"en", "de", "el"} <= languages
        assert {"1", "2", "3", "4"} <= tiers

    def test_support_is_reported_on_every_row(self, outcome: BenchmarkOutcome) -> None:
        assert all(row.support >= 0 for row in outcome.rows)
        assert any(row.support > 0 for row in outcome.rows)

    def test_relaxed_is_reported_beside_strict(self, outcome: BenchmarkOutcome) -> None:
        names = {row.metric_name for row in outcome.rows}
        assert {"strict_f1", "relaxed_f1", "leakage_rate", "over_redaction_rate"} <= names
        # With exact deterministic spans the two agree; the gap becomes informative
        # once an NER provider joins (ADR-0011).
        assert outcome.relaxed.f1 >= outcome.strict.f1

    def test_leakage_reflects_undetected_person_entities(self, outcome: BenchmarkOutcome) -> None:
        person_support = detection_metrics_by(
            _truths(), outcome.predictions, dimensions=("entity_type",)
        )[(PERSON,)].support
        assert outcome.leakage.leaked == person_support
        assert outcome.leakage.strategy == "redact"

    def test_table_renders_with_the_gap_visible(self, outcome: BenchmarkOutcome) -> None:
        table = outcome.table()
        assert "PERSON" in table
        assert "strict_recall" in table
        assert "0.000" in table

    def test_summary_states_the_headline_numbers(self, outcome: BenchmarkOutcome) -> None:
        summary = summarise(outcome)
        assert "documents=102" in summary
        assert "chain=deterministic_only" in summary


class TestStructurePreservation:
    def test_transcript_prefixes_survive_reduction(self, outcome: BenchmarkOutcome) -> None:
        corpus = load_corpus(CORPUS_DIR)
        transcripts = [d for d in corpus.documents if d.document_type == "transcript"]
        assert transcripts
        for document in transcripts:
            reduced = outcome.reduced_texts[document.document_id]
            for line in document.text.splitlines():
                prefix = line.split(":", 1)[0]
                if prefix.startswith("2026-"):
                    assert prefix in reduced, document.document_id

    def test_reduced_documents_keep_their_line_counts(self, outcome: BenchmarkOutcome) -> None:
        corpus = load_corpus(CORPUS_DIR)
        for document in corpus.documents:
            reduced = outcome.reduced_texts[document.document_id]
            assert reduced.count("\n") == document.text.count("\n"), document.document_id


class TestSplits:
    def test_a_split_can_be_evaluated_on_its_own(self) -> None:
        # Increment E calibrates on the calibration split only and reports test once
        # (ADR-0011); the plumbing for that exists now.
        outcome = run_benchmark(
            corpus_dir=CORPUS_DIR,
            configs_dir=CONFIGS_DIR,
            splits=["calibration"],
            benchmark_run_id="benchmark_split",
        )
        full = load_corpus(CORPUS_DIR)
        expected = sum(1 for d in full.documents if d.split == "calibration")
        assert outcome.documents == expected
        assert outcome.documents < len(full.documents)


class TestCli:
    def test_benchmark_command_prints_the_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["benchmark", "--corpus", str(CORPUS_DIR), "--configs", str(CONFIGS_DIR)])
        captured = capsys.readouterr().out
        assert exit_code == 0
        assert "PII reduction benchmark" in captured
        assert "strict_recall" in captured
        assert "documents=102" in captured

    def test_markdown_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(
            [
                "benchmark",
                "--corpus",
                str(CORPUS_DIR),
                "--configs",
                str(CONFIGS_DIR),
                "--markdown",
            ]
        )
        assert "| language |" in capsys.readouterr().out

    def test_build_corpus_command_writes_a_corpus(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["build-corpus", "--out", str(tmp_path / "corpus"), "--documents-per-language", "6"]
        )
        assert exit_code == 0
        assert "wrote 18 documents" in capsys.readouterr().out
        assert (tmp_path / "corpus" / "corpus.csv").is_file()


def _truths() -> list[TruthSpan]:
    from pii_reduction.benchmark import _truth_spans

    return _truth_spans(load_corpus(CORPUS_DIR))

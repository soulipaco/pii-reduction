"""Privacy tests (``docs/10_TESTING_QA.md`` §9).

The rule these enforce: logs, exception messages and persisted metadata may contain
dataset names, row ids, columns, providers, languages, counts, timings and error
categories — never source text and never a detected value (``AGENTS.md`` rule 8).

Every value asserted absent below is synthetic and comes from
``tests/pipeline_fixtures.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pii_reduction.benchmark import BenchmarkOutcome, run_benchmark, summarise
from pii_reduction.evaluation.gates import Gate, evaluate_gates, load_gate_file
from pii_reduction.evaluation.report import render_markdown
from pii_reduction.observability.logging import LOGGER_NAME, safe_fields
from pii_reduction.processing import build_pipeline
from pii_reduction.sources import PandasSource
from pii_reduction.synthetic import load_corpus
from tests.pipeline_fixtures import KNOWN_EMAILS, KNOWN_PHONES, build_frame
from tests.test_benchmark import CONFIGS_DIR, CORPUS_DIR, GATE_FILE
from tests.test_pipeline import make_config

pytestmark = pytest.mark.unit

SENSITIVE_VALUES = KNOWN_EMAILS + KNOWN_PHONES


def assert_clean(text: str, *, what: str) -> None:
    for value in SENSITIVE_VALUES:
        assert value not in text, f"{what} contains {value!r}"


class TestLogCapture:
    def test_a_full_run_logs_no_source_values(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        build_pipeline(make_config(tmp_path)).run()
        assert caplog.text  # the run did log something
        assert_clean(caplog.text, what="captured logs")

    def test_failing_rows_log_categories_not_content(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        pipeline = build_pipeline(make_config(tmp_path))
        processor = pipeline._processors[0]

        def leaky(text: str):  # type: ignore[no-untyped-def]
            raise ValueError(f"failed while handling {text}")

        monkeypatch.setattr(processor.parser, "parse", leaky)
        pipeline.process(PandasSource(build_frame(), name="demo_smoke").load())

        assert "error_category=ValueError" in caplog.text
        assert_clean(caplog.text, what="captured logs")


class TestPersistedArtifacts:
    def test_run_metrics_file_contains_no_source_values(self, tmp_path: Path) -> None:
        outcome = build_pipeline(make_config(tmp_path)).run()
        content = Path(outcome.written["run_metrics"]).read_text(encoding="utf-8")
        assert_clean(content, what="run metrics file")

    def test_audit_file_contains_no_source_values(self, tmp_path: Path) -> None:
        outcome = build_pipeline(make_config(tmp_path)).run()
        content = Path(outcome.written["audit"]).read_text(encoding="utf-8")
        assert_clean(content, what="audit file")

    def test_row_results_contain_no_original_values(self, tmp_path: Path) -> None:
        outcome = build_pipeline(make_config(tmp_path)).run()
        rendered = json.dumps(
            [result.model_dump(mode="json") for result in outcome.row_results], default=str
        )
        # Reduced text is present by design; the originals must not be.
        assert_clean(rendered, what="row results")
        assert "<EMAIL>" in rendered


class TestPublishedBenchmarkOutput:
    """The benchmark table is published, so it must be text-free by test, not by luck.

    The integration workflow writes the rendered table into the GitHub step summary,
    which is world-readable on a public repository. Nothing structurally prevents a
    future slice dimension from carrying an entity surface into a row: adding a
    ``surface`` field to ``TruthSpan`` and listing it in ``benchmark.SLICE_DIMENSIONS``
    would do it silently. These tests fail in exactly that case.

    Asserted against the committed *synthetic* corpus, whose values are generated and
    public-safe by construction (ADR-0014).
    """

    @staticmethod
    def _outcome() -> BenchmarkOutcome:
        return run_benchmark(
            corpus_dir=CORPUS_DIR,
            configs_dir=CONFIGS_DIR,
            provider_chain="deterministic_only",
            benchmark_run_id="benchmark_privacy",
        )

    @staticmethod
    def _surfaces() -> list[str]:
        # Every injected value in the corpus: names, emails and phone numbers.
        surfaces = {entity.surface for entity in load_corpus(CORPUS_DIR).entities}
        assert surfaces, "the corpus must carry surfaces for this test to mean anything"
        return sorted(surfaces)

    def _assert_no_surface(self, rendered: str, *, what: str) -> None:
        for surface in self._surfaces():
            assert surface not in rendered, f"{what} contains an injected entity value"

    def test_the_rendered_table_carries_no_entity_values(self) -> None:
        self._assert_no_surface(self._outcome().table(), what="benchmark table")

    def test_the_markdown_table_carries_no_entity_values(self) -> None:
        # This is the exact renderer the integration workflow publishes.
        outcome = self._outcome()
        rendered = render_markdown(outcome.rows, title="PII reduction benchmark")
        self._assert_no_surface(rendered, what="published markdown table")

    def test_the_gate_report_carries_no_entity_values(self) -> None:
        outcome = self._outcome()
        report = evaluate_gates(
            outcome.rows,
            load_gate_file(GATE_FILE, "deterministic_only"),
            gate_set="deterministic_only",
        )
        self._assert_no_surface(report.render(), what="gate report")

    def test_a_failing_gate_reports_numbers_rather_than_text(self) -> None:
        # The failure path is the one that gets pasted into issues and CI logs.
        outcome = self._outcome()
        impossible = Gate(name="impossible", metric="strict_f1", minimum=0.99)
        report = evaluate_gates(outcome.rows, [impossible], gate_set="deterministic_only")
        assert not report.passed
        self._assert_no_surface(report.render(), what="failing gate report")

    def test_the_benchmark_summary_carries_no_entity_values(self) -> None:
        self._assert_no_surface(summarise(self._outcome()), what="benchmark summary")


class TestSafeFields:
    def test_only_allowed_fields_are_rendered(self) -> None:
        rendered = safe_fields(
            dataset="demo",
            row_id="row_0001",
            text="Contact maria.rossi@example.com",
            output_text="anything",
        )
        assert rendered == "dataset=demo row_id=row_0001"
        assert "maria.rossi@example.com" not in rendered

    def test_none_values_are_dropped(self) -> None:
        assert safe_fields(dataset="demo", language=None) == "dataset=demo"

    def test_fields_are_ordered_for_stable_log_lines(self) -> None:
        assert safe_fields(row_id="r", dataset="d", column="c") == ("column=c dataset=d row_id=r")

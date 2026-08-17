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

from pii_reduction.observability.logging import LOGGER_NAME, safe_fields
from pii_reduction.processing import build_pipeline
from pii_reduction.sources import PandasSource
from tests.pipeline_fixtures import KNOWN_EMAILS, KNOWN_PHONES, build_frame
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

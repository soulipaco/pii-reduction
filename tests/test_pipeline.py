"""End-to-end local pipeline: source → policy → parse → detect → reduce → output."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.config import load_resolved_dataset
from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.contracts.results import ProcessingStatus
from pii_reduction.processing import (
    RUN_ID_COLUMN,
    STATUS_COLUMN,
    Pipeline,
    ProcessingError,
    build_pipeline,
)
from pii_reduction.sources import CsvSource, PandasSource, SourceDataset
from tests.conftest import write_configs
from tests.pipeline_fixtures import (
    DATASET_YAML,
    KNOWN_EMAILS,
    KNOWN_PHONES,
    PROJECT_YAML,
    ROWS,
    build_frame,
    write_dataset_csv,
)

pytestmark = pytest.mark.unit


def make_config(tmp_path: Path, *, project_yaml: str = PROJECT_YAML) -> ResolvedDataset:
    source_path = tmp_path / "input" / "demo.csv"
    write_dataset_csv(source_path)
    configs = write_configs(
        tmp_path,
        project_yaml=project_yaml,
        dataset_yaml=DATASET_YAML.format(
            source_path=source_path.as_posix(),
            destination_path=(tmp_path / "output").as_posix(),
        ),
    )
    return load_resolved_dataset(configs, "demo_smoke")


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    return build_pipeline(make_config(tmp_path), run_id="run_test_0001")


@pytest.fixture
def dataset() -> SourceDataset:
    return PandasSource(build_frame(), name="demo_smoke").load()


class TestEndToEnd:
    def test_processes_the_twenty_row_fixture(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        assert len(outcome.frame) == len(ROWS) == 20
        assert outcome.run.rows_read == 20
        assert outcome.run.rows_written == 20
        assert outcome.run.status is ProcessingStatus.SUCCESS_WITH_FALLBACK

    def test_row_count_and_row_ids_are_preserved(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        assert list(outcome.frame["row_id"]) == list(dataset.frame["row_id"])

    def test_original_column_is_unchanged(self, pipeline: Pipeline, dataset: SourceDataset) -> None:
        outcome = pipeline.process(dataset)
        assert outcome.frame["body"].equals(dataset.frame["body"])

    def test_output_and_metadata_columns_are_added(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        for column in ("body_pii_redacted", RUN_ID_COLUMN, STATUS_COLUMN):
            assert column in outcome.frame.columns
        assert set(outcome.frame[RUN_ID_COLUMN]) == {"run_test_0001"}

    def test_every_known_value_is_removed_from_the_output(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        reduced = "\n".join(str(value) for value in outcome.frame["body_pii_redacted"])
        for value in KNOWN_EMAILS + KNOWN_PHONES:
            assert value not in reduced, value

    def test_non_pii_identifiers_survive(self, pipeline: Pipeline, dataset: SourceDataset) -> None:
        outcome = pipeline.process(dataset)
        reduced = "\n".join(str(value) for value in outcome.frame["body_pii_redacted"])
        for identifier in ("INC00128492", "KB000002715", "DEMO-PC-6915", "v4.12.3", "12345"):
            assert identifier in reduced, identifier

    def test_transcript_prefixes_are_preserved(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        row = outcome.frame.loc[outcome.frame["row_id"] == "row_0011"].iloc[0]
        assert row["body_pii_redacted"].startswith("2026-04-03 09:15:04 - Agent: Hello")
        assert "<EMAIL>" in row["body_pii_redacted"]

    def test_crlf_row_keeps_its_line_ending(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        row = outcome.frame.loc[outcome.frame["row_id"] == "row_0019"].iloc[0]
        assert row["body_pii_redacted"].endswith("\r\n")

    def test_null_input_produces_null_output(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        row = outcome.frame.loc[outcome.frame["row_id"] == "row_0010"].iloc[0]
        assert row["body_pii_redacted"] is None
        result = next(r for r in outcome.row_results if r.row_id == "row_0010")
        assert result.field_results[0].status is ProcessingStatus.SKIPPED

    def test_empty_string_is_deterministic(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        row = outcome.frame.loc[outcome.frame["row_id"] == "row_0009"].iloc[0]
        assert row["body_pii_redacted"] == ""

    def test_repeated_runs_produce_identical_reduced_text(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        first = pipeline.process(dataset).frame["body_pii_redacted"]
        second = pipeline.process(dataset).frame["body_pii_redacted"]
        assert first.equals(second)

    def test_unsupported_language_falls_back_and_is_counted(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        # row_0017 is French; the configured scope is en/de/el.
        outcome = pipeline.process(dataset)
        assert outcome.detail["language_counts"]["fr"] == 1
        assert outcome.detail["language_counts"]["_fallback"] >= 1
        row = outcome.frame.loc[outcome.frame["row_id"] == "row_0017"].iloc[0]
        # The deterministic provider is language-independent, so EMAIL is still found.
        assert "<EMAIL>" in row["body_pii_redacted"]


class TestRunMetrics:
    def test_run_record_carries_the_documented_fields(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        run = pipeline.process(dataset).run
        for attribute in (
            "run_id",
            "pipeline_version",
            "config_hash",
            "source_dataset",
            "started_at",
            "completed_at",
            "rows_read",
            "rows_written",
            "fields_processed",
            "fields_failed",
            "entities_detected",
            "entities_reduced",
        ):
            assert getattr(run, attribute) is not None

    def test_config_hash_ties_the_run_to_its_configuration(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        assert pipeline.process(dataset).run.config_hash == pipeline.config_hash
        assert len(pipeline.config_hash) == 64

    def test_entity_counts_are_recorded(self, pipeline: Pipeline, dataset: SourceDataset) -> None:
        detail = pipeline.process(dataset).detail
        assert detail["entity_counts"]["EMAIL"] == len(KNOWN_EMAILS)
        assert detail["entity_counts"]["PHONE"] == len(KNOWN_PHONES)

    def test_parser_fallbacks_are_counted(self, pipeline: Pipeline, dataset: SourceDataset) -> None:
        # Plain-text parsing never falls back; the transcript rows are parsed by the
        # plain parser in this configuration, so the counter stays empty.
        detail = pipeline.process(dataset).detail
        assert detail["parser_fallbacks"] == {}

    def test_metrics_payload_is_json_serialisable_metadata_only(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        payload = pipeline.process(dataset).metrics_payload()
        rendered = json.dumps(payload, default=str)
        for value in KNOWN_EMAILS + KNOWN_PHONES:
            assert value not in rendered


class TestAudit:
    def test_audit_rows_carry_spans_but_no_text(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        assert outcome.audit
        rendered = json.dumps(list(outcome.audit), default=str)
        for value in KNOWN_EMAILS + KNOWN_PHONES:
            assert value not in rendered
        first = outcome.audit[0]
        assert set(first) >= {
            "run_id",
            "row_id",
            "column_name",
            "segment_id",
            "entity_type",
            "start",
            "end",
            "score",
            "provider",
            "language",
            "resolution_rule",
        }


class TestStructuralValidation:
    def test_duplicate_row_ids_are_refused(self, pipeline: Pipeline) -> None:
        frame = build_frame()
        frame.loc[1, "row_id"] = frame.loc[0, "row_id"]
        with pytest.raises(ProcessingError) as exc_info:
            pipeline.process(PandasSource(frame, name="demo_smoke").load())
        assert "duplicate" in str(exc_info.value)

    def test_missing_row_id_column_is_refused(self, pipeline: Pipeline) -> None:
        frame = build_frame().drop(columns=["row_id"])
        with pytest.raises(ProcessingError) as exc_info:
            pipeline.process(PandasSource(frame, name="demo_smoke").load())
        assert "row_id" in str(exc_info.value)

    def test_missing_configured_column_is_refused(self, pipeline: Pipeline) -> None:
        frame = build_frame().drop(columns=["body"])
        with pytest.raises(ProcessingError) as exc_info:
            pipeline.process(PandasSource(frame, name="demo_smoke").load())
        assert "body" in str(exc_info.value)

    def test_existing_output_column_is_refused(self, pipeline: Pipeline) -> None:
        frame = build_frame()
        frame["body_pii_redacted"] = "already here"
        with pytest.raises(ProcessingError) as exc_info:
            pipeline.process(PandasSource(frame, name="demo_smoke").load())
        assert "already exists" in str(exc_info.value)


class TestFailurePolicy:
    def test_one_failing_row_does_not_fail_the_run_and_is_counted(
        self, pipeline: Pipeline, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        processor = pipeline._processors[0]
        original_parse = processor.parser.parse
        failing_text = str(dataset.frame.loc[0, "body"])

        def explode(text: str):  # type: ignore[no-untyped-def]
            if text == failing_text:
                raise RuntimeError("synthetic parser failure")
            return original_parse(text)

        monkeypatch.setattr(processor.parser, "parse", explode)

        outcome = pipeline.process(dataset)
        assert len(outcome.frame) == 20
        assert outcome.run.fields_failed == 1
        assert outcome.run.status is ProcessingStatus.PARTIAL_FAILURE
        assert outcome.detail["error_categories"] == {"RuntimeError": 1}

        failed_row = outcome.frame.iloc[0]
        # preserve_original_and_record_error: the source text passes through.
        assert failed_row["body_pii_redacted"] == failing_text
        assert failed_row[STATUS_COLUMN] == ProcessingStatus.PARTIAL_FAILURE.value

    def test_third_party_exception_messages_are_not_retained(
        self, pipeline: Pipeline, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        processor = pipeline._processors[0]
        secret = str(dataset.frame.loc[0, "body"])

        def leaky(text: str):  # type: ignore[no-untyped-def]
            raise ValueError(f"failed while handling {text}")

        monkeypatch.setattr(processor.parser, "parse", leaky)

        outcome = pipeline.process(dataset)
        failed = [
            field_result
            for row_result in outcome.row_results
            for field_result in row_result.field_results
            if field_result.status is ProcessingStatus.FAILED
        ]
        assert len(failed) == 19  # every row except the null one, which is skipped
        for field_result in failed:
            assert field_result.error is None
            assert field_result.error_category == "ValueError"
            assert secret not in str(field_result.model_dump())

    def test_fail_fast_stops_the_run(self, tmp_path: Path, dataset: SourceDataset) -> None:
        project = PROJECT_YAML.replace(
            "failure_mode: preserve_original_and_record_error", "failure_mode: fail_fast"
        )
        strict = build_pipeline(make_config(tmp_path, project_yaml=project))
        processor = strict._processors[0]

        def explode(text: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("synthetic parser failure")

        processor.parser.parse = explode  # type: ignore[method-assign]
        with pytest.raises(ProcessingError) as exc_info:
            strict.process(dataset)
        assert "fail_fast" in str(exc_info.value)

    def test_quarantine_row_writes_no_reduced_value(
        self, tmp_path: Path, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = PROJECT_YAML.replace(
            "failure_mode: preserve_original_and_record_error", "failure_mode: quarantine_row"
        )
        quarantining = build_pipeline(make_config(tmp_path, project_yaml=project))
        processor = quarantining._processors[0]
        failing_text = str(dataset.frame.loc[0, "body"])
        original_parse = processor.parser.parse

        def explode(text: str):  # type: ignore[no-untyped-def]
            if text == failing_text:
                raise RuntimeError("synthetic parser failure")
            return original_parse(text)

        monkeypatch.setattr(processor.parser, "parse", explode)
        outcome = quarantining.process(dataset)
        assert outcome.frame.iloc[0]["body_pii_redacted"] is None
        assert outcome.frame.iloc[0][STATUS_COLUMN] == ProcessingStatus.FAILED.value
        assert len(outcome.frame) == 20


class TestRunFromConfiguration:
    def test_run_loads_writes_and_reports(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        outcome = build_pipeline(config, run_id="run_test_0002").run()

        dataset_path = Path(outcome.written["dataset"])
        metrics_path = Path(outcome.written["run_metrics"])
        assert dataset_path.is_file()
        assert metrics_path.is_file()

        written = pd.read_csv(dataset_path)
        assert len(written) == 20
        assert "body_pii_redacted" in written.columns

        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert payload["run"]["run_id"] == "run_test_0002"
        assert payload["run"]["rows_read"] == 20
        assert payload["detail"]["entity_counts"]["EMAIL"] == len(KNOWN_EMAILS)

    def test_audit_file_is_written_when_configured(self, tmp_path: Path) -> None:
        outcome = build_pipeline(make_config(tmp_path)).run()
        audit_path = Path(outcome.written["audit"])
        assert audit_path.is_file()
        audit = pd.read_csv(audit_path)
        assert set(audit.columns) >= {"entity_type", "start", "end", "provider"}

    def test_csv_source_round_trips_through_the_pipeline(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        loaded = CsvSource(config.source.path, name="demo_smoke").load()
        assert loaded.row_count == 20
        assert build_pipeline(config).process(loaded).run.rows_read == 20

    def test_detect_language_mode_names_the_increment_that_implements_it(
        self, tmp_path: Path
    ) -> None:
        project = PROJECT_YAML.replace("mode: column", "mode: detect").replace(
            "detector: none", "detector: lingua"
        )
        with pytest.raises(Exception) as exc_info:
            build_pipeline(make_config(tmp_path, project_yaml=project))
        assert "Increment C" in str(exc_info.value)

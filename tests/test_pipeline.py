"""End-to-end local pipeline: source → policy → parse → detect → reduce → output."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.config import ConfigurationError, load_resolved_dataset
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
    project_yaml_with_failure_mode,
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


class TestDroppedLabels:
    """ADR-0004: a provider dropping native labels must show up in run metrics."""

    def test_dropped_labels_reach_the_run_record(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        provider = pipeline._processors[0].providers[0]
        provider.drop_counter.record_declared(provider.name, "URL")
        provider.drop_counter.record_unmapped(provider.name, "NRP")

        run = pipeline.process(dataset).run
        assert run.dropped_labels == {
            f"{provider.name}:URL": 1,
            f"{provider.name}:NRP": 1,
        }

    def test_a_provider_that_drops_nothing_reports_nothing(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        assert pipeline.process(dataset).run.dropped_labels == {}


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
        """The fixture configures no failure mode, so this runs the default: fail-closed.

        ADR-0023: the failing field carries no reduced value and the raw source text
        must not appear anywhere in the reduced column — the property the default
        exists to guarantee.
        """
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
        # quarantine_row (the ADR-0023 default): no reduced value, visible status.
        assert failed_row["body_pii_redacted"] is None
        assert failed_row[STATUS_COLUMN] == ProcessingStatus.FAILED.value
        # And the fail-open shape can never reach the reduced artifact by default:
        # the raw text of the failed field appears in no reduced value of any row.
        reduced_values = [value for value in outcome.frame["body_pii_redacted"] if value]
        assert all(failing_text not in value for value in reduced_values)

    def test_preserve_original_is_an_explicit_opt_in(
        self, tmp_path: Path, dataset: SourceDataset, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`preserve_original_and_record_error` still works — when asked for by name.

        ADR-0023 changed the default, not the mode: a demo that wants best-effort
        pass-through opts in and the row still says `partial_failure`.
        """
        project = project_yaml_with_failure_mode("preserve_original_and_record_error")
        preserving = build_pipeline(make_config(tmp_path, project_yaml=project))
        processor = preserving._processors[0]
        failing_text = str(dataset.frame.loc[0, "body"])
        original_parse = processor.parser.parse

        def explode(text: str):  # type: ignore[no-untyped-def]
            if text == failing_text:
                raise RuntimeError("synthetic parser failure")
            return original_parse(text)

        monkeypatch.setattr(processor.parser, "parse", explode)

        outcome = preserving.process(dataset)
        failed_row = outcome.frame.iloc[0]
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
        project = project_yaml_with_failure_mode("fail_fast")
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
        # Explicitly configured, though it is also the ADR-0023 default — an explicit
        # `quarantine_row` must keep working if the default ever moves again.
        project = project_yaml_with_failure_mode("quarantine_row")
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

    def test_an_unimplemented_detector_is_refused_with_what_is_available(
        self, tmp_path: Path
    ) -> None:
        project = PROJECT_YAML.replace("mode: column", "mode: detect").replace(
            "detector: none", "detector: fasttext"
        )
        with pytest.raises(ConfigurationError) as exc_info:
            build_pipeline(make_config(tmp_path, project_yaml=project))
        assert "fasttext" in str(exc_info.value)


class TestReducedOnlyProjection:
    """ADR-0024: the written artifact can drop the configured raw text columns."""

    def _reduced_only_config(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        source_path = tmp_path / "input" / "demo.csv"
        write_dataset_csv(source_path)
        marker = "destination:\n  type: csv\n"
        assert marker in DATASET_YAML
        dataset_yaml = DATASET_YAML.replace(
            marker, "destination:\n  type: csv\n  projection: reduced_only\n"
        ).format(
            source_path=source_path.as_posix(),
            destination_path=(tmp_path / "output").as_posix(),
        )
        configs = write_configs(tmp_path, project_yaml=PROJECT_YAML, dataset_yaml=dataset_yaml)
        return load_resolved_dataset(configs, "demo_smoke")

    def test_the_projection_drops_exactly_the_configured_columns(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        outcome = pipeline.process(dataset)
        projected = pipeline.reduced_only_projection(outcome.frame)

        assert "body" not in projected.columns
        # Everything else survives: unconfigured source columns are the
        # operator's scope decision, not the projection's (ADR-0024).
        assert {"row_id", "language", "kind", "body_pii_redacted"} <= set(projected.columns)
        assert STATUS_COLUMN in projected.columns
        assert len(projected) == len(outcome.frame)

    def test_in_memory_processing_stays_non_destructive(
        self, pipeline: Pipeline, dataset: SourceDataset
    ) -> None:
        # The projection is a written-artifact shape; process() still returns and
        # validates the full frame (AGENTS.md rule 4).
        outcome = pipeline.process(dataset)
        assert "body" in outcome.frame.columns

    def test_a_reduced_only_destination_writes_no_raw_column(self, tmp_path: Path) -> None:
        config = self._reduced_only_config(tmp_path)
        assert config.destination.projection == "reduced_only"

        outcome = build_pipeline(config, run_id="run_projection").run()
        written = pd.read_csv(Path(outcome.written["dataset"]))

        assert "body" not in written.columns
        assert "body_pii_redacted" in written.columns
        assert len(written) == 20
        # The artifact carries no raw text column, and reduction removed the
        # detected values from what it does carry.
        rendered = written.to_csv(index=False)
        for value in KNOWN_EMAILS + KNOWN_PHONES:
            assert value not in rendered

    def test_the_default_projection_is_the_full_frame(self, tmp_path: Path) -> None:
        outcome = build_pipeline(make_config(tmp_path), run_id="run_full").run()
        written = pd.read_csv(Path(outcome.written["dataset"]))
        assert "body" in written.columns and "body_pii_redacted" in written.columns

    def test_reduced_only_is_refused_with_in_place_replacement(self, tmp_path: Path) -> None:
        """The confused combination: replacement mode's source column IS the reduced
        column, so the projection would drop the reduction output itself (ADR-0024)."""
        source_path = tmp_path / "input" / "demo.csv"
        write_dataset_csv(source_path)
        destination_marker = "destination:\n  type: csv\n"
        column_marker = "  body:\n    parser: plain_text\n"
        assert destination_marker in DATASET_YAML and column_marker in DATASET_YAML
        dataset_yaml = (
            DATASET_YAML.replace(
                destination_marker, "destination:\n  type: csv\n  projection: reduced_only\n"
            )
            .replace(column_marker, f"{column_marker}    output_column: body\n")
            .format(
                source_path=source_path.as_posix(),
                destination_path=(tmp_path / "output").as_posix(),
            )
            + "\nprocessing:\n  preserve_original: false\n"
        )
        configs = write_configs(tmp_path, project_yaml=PROJECT_YAML, dataset_yaml=dataset_yaml)
        with pytest.raises(ConfigurationError) as exc_info:
            load_resolved_dataset(configs, "demo_smoke")
        assert "reduced_only" in str(exc_info.value)
        assert "projection" in str(exc_info.value)

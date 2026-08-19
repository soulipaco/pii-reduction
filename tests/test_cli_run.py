"""The `pii-reduction run` command (docs/17 D6).

Until session 9 a production reduction was reachable only from Python or the
Databricks runner — one external review's capability matrix asserted a `run`
entry point that did not exist. These tests hold the one that now does: it runs
the configured pipeline end to end, prints metadata only, and exits non-zero
when any field failed, so a scripted caller cannot mistake partial output for
success.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.cli import main
from pii_reduction.processing.field_processor import FieldProcessor
from tests.conftest import write_configs
from tests.pipeline_fixtures import (
    DATASET_YAML,
    KNOWN_EMAILS,
    KNOWN_PHONES,
    PROJECT_YAML,
    write_dataset_csv,
)

pytestmark = pytest.mark.unit


def _configs(tmp_path: Path) -> Path:
    source_path = tmp_path / "input" / "demo.csv"
    write_dataset_csv(source_path)
    return write_configs(
        tmp_path,
        project_yaml=PROJECT_YAML,
        dataset_yaml=DATASET_YAML.format(
            source_path=source_path.as_posix(),
            destination_path=(tmp_path / "output").as_posix(),
        ),
    )


class TestRunCommand:
    def test_a_clean_run_exits_zero_and_writes_the_artifact(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["run", "demo_smoke", "--configs", str(_configs(tmp_path))])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "status=success" in captured.out
        assert "dataset:" in captured.out

        written = pd.read_csv(tmp_path / "output" / "demo_smoke.csv")
        assert "body_pii_redacted" in written.columns
        assert len(written) == 20

    def test_the_output_is_metadata_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The summary must never quote source text (AGENTS.md rule 8).
        main(["run", "demo_smoke", "--configs", str(_configs(tmp_path))])
        captured = capsys.readouterr()
        for value in KNOWN_EMAILS + KNOWN_PHONES:
            assert value not in captured.out
            assert value not in captured.err

    def test_failing_fields_exit_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Partial output must look like a failure to a scripted caller.

        Every field failing exercises the FAILED run status, and the warning
        stream the failures emit must stay metadata-only too (AGENTS.md rule 8).
        """

        def explode(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("synthetic processor failure")

        monkeypatch.setattr(FieldProcessor, "process", explode)
        exit_code = main(["run", "demo_smoke", "--configs", str(_configs(tmp_path))])
        captured = capsys.readouterr()
        assert exit_code == 1
        for value in KNOWN_EMAILS + KNOWN_PHONES:
            assert value not in captured.out
            assert value not in captured.err

    def test_a_single_failing_field_is_partial_failure_and_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        original = FieldProcessor.process
        state = {"failed": False}

        def explode_once(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if not state["failed"]:
                state["failed"] = True
                raise RuntimeError("synthetic processor failure")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(FieldProcessor, "process", explode_once)
        exit_code = main(["run", "demo_smoke", "--configs", str(_configs(tmp_path))])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "status=partial_failure" in captured.out

    def test_an_unknown_dataset_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["run", "demo_missing", "--configs", str(_configs(tmp_path))])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "demo_missing" in captured.err

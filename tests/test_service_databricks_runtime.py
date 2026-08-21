"""The Databricks runtime of the service layer, tested without a workspace.

`service/runtimes/databricks.py` is the one file outside `databricks/` permitted to
import that surface (ADR-0026), so its wiring is the part most likely to be wrong and
least likely to be exercised — the same shape as session 10's defect 2, where a wheel
task ignored a return value and reported a failed run green.

Two seams make this a default-tier test with no Spark anywhere: ``session_factory``
is injected exactly as `databricks/cli.py` injects it, and `run_driver` is patched in
this module's namespace so the conversion from ``DriverRunResult`` to the service's
own ``RunSummary`` is what is under test.
"""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest

from pii_reduction.databricks.runner import DriverRunResult
from pii_reduction.service import cli as cli_module
from pii_reduction.service.cli import build_runtimes, main
from pii_reduction.service.errors import RuntimeUnavailableError
from pii_reduction.service.runtimes import databricks as runtime_module
from pii_reduction.service.runtimes.databricks import databricks_runtime

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Sentinel:
    """Stands in for a Spark session. Never used for anything but identity."""


def _result(**overrides: Any) -> DriverRunResult:
    fields: dict[str, Any] = {
        "run_id": "abc123",
        "config_hash": "f" * 64,
        "rows": 30,
        "reduced_table": "cat.reduced.tickets_reduced",
        "audit_table": "cat.reduced.tickets_pii_audit",
        "metrics_table": "cat.reduced.tickets_run_metrics",
    }
    fields.update(overrides)
    return DriverRunResult(**fields)


class TestTheDriverPathRuntime:
    def test_it_converts_the_driver_result_to_service_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_run_driver(spark: Any, config: Any, **kwargs: Any) -> DriverRunResult:
            captured["spark"] = spark
            captured["kwargs"] = kwargs
            return _result()

        monkeypatch.setattr(runtime_module, "run_driver", fake_run_driver)
        session = _Sentinel()
        runtime = databricks_runtime("a-profile", session_factory=lambda profile: session)

        summary = runtime(None)  # type: ignore[arg-type]

        assert captured["spark"] is session
        assert summary.engine_run_id == "abc123"
        assert summary.rows_read == 30
        assert summary.outputs == {
            "reduced": "cat.reduced.tickets_reduced",
            "audit": "cat.reduced.tickets_pii_audit",
            "metrics": "cat.reduced.tickets_run_metrics",
        }
        # The driver result carries no per-field or per-entity totals. `None` says
        # so; `0` would read as "nothing was detected", which is a different claim.
        assert summary.fields_processed is None
        assert summary.entities_detected is None

    def test_it_passes_no_source_or_destination_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR-0026 rule 4 at the last place it could be broken.

        `run_driver` accepts `source_table`, `destination_prefix`, `reduced_only_prefix`
        and `mode`, and every one of them would let a caller redirect a run if the
        service ever threaded a request field through. It passes none, so the dataset
        configuration decides — which is what makes the service not a confused deputy.
        """
        captured: dict[str, Any] = {}

        def fake_run_driver(spark: Any, config: Any, **kwargs: Any) -> DriverRunResult:
            captured.update(kwargs)
            return _result()

        monkeypatch.setattr(runtime_module, "run_driver", fake_run_driver)
        databricks_runtime(None, session_factory=lambda profile: _Sentinel())(None)  # type: ignore[arg-type]
        assert captured == {}

    def test_the_reduced_only_projection_is_reported_when_it_was_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runtime_module,
            "run_driver",
            lambda *_a, **_k: _result(reduced_only_table="other.schema.tickets_reduced_only"),
        )
        summary = databricks_runtime(None, session_factory=lambda profile: _Sentinel())(None)  # type: ignore[arg-type]
        assert summary.outputs["reduced_only"] == "other.schema.tickets_reduced_only"

    def test_failed_fields_survive_the_conversion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The counter the run store turns into `state: failed`. Losing it here would
        # make a partial reduction look green in the status view — session 10's
        # defect 2, one layer up.
        monkeypatch.setattr(
            runtime_module,
            "run_driver",
            lambda *_a, **_k: _result(status="partial_failure", fields_failed=4),
        )
        summary = databricks_runtime(None, session_factory=lambda profile: _Sentinel())(None)  # type: ignore[arg-type]
        assert summary.fields_failed == 4
        assert summary.status == "partial_failure"

    def test_the_profile_reaches_the_session_factory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runtime_module, "run_driver", lambda *_a, **_k: _result())
        seen: list[str | None] = []

        def factory(profile: str | None) -> _Sentinel:
            seen.append(profile)
            return _Sentinel()

        databricks_runtime("prod", session_factory=factory)(None)  # type: ignore[arg-type]
        assert seen == ["prod"]


class TestTheBindRefusal:
    """`docs/19` calls an unauthenticated network bind a deployment error.

    So the code refuses it rather than printing a warning: a warning on stderr is
    invisible in a container log nobody reads, and with no authentication the bind
    address is the entire control. Fail-closed, like ADR-0023's failure mode and the
    Delta writer's `errorifexists`.
    """

    def test_a_non_localhost_bind_is_refused_without_the_acknowledgement(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["--configs", str(tmp_path), "--host", "0.0.0.0", "--port", "0"])
        assert code == 2
        message = capsys.readouterr().err
        assert "refusing to bind" in message
        assert "--i-provide-authentication" in message

    def test_the_acknowledgement_gets_past_the_refusal(self) -> None:
        # Stops at `uvicorn.run`, which is as far as this test wants to go: the point
        # is that the refusal is not what ended it.
        served: dict[str, object] = {}
        code = main(
            [
                "--configs",
                str(REPO_ROOT / "configs"),
                "--host",
                "0.0.0.0",
                "--port",
                "0",
                "--i-provide-authentication",
            ],
            serve=lambda app, **kwargs: served.update(kwargs),
        )
        assert code == 0
        assert served["host"] == "0.0.0.0"

    def test_localhost_needs_no_acknowledgement(self) -> None:
        served: dict[str, object] = {}
        code = main(
            ["--configs", str(REPO_ROOT / "configs"), "--port", "0"],
            serve=lambda app, **kwargs: served.update(kwargs),
        )
        assert code == 0
        assert served["host"] == "127.0.0.1"


class TestTheMissingExtraPath:
    """`uvicorn` is in the `service` extra and **not** in `dev`.

    So the environment CI provisions — and the one most contributors have — can
    import `fastapi` and start the app, then fail at the very last step. That is the
    likeliest operator mistake this script sees, and it must produce the install
    instruction rather than a traceback from the bottom of `main` after the app and
    its worker thread have already been built.

    Caught by the architecture audit after an earlier refactor moved the import out
    of the guarded block, where nothing noticed because every other test injects
    `serve` and never reaches it.
    """

    def test_a_missing_server_exits_2_with_the_instruction(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `importlib.util.find_spec`, not `cli_module.find_spec`: strict mypy refuses
        # to read a name a module did not explicitly re-export, and setting it is
        # what the patch needs anyway.
        monkeypatch.setattr(
            cli_module,
            "find_spec",
            lambda name: None if name == "uvicorn" else find_spec(name),
        )

        code = main(["--configs", str(REPO_ROOT / "configs"), "--port", "0"])

        assert code == 2
        message = capsys.readouterr().err
        assert "uvicorn is not installed" in message
        assert '".[service]"' in message

    def test_an_injected_server_needs_no_uvicorn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`main` needs a server only if it is going to start one.

        The probe is skipped when the caller supplies `serve`, which is what lets the
        default test tier — whose `dev` extra deliberately has no `uvicorn` — drive
        the argument wiring at all.
        """
        # `importlib.util.find_spec`, not `cli_module.find_spec`: strict mypy refuses
        # to read a name a module did not explicitly re-export, and setting it is
        # what the patch needs anyway.
        monkeypatch.setattr(
            cli_module,
            "find_spec",
            lambda name: None if name == "uvicorn" else find_spec(name),
        )
        served: dict[str, object] = {}
        code = main(
            ["--configs", str(REPO_ROOT / "configs"), "--port", "0"],
            serve=lambda app, **kwargs: served.update(kwargs),
        )
        assert code == 0
        assert served["host"] == "127.0.0.1"


class TestRuntimeWiring:
    def test_a_service_started_without_the_flag_offers_only_local(self) -> None:
        assert sorted(build_runtimes()) == ["local"]

    def test_the_flag_refuses_to_start_without_the_extra(self) -> None:
        """The core venv has no `databricks-connect`, and this is the real behaviour.

        Importing the runtime module succeeds without the extra — that is the point of
        the lazy session seam — so without the startup probe the service would accept
        a run, fail it on the worker thread, and record a bare
        `error_category="DatabricksError"`. The install instruction that error carries
        would never reach anybody.
        """
        with pytest.raises(RuntimeUnavailableError, match="databricks extra"):
            build_runtimes(databricks=True)

    def test_the_flag_adds_the_driver_path_when_the_extra_is_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulates the dedicated `.venv-dbx` environment: the probe finds the
        # distribution, so the runtime is offered.
        monkeypatch.setattr(cli_module, "find_spec", lambda name: object())
        assert sorted(build_runtimes(databricks=True)) == ["databricks", "local"]

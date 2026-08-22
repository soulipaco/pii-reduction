"""The service layer, driven the way a caller drives it (ADR-0026).

These tests run over a **real ASGI transport**, not a mock: `TestClient` speaks HTTP
to the application object. That is the property the whole decision rests on — session
10 produced six defects, every one found by running something rather than reading it,
and rung 4 was built specifically so that "running something" is possible on the
machine that builds it, with no workspace, no Spark and no models.

Everything here is the default tier: the committed synthetic corpus, the
deterministic chain, and the templates file this repository ships.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from pii_reduction.config.errors import ConfigurationError
from pii_reduction.config.loader import load_project_config
from pii_reduction.service.api import create_app
from pii_reduction.service.builder import build_dataset_config, config_path_for
from pii_reduction.service.errors import InvalidRequestError, UnknownTemplateError
from pii_reduction.service.models import BuildConfigRequest, ColumnRequest, RunState
from pii_reduction.service.runs import RunStore
from pii_reduction.service.runtimes.local import local_runtime
from pii_reduction.service.templates import load_templates

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIGS = REPO_ROOT / "configs"
TEMPLATE = "synthetic_corpus"


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    """A copy of the shipped configuration, so a saving test cannot dirty the repo.

    The corpus the template points at is a *relative* path resolved against the
    working directory, not against the config file, so the copy still reads the
    committed corpus — which is the point: the template under test is the one that
    ships, not a fixture written to pass.
    """
    destination = tmp_path / "configs"
    shutil.copytree(SHIPPED_CONFIGS, destination)
    # The shipped template writes to `data/output/`, relative to the working
    # directory, which would leave artifacts in the repository on every default-tier
    # run. Repointed at tmp_path so the test is hermetic on the way out as well as in.
    # The *source* stays as shipped — the committed corpus, read from its real path —
    # because the template under test should be the one that ships.
    templates = destination / "service_templates.yaml"
    templates.write_text(
        templates.read_text(encoding="utf-8").replace(
            "path: data/output/", f"path: {(tmp_path / 'output').as_posix()}/"
        ),
        encoding="utf-8",
    )
    return destination


@pytest.fixture
def store() -> Iterator[RunStore]:
    run_store = RunStore({"local": local_runtime})
    yield run_store
    run_store.shutdown()


@pytest.fixture
def client(configs_dir: Path, store: RunStore) -> Iterator[TestClient]:
    with TestClient(create_app(configs_dir, store=store)) as test_client:
        yield test_client


def _build_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "template": TEMPLATE,
        "dataset_name": "service_test",
        "row_id": "document_id",
        "columns": [{"column": "text", "entities": ["EMAIL", "PHONE"]}],
    }
    body.update(overrides)
    return body


class TestTheShippedTemplate:
    def test_it_loads_and_offers_only_class_a_values(self, configs_dir: Path) -> None:
        templates = load_templates(configs_dir)
        template = templates[TEMPLATE]
        assert not template.requires_databricks
        assert template.source.type == "csv"
        # The template exists to hold the switches a caller may not set.
        assert template.processing is not None
        assert template.processing.failure_mode is not None
        assert template.processing.failure_mode.value == "quarantine_row"
        assert template.destination.projection == "full"

    def test_a_template_naming_an_unregistered_parser_is_refused_at_load(
        self, tmp_path: Path
    ) -> None:
        # Silently intersecting with the registry would turn an operator's typo into
        # an empty menu and an error message pointing at the caller.
        (tmp_path / "service_templates.yaml").write_text(
            "templates:\n"
            "  t:\n"
            "    source: {type: csv, path: a.csv}\n"
            "    destination: {type: csv, path: out/}\n"
            "    columns: [text]\n"
            "    parsers: [note_history]\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="unknown parser"):
            load_templates(tmp_path)

    def test_a_template_naming_an_undefined_chain_is_refused_at_startup(
        self, configs_dir: Path
    ) -> None:
        """The menu must not advertise something the builder cannot deliver."""
        path = configs_dir / "service_templates.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "provider_chains: [deterministic_only, deterministic_presidio]",
                "provider_chains: [deterministic_only, no_such_chain]",
            ),
            encoding="utf-8",
        )
        store = RunStore({"local": local_runtime})
        try:
            with pytest.raises(ConfigurationError, match="no_such_chain"):
                create_app(configs_dir, store=store)
        finally:
            store.shutdown()

    def test_a_missing_templates_file_is_not_an_error(self, tmp_path: Path) -> None:
        # A configuration directory that offers no builder is a legitimate
        # deployment, and must not be a stack trace on the first request.
        assert load_templates(tmp_path) == {}

    def test_two_datasets_declaring_one_name_refuse_to_start(self, configs_dir: Path) -> None:
        """An operator error in files the service did not write belongs at startup.

        Surfacing it per request would answer 404 on whichever dataset was asked for,
        blaming a file that is not the problem.
        """
        (configs_dir / "datasets" / "shadow.yaml").write_text(
            (configs_dir / "datasets" / "benchmark_plain.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        store = RunStore({"local": local_runtime})
        try:
            with pytest.raises(ConfigurationError, match="declare the name"):
                create_app(configs_dir, store=store)
        finally:
            store.shutdown()

    def test_a_malformed_templates_file_fails_at_load(self, tmp_path: Path) -> None:
        (tmp_path / "service_templates.yaml").write_text("templates: [1, 2]", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            load_templates(tmp_path)


class TestTheBuilder:
    def test_it_produces_a_config_the_engine_validates(self, configs_dir: Path) -> None:
        templates = load_templates(configs_dir)
        project = load_project_config(configs_dir)
        built = build_dataset_config(
            BuildConfigRequest(
                template=TEMPLATE,
                dataset_name="service_test",
                row_id="document_id",
                columns=(ColumnRequest(column="text", entities=("EMAIL", "PHONE")),),
            ),
            templates=templates,
            project=project,
        )
        # `resolve_dataset` ran, which is the whole point: the builder assembles, the
        # configuration layer judges.
        assert built.resolved.dataset.name == "service_test"
        assert built.resolved.columns[0].output_column == "text_pii_redacted"

    def test_the_template_supplies_the_switches_a_caller_cannot_set(
        self, configs_dir: Path
    ) -> None:
        templates = load_templates(configs_dir)
        project = load_project_config(configs_dir)
        built = build_dataset_config(
            BuildConfigRequest(**_build_body()),
            templates=templates,
            project=project,
        )
        document = yaml.safe_load(built.to_yaml())
        assert document["source"] == {"type": "csv", "path": "tests/fixtures/corpus/corpus.csv"}
        assert document["processing"]["failure_mode"] == "quarantine_row"
        assert document["processing"]["preserve_original"] is True
        assert document["destination"]["projection"] == "full"

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"template": "nope"}, "unknown template"),
            ({"row_id": "text"}, "does not offer row id column"),
            ({"columns": [{"column": "language", "entities": ["EMAIL"]}]}, "does not offer column"),
            (
                {"columns": [{"column": "text", "entities": ["EMPLOYEE_ID"]}]},
                "does not offer entity",
            ),
            (
                {"columns": [{"column": "text", "entities": ["EMAIL"], "parser": "key_value"}]},
                "does not offer parser",
            ),
            (
                {
                    "columns": [
                        {"column": "text", "entities": ["EMAIL"], "provider_chain": "invented"}
                    ]
                },
                "does not offer provider chain",
            ),
        ],
    )
    def test_off_menu_choices_are_refused_by_name(
        self, configs_dir: Path, overrides: dict[str, object], match: str
    ) -> None:
        templates = load_templates(configs_dir)
        project = load_project_config(configs_dir)
        with pytest.raises((InvalidRequestError, UnknownTemplateError), match=match):
            build_dataset_config(
                BuildConfigRequest(**_build_body(**overrides)),
                templates=templates,
                project=project,
            )

    def test_the_row_id_column_cannot_also_be_reduced(self, configs_dir: Path) -> None:
        # A dataset whose identifier is redacted has no usable identifier, and the
        # engine would happily do it.
        templates = load_templates(configs_dir)
        templates[TEMPLATE] = templates[TEMPLATE].model_copy(
            update={"columns": ("text", "document_id")}
        )
        project = load_project_config(configs_dir)
        with pytest.raises(InvalidRequestError, match="row identifier"):
            build_dataset_config(
                BuildConfigRequest(
                    **_build_body(
                        row_id="document_id",
                        columns=[{"column": "document_id", "entities": ["EMAIL"]}],
                    )
                ),
                templates=templates,
                project=project,
            )

    @pytest.mark.parametrize(
        "name", ["../escape", "a/b", "with.dot", "UPPER", "no", "1leading", ""]
    )
    def test_a_dataset_name_that_could_escape_a_directory_is_refused(
        self, configs_dir: Path, name: str
    ) -> None:
        # The saved path is server-derived, and this is what makes that true: the
        # name is validated as an identifier before it is ever joined to a path.
        with pytest.raises(InvalidRequestError):
            config_path_for(configs_dir, name)


class TestTheHttpSurface:
    def test_health_names_the_wired_runtimes(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["runtimes"] == ["local"]

    def test_the_entity_menu_says_which_labels_are_actually_detected(
        self, client: TestClient
    ) -> None:
        # ADR-0002: ADDRESS is in the taxonomy and nothing detects it. A column
        # picker that lists it without saying so invites a configuration whose run
        # reports success and reduces none of them.
        by_label = {entry["label"]: entry for entry in client.get("/entities").json()}
        assert sorted(by_label) == ["ADDRESS", "EMAIL", "PERSON", "PHONE"]
        assert by_label["ADDRESS"]["detected_at_baseline"] is False
        assert by_label["EMAIL"]["detected_at_baseline"] is True

    def test_templates_describe_the_menu_and_not_the_data(self, client: TestClient) -> None:
        offered = {template["name"]: template for template in client.get("/templates").json()}
        template = offered[TEMPLATE]
        assert template["columns"] == ["text"]
        assert template["requires_databricks"] is False
        # A fixed-source template, so no file picker (ADR-0036).
        assert template["select_file"] is False
        # And the shipped inbox template is the other shape.
        assert offered["corpus_inbox"]["select_file"] is True

    def test_a_configured_dataset_is_described_by_metadata_only(self, client: TestClient) -> None:
        body = client.get("/datasets/benchmark_plain").json()
        assert body["source_type"] == "csv"
        assert len(body["config_hash"]) == 64
        assert body["columns"][0]["failure_mode"] == "quarantine_row"

    def test_an_unknown_dataset_answers_with_the_menu(self, client: TestClient) -> None:
        response = client.get("/datasets/nope")
        assert response.status_code == 404
        assert response.json()["error"]["category"] == "unknown_dataset"

    def test_build_returns_yaml_and_can_save_it(
        self, client: TestClient, configs_dir: Path
    ) -> None:
        response = client.post("/configs", json=_build_body(save=True))
        assert response.status_code == 201
        body = response.json()
        assert body["dataset"]["name"] == "service_test"
        # Relative to the configuration directory: an absolute path carries the
        # deployment root and, on a developer machine, an OS username, and this value
        # goes to a caller (`docs/09`).
        assert body["saved_path"] == "datasets/service_test.yaml"
        assert (configs_dir / body["saved_path"]).is_file()
        # Round trip: what was saved is loadable as the dataset it claims to be.
        assert client.get("/datasets/service_test").json()["name"] == "service_test"

    def test_a_build_cannot_take_a_name_another_dataset_declares(self, client: TestClient) -> None:
        """`open("x")` guards the file name; this guards the *declared* name.

        `benchmark_plain.yaml` declares `benchmark_corpus_plain`. Saving a dataset
        under that name would put two datasets' output in one place and — because the
        reader refuses the resulting ambiguity — make `benchmark_plain` unreachable,
        with the 404 blaming the file nobody touched.
        """
        assert "benchmark_plain" in client.get("/datasets").json()
        response = client.post(
            "/configs", json=_build_body(dataset_name="benchmark_corpus_plain", save=True)
        )
        assert response.status_code == 400
        assert "already used" in response.json()["error"]["message"]
        assert client.get("/datasets/benchmark_plain").status_code == 200

    def test_saving_over_an_existing_dataset_is_refused(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        assert client.post("/configs", json=_build_body(save=True)).status_code == 201
        response = client.post("/configs", json=_build_body(save=True))
        assert response.status_code == 400
        assert response.json()["error"]["category"] == "invalid_configuration"
        # The dataset name, not the path. A path is a server-environment string.
        assert str(tmp_path) not in response.text

    def test_unknown_paths_and_methods_use_the_documented_envelope(
        self, client: TestClient
    ) -> None:
        # Otherwise these two answer `{"detail": "Not Found"}` and the envelope
        # documented in docs/19 would be a claim with two silent exceptions.
        assert client.get("/nope").json()["error"]["category"] == "http_404"
        assert client.delete("/health").json()["error"]["category"] == "http_405"

    def test_a_caller_cannot_name_a_source_or_destination(self, client: TestClient) -> None:
        """ADR-0026 rule 4, enforced by the model having nowhere to put it.

        The service runs with its own credentials, so a request that could name a
        table would let a caller read a schema they cannot (`docs/09`, threat T4).
        """
        for extra in (
            {"source": {"type": "spark_table", "table": "a.b.c"}},
            {"destination": {"type": "delta_table", "catalog": "a", "schema": "b"}},
            {"processing": {"failure_mode": "preserve_original_and_record_error"}},
            {"projection": "reduced_only"},
            {"preserve_original": False},
        ):
            response = client.post("/configs", json=_build_body(**extra))
            assert response.status_code == 422, extra
            assert "Extra inputs are not permitted" in response.json()["error"]["message"]

    def test_a_validation_error_does_not_echo_what_was_sent(self, client: TestClient) -> None:
        """Pydantic puts the rejected value in ``input`` and FastAPI serializes it.

        The service installs its own handler because that is a framework *default*,
        not an exception it raises — so "report by category" does not reach it
        (`docs/09`, request payloads).
        """
        # Deliberately unmistakable rather than realistic: the point is that a
        # rejected value does not come back, and a fixture that looks like real
        # PII would be a fixture this repository forbids (`AGENTS.md` rule 2).
        secret = "not-a-valid-dataset-name-çöğü-that-must-not-come-back"
        response = client.post("/configs", json=_build_body(dataset_name=secret))
        assert response.status_code == 422
        assert secret not in response.text
        assert "dataset_name" in response.json()["error"]["message"]


class TestTheRunTriggerEndToEnd:
    def test_a_run_goes_from_accepted_to_succeeded_with_metadata_only(
        self, client: TestClient, store: RunStore
    ) -> None:
        """The whole flow: build a config, save it, run it, read the status.

        102 documents of the committed corpus through the deterministic chain — a
        real reduction, over real HTTP, in the default test tier.
        """
        assert client.post("/configs", json=_build_body(save=True)).status_code == 201

        accepted = client.post("/runs", json={"dataset": "service_test", "runtime": "local"})
        assert accepted.status_code == 202
        record = accepted.json()
        assert record["state"] == RunState.PENDING.value
        assert record["summary"] is None

        finished = store.wait(record["run_id"])
        assert finished.state is RunState.SUCCEEDED
        assert finished.summary is not None
        assert finished.summary.rows_read == 102
        assert finished.summary.rows_written == 102
        assert finished.summary.fields_failed == 0
        assert finished.summary.entities_reduced is not None
        assert finished.summary.entities_reduced > 0

        polled = client.get(f"/runs/{record['run_id']}").json()
        assert polled["state"] == RunState.SUCCEEDED.value
        assert polled["summary"]["engine_run_id"] == finished.summary.engine_run_id
        assert [entry["run_id"] for entry in client.get("/runs").json()] == [record["run_id"]]

    def test_an_unknown_run_is_a_404(self, client: TestClient) -> None:
        # A well-formed id (uuid4 hex) that no run has.
        response = client.get(f"/runs/{'a' * 32}")
        assert response.status_code == 404
        assert response.json()["error"]["category"] == "unknown_run"

    def test_a_malformed_run_id_never_reaches_the_404_message(self, client: TestClient) -> None:
        """Path parameters are bounded for the reason body fields are.

        An unbounded path segment is echoed by the 404 *and* recorded in the access
        log, where a caller's string becomes an operator-channel string. Bounded, it
        is refused by the 422 handler, which echoes neither.
        """
        probe = "not-a-valid-dataset-name-çöğü"
        for path in (f"/runs/{probe}", f"/datasets/{probe}"):
            response = client.get(path)
            assert response.status_code == 422, path
            assert probe not in response.text

    def test_a_runtime_this_process_does_not_offer_is_refused_before_the_run(
        self, client: TestClient
    ) -> None:
        # 409, not a failed run: a status view whose entries are all failures for a
        # deployment reason is a worse answer than a refusal.
        assert client.post("/configs", json=_build_body(save=True)).status_code == 201
        response = client.post("/runs", json={"dataset": "service_test", "runtime": "databricks"})
        assert response.status_code == 409
        assert response.json()["error"]["category"] == "runtime_unavailable"
        assert client.get("/runs").json() == []

    def test_a_failing_run_is_recorded_as_a_category_not_a_message(self, configs_dir: Path) -> None:
        """A message raised below this layer is not one this layer can vouch for."""
        leaky = "contact maria.schneider@example.com about ticket INC0012345"

        def exploding_runtime(config: object) -> object:
            raise ConfigurationError(leaky)

        run_store = RunStore({"local": exploding_runtime})  # type: ignore[dict-item]
        try:
            app = create_app(configs_dir, store=run_store)
            with TestClient(app) as client:
                submitted = client.post(
                    "/runs", json={"dataset": "benchmark_plain", "runtime": "local"}
                ).json()
                record = run_store.wait(submitted["run_id"])
                assert record.state is RunState.FAILED
                assert record.error_category == "ConfigurationError"
                assert record.summary is None
                assert leaky not in client.get(f"/runs/{submitted['run_id']}").text
        finally:
            run_store.shutdown()

    def test_failed_fields_make_the_run_state_failed(self, configs_dir: Path) -> None:
        """Partial output must look like a failure, as it does to `pii-reduction run`.

        The CLI exits 1 on this condition (R6) and the job entry point raises on it
        (session 10). A status view that called it green would be the weakest of the
        three signals over the same run.
        """
        from pii_reduction.service.models import RunSummary

        def partial_runtime(config: object) -> RunSummary:
            return RunSummary(
                engine_run_id="r", config_hash="c", status="partial_failure", fields_failed=3
            )

        run_store = RunStore({"local": partial_runtime})
        try:
            app = create_app(configs_dir, store=run_store)
            with TestClient(app) as client:
                submitted = client.post(
                    "/runs", json={"dataset": "benchmark_plain", "runtime": "local"}
                ).json()
                assert run_store.wait(submitted["run_id"]).state is RunState.FAILED
        finally:
            run_store.shutdown()


class TestParserOptionsCrossTheBoundary:
    """ADR-0034 over real HTTP: the menu, the happy path, and every refusal.

    The unit-level rules are in `tests/test_service_parser_options.py`. What is
    asserted here is that they survive the framework — that a refusal is a 4xx a
    caller can act on rather than a 500, and that an accepted option reaches the
    generated configuration.
    """

    def build(self, client: TestClient, **column: object) -> httpx.Response:
        response: httpx.Response = client.post(
            "/configs",
            json={
                "template": TEMPLATE,
                "dataset_name": "opts_dataset",
                "row_id": "document_id",
                "columns": [{"column": "text", "entities": ["PERSON"], **column}],
            },
        )
        return response

    def test_the_template_advertises_which_parser_takes_which_option(
        self, client: TestClient
    ) -> None:
        summary = next(t for t in client.get("/templates").json() if t["name"] == TEMPLATE)
        offered = summary["parser_options"]
        assert set(offered) == {"preserve_prefix", "split_lines"}
        assert offered["preserve_prefix"]["parsers"] == ["transcript"]
        assert offered["split_lines"]["parsers"] == ["plain_text"]
        # The engine's defaults, reported so a client renders the truth instead of
        # remembering it (ADR-0035). These are the parsers' own values.
        assert offered["preserve_prefix"]["default"] is True
        assert offered["split_lines"]["default"] is False
        # And a caption for each, server-side, so a knob cannot ship unexplained.
        assert all(option["caption"] for option in offered.values())

    def test_an_offered_option_reaches_the_built_configuration(self, client: TestClient) -> None:
        response = self.build(client, parser="plain_text", parser_options={"split_lines": True})
        assert response.status_code == 201, response.text
        assert "split_lines: true" in response.json()["config_yaml"]

    def test_the_other_option_reaches_it_too_on_its_own_parser(self, client: TestClient) -> None:
        response = self.build(
            client, parser="transcript", parser_options={"preserve_prefix": False}
        )
        assert response.status_code == 201, response.text
        assert "preserve_prefix: false" in response.json()["config_yaml"]

    def test_an_option_on_the_wrong_parser_is_refused_here_not_at_run_time(
        self, client: TestClient
    ) -> None:
        """The defect this check exists to prevent: a 201 followed by a failed run."""
        response = self.build(client, parser="transcript", parser_options={"split_lines": True})
        assert response.status_code == 400, response.text
        assert "does not offer" in response.json()["error"]["message"]

    def test_options_without_a_parser_are_refused(self, client: TestClient) -> None:
        response = self.build(client, parser_options={"split_lines": True})
        assert response.status_code == 400, response.text
        assert "requires 'parser'" in response.json()["error"]["message"]

    def test_an_unknown_option_is_refused(self, client: TestClient) -> None:
        response = self.build(
            client, parser="plain_text", parser_options={"max_speaker_words": True}
        )
        assert response.status_code == 400, response.text

    def test_a_non_boolean_value_is_a_422_that_does_not_echo_it(self, client: TestClient) -> None:
        """A delimiter string must not reach a parser, and must not come back either.

        The 422 handler is deliberately silent about what was sent (ADR-0026): a
        request body is Class B from the moment it exists, and a framework's default
        validation error quotes the offending input straight back.
        """
        response = self.build(client, parser="plain_text", parser_options={"split_lines": "; DROP"})
        assert response.status_code == 422, response.text
        assert "DROP" not in response.text

    def test_a_caller_supplied_key_is_not_echoed_either(self, client: TestClient) -> None:
        """The half the value test does not cover, and the one that was leaking.

        Pydantic puts a rejected value in `input` — which the handler discards — but a
        rejected **dict key** in `loc`, which the handler joins into the message.
        `parser_options` is the first request field where a caller supplies keys, so a
        client that mapped a column's content into an options map would have had that
        content reflected verbatim, unbounded, in a 422 body. Found by the privacy
        audit; the value-only test above passed throughout.
        """
        marker = "CANARY please call Ada Okonkwo on 0000 000 0000 about her account"
        response = self.build(client, parser="plain_text", parser_options={marker: True})
        assert response.status_code == 422, response.text
        assert "CANARY" not in response.text
        assert "Okonkwo" not in response.text
        # It still says *where* the error is, which is what a caller needs.
        assert "parser_options" in response.json()["error"]["message"]

    def test_an_unexpected_top_level_key_is_not_echoed_either(self, client: TestClient) -> None:
        """The pre-existing route the same fix closes.

        `extra="forbid"` reflects an unknown key the same way. `docs/19` had accepted
        that as "a key name and not a value"; an unbounded key *is* a value.
        """
        marker = "CANARY-Ada-Okonkwo-0000-000-0000"
        response = client.post(
            "/configs",
            json={
                "template": TEMPLATE,
                "dataset_name": "echo_check",
                "row_id": "document_id",
                "columns": [{"column": "text", "entities": ["PERSON"]}],
                marker: 1,
            },
        )
        assert response.status_code == 422, response.text
        assert "CANARY" not in response.text

    def test_a_saved_dataset_reports_the_options_it_resolved(self, client: TestClient) -> None:
        built = client.post(
            "/configs",
            json={
                "template": TEMPLATE,
                "dataset_name": "opts_saved",
                "row_id": "document_id",
                "columns": [
                    {
                        "column": "text",
                        "entities": ["PERSON"],
                        "parser": "plain_text",
                        "parser_options": {"split_lines": True},
                    }
                ],
                "save": True,
            },
        )
        assert built.status_code == 201, built.text
        summary = client.get("/datasets/opts_saved")
        assert summary.status_code == 200, summary.text
        assert summary.json()["columns"][0]["parser_options"] == {"split_lines": True}

    def test_a_configuration_carrying_an_option_actually_runs(
        self, client: TestClient, store: RunStore
    ) -> None:
        """The claim the pre-flight check is worth anything: 201 means it will run.

        Everything else in this class asserts a refusal. This asserts the accepting
        direction end to end — build with `split_lines`, save, trigger, succeed — so
        a passing build cannot quietly mean a run that dies when the pipeline
        constructs the parser.
        """
        built = client.post(
            "/configs",
            json={
                "template": TEMPLATE,
                "dataset_name": "opts_runnable",
                "row_id": "document_id",
                "columns": [
                    {
                        "column": "text",
                        "entities": ["EMAIL", "PHONE"],
                        "parser": "plain_text",
                        "provider_chain": "deterministic_only",
                        "parser_options": {"split_lines": True},
                    }
                ],
                "save": True,
            },
        )
        assert built.status_code == 201, built.text

        accepted = client.post("/runs", json={"dataset": "opts_runnable", "runtime": "local"})
        assert accepted.status_code == 202, accepted.text
        finished = store.wait(accepted.json()["run_id"])
        assert finished.state is RunState.SUCCEEDED
        assert finished.summary is not None
        assert finished.summary.rows_read == 102
        assert finished.summary.fields_failed == 0

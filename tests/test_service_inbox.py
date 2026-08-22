"""ADR-0036: a template may offer a directory, and a caller may name a file in it.

This is the one place the service takes a **caller-supplied string that becomes part
of a filesystem path**, so it is the one place a traversal could exist. Two defences,
tested separately because either alone would be enough and neither is trusted to be:

1. the name is pattern-bounded — no separator, no `..`, no leading dot;
2. the joined path is **resolved** and must land inside the declared directory, which
   is what catches a symlink, the only route the pattern cannot see.

The rest asserts the shape of the offer: required exactly when the template offers a
directory, refused otherwise, and the listing never opens anything.

Default tier: `tmp_path` directories and an ASGI client. No models, no workspace.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from pii_reduction.config.registries import (
    DATABRICKS_SOURCE_TYPES,
    KNOWN_SOURCE_TYPES,
    PATH_SOURCE_SUFFIXES,
)
from pii_reduction.service.api import create_app
from pii_reduction.service.errors import InvalidRequestError
from pii_reduction.service.inbox import list_offered_files, resolve_offered_file
from pii_reduction.service.runs import RunStore
from pii_reduction.service.runtimes.local import local_runtime
from pii_reduction.service.templates import DatasetTemplate

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "tests" / "fixtures" / "corpus" / "corpus.csv"


class TestTheNameIsANameNotAPath:
    """Defence 1. Every textual route out of the directory."""

    @pytest.mark.parametrize(
        "name",
        [
            "../secrets.csv",
            "..\\secrets.csv",
            "sub/dir.csv",
            "sub\\dir.csv",
            "/etc/passwd",
            "C:/Windows/win.ini",
            "..",
            ".",
            ".hidden.csv",
            "",
            "a" * 200,
            "file\x00.csv",
            "file\n.csv",
        ],
    )
    def test_it_is_refused(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, name, "csv")

    @pytest.mark.parametrize("name", ["corpus.csv", "a.csv", "tickets_2026-08.csv", "A1.CSV"])
    def test_an_ordinary_name_is_accepted(self, tmp_path: Path, name: str) -> None:
        assert resolve_offered_file(tmp_path, name, "csv").parent == tmp_path.resolve()

    def test_the_refusal_names_neither_path(self, tmp_path: Path) -> None:
        """One of them came from a request; the other is the operator's directory."""
        with pytest.raises(InvalidRequestError) as raised:
            resolve_offered_file(tmp_path, "../escape.csv", "csv")
        assert "escape" not in str(raised.value)
        assert str(tmp_path) not in str(raised.value)


class TestTheOfferAndTheAcceptanceAreTheSameSet:
    """The defect an earlier draft had, and the argument it broke.

    `list_offered_files` filtered by suffix; `resolve_offered_file` did not. So a
    caller could name any pattern-matching file the operator's directory happened to
    contain — a `.txt`, a `.bak`, an unrelated dump — that the listing had
    deliberately withheld. ADR-0036's whole safety argument is "the caller chose from
    what the place contains", and that is only true if both directions agree.

    Found by the privacy audit. The listing-side test alone could not catch it: it
    only ever checked the direction that held.
    """

    @pytest.mark.parametrize("name", ["notes.txt", "dump.bak", "data.json", "archive.csv.bak"])
    def test_a_file_the_listing_withholds_cannot_be_named(self, tmp_path: Path, name: str) -> None:
        (tmp_path / name).write_text("x", encoding="utf-8")
        assert name not in list_offered_files(tmp_path, "csv")
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, name, "csv")

    def test_the_wrong_source_type_is_refused(self, tmp_path: Path) -> None:
        """A parquet file is not offerable to a CSV template, and the reverse."""
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, "part.parquet", "csv")
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, "rows.csv", "parquet")
        assert resolve_offered_file(tmp_path, "part.parquet", "parquet").name == "part.parquet"

    def test_the_refusal_says_what_is_readable(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError, match=r"\.csv"):
            resolve_offered_file(tmp_path, "notes.txt", "csv")

    def test_a_source_type_with_no_directory_offers_and_accepts_nothing(
        self, tmp_path: Path
    ) -> None:
        """A `spark_table` has no directory; every name is refused, not silently taken."""
        assert list_offered_files(tmp_path, "spark_table") == ()
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, "anything.csv", "spark_table")

    @pytest.mark.parametrize("suffix", ["\n", "\r\n"])
    def test_a_trailing_newline_is_refused(self, tmp_path: Path, suffix: str) -> None:
        """Python's `$` matches before a final newline; pydantic's Rust engine does not.

        `fullmatch` is what keeps the two agreeing — otherwise a name ending in a
        newline would be *listed* on POSIX and then refused on the way back.
        """
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, "corpus.csv" + suffix, "csv")


class TestTheSuffixTableMatchesTheRegistry:
    """`PATH_SOURCE_SUFFIXES` restates engine knowledge, so it is pinned like the rest.

    The same trade `KNOWN_PARSER_OPTIONS` makes: restated to preserve the dependency
    direction, and held to an equality in both directions so it cannot drift.
    """

    def test_every_path_based_source_type_has_an_entry(self) -> None:
        path_based = KNOWN_SOURCE_TYPES - DATABRICKS_SOURCE_TYPES
        assert set(PATH_SOURCE_SUFFIXES) == path_based

    def test_no_databricks_source_type_has_one(self) -> None:
        """Stated rather than left to be read as an omission: a table has no directory."""
        assert set(PATH_SOURCE_SUFFIXES) & DATABRICKS_SOURCE_TYPES == set()

    def test_every_suffix_is_lowercase_and_dotted(self) -> None:
        """`_is_offerable_name` lowercases before comparing, so the table must be too."""
        for suffixes in PATH_SOURCE_SUFFIXES.values():
            assert suffixes
            for suffix in suffixes:
                assert suffix.startswith(".") and suffix == suffix.lower()


class TestCanonicalisationGaps:
    """Names that pass the pattern and are still refused, and why (ADR-0036).

    Neither is a traversal — both stay inside the directory. Both are
    *canonicalisation* mismatches, which is where traversal bugs are born: the name
    that was checked stops being the name that is opened.

    **Refused on every platform**, so a configuration built on Linux and run on
    Windows cannot mean two different things.
    """

    @pytest.mark.parametrize(
        "name", ["CON", "NUL", "COM1", "LPT9", "PRN", "AUX", "NUL.csv", "com3.CSV"]
    )
    def test_a_windows_device_name_is_refused(self, tmp_path: Path, name: str) -> None:
        """`NUL` is an empty stream and `COM1` is a serial port a read can block on.

        They pass the pattern, and containment says yes because they resolve inside
        the directory. Opening one reaches a device rather than a file.
        """
        with pytest.raises(InvalidRequestError, match="device name"):
            resolve_offered_file(tmp_path, name, "csv")

    @pytest.mark.parametrize("name", ["report.csv.", "report.csv..", "a."])
    def test_a_trailing_dot_is_refused(self, tmp_path: Path, name: str) -> None:
        """Windows strips it when opening, so `report.csv.` opens `report.csv`.

        Two names for one file, and the listing would only ever show one of them.
        """
        with pytest.raises(InvalidRequestError):
            resolve_offered_file(tmp_path, name, "csv")

    @pytest.mark.parametrize(
        "name", ["console.csv", "nullable.csv", "communications.csv", "a..b.csv", "printer.csv"]
    )
    def test_an_ordinary_name_that_merely_looks_like_one_is_fine(
        self, tmp_path: Path, name: str
    ) -> None:
        """The negative control. The rule matches the stem, not a substring."""
        assert resolve_offered_file(tmp_path, name, "csv").name == name

    def test_the_listing_and_the_builder_use_one_predicate(self, tmp_path: Path) -> None:
        """A picker must not offer a name the builder refuses, in either direction."""
        for name in ("NUL.csv", "report.csv.", "fine.csv"):
            (tmp_path / name).write_text("x", encoding="utf-8")
        offered = list_offered_files(tmp_path, "csv")
        for name in offered:
            resolve_offered_file(tmp_path, name, "csv")  # must not raise
        assert "fine.csv" in offered
        assert "NUL.csv" not in offered


class TestTheContainmentCheckIsReachable:
    """The branch the symlink tests below exercise, provable on any OS.

    Creating a symlink needs a privilege Windows does not grant by default, so those
    tests run only in CI. This one drives the same branch by making resolution move
    the path — which is exactly what a symlink does — so the check is never untested
    on a developer's machine.
    """

    def test_a_resolution_that_leaves_the_directory_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        elsewhere = tmp_path / "elsewhere" / "secret.csv"
        real_resolve = Path.resolve

        def resolve(self: Path, strict: bool = False) -> Path:
            # Only the *file* moves, as a symlink would; the directory resolves
            # normally, so this is the real asymmetry rather than a rigged pair.
            if self.name == "innocent.csv":
                return real_resolve(elsewhere)
            return real_resolve(self, strict)

        monkeypatch.setattr(Path, "resolve", resolve)
        with pytest.raises(InvalidRequestError, match="does not resolve inside"):
            resolve_offered_file(inbox, "innocent.csv", "csv")

    def test_an_ordinary_file_still_passes_under_the_same_patch(self, tmp_path: Path) -> None:
        """The negative control: the check refuses movement, not everything."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        assert resolve_offered_file(inbox, "ordinary.csv", "csv").name == "ordinary.csv"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privilege on Windows")
class TestResolutionCatchesWhatThePatternCannot:
    """Defence 2. A symlink has an ordinary name, so only resolving both sides sees it."""

    def test_a_symlink_pointing_outside_is_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.csv").write_text("x", encoding="utf-8")
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "innocent.csv").symlink_to(outside / "secret.csv")

        # The name passes the pattern — that is the whole point of this test.
        with pytest.raises(InvalidRequestError, match="does not resolve inside"):
            resolve_offered_file(inbox, "innocent.csv", "csv")

    def test_a_symlink_pointing_inside_is_fine(self, tmp_path: Path) -> None:
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "real.csv").write_text("x", encoding="utf-8")
        (inbox / "alias.csv").symlink_to(inbox / "real.csv")
        assert resolve_offered_file(inbox, "alias.csv", "csv").name == "real.csv"


class TestTheListing:
    def test_it_offers_only_what_the_source_type_can_read(self, tmp_path: Path) -> None:
        for name in ("a.csv", "b.CSV", "c.parquet", "d.txt", "notes.csv.bak"):
            (tmp_path / name).write_text("x", encoding="utf-8")
        assert list_offered_files(tmp_path, "csv") == ("a.csv", "b.CSV")
        assert list_offered_files(tmp_path, "parquet") == ("c.parquet",)

    def test_it_does_not_recurse(self, tmp_path: Path) -> None:
        """One level. A listing that walked would be a way to explore a volume."""
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "deep.csv").write_text("x", encoding="utf-8")
        (tmp_path / "top.csv").write_text("x", encoding="utf-8")
        assert list_offered_files(tmp_path, "csv") == ("top.csv",)

    def test_it_never_offers_a_name_the_builder_would_refuse(self, tmp_path: Path) -> None:
        """The picker and the builder must agree about what is pickable."""
        (tmp_path / ".hidden.csv").write_text("x", encoding="utf-8")
        (tmp_path / "fine.csv").write_text("x", encoding="utf-8")
        assert list_offered_files(tmp_path, "csv") == ("fine.csv",)

    def test_a_missing_directory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        """An inbox that does not exist yet is an ordinary state on a workspace.

        A 500 here would put the operator's directory path in a response body.
        """
        assert list_offered_files(tmp_path / "nope", "csv") == ()

    def test_an_unreadable_source_type_offers_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "a.csv").write_text("x", encoding="utf-8")
        assert list_offered_files(tmp_path, "spark_table") == ()


class TestTheTemplateRefusesAnImpossibleOffer:
    def test_select_file_on_a_table_source_is_refused_at_load(self) -> None:
        """A `spark_table` has no directory. The operator learns it from their file."""
        with pytest.raises(ValueError, match="has no path"):
            DatasetTemplate.model_validate(
                {
                    "name": "t",
                    "source": {"type": "spark_table", "table": "cat.sch.tbl"},
                    "destination": {"type": "csv", "path": "out/"},
                    "columns": ["text"],
                    "select_file": True,
                }
            )

    def test_a_fixed_source_template_offers_no_directory(self) -> None:
        template = DatasetTemplate.model_validate(
            {
                "name": "t",
                "source": {"type": "csv", "path": "x.csv"},
                "destination": {"type": "csv", "path": "out/"},
                "columns": ["text"],
            }
        )
        assert template.offered_directory() is None


@pytest.fixture
def inbox_client(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    """A service whose inbox template points at a real, writable directory."""
    configs = tmp_path / "configs"
    shutil.copytree(REPO_ROOT / "configs", configs)
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    templates_file = configs / "service_templates.yaml"
    document = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    template = document["templates"]["corpus_inbox"]
    template["source"]["path"] = inbox.as_posix()
    template["destination"]["path"] = (tmp_path / "out").as_posix() + "/"
    # **The shipped template detects language, and detection needs the `language`
    # extra** — which the default test tier deliberately does not install (ADR-0009).
    # `detect` is right for a real inbox, where nobody knows what arrives; the corpus
    # this test feeds it carries its own `language` column, so the fixture uses that
    # and the tier stays model-free and extra-free.
    #
    # This is the failure §8's Q1 already recorded once: a green local run does not
    # prove the push tier is green, because a developer machine has the extras. It
    # reached CI a second time before being caught here.
    template["language"] = {"mode": "column", "language_column": "language"}
    templates_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    store = RunStore({"local": local_runtime})
    try:
        with TestClient(create_app(configs, store=store)) as client:
            yield client, inbox
    finally:
        store.shutdown()


class TestOverHttp:
    @staticmethod
    def build(client: TestClient, **extra: Any) -> Any:
        body = {
            "template": "corpus_inbox",
            "dataset_name": "inbox_dataset",
            "row_id": "document_id",
            "columns": [
                {
                    "column": "text",
                    "entities": ["EMAIL", "PHONE"],
                    "provider_chain": "deterministic_only",
                }
            ],
            **extra,
        }
        return client.post("/configs", json=body)

    def test_the_listing_reflects_what_is_in_the_directory(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        client, inbox = inbox_client
        assert client.get("/templates/corpus_inbox/files").json() == []
        shutil.copy(CORPUS, inbox / "corpus.csv")
        assert client.get("/templates/corpus_inbox/files").json() == ["corpus.csv"]

    def test_a_fixed_source_template_answers_empty_rather_than_erroring(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        """ "Which files do you offer" has a correct answer for it, and it is none."""
        client, _ = inbox_client
        response = client.get("/templates/synthetic_corpus/files")
        assert response.status_code == 200
        assert response.json() == []

    def test_an_unknown_template_is_a_404_with_the_menu(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = inbox_client
        assert client.get("/templates/nope/files").status_code == 404

    def test_the_response_names_the_file_without_the_operators_directory(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        """`saved_path` is relativized for this reason; the document must match.

        On a workspace the joined path is `/Volumes/<catalog>/<schema>/…`, which names
        a catalog and a schema — `docs/09` puts that on the unsafe side of a display
        surface. The caller chose the file and the template chose the directory, so
        showing the placeholder withholds nothing they needed.
        """
        client, inbox = inbox_client
        shutil.copy(CORPUS, inbox / "corpus.csv")
        response = self.build(client, source_file="corpus.csv")
        assert response.status_code == 201, response.text
        document = response.json()["config_yaml"]
        assert "<template directory>/corpus.csv" in document
        assert inbox.as_posix() not in document
        assert str(inbox) not in document

    def test_the_saved_document_keeps_the_real_path(
        self, inbox_client: tuple[TestClient, Path], tmp_path: Path
    ) -> None:
        """The other half: what runs must be complete, and it is a different string.

        The saved configuration is read later by a process with no memory of the
        template, so a placeholder there would be a config that cannot run.
        """
        client, inbox = inbox_client
        shutil.copy(CORPUS, inbox / "corpus.csv")
        assert self.build(client, source_file="corpus.csv", save=True).status_code == 201
        saved = (tmp_path / "configs" / "datasets" / "inbox_dataset.yaml").read_text(
            encoding="utf-8"
        )
        assert (inbox / "corpus.csv").as_posix() in saved
        assert "<template directory>" not in saved

    def test_a_fixed_source_template_returns_its_document_unchanged(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        """The placeholder applies only where a path was joined."""
        client, _ = inbox_client
        response = client.post(
            "/configs",
            json={
                "template": "synthetic_corpus",
                "dataset_name": "fixed_doc",
                "row_id": "document_id",
                "columns": [{"column": "text", "entities": ["EMAIL"]}],
            },
        )
        assert response.status_code == 201, response.text
        document = response.json()["config_yaml"]
        assert "tests/fixtures/corpus/corpus.csv" in document
        assert "<template directory>" not in document

    def test_omitting_the_file_is_refused_with_the_available_names(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        client, inbox = inbox_client
        shutil.copy(CORPUS, inbox / "corpus.csv")
        response = self.build(client)
        assert response.status_code == 400, response.text
        message = response.json()["error"]["message"]
        assert "source_file" in message and "corpus.csv" in message

    def test_naming_a_file_for_a_fixed_source_template_is_refused(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        """Silently ignoring it is the failure `extra="forbid"` exists to prevent."""
        client, _ = inbox_client
        response = client.post(
            "/configs",
            json={
                "template": "synthetic_corpus",
                "dataset_name": "fixed_dataset",
                "row_id": "document_id",
                "columns": [{"column": "text", "entities": ["EMAIL"]}],
                "source_file": "anything.csv",
            },
        )
        assert response.status_code == 400, response.text
        assert "fixed source" in response.json()["error"]["message"]

    @pytest.mark.parametrize("name", ["../escape.csv", "sub/deep.csv", "/etc/passwd"])
    def test_a_traversal_attempt_is_a_422_that_does_not_echo_it(
        self, inbox_client: tuple[TestClient, Path], name: str
    ) -> None:
        """Refused by the pattern, before the builder, and not quoted back."""
        client, _ = inbox_client
        response = self.build(client, source_file=name)
        assert response.status_code == 422, response.text
        assert "escape" not in response.text
        assert "passwd" not in response.text

    def test_a_file_that_is_not_there_is_refused_by_the_run_not_the_build(
        self, inbox_client: tuple[TestClient, Path]
    ) -> None:
        """The builder does not stat the file, and that is deliberate.

        Checking existence at build time would mean the service reaching into the
        directory to answer a question about a *configuration*, and it would still be
        a race — the file can vanish between the check and the run. The run's own
        source error is the honest report, and it names the missing path.
        """
        client, _ = inbox_client
        response = self.build(client, source_file="absent.csv")
        assert response.status_code == 201, response.text

    def test_an_uploaded_file_runs_end_to_end(self, inbox_client: tuple[TestClient, Path]) -> None:
        """The whole point: a file appears in a directory, and a run reduces it.

        The service never receives the file — it is told which one to read, from a
        directory the operator chose.
        """
        client, inbox = inbox_client
        shutil.copy(CORPUS, inbox / "corpus.csv")
        built = self.build(client, source_file="corpus.csv", save=True)
        assert built.status_code == 201, built.text

        accepted = client.post("/runs", json={"dataset": "inbox_dataset"})
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["run_id"]
        for _ in range(200):
            record = client.get(f"/runs/{run_id}").json()
            if record["state"] in ("succeeded", "failed"):
                break
        assert record["state"] == "succeeded", record
        assert record["summary"]["rows_read"] == 102
        assert record["summary"]["fields_failed"] == 0

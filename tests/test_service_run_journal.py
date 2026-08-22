"""The durable run journal: what survives a restart, and what must not pretend to.

Pickup item 2 from the session-11 list — "part of hosting being correct rather than a
follow-up to it". Without it the first thing a hosted user does (`POST /runs`, then
poll `GET /runs/{id}`) answers 404 after a restart for a run that really happened.

Default tier: a journal is file IO and a model, with no engine behind it.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import pytest

from pii_reduction.service.errors import RunJournalError
from pii_reduction.service.journal import FileRunJournal, NullRunJournal
from pii_reduction.service.models import RunRecord, RunState, RunSummary
from pii_reduction.service.runs import RunStore

pytestmark = pytest.mark.unit


def _record(run_id: str = "a" * 32, state: RunState = RunState.PENDING) -> RunRecord:
    from datetime import UTC, datetime

    return RunRecord(
        run_id=run_id,
        dataset="tickets",
        runtime="local",
        state=state,
        submitted_at=datetime(2026, 4, 3, 9, 15, tzinfo=UTC),
    )


class TestBothJournalsSatisfyTheProtocol:
    def test_both_are_accepted_where_a_journal_is_required(self, tmp_path: Path) -> None:
        """`RunJournal` is not `runtime_checkable` on purpose — `isinstance` against
        a Protocol compares method *names* and would accept a `record` taking no
        arguments. mypy checks conformance statically; this checks the store takes
        both, which is the property that actually matters."""
        for journal in (NullRunJournal(), FileRunJournal(tmp_path / "runs.jsonl")):
            store = RunStore({}, journal=journal)
            store.shutdown()

    def test_the_null_journal_remembers_nothing(self) -> None:
        journal = NullRunJournal()
        journal.record(_record())
        assert journal.load() == ()


class TestTheFileJournalRoundTrips:
    def test_a_record_survives_a_new_journal_over_the_same_file(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.jsonl"
        FileRunJournal(path).record(_record(state=RunState.SUCCEEDED))
        assert [r.run_id for r in FileRunJournal(path).load()] == ["a" * 32]

    def test_the_last_state_of_a_run_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.jsonl"
        journal = FileRunJournal(path)
        journal.record(_record(state=RunState.PENDING))
        journal.record(_record(state=RunState.RUNNING))
        journal.record(_record(state=RunState.SUCCEEDED))
        loaded = FileRunJournal(path).load()
        assert len(loaded) == 1
        assert loaded[0].state is RunState.SUCCEEDED

    def test_a_missing_file_is_an_empty_history_not_an_error(self, tmp_path: Path) -> None:
        assert FileRunJournal(tmp_path / "nothing.jsonl").load() == ()

    def test_the_parent_directory_is_created(self, tmp_path: Path) -> None:
        journal = FileRunJournal(tmp_path / "deep" / "deeper" / "runs.jsonl")
        journal.record(_record())
        assert journal.path.exists()


class TestItRefusesToServeAPartialHistory:
    """ "Found nothing" must not be reachable by accident — this repository's own rule,
    applied to the file that answers "did my run happen?"."""

    def test_a_truncated_final_line_is_tolerated(self, tmp_path: Path) -> None:
        # What a crash mid-append actually looks like.
        path = tmp_path / "runs.jsonl"
        journal = FileRunJournal(path)
        journal.record(_record(run_id="b" * 32, state=RunState.SUCCEEDED))
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"run_id": "cccc')
        loaded = journal.load()
        assert [r.run_id for r in loaded] == ["b" * 32]

    def test_a_truncated_tail_is_repaired_so_the_next_write_cannot_weld_onto_it(
        self, tmp_path: Path
    ) -> None:
        """The defect the architecture review found, and the reason tolerating a
        truncated tail without repairing it is worse than not tolerating it.

        `record()` appends, so a surviving fragment is welded onto the front of the
        next line — turning a tolerated *trailing* fragment into a malformed line in
        the *middle*. The next load then refuses the whole history and the service
        stops starting, days later, blaming a second writer that never existed.
        """
        path = tmp_path / "runs.jsonl"
        journal = FileRunJournal(path)
        journal.record(_record(run_id="b" * 32, state=RunState.SUCCEEDED))
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"run_id": "cccc')

        assert [r.run_id for r in journal.load()] == ["b" * 32]

        # Carry on as a restarted process would, then load again.
        journal.record(_record(run_id="d" * 32, state=RunState.PENDING))
        journal.record(_record(run_id="d" * 32, state=RunState.SUCCEEDED))
        loaded = journal.load()
        assert sorted(r.run_id for r in loaded) == ["b" * 32, "d" * 32]

    def test_a_malformed_line_in_the_middle_raises(self, tmp_path: Path) -> None:
        # Not a crash artifact: the file was edited, or a second writer interleaved.
        # Continuing would silently serve a history missing whatever came after it.
        path = tmp_path / "runs.jsonl"
        journal = FileRunJournal(path)
        journal.record(_record(run_id="b" * 32))
        with path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        journal.record(_record(run_id="c" * 32))
        with pytest.raises(RunJournalError, match="single writer"):
            journal.load()

    def test_the_refusal_names_the_file_and_not_its_contents(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.jsonl"
        journal = FileRunJournal(path)
        journal.record(_record(run_id="b" * 32))
        with path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        journal.record(_record(run_id="c" * 32))
        with pytest.raises(RunJournalError) as caught:
            journal.load()
        # The composed message, the chained cause, and the rendered traceback. Pydantic
        # embeds the rejected input in its own message, and the input on this branch is
        # a line of unknown provenance — chaining it would put that line into whatever
        # a hosting wrapper renders.
        rendered = "".join(
            traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
        )
        assert "not json" not in str(caught.value)
        assert caught.value.__cause__ is None
        assert "not json" not in rendered
        # And the path is on the operator log, not in the caller-facing message.
        assert str(path) not in str(caught.value)


class TestAnInterruptedRunDoesNotLookLikeWorkInProgress:
    """The worst thing a status view can show is `running` for a process that is gone:
    it is the one state a caller waits on."""

    @pytest.mark.parametrize("state", [RunState.PENDING, RunState.RUNNING])
    def test_a_non_terminal_record_is_recovered_as_failed(self, state: RunState) -> None:
        recovered = RunStore._interrupted([_record(state=state)])
        assert recovered[0].state is RunState.FAILED
        assert recovered[0].error_category == "interrupted"

    @pytest.mark.parametrize("state", [RunState.SUCCEEDED, RunState.FAILED])
    def test_a_terminal_record_is_left_exactly_alone(self, state: RunState) -> None:
        original = _record(state=state)
        assert RunStore._interrupted([original]) == (original,)

    def test_the_store_recovers_through_the_same_rule(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.jsonl"
        FileRunJournal(path).record(_record(state=RunState.RUNNING))
        store = RunStore({}, journal=FileRunJournal(path))
        try:
            record = store.get("a" * 32)
            assert record.state is RunState.FAILED
            assert record.error_category == "interrupted"
        finally:
            store.shutdown()

    def test_it_does_not_claim_the_run_wrote_nothing(self) -> None:
        """`interrupted` is a statement about the *service*, not about the data.

        Whether the reduction wrote anything before the process died is a question for
        the engine's `<dataset>_run_metrics` artifact. A category that guessed would be
        the service vouching for something it did not observe.
        """
        recovered = RunStore._interrupted([_record(state=RunState.RUNNING)])
        assert recovered[0].summary is None
        assert recovered[0].completed_at is None


class TestTheStoreWithoutAJournalIsUnchanged:
    def test_the_default_store_remembers_nothing_across_instances(self) -> None:
        store = RunStore({})
        try:
            assert store.list() == ()
        finally:
            store.shutdown()


class TestTheJournalWritesNothingButTheRecord:
    """The journal serializes the same model the API returns, so the reflection guard
    in `test_service_contracts.py` already proves no field can hold text. This is the
    written-bytes half of that claim, which a model check cannot make."""

    def test_the_written_line_is_the_record_and_nothing_more(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.jsonl"
        summary = RunSummary(
            engine_run_id="run-1",
            config_hash="abc123",
            status="success",
            rows_read=25,
            rows_written=25,
            outputs={"reduced": "cat.sch.tickets_reduced"},
        )
        record = _record(state=RunState.SUCCEEDED).model_copy(update={"summary": summary})
        FileRunJournal(path).record(record)

        payload = json.loads(path.read_text(encoding="utf-8").strip())
        assert set(payload) == set(RunRecord.model_fields)
        assert set(payload["summary"]) == set(RunSummary.model_fields)


class TestTheOperatorChoosesThePath:
    def test_no_request_model_can_carry_a_journal_path(self) -> None:
        """Same doctrine as the server-side templates (ADR-0026): a caller who could
        name a path would make the service write wherever its own credentials reach.

        Scoped to **request** models deliberately. `BuiltConfigResponse.saved_path` is
        a path the server chose and is reporting back, which is the opposite direction
        and is allowed — `docs/09` permits naming a destination that came from
        configuration. The rule is about what a caller may *supply*.
        """
        from pii_reduction.service import models

        requests = [
            getattr(models, name)
            for name in dir(models)
            if name.endswith("Request") and hasattr(getattr(models, name), "model_fields")
        ]
        assert requests, "no request models found; this guard would pass vacuously"
        for model in requests:
            offending = [
                field for field in model.model_fields if "journal" in field or "path" in field
            ]
            assert offending == [], f"{model.__name__} lets a caller name {offending}"

    def test_the_store_takes_its_journal_from_construction_not_from_a_run(self) -> None:
        # The only way a journal reaches the store is its constructor, which only the
        # console script calls. `submit` takes a resolved config and a runtime name.
        import inspect

        assert "journal" in inspect.signature(RunStore.__init__).parameters
        assert "journal" not in inspect.signature(RunStore.submit).parameters

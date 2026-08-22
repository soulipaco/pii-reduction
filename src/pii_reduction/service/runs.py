"""Triggering runs, and remembering only their metadata.

The store holds :class:`~pii_reduction.service.models.RunRecord` objects and nothing
else. It never sees a ``ProcessingOutcome``, a ``DriverRunResult`` or a frame — each
runtime converts at its own boundary (ADR-0026 rule 3), so "the status view is
metadata-only" is a property of what the process retains rather than a rule the
serializer has to enforce.

**Durable only if an operator asks for it.** By default the store is process-local,
which is honest for a run from a terminal. Given a
:class:`~pii_reduction.service.journal.RunJournal` it also survives a restart, which is
what hosting needs: the first thing a hosted user does is `POST /runs` and then poll
`GET /runs/{id}`, and without a journal that poll answers 404 for a run that happened.

The journal records what the **service** was asked and observed. The durable record of
what a run *did* remains the engine's ``<dataset>_run_metrics`` artifact, and the two
are deliberately different claims — which is why a run recovered as `interrupted` says
exactly that rather than guessing whether anything was written.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.observability.logging import get_logger, safe_fields
from pii_reduction.service.errors import RunNotFoundError, RuntimeUnavailableError
from pii_reduction.service.journal import NullRunJournal, RunJournal
from pii_reduction.service.models import RunRecord, RunState, RunSummary
from pii_reduction.service.runtimes import Runtime

__all__ = ["RunStore"]

logger = get_logger("service")


def _now() -> datetime:
    return datetime.now(UTC)


class RunStore:
    """Submit runs, one at a time, and answer questions about them.

    A single worker thread, not a pool: two reductions in one process would each
    build their own providers and NLP models, and `AGENTS.md`'s "initialize expensive
    models once per process" is the reason the pipeline caches them per instance.
    Serialising is also what makes the status view mean something — a queued run says
    `pending` rather than competing for the same memory.
    """

    #: States from which a record will not change again. One definition: the
    #: recovery policy below and `_finish_failed` must agree about what "finished"
    #: means, and two literals are how they stop agreeing.
    TERMINAL = (RunState.SUCCEEDED, RunState.FAILED)

    def __init__(self, runtimes: dict[str, Runtime], *, journal: RunJournal | None = None) -> None:
        self._runtimes = dict(runtimes)
        self._journal: RunJournal = journal or NullRunJournal()
        # Recovered **before** the executor can run anything, and rewritten on the way
        # in: a record loaded as `pending` or `running` belongs to a process that no
        # longer exists, so nothing will ever advance it. Serving it unchanged would
        # show a caller work in progress that is not in progress.
        self._records: dict[str, RunRecord] = {
            record.run_id: record for record in self._interrupted(self._journal.load())
        }
        recovered = len(self._records)
        if recovered:
            logger.info("service run history recovered %s", safe_fields(runs_recovered=recovered))
        self._lock = threading.Lock()
        # Checked under the same lock as the insert, so a run cannot be recorded as
        # `pending` and then rejected by the executor — which would leave a record
        # that never reaches a terminal state.
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pii-service-run")

    # -- introspection -----------------------------------------------------------

    @property
    def runtimes(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtimes))

    def require_runtime(self, name: str) -> Runtime:
        runtime = self._runtimes.get(name)
        if runtime is None:
            available = ", ".join(sorted(self._runtimes)) or "(none)"
            raise RuntimeUnavailableError(
                f"runtime {name!r} is not wired into this service; available: {available}"
            )
        return runtime

    # -- submission --------------------------------------------------------------

    def submit(self, config: ResolvedDataset, *, runtime: str) -> RunRecord:
        """Accept a run and return immediately with a `pending` record.

        The runtime is resolved *before* the record is created, so an unavailable
        runtime is a refusal rather than a run that fails a second later — a status
        view whose first entries are all failures is a worse answer than a 409.
        """
        runner = self.require_runtime(runtime)
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            dataset=config.dataset.name,
            runtime=runtime,
            state=RunState.PENDING,
            submitted_at=_now(),
        )
        with self._lock:
            if self._closed:
                raise RuntimeUnavailableError(
                    "this service is shutting down and is not accepting runs"
                )
            # **Journal first, then remember, then submit**, and the order is the
            # point. A failed journal write must leave no trace anywhere: recording
            # in memory first would strand a `pending` record the executor never
            # received, which is the run-that-never-terminates this class works hard
            # to make unreachable. Writing before the executor is handed the work also
            # keeps the file's state order honest — the worker could otherwise append
            # `running` before `pending`, and the last line wins on load.
            self._journal.record(record)
            self._records[record.run_id] = record
            # Submitted **inside** the lock, with the insert. Outside it, a
            # `shutdown()` landing in the gap would leave a record recorded as
            # `pending` that the executor then refuses — a run that never reaches a
            # terminal state, which is the worst thing a status view can show,
            # because it looks like work in progress. No deadlock: the worker's first
            # lock acquisition simply waits for this block to end.
            self._executor.submit(self._execute, record.run_id, config, runner)
        logger.info(
            "service run submitted %s",
            safe_fields(
                dataset=config.dataset.name, run_id=record.run_id, status=RunState.PENDING.value
            ),
        )
        return record

    def _replace(
        self,
        run_id: str,
        *,
        state: RunState | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        summary: RunSummary | None = None,
        error_category: str | None = None,
    ) -> RunRecord:
        """Update a record in place, under the lock.

        Explicit keywords rather than ``**fields``: ``model_copy(update=...)`` skips
        validation on a frozen, ``extra="forbid"`` model, so a misspelled key would
        become a stray attribute and a wrong type would be accepted silently — and
        ``**fields: object`` is exactly the signature mypy cannot see through.
        """
        fields: dict[str, object] = {
            key: value
            for key, value in (
                ("state", state),
                ("started_at", started_at),
                ("completed_at", completed_at),
                ("summary", summary),
                ("error_category", error_category),
            )
            if value is not None
        }
        with self._lock:
            updated = self._records[run_id].model_copy(update=fields)
            self._records[run_id] = updated
            # Every transition, not only terminal ones: a `running` line is what tells
            # the next process this run was interrupted rather than never started.
            #
            # **Memory first here**, the opposite of `submit`, and for the same reason
            # — a failed write must not misreport what happened. On a transition the
            # run really did reach this state, so the in-memory record is the truth and
            # the file is behind. Both failure paths were measured: on a *terminal*
            # write the raised error reaches `_execute`, which finds the record already
            # terminal and logs rather than overwriting a success with a failure; on the
            # `running` write the record is *not* terminal, so `_finish_failed` runs and
            # marks it failed — truthful, because the runner never executed. The outcome
            # is right in both cases, but for two different reasons, and the terminal
            # guard covers only one of them. In `submit` nothing has happened yet, so
            # the truthful outcome of a failed write is that no run exists.
            self._journal.record(updated)
        return updated

    def _execute(self, run_id: str, config: ResolvedDataset, runner: Runtime) -> None:
        """The worker thread's whole body, inside one try.

        Nothing here may raise into the future: an exception escaping this method is
        never retrieved by anybody, so the run would sit in `running` for the life of
        the process with no log line and no terminal state — a status view's worst
        failure, because it looks like work in progress.
        """
        try:
            self._run_once(run_id, config, runner)
        except Exception as error:
            try:
                self._finish_failed(run_id, config, f"unexpected {type(error).__name__}")
            except Exception:
                # Last resort. If the bookkeeping itself fails there is nothing left
                # to record the failure *in*, so the traceback goes to the operator's
                # channel rather than into a future nobody retrieves.
                logger.exception("service run bookkeeping failed %s", safe_fields(run_id=run_id))

    def _run_once(self, run_id: str, config: ResolvedDataset, runner: Runtime) -> None:
        self._replace(run_id, state=RunState.RUNNING, started_at=_now())
        try:
            summary = runner(config)
        except PiiReductionError as error:
            # This package's own errors are written to be privacy-safe, so the class
            # name is a meaningful category. The message is still not stored: the
            # store answers a caller, and a message raised below this layer is not
            # one this layer can vouch for (`docs/09`, errors crossing a boundary).
            self._finish_failed(run_id, config, type(error).__name__)
            return
        except Exception as error:
            self._finish_failed(run_id, config, f"unexpected {type(error).__name__}")
            return
        # A run that completed but reduced nothing successfully is not a success.
        # `pii-reduction run` exits 1 on the same condition (R6) and the job entry
        # point raises on it (session 10); a status view must not be the weaker
        # signal of the three.
        state = RunState.FAILED if summary.fields_failed else RunState.SUCCEEDED
        self._replace(run_id, state=state, completed_at=_now(), summary=summary)
        logger.info(
            "service run finished %s",
            safe_fields(
                dataset=config.dataset.name,
                run_id=run_id,
                status=summary.status,
                rows_read=summary.rows_read,
                rows_written=summary.rows_written,
                fields_failed=summary.fields_failed,
            ),
        )

    def _finish_failed(self, run_id: str, config: ResolvedDataset, category: str) -> None:
        # **Must not be called while holding `self._lock`.** It calls `get`, which
        # re-acquires it, and the lock is a plain `Lock` rather than an `RLock` on
        # purpose — an `RLock` would hide the ordering this class makes visible.
        # A record that already reached a terminal state is not rewritten. If the
        # *bookkeeping* after a success raises, the run still succeeded, and marking
        # it failed would be a worse answer than losing a log line.
        if self.get(run_id).state in self.TERMINAL:
            logger.warning(
                "service run bookkeeping failed after completion %s",
                safe_fields(dataset=config.dataset.name, run_id=run_id, error_category=category),
            )
            return
        self._replace(run_id, state=RunState.FAILED, completed_at=_now(), error_category=category)
        logger.warning(
            "service run failed %s",
            safe_fields(
                dataset=config.dataset.name,
                run_id=run_id,
                status=RunState.FAILED.value,
                error_category=category,
            ),
        )

    @classmethod
    def _interrupted(cls, records: Iterable[RunRecord]) -> tuple[RunRecord, ...]:
        """Rewrite non-terminal records as failed, because their process is gone.

        Lives here rather than in ``journal.py`` for one reason that matters: it has to
        agree with :data:`TERMINAL` about what "finished" means, and a second literal
        list of terminal states is a second thing to forget when one is added. The
        journal is durability with no opinion about run semantics; this is the opinion.

        A record loaded as `pending` or `running` is a **lie** — the thread that would
        have advanced it died with the previous process, so nothing will ever move it.
        Leaving it is the worst thing a status view can do, because `running` is the one
        state a caller waits on.

        `interrupted` rather than a guess about what went wrong. Whether the underlying
        reduction wrote anything before the process ended is a question for the engine's
        ``<dataset>_run_metrics`` artifact, which is why that remains the record of what
        a run *did*. The rewrite is **in memory only**: the file still ends at
        `running`, so an operator reading it directly sees the raw history while the API
        reports the recovery. Persisting it would be a write on a read path, and the
        recovery is idempotent anyway.
        """
        return tuple(
            record
            if record.state in cls.TERMINAL
            else record.model_copy(
                update={"state": RunState.FAILED, "error_category": "interrupted"}
            )
            for record in records
        )

    # -- reading -----------------------------------------------------------------

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            record = self._records.get(run_id)
        if record is None:
            raise RunNotFoundError(f"unknown run {run_id!r}")
        return record

    def list(self) -> tuple[RunRecord, ...]:
        """Newest first, so a status view's first page is the interesting one."""
        with self._lock:
            records = tuple(self._records.values())
        return tuple(sorted(records, key=lambda record: record.submitted_at, reverse=True))

    def wait(self, run_id: str, timeout: float = 60.0) -> RunRecord:
        """Block until a run reaches a terminal state. For tests and scripted callers.

        Deliberately **not** reachable over HTTP: an endpoint that blocks a request
        thread for the length of a reduction is a denial-of-service surface with a
        friendly name. Polling `GET /runs/{id}` is the HTTP answer.
        """
        deadline = time.monotonic() + timeout
        while True:
            record = self.get(run_id)
            if record.state in self.TERMINAL:
                return record
            if time.monotonic() >= deadline:
                raise TimeoutError(f"run {run_id!r} did not reach a terminal state in time")
            time.sleep(0.02)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)

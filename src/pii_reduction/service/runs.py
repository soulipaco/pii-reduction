"""Triggering runs, and remembering only their metadata.

The store holds :class:`~pii_reduction.service.models.RunRecord` objects and nothing
else. It never sees a ``ProcessingOutcome``, a ``DriverRunResult`` or a frame — each
runtime converts at its own boundary (ADR-0026 rule 3), so "the status view is
metadata-only" is a property of what the process retains rather than a rule the
serializer has to enforce.

**In memory, and deliberately.** A process-local store is honest for v1 and wrong for
a multi-replica deployment; the durable record of a run is the
``<dataset>_run_metrics`` artifact the engine already writes, which is where a status
view should eventually read from. Persisting service-side state is a named later
increment, not an oversight.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.observability.logging import get_logger, safe_fields
from pii_reduction.service.errors import RunNotFoundError, RuntimeUnavailableError
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

    def __init__(self, runtimes: dict[str, Runtime]) -> None:
        self._runtimes = dict(runtimes)
        self._records: dict[str, RunRecord] = {}
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

    #: States from which a record will not change again.
    TERMINAL = (RunState.SUCCEEDED, RunState.FAILED)

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

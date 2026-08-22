"""Making a run record survive the process that produced it.

The store is process-local, which is honest for a script and wrong the moment the
service is hosted: the first thing a hosted user does is `POST /runs` and then poll
`GET /runs/{id}`, and after a restart that poll answers 404 for a run that really
happened. The plan's pickup list calls this "part of hosting being correct rather
than a follow-up to it", and this is it.

**A journal, not a database.** One append-only JSON-lines file, last write wins per
run id. That is the whole design, and it is chosen for what it refuses to become: a
schema to migrate, a connection to configure, a dependency to install, or a second
place where run state can disagree with the engine's own
``<dataset>_run_metrics`` artifact — which remains the durable record of what a run
*did*. This file records what the **service** was asked and what it observed, which
is a smaller and different claim.

**Metadata only, by construction rather than by filtering.** The journal serializes
:class:`~pii_reduction.service.models.RunRecord`, the same model the API returns, so
the reflection test that proves no response carries text proves it of the file too.
Nothing here reaches into an outcome, a frame or a row result.

**Single writer.** Two replicas appending to one file would interleave partial
writes, so a hosted deployment stays single-replica until something better exists —
stated in `docs/19_SERVICE_LAYER.md` as a constraint rather than left to be
discovered. The journal makes restarts survivable; it does not make replicas safe.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Protocol

from pii_reduction.observability.logging import get_logger, safe_fields
from pii_reduction.service.errors import RunJournalError
from pii_reduction.service.models import RunRecord

__all__ = ["FileRunJournal", "NullRunJournal", "RunJournal"]

logger = get_logger("service")


class RunJournal(Protocol):
    """What :class:`~pii_reduction.service.runs.RunStore` needs of durability.

    Not ``runtime_checkable``: ``isinstance`` against a Protocol compares method
    *names*, so it would accept a ``record`` that took no arguments. Conformance
    is checked statically by the annotation in ``RunStore.__init__``, which is
    what ``mypy src tests`` verifies on every gate run.
    """

    def load(self) -> tuple[RunRecord, ...]:
        """Records from previous processes, oldest first."""

    def record(self, record: RunRecord) -> None:
        """Persist one state of one run. Called for every transition."""


class NullRunJournal:
    """Remember nothing. The default, and correct for a run from a terminal.

    Not an `Optional[RunJournal]` on the store: a null object keeps the store's code
    free of "if a journal was configured" branches, and those branches are where a
    write gets forgotten.
    """

    def load(self) -> tuple[RunRecord, ...]:
        return ()

    def record(self, record: RunRecord) -> None:
        return None


class FileRunJournal:
    """Append-only JSON lines at a path the **operator** chose.

    The path comes from the command line, never from a request — same doctrine as the
    server-side templates (ADR-0026): a caller who could name a path would make the
    service write wherever its own credentials reach.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        # One lock for the file, held across read-modify-write. The store has its own
        # lock; this one exists because a journal is usable on its own and must not
        # depend on a caller's discipline for its file to stay parseable.
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            logger.error(
                "run journal directory unavailable %s",
                safe_fields(destination=str(self._path.parent)),
            )
            raise RunJournalError(
                f"cannot create the directory for the run journal ({type(error).__name__})"
            ) from error

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> tuple[RunRecord, ...]:
        """Every record ever written, collapsed to the last state of each run.

        **A malformed line raises, except the last one, which is repaired.** A
        truncated final line is what a crash mid-append looks like: the record is
        dropped, a warning is logged, and **the file is truncated back to the last
        complete record**.

        The truncation is the part that took a review to find, and without it the
        tolerance is worse than useless. `record()` appends, so a surviving fragment
        is welded onto the front of the next line written — turning a tolerated
        *trailing* fragment into a malformed line in the *middle* of the file. The
        next load then refuses the whole history, `RunStore.__init__` raises, and the
        console script exits 2: **the service stops starting**, days after the crash,
        blaming a second writer that never existed. One ordinary crash-and-carry-on
        would have done it.

        A malformed line anywhere else still raises. That means the file was edited or
        interleaved, and continuing would silently serve a partial history — this
        package's own rule, that "found nothing" must not be reachable by accident.
        """
        if not self._path.exists():
            return ()
        with self._lock:
            text = self._path.read_text(encoding="utf-8")

        lines = [line for line in text.split("\n") if line.strip()]
        by_run: dict[str, RunRecord] = {}
        for index, line in enumerate(lines):
            try:
                record = RunRecord.model_validate_json(line)
            except ValueError as error:
                if index == len(lines) - 1:
                    logger.warning(
                        "run journal ends in a truncated record %s",
                        safe_fields(status="truncated_tail"),
                    )
                    self._drop_truncated_tail(text)
                    break
                logger.error("run journal unreadable %s", safe_fields(destination=str(self._path)))
                # **`from None`, deliberately.** Pydantic embeds the rejected input in
                # its message, and the input here is a line of *unknown provenance* —
                # this branch fires precisely when the file was edited or interleaved.
                # Chaining it would put that line into any traceback a future hosting
                # wrapper renders. The type name keeps the diagnostic value.
                raise RunJournalError(
                    f"the run journal is unreadable at record {index + 1} of "
                    f"{len(lines)} ({type(error).__name__}). A record in the middle of "
                    "the file is malformed: it was edited, or two processes wrote to "
                    "it — this service supports a single writer. The path is on the "
                    "operator log"
                ) from None
            by_run[record.run_id] = record
        return tuple(by_run.values())

    def _drop_truncated_tail(self, text: str) -> None:
        """Cut the file back to the last complete record.

        Best effort on purpose: if the truncation itself fails there is still a
        readable history in memory, and refusing to start would be a worse answer than
        a warning. The next crash-free write is what would then weld the fragment on,
        and the operator has been told twice by that point.
        """
        cut = text.rfind("\n", 0, text.rstrip("\n").rfind("\n") + 1)
        keep = text[: cut + 1] if cut >= 0 else ""
        try:
            with self._lock:
                self._path.write_text(keep, encoding="utf-8")
        except OSError:
            logger.warning(
                "run journal tail could not be repaired %s",
                safe_fields(destination=str(self._path), status="truncated_tail"),
            )

    def record(self, record: RunRecord) -> None:
        """Append one state. Flushed and fsynced, because the point is a crash.

        A buffered write that a restart loses is a journal that works in tests and
        not in the situation it exists for.
        """
        line = record.model_dump_json() + "\n"
        try:
            with self._lock, self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            logger.error("run journal unwritable %s", safe_fields(destination=str(self._path)))
            raise RunJournalError(
                f"cannot write to the run journal ({type(error).__name__})"
            ) from error

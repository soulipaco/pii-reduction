# ADR-0030: The service journals what it was asked; the engine records what a run did

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 12

## Context

The service layer's run store is process-local. That is honest for a run from a
terminal and wrong the moment the service is hosted: the first thing a hosted user does
is `POST /runs` and then poll `GET /runs/{id}`, and after a restart that poll answers
404 for a run that really happened. The session-11 pickup list calls this "part of
hosting being correct rather than a follow-up to it", and item 1 (hosting) is blocked
on a CLI issue rather than on this — so this could be built first, and was.

**The plan recorded a different answer**, and this ADR exists because that answer was
not taken:

> The `<dataset>_run_metrics` table is the record that already survives a restart.

That is true and it is not sufficient, which is a distinction worth writing down rather
than leaving in three module docstrings.

## Decision

**Two records, of two different things, joinable but not interchangeable.**

- The engine's `<dataset>_run_metrics` artifact records **what a run did**: rows read
  and written, entity counts, provider and model versions, the config hash, the source
  version. It is written *by* the run, *at the end* of it.
- The service's journal records **what the service was asked and what it observed**:
  that a request arrived, that it was accepted, that a worker started it, and how it
  ended. `--run-journal PATH` appends every state transition as JSON lines and loads
  them at startup.

`RunSummary` carries `engine_run_id` and `config_hash`, so the two are joinable. They
are deliberately not merged.

### Why the artifact cannot answer the question

Four cases where reading `<dataset>_run_metrics` returns nothing and the caller is
still owed an answer — and the fourth is the one an operator cares most about:

1. A run **submitted and never started** (the process died while it was queued).
2. A run the executor **refused** because the service was shutting down.
3. A run **killed mid-flight**, which wrote no metrics row at all.
4. A run that **crashed at second three**. `GET /runs/{id}` after a restart would
   answer 404 — indistinguishable from "you made that run id up".

The artifact also has no idea what a service `run_id` is: it is a `uuid4` this layer
minted, and nothing below rung 4 has ever seen it. And on the local runtime there is no
Delta table to read at all.

### Why this is not a second source of truth

The two records make different claims and the code keeps them apart at the one place
they could blur. `RunStore._interrupted` rewrites a recovered `pending`/`running`
record to `failed` with category **`interrupted`** — and deliberately does *not* guess
whether the reduction wrote anything before the process ended. That question belongs to
the artifact. A category like `failed_before_writing` would be this layer vouching for
something it did not observe, which is the same discipline ADR-0026 rule 3 applies to
error messages raised below the answering layer.

ADR-0026 rule 3 already deleted the fields that *would* have duplicated the artifact —
`provider_versions`, `pipeline_version`, `dropped_labels`, the detail distributions — so
`RunSummary` is a deliberately thin projection rather than a copy.

### Why a JSON-lines file rather than a database

It is chosen for what it refuses to become: a schema to migrate, a connection to
configure, a dependency to install. It also inherits the store's existing guarantees
without changing them — the store already serializes runs on one worker thread, so
there is exactly one writer within a process.

## Consequences, including the ones that are costs

- **Single replica.** Two processes appending to one file would interleave partial
  writes. The journal refuses any history with a gap in the middle rather than serving
  part of one, so the failure is loud — but the constraint is real and is now stated in
  `docs/19_SERVICE_LAYER.md` rather than discovered. Hosting inherits it.
- **A lost terminal write misreports a success.** If the fsync of the final transition
  fails, the journal ends at `running` and the next process reports
  `failed`/`interrupted` for a run that actually succeeded. The reconciliation is the
  metrics artifact — which is an argument *for* keeping the two records rather than
  against it, and is written down here because it was measured rather than assumed.
- **Recovery is in memory only.** The file still ends at `running`, so an operator
  reading it directly sees the raw history while the API reports the recovery. It is
  idempotent, and persisting it would be a write on a read path.
- **fsync happens under the store's lock**, so `GET /runs` blocks for the flush. Three
  transitions per run makes that invisible on local disk. On the Volumes/FUSE path the
  hosting increment intends, fsync latency is tens to hundreds of milliseconds and every
  status poll would stall behind it. Stated in `docs/19` next to the single-writer
  constraint. Moving the write outside the lock is a real trade rather than a free win —
  it would break `submit()`'s journal-before-accept ordering — so it is not done here.
- **Nothing bounds growth.** Every run ever submitted is retained in memory and on
  disk, `load()` reads the whole file at startup, and `GET /runs` is unpaginated. The
  store was previously bounded by process lifetime and no longer is. Rotation is safe
  (a missing file is an empty history) and is the operator's job for now; capping
  `GET /runs` is a separate increment. Recorded rather than left to be found.

## Alternatives considered

**Read run state from `<dataset>_run_metrics`.** The recorded direction, and refused
above: it cannot see the four cases that matter most, it does not know a service run id,
and it does not exist on the local runtime. It remains the right place to read what a
run *did*, and a future status view that wants entity counts should join to it.

**Persist to SQLite.** A schema, a migration story and a file-locking model, to hold a
few hundred rows that are already append-only and already single-writer. Reopens if
retention, pagination or multi-replica become requirements — at which point the file is
trivially importable.

**Do nothing and state the limitation.** This is what the plan's own hosting item
offered as the alternative: "either the hosting increment states
single-replica-and-restarts-forget as a constraint, or this lands with it." Refused
because "your run vanished" is the first thing a hosted user would experience, and
because restarts-forget and single-replica are separable — this removes the first and
leaves the second, stated.

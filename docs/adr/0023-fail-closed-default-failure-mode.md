# ADR-0023: the default failure mode is `quarantine_row` — fail closed, opt in to pass-through

**Status:** accepted · **Date:** 2026-08-19 · **Session:** 9

## Context

`ProcessingSettings.failure_mode` selects what happens when processing a field
raises: `fail_fast` aborts the run, `quarantine_row` keeps the row but writes no
reduced value, and `preserve_original_and_record_error` writes the **raw source
text** into the reduced output column and marks the row `partial_failure`
(`Pipeline._handle_failure`). Since Increment A5 the default — in
`config/models.py` *and* in the shipped `configs/project.yaml` — was
`preserve_original_and_record_error`, following `docs/01_ARCHITECTURE.md`'s advice
that it "is often the safest default" for portfolio demos.

Two independent external assessments (reconciled in
`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md`, finding D1) each ranked this the
single largest privacy defect in the repository, for the same reason: any
exception in any layer silently converts a column named "reduced" into a copy of
the raw text. The failure is visible (`pii_status`, error-category counts, a
privacy-safe warning) but nothing forces a consumer to filter on it, and the
reduced table is the artifact people read.

Verified facts that decided the priority:

1. **The most likely production failure amplifies it.** The Presidio engine is
   built lazily at first `detect`, so a missing or upgraded spaCy model raises
   `ProviderNotAvailableError` per field — under the old default, an entire run
   completes "successfully" with every row's raw text passed through.
2. **The pass-through was pinned by a test as intended behaviour**
   (`test_one_failing_row_does_not_fail_the_run_and_is_counted` asserted the
   source text appears in the reduced column), so this is a recorded behaviour
   change, not a bug fix — hence an ADR rather than a patch.
3. **The flip costs nothing measured.** Both chains re-run on the benchmark
   corpus (10/10 and 15/15 gates) and the incident corpus (6/6 and 10/10 gates)
   before and after the change: no corpus triggers a failure path, so no
   published number moves. The change is enforced by tests, not by benchmarks.
   The runs are session-9 work (`pii-reduction benchmark --gates
   configs/benchmark_gates.yaml`, `--chain deterministic_presidio`, and both
   again with `--corpus tests/fixtures/incidents --gates
   configs/incident_gates.yaml`), recorded in the session-9 handoff; the
   architecture audit for this commit re-executed all four independently.

## Decision

**`quarantine_row` is the default failure mode**, in the pydantic model and in the
shipped project configuration. On failure the row survives (row count preserved),
the reduced value is `None`, and the row carries `pii_status = failed` — nothing
unreviewed can be mistaken for reduced output.

`preserve_original_and_record_error` **remains implemented and available** as an
explicit per-project, per-dataset, or per-column opt-in. The mode was never the
problem; the default was. A demo that wants best-effort pass-through now has to
say so in configuration, where the choice is visible in the config hash and
reviewable in a diff.

`docs/01_ARCHITECTURE.md`'s failure-strategy section is superseded in place; the
old advice optimized for "the demo output looks complete" over "the reduced
artifact contains no raw text", which is backwards for a system whose one job is
the second property.

## Consequences

- **A failing field now yields an empty reduced value instead of a full leak.**
  The visible cost: a consumer joining on the reduced column sees `None` for
  failed rows and must handle it. That is the intended friction — a `None` asks a
  question; passed-through raw text answers it wrongly and silently.
- **Tests assert the fail-closed property directly.** The default-mode pipeline
  test now asserts the failed field's raw text appears in **no** reduced value of
  any row, and a shipped-config test refuses `configs/project.yaml` re-opening the
  fail-open default. The explicit opt-in keeps its own test, so the mode cannot
  rot.
- **`tests/pipeline_fixtures.py` no longer sets a failure mode**, so the fixture
  pipeline exercises the true default; tests of the two non-default modes opt in
  through `project_yaml_with_failure_mode()`, which asserts its marker so a
  fixture reshuffle cannot turn the injection into a silent no-op.
- **Run-level status semantics are unchanged.** A run with some failed fields
  still reports `partial_failure` at the run level; what changed is what lands in
  the output column, not how failure is counted.
- **No published number moved**, and none was allowed to: the gates were run
  before and after (41/41 both times). If a future corpus does trigger a failure
  path, the fail-closed default converts what would have been an invisible leak
  into a visible metric (`fields_failed`, `pii_status`) — the direction ADR-0016
  and ADR-0021 already chose: prefer the visible error.

## Alternatives rejected

- **Keep the default, document harder.** The documentation already carried the
  qualifier ("for portfolio demos"); both external reviews read it and still
  ranked the default as the top finding, because a default is what runs when
  nobody reads. A privacy property that depends on every consumer filtering
  `pii_status` is a convention, not a control.
- **`fail_fast` as the default.** Safer still, but it turns one poisoned row into
  a denial of the whole run, and the failure-isolation property ("one failing row
  does not fail the run") is load-bearing for batch use and pinned by test.
  `quarantine_row` keeps that property and the privacy one.
- **Remove `preserve_original_and_record_error` entirely.** It has a legitimate
  use (side-by-side demos on wholly synthetic data), and removing a mode is a
  bigger contract break than changing a default. Making it opt-in prices it
  correctly.

## What would revisit this

A downstream contract that cannot represent a null reduced value — for example a
sink schema with a non-null constraint on the reduced column — would need either
a sentinel replacement value (a fourth mode, e.g. `redact_entire_field`) or the
explicit opt-in. If that case arrives, add the fourth mode; do not move the
default back.

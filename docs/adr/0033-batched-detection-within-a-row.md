# ADR-0033: Detection batches within a row, and deliberately not across rows

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 13

## Context

`detect_batch` has been on the provider protocol since Increment A3 and **had no
caller**. Both external reviews found it (`docs/17` §1.4), the decision table deferred
it as D10, and it was the last item on a pickup list that had otherwise emptied.

The deferral's stated reopening condition was "Phase 7 provider work, or a demonstrated
throughput need". Neither had arrived. What had arrived was a platform: ADR-0025 makes
Azure Databricks the primary target, the driver path runs there, and `AGENTS.md`'s
Databricks rules already say *"expensive model inference should be batch-oriented"*.

Before deciding, three things were measured that nobody had.

**1. Detection is almost entirely the spaCy pass.** Over 272 English segments from the
committed corpus, `PresidioProvider.detect` takes 1.64 s and the bare `nlp()` calls
inside it take 1.57 s — **96%**. The recognizers, the context enhancer and the scoring
are the remaining 4%. So the only thing worth batching is the NLP pass.

**2. `nlp.pipe` is worth 1.6–1.8× on that pass, and Presidio exposes it.** An earlier
reading of `BatchAnalyzerEngine` as "just a loop" was **wrong**:
`analyze_iterator` runs `NlpEngine.process_batch` — one `nlp.pipe` over the batch — and
then calls the ordinary `analyze` per text with the artifacts already computed. The
supported API does the right thing, so no Presidio internals need touching.

**3. Where the batch comes from decides everything.** Measured segments per row:

| corpus | plain | transcript |
|---|---|---|
| benchmark | 1.00 | 3.00 |
| incidents | 1.00 | 5.00 |
| markup | 1.00 | 4.00 |

A plain-text column is **one segment per row**. Batching the segments of one row can
therefore do nothing at all for it, and everything for a transcript. Raw `nlp.pipe`
timings on 5-segment transcript rows: 1.00× per segment, **1.87×** batching within a
row, **2.40×** batching across rows.

## Decision

**Batch within a row. Do not batch across rows.**

`FieldProcessor` calls `provider.detect_batch(...)` **once per provider per row**, with
the row's whole segment list, instead of once per segment. `PresidioProvider` overrides
the batch hook and routes it through `BatchAnalyzerEngine.analyze_iterator`.

Three supporting rulings:

### The repair chain stays in one place

`BaseProvider.detect` did validation, ADR-0016 line-bounding, the ADR-0021 extension,
the ADR-0027 markup clip and de-duplication inline. All of it is a property of **one
text and its own spans**, so it was extracted to `_finalize` and both entry points call
it. Providers override `_detect_batch`, which sits *below* the repair chain and returns
raw candidates. **A batching provider cannot acquire a second copy of the repair logic
to drift from**, which is the failure this structure exists to prevent.

### One text is not a batch

A language group of size one delegates to the scalar `_detect`. Measured: routing a
single text through the batch machinery costs **~3%**, and a plain-text column is
exactly that case on every row. It also makes single-text identity true by construction
rather than by assertion.

### Across rows is refused, and the reason is not performance

Across-row batching is worth another ~1.35× on top (2.40× against 1.87× on the
transcript workload). It is refused because it moves detection outside the per-row
`try`/`except` that ADR-0023's `quarantine_row` depends on: **one malformed row would
take its whole batch with it**, converting a contained one-row quarantine into a
batch-sized outage. It would also break the single-language property that lets the
adapter hand a batch straight to `analyze_iterator` — a row's language is resolved once,
before any segment is detected, so a within-row batch is single-language by
construction. `analyze_iterator` accepts one language per call.

The adapter still groups a mixed batch by language, so the *contract* permits one even
though the shipped pipeline never sends one. A protocol that quietly refuses what it
advertises is worse than a slower one.

## What was measured

### Output identity, which is the precondition for all of it

`AGENTS.md` forbids moving a published number, and a throughput change that moves a
detection number is not a throughput change. Identity was verified before the wiring
was written and is now asserted by
[`tests/test_batched_detection.py`](../../tests/test_batched_detection.py):

- **576 segments** — every processable segment of all three committed corpora, in
  `en`, `de` and `el`, through both shipped Presidio instances including the Greek one
  with promotion, left extension and the markup clip active — **0 differences**;
- a mixed-language batch answers per text, and a language an instance does not serve
  yields `[]` rather than borrowing its neighbour's model;
- the base class's own rules (empty texts dropped before the batch and re-inserted in
  place, order preserved, a non-`str` refused exactly as `detect` refuses it, a
  miscounting `_detect_batch` raising rather than silently misaligning) in the default
  tier, with no models.

**All 56 gates pass unchanged** on both chains across all three corpora — 10/10, 15/15,
6/6, 10/10, 7/7, 8/8. No published number moved, because none could.

### Throughput

Median of five (benchmark corpus) or three (others) warm in-process runs, model load
excluded, `deterministic_presidio`, one laptop CPU. **Throughput is context, never a
gate** (ADR-0009); these numbers are recorded so a future change can be compared, not
so anything can be held to them.

| corpus | document type | segments/row | before | after | |
|---|---|---|---|---|---|
| benchmark | plain | 1.0 | 181.5 rows/s | 181.8 rows/s | unchanged |
| benchmark | transcript | 3.0 | 76.6 rows/s | **119.7 rows/s** | **1.56×** |
| incidents | plain | 1.0 | 83.2 rows/s | 82.1 rows/s | unchanged |
| incidents | transcript | 5.0 | 46.2 rows/s | **81.7 rows/s** | **1.77×** |
| markup | plain | 1.0 | 85.4 rows/s | 82.4 rows/s | unchanged |
| markup | transcript | 4.0 | 51.5 rows/s | **81.2 rows/s** | **1.58×** |

**The corpus is named because the shape is the whole story.** The gain tracks segments
per row and nothing else; a reader who quotes "1.77×" without saying "5-segment
transcript rows" has quoted a number that does not exist. The plain rows are the
control: the fast path means they are unchanged, and the small negative deltas are
inside the run-to-run spread (the benchmark plain slice ranged 176–184 rows/s before and
180–182 after).

**The 10k pack was not used.** It needs a download; the committed corpora do not, and
`docs/16`'s two-chain comparison is the published 10k measurement. This is a
reproducible measurement on data that ships, which is the honest fallback `docs/21`
named.

## Consequences

- **`detect_batch` has a caller**, and the last pickup-list item is closed.
- **A provider with no batch path is unaffected.** The default `_detect_batch` is still
  one `_detect` per text, pinned by a test, so the deterministic provider's behaviour
  and cost are identical.
- **The `AGENTS.md` Databricks rule is now met by the engine rather than by intention.**
  "Expensive model inference should be batch-oriented" was previously true only of the
  advice; the driver path now batches whatever the parser gives it per row.
- **`PRESIDIO_BATCH_SIZE = 32`, and it is documented as the knee.** Measured on English
  plain text, best of five: **1.69× at 32, 1.75× at 64, 1.77× at 128, 1.74× at 256** —
  flat from 32 upward within measurement noise, while a larger value only holds more
  parsed `Doc` objects in memory at once. On a Databricks worker that is the constraint
  that matters; `docs/20` §6 already records the serverless memory budget as a trap.
- **The batch wrapper is cached with the analyzer**, keyed by its identity, so it
  follows `_ENGINE_CACHE`'s lifetime: one per model set, per process.
- **A plain-text column gains nothing**, and that is stated rather than buried. An
  operator whose column is prose gets the same throughput as before; one whose column
  is a transcript or a line-split note block gets 1.5–1.8×.

## What would reopen this

- **Across-row batching**, if the per-row failure isolation can be preserved — a batch
  that re-runs its members individually when any one of them raises would do it, at the
  cost of a second pass on the failing batch. Worth ~1.35× beyond what this ships, and
  it needs its own measurement because the retry path changes the arithmetic.
- **A provider whose batch API is not output-identical.** The identity assertion is a
  contract on `detect_batch`, not a property of batching in general. A future provider
  that cannot meet it must not override the hook.
- **A transformer provider at Phase 7**, where batching stops being a 1.6× and becomes
  the difference between usable and not. The structure this ADR puts in place —
  `_detect_batch` below the repair chain — is what such a provider would plug into.

## Alternatives rejected

- **Leaving it parked.** The stated condition had not arrived, but the *reason* for the
  deferral was that nobody knew what it was worth. Measuring it took under an hour and
  the answer was 1.6–1.8× on half the corpora, with output identity verifiable in
  advance.
- **Batching across rows** — see above; it trades ADR-0023's fail-closed row isolation
  for 1.35×, and that is not a trade this project makes for throughput.
- **Overriding the public `detect_batch` in `PresidioProvider`** instead of the
  `_detect_batch` hook. It would have duplicated the whole repair chain in the adapter,
  which is precisely how the batch and scalar paths come to disagree six months later.
- **Presidio's `batch_size`/`n_process` multiprocessing.** `n_process > 1` forks per
  call; on a Databricks worker already parallel across rows that oversubscribes the CPU,
  and ADR-0015 makes CPU the only resource there is.
- **A configurable batch size.** It would be a knob with one measured value and no
  scenario in which a user knows better than the measurement. It is a module constant
  with the measurement written beside it; if a scenario appears, the constant becomes an
  option then.

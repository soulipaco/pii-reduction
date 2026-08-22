# ADR-0028: Recall is decomposed into what the detector was offered and what it never saw

**Status:** accepted · **Date:** 2026-08-21 · **Session:** 12

## Context

`AGENTS.md` rule 5 says a reduction must not treat a whole cell as eligible when the
parser contract says only part of it is. The pipeline obeys that: a provider is handed
processable segments and never the preserved structure around them.

**The benchmark did not know this.** `detection_metrics` scores every ground-truth
entity against every prediction, so an entity sitting in a region the parser preserves
counts as a miss — one no provider, threshold, promotion rule or span repair can ever
fix, because nothing was ever offered it. Nothing in the metric grain distinguished
that from a miss a better model would close.

The reference implementation at `..\pii_alternative` hit this at scale and recorded it
as one of the two conclusions it most wanted to transfer. Its whole-cell "did an email
survive?" check reported **8,346 of 8,442 cells** on a ServiceNow journal column as
recall failures. Decomposed against the preserved regions: **17,669 occurrences sat in
a note header the parser is *required* to keep**, and the genuine body-level misses
numbered **24**. A ~500× reading error, in the direction that invites someone to "fix"
a system working as specified.

**This repository has the same hazard, on a corpus it already ships.** The
incident-notes stress corpus (ADR-0022) puts the work-note author in the speaker
prefix — `2026-04-03 09:12:04 - {PERSON}:` — which `TranscriptParser` marks as
structure. ADR-0022 already states that those names "cannot be redacted by any
provider or repair rule" and that this is why tier-4 PERSON recall is 0.000 in all
three languages. It was true, it was written down, and it was **absent from every
number the benchmark produced**. A reader of the metric table saw 0.000 and had no way
to tell a scope decision from a detection failure.

## Decision

**The benchmark reports how much of the ground truth the configured parser ever
offered to a provider, beside the recall computed over it.**

- `evaluation/metrics.is_reachable(truth, ranges)` — is this span wholly inside **one**
  processable range? Wholly and one, because a span straddling a segment boundary is
  offered in pieces, and a provider that never sees the whole surface cannot return
  it; calling that reachable would credit an opportunity nobody had.
- `evaluation/metrics.reachability_metrics(truths, eligible_ranges)` →
  `ReachabilityMetric(reachable, unreachable)`.
- `run_benchmark` builds the ranges with each document type's **configured** parser
  (one parser per document type, not per document) and emits two additive rows at the
  overall grain: `unreachable_entity_rate` and `reachable_strict_recall`. Both are on
  `BenchmarkOutcome`; the summary line prints them only when the unreachable count is
  non-zero, so the line reads as a finding about that corpus rather than as decoration.

The ranges are computed in `benchmark.py` rather than in `evaluation/`, deliberately.
`evaluation/` depends on `contracts/` and nothing else; giving it a `parsers/`
dependency would put a sideways edge between two interface layers
(`docs/01_ARCHITECTURE.md`). A benchmark entry point is an execution surface and may
reach both.

**Unreachable is a scope statement, not a defect and not an excuse.** The
configuration decided that region is out of scope. What the number is *for* is that a
rising unreachable rate on a corpus that used to be reachable means the parser's idea
of the format has drifted — the same early-warning role the reference implementation
assigns to its parser-fallback counter.

## What was measured

Model-free chain unless stated. Every gate re-run before and after: **41/41 pass, no
published number moved**, which is the property an additive metric has to have.

**The committed benchmark corpus is fully reachable** — 0 of 180. That is not luck: the
injector places entities at `eligible_offsets`, which is restricted to a parser's
processable regions. The assertion now exists, so if the corpus and the parser
configuration ever drift apart, a test says so instead of every recall number quietly
becoming a blend.

**The incident-notes corpus is not**, and the decomposition is large:

| | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| ground-truth entities | 315 | 315 |
| **unreachable** | **90 (0.286)** | **90 (0.286)** |
| overall strict recall | 0.571 | 0.711 |
| **strict recall over the 225 reachable** | **0.800** | **0.996** |

The 90 are exactly the tier-4 PERSON entities in the speaker prefixes, 30 per language.
On the hybrid chain the engine finds **224 of the 225 entities it was ever offered**,
against an overall recall of 0.711 — and PERSON recall 0.326 over 135 becomes 44 of the
45 PERSON entities that reach a provider at all.

## Consequences

- **The incident corpus's published numbers are now readable.** ADR-0022's tier-4
  0.000 rows and `configs/incident_gates.yaml`'s explanatory header stop being the only
  place the reason lives. **None of those numbers changes** — the gates are the same
  floors on the same corpus.
- **`reachable_strict_recall` is not a replacement headline.** The benchmark corpus's
  published table is unaffected because nothing there is unreachable, and quoting the
  reachable number on a corpus with a large unreachable share without quoting the share
  beside it would be the mirror of the error this metric exists to prevent. Both rows
  are emitted together for that reason.
- **It sharpens the speaker-prefix question rather than answering it.** That open
  design item — redacting inside a speaker prefix collides with the reconstruction
  guarantee — now has a number attached: 28.6% of one corpus's ground truth, and the
  entire gap between 0.711 and 0.996 on the hybrid chain.
- **It is not a gate.** No gate file reads either row, and none should until the
  question of what a good unreachable rate *is* has an answer. A gate that measures
  something nobody has decided about is how a floor gets set by accident.
- **Cost.** One parse per document per benchmark run, on top of the parse the pipeline
  already does. Measured in the default tier's wall clock: unchanged.

## Alternatives rejected

- **Scoping recall to eligible regions instead of reporting both**, which is the
  reference implementation's own first option. It would silently change what every
  published number means, and `AGENTS.md` forbids moving a number without re-running
  it. Reporting both leaves the existing numbers exactly as measured.
- **Excluding unreachable entities from the corpus manifest.** That makes the corpus
  easier to look good on — ADR-0019's prohibition, and it would delete the finding
  ADR-0022 built the corpus to expose.
- **Per-slice reachability rows** (by language, tier, entity type). Deferred: the
  overall pair answers the question that exists today, and the slice grain can be added
  when something needs it rather than pre-emptively widening the metric table.
- **Computing reachability inside `evaluation/`.** Would put a `parsers/` dependency on
  a layer that has none.

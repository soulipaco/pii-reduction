# ADR-0024: an opt-in reduced-only projection makes the documented grant model realisable

**Status:** accepted · **Date:** 2026-08-19 · **Session:** 9

## Context

`docs/09_SECURITY_PRIVACY_GOVERNANCE.md` specifies a permission model in which the
"reduced schema" is granted to "broader analytics consumers". As shipped, that model
was not achievable: `Pipeline.process` appends reduced columns to the source frame
(AGENTS.md rule 4, non-destructive by default), `_validate_output` asserts the
originals unchanged, and `run_driver` wrote every artifact under one
`catalog.schema` prefix. Granting the reduced table granted the raw text. Both
external reviews found this independently and ranked it P0
(`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md`, D3): the clearest doc-vs-code
divergence with a privacy consequence.

## Decision

**A written-artifact projection, opt-in, at two surfaces:**

- **Locally:** `destination.projection: reduced_only` in the dataset contract.
  The dataset artifact is written without the configured source text columns;
  audit and run-metrics artifacts are unchanged.
- **On Databricks:** `run_driver(..., reduced_only_prefix="catalog.schema")`
  additionally writes `<dataset>_reduced_only` to that *separate* prefix. The
  full frame, audit and metrics stay under the operator's prefix; the projection
  lives where the broader grant applies.

**What "reduced-only" means, precisely:** the frame minus exactly the columns
configured for reduction. Row id, the reduced columns, `pii_run_id`, `pii_status`
and every *unconfigured* source column survive. Whether an unconfigured column
carries PII is the operator's scope declaration (AGENTS.md rule 7 cuts both
ways) — the projection neither knows nor overrides it, and saying so here is what
stops the artifact being mistaken for a stronger claim.

**In-memory behaviour is unchanged.** `process()` still returns the full frame and
still validates the originals untouched; the projection is applied at write time
only. Non-destructiveness (rule 4) and the projection are not in tension — one
governs processing, the other the shape of a written artifact.

## Consequences

- The `docs/09` grant model is now realisable with shipped code: raw source table,
  operator-prefix artifacts, and a separately-granted reduced-only table.
- A reduced-only artifact still contains whatever reduction did **not** remove:
  undetected entities (the leakage rate is the measure of these), non-PII text by
  design, and quarantined rows as nulls (ADR-0023). It is a pseudonymous
  artifact, not an anonymous one — `docs/09`'s "reduced does not automatically
  mean non-sensitive" applies to it in full.
- `DriverRunResult` gains `reduced_only_table` (None unless requested). The
  parity test asserts the projection's column set against a real workspace on
  its next run; until then the projection logic is default-tier tested locally,
  the same shipped-then-workspace-verified pattern the runner itself used.
- The local default stays `full`: changing the artifact shape under an existing
  consumer is a breaking change nothing forced.

## Alternatives rejected

- **Make `reduced_only` the default.** It would silently change every existing
  consumer's artifact, and the benchmark corpus round-trip (originals preserved
  and validated) is load-bearing for evaluation. Opt-in prices the choice
  visibly in the dataset contract and the config hash.
- **A minimal projection (row id + reduced columns only).** Strictly safer and
  strictly less useful: unconfigured columns (category, timestamps, language)
  are what make the artifact analytically usable, and dropping them implies a
  judgement about their sensitivity the tool cannot make. Rejected for the same
  reason rule 7 forbids silent scope expansion — silently declaring every other
  column sensitive is the same overreach mirrored.
- **Mutating the source column in place under a flag.** Contradicts rule 4
  outright and destroys the local/Databricks parity assertion, which hashes the
  reduced column beside the untouched original.

## What would revisit this

A consumer contract that needs column-level grants *within* the projection (some
unconfigured columns visible to some consumers) is a governance feature, not a
projection option — that is Unity Catalog column masking's job, downstream of
this artifact. If a second projection shape is ever genuinely needed, add a named
projection, never a boolean.

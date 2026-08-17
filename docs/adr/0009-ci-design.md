# ADR-0009: CI — fast model-free gate on every push; model and benchmark jobs opt-in

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

`docs/10_TESTING_QA.md` defines markers (`unit`, `integration`, `slow`,
`databricks`) and warns against wall-clock gates on heterogeneous machines.
The lg spaCy models are hundreds of MB; md models load in ~1 s and expose identical
label sets (probe-verified), making them the right CI tier for integration tests.

## Decision

GitHub Actions, three tiers:

1. **Every push/PR (`ci.yml`):** `ruff check` + `ruff format --check`, `mypy`,
   `pytest -m "not integration and not slow and not databricks"` on
   `ubuntu-latest` and `windows-latest` (Windows is the primary dev machine;
   CRLF/path bugs must surface in CI), Python 3.11. Core install only — no models,
   no extras beyond `dev`. Target: minutes.
2. **Integration (nightly + on-demand label):** installs `presidio` + `language`
   extras and **md** models plus `xx_ent_wiki_sm` (cached by hash),
   runs `-m "integration or slow"`, then the committed-corpus benchmark with
   regression gates.
3. **Never in CI:** `databricks`-marked tests (need credentials; run manually per
   ADR-0006).

Benchmark gate policy: gates are **quality floors on the committed deterministic
corpus** (e.g. EMAIL/PHONE strict recall — exact values locked from the Increment
A6/E baselines, not invented in advance), never latency/wall-clock assertions.
`docs/08`'s example numbers are explicitly *examples*; committing them as gates
before a baseline exists would be a fabricated claim. Gate values live in one
versioned config file so changing them is a reviewed, visible act
(`CONTRIBUTING.md` already forbids silently weakening gates).

## Consequences

- A contributor without models gets full signal on contracts, parsers, reducers,
  evaluation math, and privacy tests from tier 1 alone.
- Integration failures can't block unrelated pushes but are visible nightly.
- The lg-vs-md quality difference becomes a measured benchmark dimension rather
  than a CI variable (benchmarks pin lg locally; CI pins md).

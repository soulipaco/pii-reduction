# ADR-0013: Masking and deterministic pseudonymization ship in Increment A4, not Phase 8

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 3

## Context

`docs/11_ROADMAP.md` Phase 8 and `docs/14_IMPLEMENTATION_PLAN.md` §5 both deferred
masking and pseudonymization until after the first measured baseline, on the
prioritization rule that a simple baseline should be completed and measured before
more surface is added. Reduction strategy does not affect detection quality, which is
what Increments A6 and B measure.

Session 3 raised that trade-off explicitly before starting A4. The repository owner
decided to build all three strategies now, so that the extension point is real and
demonstrated rather than asserted. That decision is recorded here rather than left
implicit in the code.

Two consequences had to be settled at the same time, because they are cheap now and
expensive later.

## Decision

1. **The reducer boundary is `reduce(text, entities) -> ReductionResult`**, not
   `replacement_for(entity) -> str`. Redaction is the only strategy that does not
   need the matched value; masking and pseudonymization both do. The surface string
   is passed to `BaseReducer._replacement` and nowhere else — `ReductionOperation`
   keeps recording offsets, label, replacement and strategy only, never the original
   value (`docs/03_DATA_CONTRACTS.md` §8, `AGENTS.md` rule 8). The right-to-left
   replacement loop, span validation and operation recording live once in
   `BaseReducer`; a strategy only decides what one span becomes.
2. **Three strategies ship:** `redact` (default), `mask` (per-entity rules
   `full` / `last4` / `partial_email`, defaults per `docs/06`), and `pseudonymize`
   (HMAC-SHA256, key from the environment only, configurable scope, non-reversible).
   `config.registries.KNOWN_REDUCERS` and `reducers.registry` are pinned to each
   other by test.
3. **Pseudonymization specifics.** Key is read from the variable named by `key_env`
   (default `PII_PSEUDONYMIZATION_KEY`); a missing key is a hard failure naming the
   variable, never a generated default. Scope (`dataset` / `project` / `global`) is
   mixed into the HMAC message, so scope is a linkability decision. No normalization
   of the value before hashing (ADR-0011), so case matters unless
   `case_sensitive: false` is set deliberately. No mapping table is persisted and no
   reverse operation exists; reversible tokenization stays out of scope
   (`docs/00_PROJECT_CHARTER.md`).
4. **Collisions are detected in-process, not globally.** Tokens are a truncated
   digest (6 hex by default ≈ 16.7M values, so a birthday collision becomes likely
   somewhere past a few thousand distinct values of one entity type). The reducer
   keeps digest-to-token pairs — digests, never plaintext — and raises rather than
   silently merging two identities. Across processes and Spark workers no such check
   is possible, so `token_length` is configurable and 6 is documented as a demo
   default.
5. **Leakage is defined per strategy** for `docs/08_EVALUATION_BENCHMARKING.md` and
   Increment E. ADR-0011 defines leakage as "the ground-truth surface string survives
   in the reduced text". That holds unchanged for `redact` and `pseudonymize`. For
   `mask` it must be reported separately, because masking *deliberately* retains part
   of the value (`ma***@example.com` keeps the domain; `last4` keeps four digits).
   Benchmark rows therefore carry the strategy, and mask leakage is reported as
   "full value survived" plus a distinct "retained fragment" measure. Comparing a
   masked run's leakage against a redacted run's as if they were the same metric is
   forbidden.
6. **Masked output can be re-detected.** `ma***@example.com` still matches the EMAIL
   pattern. The idempotency guarantee is "the pipeline run twice on the same source
   produces the same output", not "reduction is a fixed point"; pointing the reducer
   at its own output remains outside the contract (`docs/10_TESTING_QA.md` §10).

## Consequences

- The first benchmark can compare reduction strategies, not just providers — a
  genuinely better portfolio story than redaction alone.
- Increment E must implement two leakage variants rather than one, and the benchmark
  schema must carry the strategy dimension.
- A pseudonymized demo cannot be reproduced by a reviewer without a key of their own;
  the demo defaults to `redact` for that reason.
- Roadmap Phase 8 loses its main content; what remains there is synthetic
  replacement and any reversible-tokenization work, which stays out of scope.

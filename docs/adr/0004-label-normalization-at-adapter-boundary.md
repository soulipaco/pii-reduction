# ADR-0004: Label normalization happens per model inside each provider adapter

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

Session 1 found German spaCy emits `PER` while English emits `PERSON`, so mapping is
per-model, not per-provider-family. Session 2 additionally verified that Presidio
performs its own internal mapping (German text returned `PERSON`, not `PER`) and
emits its own label set (`EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `URL`).
`docs/04_PII_ENGINE.md` forbids provider-native labels leaking into the codebase.

## Decision

- `entities/` owns the normalized taxonomy only (`PERSON`, `EMAIL`, `PHONE`,
  `ADDRESS`, extensible). Provider-native label strings never appear outside
  `providers/`: **each provider adapter owns its own declarative mapping table**
  from its native labels to the taxonomy, keeping `docs/04_PII_ENGINE.md`'s
  no-leakage rule literal rather than approximate.
- Every provider adapter translates to normalized labels before returning
  `EntityMatch` objects; unmapped labels are dropped and counted in run metrics
  through a shared drop-counter interface (never silently passed through).
- For the Presidio adapter the effective mapping is
  `EMAIL_ADDRESS→EMAIL`, `PHONE_NUMBER→PHONE`, `PERSON→PERSON`; `URL` is dropped
  (probe: partial-match noise such as `maria.ro` from `maria.rossi@…`);
  `LOCATION` is dropped at baseline (not ADDRESS — ADR-0002). A future
  direct-spaCy provider would own its own `PER→PERSON`-style table.

## Consequences

- A new provider is added by writing an adapter plus a mapping table — no central
  code changes.
- Dropped-label counts make silent coverage loss visible in observability output.
- Contract tests assert normalized labels for every provider via one shared suite.

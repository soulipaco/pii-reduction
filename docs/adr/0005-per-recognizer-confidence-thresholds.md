# ADR-0005: Confidence thresholds are per provider and per entity; a global threshold is forbidden

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

Session 2 measured what Presidio 2.2.364 scores actually are on synthetic text:
spaCy-backed NER hits are a **flat 0.85** regardless of certainty (correct German
PERSON, wrong Greek `ORG` on a surname, and a false-positive PERSON on the word
"Email" all scored 0.85); `EmailRecognizer` emits 1.0; `PhoneRecognizer` emits
0.40 for every format it matched (+30/+49 international, 0030-prefixed,
parenthesized US, extension-suffixed). Scores are recognizer-specific constants,
not calibrated probabilities. A single global threshold of 0.5 — a natural-looking
default — would silently drop **every phone number**.

## Decision

- Threshold configuration lives per provider **and** per entity in
  `providers.yaml`; the config schema has no global threshold field.
- Initial defaults (evidence-based placement relative to observed constants, not
  quality claims): PHONE ≥0.3, EMAIL ≥0.6, PERSON ≥0.5, applied to the Presidio
  adapter. The deterministic provider's semantics are fixed by construction:
  EMAIL matches score 1.0 (anchored structural match); PHONE scores 1.0 when
  `phonenumbers` validates the number for a configured region and 0.85 when it is
  only possible-format (matched but not region-valid).
- Real calibration happens in Increment E on the calibration split only, then
  locked (per `docs/08_EVALUATION_BENCHMARKING.md`); until then run metadata labels
  thresholds `default_uncalibrated`.
- Scores are never averaged or compared across providers (per
  `docs/04_PII_ENGINE.md`); the reconciler uses entity priority first, score only
  within a provider.

## Consequences

- Config validation rejects a bare `threshold:` key with an actionable message.
- Benchmark reports record the threshold set used, keeping results reproducible.
- If a future provider emits calibrated scores, calibration is additive — no
  schema change.

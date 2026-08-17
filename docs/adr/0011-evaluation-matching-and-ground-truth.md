# ADR-0011: Strict span matching is primary, IoU-relaxed secondary; ground truth only from the injection manifest

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

`docs/08_EVALUATION_BENCHMARKING.md` allows strict and relaxed matching but leaves
the combination open. Probe evidence makes the choice concrete: on Greek, the
multilingual model returned a PERSON span that absorbed the preceding verb
(`Ονομάζομαι Μαρία Παπαδοπούλου` as one span) — strict-only scoring would call
that a total miss even though the sensitive name is fully covered, while
relaxed-only scoring would hide boundary sloppiness that matters for reduction.
Separately, Unicode normalization changes offsets (the same Greek name is 18
codepoints in NFC, 20 in NFD — probe-verified), so span validity is tied to the
exact string form.

## Decision

- **Strict span match (type + exact start/end) is the primary metric.** Relaxed
  match (same type, IoU ≥ 0.5) is always reported beside it; the strict-relaxed
  gap is itself a published signal (boundary quality).
- **Leakage rate is computed on the reduced text**, not the spans: a ground-truth
  entity leaks if its exact surface string survives in the output. This catches
  partial redactions that span metrics miss.
- **Ground truth comes only from the injection manifest**, written at injection
  time with spans measured against the exact emitted document string. Nothing
  reverse-engineers truth from generated text after the fact
  (`AGENTS.md` benchmark-integrity rule).
- **No Unicode normalization anywhere in the pipeline or the generator.** Documents
  are processed byte-for-byte as loaded; the manifest loader validates every span
  by slice equality (`doc[start:end] == expected_surface`) and refuses the corpus
  on mismatch. Offsets are Python codepoint indices (probe confirmed spaCy,
  Presidio, and slicing agree on NFC, NFD, and astral-plane text).
- Splits per `docs/02`: 20% dev / 20% calibration / 60% test, assigned
  deterministically by seeded hash of `document_id`; thresholds calibrated on the
  calibration split only (ADR-0005).

## Consequences

- The evaluator is testable with hand-computed cases and has no dependency on any
  provider.
- Corpus regeneration is verifiable: same seed → byte-identical corpus + manifest.
- A future NFC-normalizing source adapter would be a breaking change and is
  forbidden by the slice-equality validation.

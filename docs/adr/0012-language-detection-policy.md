# ADR-0012: lingua as the language detector, restricted to configured languages, with a hard short-text gate

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

Doc examples (`docs/01`, `03`, `05`, `06`) name `fasttext` as the illustrative
detector. Session 2 compared lingua 2.1.1 and langdetect on domain-typical strings:

- lingua (restricted to en/de/el): `Thanks`→en 0.89, `Resolved`→en 0.96,
  `OK`→en 0.52, `Danke`→de 0.89, `Ευχαριστώ`→el 1.00, long sentences ≥0.99;
  200 medium detections in 9 ms after lazy init.
- langdetect: `Danke`→`da`, `Call me`→`it`, `Resolved`→`no` — unusable here.
- fastText: LID model licence CC BY-SA + Windows wheel friction — rejected
  without probing.
- Failure modes found: `maria@example.com` alone → en 0.95 (spuriously confident);
  `Resolved` → 0.96 shows **confidence alone cannot gate short text** — a
  restricted candidate set inflates confidence.

## Decision

- `lingua-language-detector`, built from the configured language set only, is the
  detector behind the `LanguageDetector` protocol (`language` extra).
- Short-text policy is a **hard gate before detection**, not a confidence check:
  after stripping emails, URLs, and digit runs, the segment needs ≥20 chars and
  ≥12 alphabetic chars; otherwise the result is `und` with reason
  `insufficient_text`. The stripping patterns are imported from the same shared
  pattern module the deterministic provider uses (single definition — the gate
  regex and the EMAIL recognizer regex must not drift apart). Below-threshold confidence (<0.70) also yields `und` with
  reason `low_confidence`.
- `und` routes to the safe fallback chain (deterministic entities only) and is
  counted in run metrics — never silently treated as English
  (`docs/05` requirement).
- Doc examples naming `fasttext` are treated as illustrative; configuration will
  name `lingua`. No doc rewrite — this ADR records the divergence.

## Consequences

- Deterministic EMAIL/PHONE still run on short/unknown text, so the most
  mechanical PII is caught even when language is unknowable.
- Detector confidence values are treated as routing metadata, not truth labels
  (`docs/05`); the restricted-set inflation is documented.
- Gate constants (20/12/0.70) are config defaults, revisited with benchmark
  evidence in Increment E, and recorded in run metadata.

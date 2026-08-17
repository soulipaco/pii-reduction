# ADR-0003: Synthetic email fixtures use example.com/org/net; `.test` reserved for edge tests

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

`AGENTS.md` requires obviously-synthetic fixtures; session 1 found Presidio's
default `EmailRecognizer` rejects `.test` domains. Session 2 swept the recognizer:
`example.com`, `example.org`, `example.net`, `example.co.uk` → EMAIL 1.0;
`example.test`, `support.invalid`, `demo.example` → no EMAIL (the last one was even
tagged PERSON 0.85). If fixtures used `.test`, the benchmark would measure the
fixture format, not detection quality.

## Options

1. Fixtures on `.test`/`.invalid` + custom Presidio email pattern accepting them.
2. Fixtures on `example.com`/`example.org`/`example.net` — RFC 2606-reserved,
   obviously synthetic, and accepted by the default recognizer.
3. Fixtures on invented fictional domains.

## Decision

Option 2 for all detection fixtures and the injected benchmark corpus. Option 1
modifies the system under test to fit the test data — backwards. Option 3 risks
colliding with real registrable domains.

`.test`/`.invalid` remain useful and are used only in explicitly-marked edge-case
tests documenting the recognizer limitation (the deterministic core EMAIL regex
accepts any ≥2-alpha TLD, so those tests also demonstrate the deterministic/Presidio
behavioral difference).

## Consequences

- No Presidio recognizer customization needed at baseline; provider config stays
  stock and documented.
- The privacy hook (`.claude/hooks/privacy_guard.py`) already allows reserved
  domains, so fixtures pass the write gate.
- Benchmark EMAIL numbers reflect detector quality on realistic-shaped synthetic
  addresses.

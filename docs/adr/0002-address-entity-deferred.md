# ADR-0002: ADDRESS stays in the taxonomy but is not detected in v0.1

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

`README.md`, `docs/00_PROJECT_CHARTER.md` and roadmap Phase 2 place `ADDRESS` in the
initial baseline. Probes (sessions 1 and 2) show no permissively-licensed model in
the candidate stack emits an address label: spaCy en/de/xx models expose only
`LOC`/`GPE`/`FAC`-style labels, and Presidio has no address recognizer. A probe of
the composition idea on synthetic German ("Musterstrasse 12, 10115 Berlin") tagged
only `Musterstrasse` and `Berlin` as LOCATION — street number and postal code were
not covered; on Greek, the street name was tagged `ORG`. Composed LOC+context rules
would ship a detector whose spans are wrong more often than right.

## Options

1. Ship LOC→ADDRESS mapping anyway and let the benchmark show poor numbers.
2. Build hand-written address grammars per locale now.
3. Keep ADDRESS in taxonomy/config/fixtures/benchmark schema; detect nothing for it
   until a capable provider (transformer/GLiNER, roadmap Phase 7) is added and
   measured.

## Decision

Option 3. Option 1 turns LOCATION false positives (cities in operational text) into
over-redaction and misrepresents span quality; option 2 is a locale rabbit hole
before any baseline exists. The benchmark reports ADDRESS rows with zero recall and
full support counts — visible, honest, and it strengthens the Phase 7 provider
story.

## Consequences

- Phase 2 exit criteria in `docs/11_ROADMAP.md` are amended by this ADR: Presidio
  increment delivers PERSON, not ADDRESS.
- Fixtures and the injection generator still produce ADDRESS ground truth so the
  gap is measured, not ignored.
- README claims must say "PERSON, EMAIL, PHONE detected; ADDRESS planned" until
  Phase 7 lands.

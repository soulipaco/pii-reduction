# ADR-0001: Core dependency stack — deterministic recognizers + Presidio/spaCy + lingua

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

The repository deliberately shipped no dependency file. `AGENTS.md` requires every
major NLP dependency to be justified. Session 2 probed one candidate stack
(Presidio 2.2.364, spaCy 3.8.15 with en/de/el/xx models, lingua 2.1.1,
phonenumbers 9.0.37, langdetect for comparison) on synthetic en/de/el text.

Probe evidence (full detail in `.claude/SESSION_HANDOFF.md`, session 2):

- Presidio detects PERSON in all three languages behind one interface, maps
  German `PER`→`PERSON` itself, and its deterministic recognizers give EMAIL 1.0
  and PHONE 0.40 scores. Warm per-text latency 7–30 ms; 3-model engine init ~8 s.
- spaCy en/de models and `xx_ent_wiki_sm` are MIT; the Greek models are
  CC BY-NC-SA (see ADR-0007) and are excluded.
- lingua identified en/de/el correctly including short strings, with usable
  confidence collapse on `OK` (0.52); langdetect misidentified `Danke`→`da`,
  `Call me`→`it`, `Resolved`→`no`.
- `phonenumbers.PhoneNumberMatcher` is the same engine behind Presidio's phone
  recognizer and works standalone for the deterministic provider.

## Options

1. Presidio + spaCy as first NER provider; deterministic EMAIL/PHONE in core;
   lingua for language detection.
2. Transformer NER (HF pipeline) first — better Greek/address potential, but
   heavyweight, GPU-leaning, offset/subword handling is extra work, and it
   pre-empts the provider-benchmark story by starting with the expensive option.
3. GLiNER zero-shot first — same objections plus less mature ecosystem.
4. langdetect / fastText for language detection — rejected on probe accuracy and
   model licence (fastText LID model is CC BY-SA) respectively.

## Decision

Option 1. Core package: `pydantic`, `PyYAML`, `pandas>=1.5,<3`, `phonenumbers`.
Extras: `presidio` (presidio-analyzer, spacy), `language` (lingua-language-detector),
`databricks`, `dev` (pytest, ruff, mypy, Faker). spaCy models are documented
installs, never pip dependencies. Transformer/GLiNER providers are deferred to
roadmap Phase 7 as benchmark comparisons, not rejected.

## Consequences

- The test suite runs with zero NLP models installed (deterministic provider only).
- Greek NER runs through `xx_ent_wiki_sm` with known boundary fuzziness; the
  benchmark must expose this rather than hide it (ADR-0011 relaxed matching).
- Presidio's flat 0.85 spaCy score makes scores non-comparable across providers
  (ADR-0005).
- Re-probe obligations if the stack changes are recorded in the handoff.

# Implementation Roadmap

## Purpose

This roadmap is intentionally phased. The project should become useful early and add sophistication only after measurable baselines exist.

---

# Phase 0 — Repository foundation

## Goal

Create a clean Python project that can run locally and is ready for Databricks integration.

## Deliverables

- Python package under `src/pii_reduction/`
- `pyproject.toml`
- dependency groups
- configuration loader
- typed core contracts
- structured logging
- test framework
- synthetic fixtures
- pre-commit/lint configuration if desired

## Exit criteria

- package imports successfully,
- configuration validates,
- test suite runs locally,
- no provider/model required yet.

---

# Phase 1 — Core parsing and redaction framework

## Goal

Prove the architecture without depending on advanced NER.

## Deliverables

### Parsers

- plain text
- transcript
- ServiceNow-style note history

### Core objects

- `TextSegment`
- `LanguageResult`
- `EntityMatch`
- `ResolvedEntity`
- `ProcessedFieldResult`

### Reduction

- `<ENTITY>` redaction
- overlap resolution
- reconstruction

### Source adapters

- pandas
- CSV
- Excel

## Provider baseline

Deterministic:

- email
- phone

## Exit criteria

- parser round-trip tests pass,
- email/phone are redacted in all three parser styles,
- original fields preserved,
- privacy-safe logs.

---

# Phase 2 — Presidio baseline

## Goal

Add a widely recognized PII framework and establish the first NLP baseline.

## Deliverables

- Presidio provider wrapper
- normalized entity mappings
- `PERSON`
- `ADDRESS`
- provider-specific thresholds
- provider version metadata
- local benchmark runner

## Exit criteria

- baseline precision/recall/F1 generated on synthetic corpus,
- provider limitations documented,
- deterministic + Presidio hybrid chain available.

> Amended by `docs/adr/0002-address-entity-deferred.md`: `ADDRESS` detection is not
> a Phase 2 deliverable (no capable permissively-licensed model exists; deferred to
> Phase 7). Minimal evaluation arrives with the first slice per
> `docs/14_IMPLEMENTATION_PLAN.md` §6, which this phase's metrics requirement
> presupposes.

---

# Phase 3 — Multilingual routing

## Goal

Make language-aware processing real rather than cosmetic.

## Deliverables

- language detector interface
- at least one detector implementation
- confidence/short-text policy
- language-provider registry
- unsupported-language fallback
- multilingual synthetic fixtures
- metrics by language

## Exit criteria

- at least three languages exercised end-to-end,
- unknown-language handling tested,
- README claims match measured coverage.

---

# Phase 4 — Public dataset demo builder

## Goal

Create a reproducible public portfolio dataset.

## Deliverables

- dataset registry
- downloader/preparation scripts
- license/provenance metadata
- customer-support ticket demo
- conversation demo
- incident-note demo
- deterministic synthetic PII injection
- ground-truth manifest

## Exit criteria

- no private data required,
- demo can be recreated from documented steps,
- exact truth spans generated deterministically.

---

# Phase 5 — Benchmark framework

## Goal

Turn the repository into a measurable comparison platform.

## Deliverables

- strict span metrics
- relaxed overlap metrics
- precision/recall/F1
- leakage rate
- document clean rate
- over-redaction checks
- runtime measurements
- slice metrics by language/entity/document type
- Markdown benchmark report

## Exit criteria

- at least two provider chains compared,
- support counts reported,
- benchmark run metadata reproducible.

---

# Phase 6 — Databricks / Spark execution

## Goal

Run the same pipeline against Spark DataFrames and Delta tables.

## Deliverables

- Spark source adapter
- Databricks table source adapter
- Delta output adapter
- batch NLP execution strategy
- worker/model lifecycle handling
- run metrics Delta table
- detection audit Delta table

## Exit criteria

- local and Databricks results match on shared fixture,
- model is not loaded once per row,
- at least one meaningful distributed benchmark executed.

---

# Phase 7 — Provider expansion

## Goal

Demonstrate provider-agnostic architecture.

Candidate additions:

- multilingual transformer NER
- GLiNER-style model
- Databricks-hosted model
- optional LLM provider

## Exit criteria

Each provider must include:

- wrapper,
- language/entity mapping,
- benchmark results,
- dependency/license documentation,
- known limitations.

No provider should be added only for a longer README list.

---

# Phase 8 — Pseudonymization

> Amended by ADR-0013: masking and deterministic pseudonymization were built in
> Increment A4 instead, together with the reducer boundary that makes them
> interchangeable. What remains open here is synthetic replacement and the optional
> reversible mapping vault (still out of scope per `docs/00_PROJECT_CHARTER.md`).

## Goal

Support analytics-preserving reduction beyond plain redaction.

Deliverables:

- deterministic token reducer
- keyed pseudonymization
- scope controls
- collision tests
- documentation of privacy limitations

Optional later:

- reversible mapping vault.

---

# Phase 9 — Databricks presentation layer

## Goal

Make the project easy to review visually.

### AI/BI dashboard

Suggested pages:

1. Benchmark overview
2. Entity quality
3. Language quality
4. Provider comparison
5. Leakage/over-redaction
6. Runtime performance
7. Parser health

### Optional Databricks App

Side-by-side public/synthetic samples:

```text
Original | Reduced | Detected entities | Provider
```

Only synthetic/public-safe data may appear.

---

# Phase 10 — Production-hardening examples

## Goal

Demonstrate design maturity without pretending the demo is enterprise production.

Potential additions:

- incremental merge pattern,
- quarantine pattern,
- config-driven data contracts,
- CI benchmark gates,
- MLflow benchmark tracking,
- Unity Catalog tags/comments,
- deployment resources,
- observability dashboard.

---

# Phase 11 — Release and adoption

## Deliverables

- polished README
- architecture diagram
- 3-5 minute walkthrough
- example benchmark results
- one-command local demo path
- Databricks quickstart
- starter issues
- contribution guide
- changelog/release notes

## Suggested first public release scope

Do not wait for every phase.

A strong `v0.1` can include:

- public demo generator,
- plain/transcript/note parsers,
- deterministic + Presidio baseline,
- three languages,
- local benchmark,
- Databricks Delta execution example,
- documented metrics.

## Prioritization rule

When deciding between a new feature and better evaluation, prefer better evaluation until the existing feature's behavior is understood.

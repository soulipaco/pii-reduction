# Implementation Roadmap

## Purpose

This roadmap is intentionally phased. The project should become useful early and add sophistication only after measurable baselines exist.

> **Status (session 13).** **Phases 0–6 are built and Phase 11 is done: `v0.1.0` is
> released.** Phase 6's distributed exit criterion is the one that remains unmet, and
> it is annotated in place below. **Phases 7–10 were never in the charter's definition
> of done** and are parked as roadmap rather than as debt (`docs/21_FINALIZATION.md`,
> *What finalization does not mean*).
>
> **This document is not the live sequence.** ADR-0025 makes Azure Databricks the
> primary deployment target, so Databricks-facing capability — config-nameable Unity
> Catalog IO, a runbook, a deployable job, batching — came before Phase 7's provider
> expansion, and did. The register of what is parked and what would reopen it is
> `docs/14_IMPLEMENTATION_PLAN.md` §8; the phase order below is kept as the record of
> how the build actually went, not rewritten to match current priorities.

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

> **Status lives in `docs/14_IMPLEMENTATION_PLAN.md` §8, not here.** Phases 0-5 are
> complete too; only this phase is annotated below, because it is the one whose exit
> criteria are *partly* met and a roadmap that reads as fully green would be wrong.

## Deliverables

Shipped as Increment F (`src/pii_reduction/databricks/`); see plan §8 F for evidence.

- ~~Spark source adapter~~ / ~~Databricks table source adapter~~ — **one adapter, not
  two**: `SparkTableSource` reads a Unity Catalog table through a Spark session, which
  is what both bullets described.
- ~~Delta output adapter~~ — `DeltaTableOutput`.
- ~~batch NLP execution strategy~~ — `distributed_frame` (`mapInPandas`).
- ~~worker/model lifecycle handling~~ — pipeline built once per worker, cache keyed on
  run id + config hash.
- ~~run metrics Delta table~~ / ~~detection audit Delta table~~ — written by
  `run_driver`, verified metadata-only.

## Exit criteria

- ~~local and Databricks results match on shared fixture~~ — **met** on the real
  workspace: reduced-column hashes equal between a Databricks run and a local one.
- ~~model is not loaded once per row~~ — **met**, and regression-guarded in the default
  tier without Spark.
- at least one meaningful distributed benchmark executed — **not met, infra-blocked.**
  The `mapInPandas` path is shipped and unit-tested, but this workspace's serverless
  Python-UDF sandbox fails server-side (`ISOLATION_STARTUP_FAILURE`), so no distributed
  run has executed. A `databricks`-marked test skips today and asserts distributed
  parity the day the sandbox works. Recorded rather than quietly dropped — plan §8 F
  carries the re-check log.

---

# Phase 7 — Provider expansion

> **Displaced by ADR-0025.** This phase is where the Greek gap's next real move
> lives (a better-licensed model, plan §8), and it is still the right next
> *quality* investment. It now sits behind the platform queue: a provider that
> nobody can run on the target platform is worth less than the path that makes the
> shipped providers deployable.

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

> Not to be confused with ADR-0025's rung 4. This is a **demo** surface over
> synthetic/public data for reviewers; rung 4 is the service layer over the engine
> for internal operators. Same technology, different data class and different
> obligations.

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

# Phase 11 — Release and adoption — **DONE (`v0.1.0`, 2026-08-22)**

## Deliverables

Seven of ten shipped. The three that did not are parked here rather than dropped
quietly, because a deliverable list with silent omissions is not a record.

| deliverable | state |
|---|---|
| polished README | done — revised in session 9's honesty sweep and again at the release |
| example benchmark results | done — `docs/14` §8: three corpora, both chains, all locked as gates |
| one-command local demo path | done — `pip install -e ".[dev]"`, then `pii-reduction benchmark` |
| Databricks quickstart | done — `docs/18_RUNBOOK_DATABRICKS.md`, executed end to end |
| contribution guide | done — `CONTRIBUTING.md`, `AGENTS.md`, `SECURITY.md` |
| changelog / release notes | done — `CHANGELOG.md` |
| documented metrics | done — `docs/08`, and every published number is a gate |
| architecture diagram | **not shipped.** `docs/01_ARCHITECTURE.md` carries the component boundaries and dependency direction in prose and tables, and static guards enforce them. A diagram would render documentation that already exists and is tested. Parked. |
| 3–5 minute walkthrough | **not shipped.** A recording is a portfolio artifact rather than a repository one; `docs/13_PORTFOLIO_STORY.md` is the script for it. Parked. |
| starter issues | **not shipped.** The repository is private and has no contributors to onboard. Reopens if it is made public — in the same change as the `NOTICE` obligation (`docs/17` D14). |

## Suggested first public release scope — met, with one substitution

Written in session 2 as a target. What `v0.1.0` shipped against it:

| planned | shipped |
|---|---|
| public demo generator | yes — plus three public-dataset packs from pinned checksummed sources (ADR-0017) |
| plain/transcript/**note** parsers | plain and transcript; **not** note-history. Deferred as `docs/17` D13, whose blocking condition — the speaker-prefix decision — was met by ADR-0032, so it now rests on its own merits. Charter UC-03 carries the unmet status. |
| deterministic + Presidio baseline | yes, both chains, both gated |
| three languages | yes — en, de, el |
| local benchmark | yes, plus 56 regression gates over three corpora |
| Databricks Delta execution example | yes — driver-path parity asserted against a real workspace |
| documented metrics | yes |

## Prioritization rule

When deciding between a new feature and better evaluation, prefer better evaluation until the existing feature's behavior is understood.

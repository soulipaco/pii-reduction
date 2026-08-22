# AGENTS.md

This file defines repository-wide working rules for coding agents such as Codex, Claude Code, or other automated development assistants.

## Mission

Implement and maintain a portfolio-quality, open-source Databricks PII Reduction Accelerator according to the contracts in `README.md` and `docs/`.

The project must remain:

- reproducible,
- privacy-safe,
- modular,
- testable locally,
- executable on Databricks,
- provider-agnostic,
- multilingual by design,
- measurable through deterministic evaluation.

## Read-before-edit order

Before making significant architectural changes, read:

1. `README.md`
2. `docs/00_PROJECT_CHARTER.md`
3. `docs/01_ARCHITECTURE.md`
4. the domain-specific document related to the requested change
5. existing tests for the affected component

Do not redesign the repository based only on one isolated task if the change would violate these contracts.

## Hard rules

### 1. No secrets

Never commit, print, echo, log, serialize, or add example values that resemble real authentication secrets.

Use environment variables or Databricks secret references. `.env.example` may contain variable names but must not contain working credentials.

### 2. No private production data

Do not introduce real customer, employee, incident, ticket, transcript, or corporate data into fixtures, screenshots, logs, README examples, or tests.

All committed PII examples must be clearly synthetic.

### 3. Business logic must not live primarily in notebooks

Notebooks are orchestration and demonstration surfaces. Reusable logic belongs under `src/pii_reduction/`.

### 4. Preserve source data

PII transformation must be non-destructive by default. Original text columns remain unchanged. Reduced variants are created as additional fields unless a configuration explicitly defines a controlled replacement workflow.

### 5. Structure-aware processing

Do not apply a single whole-cell transformation when a parser contract says only part of the text is eligible.

Examples:

- transcript metadata before the speaker delimiter may be out of scope,
- note headers may be preserved,
- timestamps must not be damaged,
- multiple note blocks in one cell must remain ordered.

### 6. Do not equate regex with a complete PII solution

Deterministic pattern recognizers are acceptable for entity types such as email and telephone numbers. Names and addresses require NLP/entity-recognition capability or another justified recognizer.

### 7. Do not silently expand PII scope

Entity policies are configuration-driven. If the current dataset policy includes `PERSON`, `EMAIL`, `PHONE`, and `ADDRESS`, do not start removing employee IDs, ticket numbers, machine names, or dates unless explicitly configured.

### 8. Privacy-safe observability, and everything else that leaves the process

Logs should contain identifiers such as dataset name, row ID, parser type, provider, language, entity counts, timing, and error categories. Logs must not contain full source text or detected raw PII values by default.

**The same rule governs every channel that crosses the process boundary, not just logging.** A rendered page, an HTTP response body, an API error payload, a notebook cell output, a redirect, a downloaded file, a screenshot and a `print` are one disclosure with different transport. A surface may show *metadata about* text — dataset, column, row id, run id, config hash, provider, parser, reducer, language, status, error category, timings, row and field counts, entity counts, and configured names. One addition is **data-derived** rather than configured and is therefore governed rather than assumed: the *name* of a file in a directory a template explicitly offers (ADR-0036, `docs/09`). A filename can itself be personal data, and no code can tell — the operator who opts a directory in owns that. It may not show, stream, redirect to, or vend a URL for the text: not source text, not reduced text, not a detected value, in whole or in fragment.

Two things belong on the unsafe side that look like metadata: **span offsets, span lengths and per-entity confidence** (offsets restore what redaction removed — `docs/09` governs audit metadata at least as strictly as reduced output) and **authentication headers, tokens and workspace URLs**.

Reduced text is included deliberately. Reduction is measured, not guaranteed, so displaying reduced text displays whatever leaked.

This applies to Class B and Class C data (`docs/09`, *Data classifications*). **Class A synthetic or explicitly public-safe text may be shown where a document says so** — the demo surfaces in `docs/11_ROADMAP.md` Phase 9 and `docs/09`'s *Public demo screenshots* depend on that carve-out, as does `CLAUDE.md`'s debugging exception. Per dataset and per document, never per judgement call — and it never creates a service endpoint: an endpoint blessed for a synthetic dataset is still an endpoint.

The inbound direction is governed too: text must never travel in a URL path or query string, an accepted upload is Class B from the moment it exists, and a service must disable request-body logging and debug mode rather than trust their defaults. A framework's own validation error commonly echoes the offending input — install a handler.

A surface that triggers work runs it with its own credentials, so it must resolve sources and destinations from server-side configuration, never from free-form request strings; otherwise it is a confused deputy for whoever calls it.

A side-by-side original/reduced view over Class B data is a governed change: `docs/09_SECURITY_PRIVACY_GOVERNANCE.md`, *Display surfaces, API responses, and request payloads*, states seven conditions, the last of which is that the decision be recorded as an ADR. No such view exists (ADR-0026).

An error crossing a service boundary is a display surface too: report an unexpected exception by category, never by relaying a message raised below the answering layer.

### 9. Reproducibility

Synthetic data generation must use deterministic seeds. Benchmark splits and provider settings must be recorded so results can be reproduced.

### 10. One implementation, two runtimes

Local and Databricks execution should call the same core Python APIs. Avoid parallel implementations that can drift.

## Expected package boundaries

Prefer modules similar to:

```text
src/pii_reduction/
├── config/
├── sources/
├── parsers/
├── language/
├── providers/
├── entities/
├── reducers/
├── processing/
├── outputs/
├── evaluation/
├── observability/
├── databricks/
└── service/
```

Exact names may evolve, but maintain the architectural separation described in `docs/01_ARCHITECTURE.md`.

## Design rules

### Source adapters

A source adapter loads data and metadata. It should not perform PII detection.

### Parsers

A parser converts a source field into one or more processable segments plus immutable reconstruction metadata.

### Language detector

Language detection consumes eligible text, not irrelevant headers whenever possible.

### PII provider

A provider detects candidate entities and returns normalized entity objects. It should not decide how entities are rendered in the final text.

### Reducer

A reducer converts approved entity spans into redacted, masked, or pseudonymized output.

### Reconstructor

Reconstruction combines transformed segments with preserved source structure.

### Evaluator

Evaluation compares predictions with ground truth and produces metrics. It must be separate from production transformation logic.

## Normalized entity result

Providers should converge on a normalized internal result similar to:

```python
EntityMatch(
    entity_type="EMAIL",
    start=42,
    end=64,
    score=0.997,
    provider="presidio",
    recognizer="EmailRecognizer",
    language="en",
)
```

The raw matched text should not be required in ordinary logs or audit tables.

## Coding quality

- Type hints for public APIs.
- Small cohesive functions.
- Dataclasses or typed models for core contracts.
- Explicit exceptions for configuration, parsing, provider, and output failures.
- Avoid hidden global state.
- Initialize expensive NLP models once per process/worker where practical.
- Avoid one-model-load-per-row designs.
- Use dependency injection for providers and language detectors.
- Keep provider-specific dependencies optional where possible.

## Testing expectations

Every substantive feature should include at least one test from the following categories where applicable:

- unit test,
- contract test,
- parser reconstruction test,
- provider integration test,
- synthetic PII regression test,
- Spark parity test,
- idempotency test,
- negative test showing non-PII data remains untouched.

Before claiming a phase complete, execute the relevant test suite and report the results accurately.

## Benchmark integrity

Never tune a provider against the benchmark test split and then report that split as an unbiased evaluation.

Maintain train/development/test or calibration/evaluation separation where model tuning is involved.

When synthetic PII is injected, retain the injection manifest so ground truth is derived deterministically rather than reverse-engineered after generation.

## Databricks rules

- Unity Catalog object names should be configurable.
- Do not hard-code personal workspace paths.
- Do not hard-code warehouse or cluster IDs.
- Keep local mode functional without Databricks credentials.
- Use Delta tables for benchmark outputs where Databricks is available.
- Expensive model inference should be batch-oriented.
- Avoid Python scalar UDFs for heavy NLP when a more efficient batch strategy is available.

## Documentation rules

When architecture changes materially, update the relevant document in `docs/` in the same change.

When adding a provider, document:

- supported languages,
- entity mapping,
- confidence semantics,
- dependencies,
- known limitations,
- expected runtime mode,
- benchmark results when available.

When adding a dataset, document:

- source,
- license,
- whether redistribution is allowed,
- language coverage,
- document type,
- whether it contains real or synthetic data,
- transformation performed before use.

## Completion behavior for coding agents

At the end of a meaningful implementation task, report:

1. files changed,
2. architecture or behavior added,
3. tests executed and exact results,
4. known limitations,
5. any decisions that should be recorded in documentation,
6. the most logical next implementation step.

Do not claim Databricks execution succeeded unless it was actually executed in a Databricks environment.

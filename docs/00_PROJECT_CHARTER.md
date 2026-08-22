# Project Charter

## Project name

**Databricks PII Reduction Accelerator**

## Product statement

A reusable open-source accelerator for reducing personally identifiable information in operational text on Databricks, with first-class support for multilingual content, structured text parsing, configurable PII providers, deterministic evaluation, and privacy-safe observability.

## Problem statement

Operational data platforms commonly contain free-text fields that are difficult to govern with traditional column-level data controls. A ticket table may be structurally well controlled while `description`, `comments`, `work_notes`, `transcript`, or `resolution_notes` contain names, phone numbers, addresses, email addresses, and other sensitive information.

Three problems make this difficult:

1. **PII is embedded in context.** The same string shape can be sensitive in one context and operational metadata in another.
2. **Text is structured even when stored as a string.** Speaker labels, timestamps, note headers, and key/value sections may need to be preserved.
3. **Model quality is uneven.** Entity detection performance varies by language, entity type, domain, and provider.

The accelerator exists to make these tradeoffs explicit and measurable.

## Primary users

### Data engineers

Need a scalable transformation pipeline that can process unstructured text inside governed lakehouse tables.

### Analytics engineers

Need reduced datasets that preserve useful business context and table grain.

### ML / NLP engineers

Need provider interfaces and reproducible benchmarks to compare recognizers.

### Privacy and governance teams

Need evidence of what is detected, what is reduced, how often the pipeline fails, and what data remains at risk.

### Portfolio reviewers / hiring managers

Need a clear demonstration that the repository solves a realistic data-platform problem rather than presenting isolated NLP experimentation.

## Core use cases

### UC-01: Free-text column reduction

Given a Delta table with one or more configured text columns, create reduced columns while preserving the originals.

### UC-02: Transcript-aware reduction

Given a multi-turn transcript, preserve timestamps and speaker metadata while transforming only the actual conversation body.

### UC-03: Note-history reduction

Given a field containing multiple ServiceNow-style note blocks, preserve each note header and transform only the note body.

*Status (session 13): unmet — no `note_history` parser exists (plan §5 defers it;
README's shipped-parser list omits it). It was sequenced after the speaker-prefix
decision because both concern prefix semantics (docs/17 D13); **that decision landed
as ADR-0032**, so the block is gone and the deferral now rests on its own merits
alone. What ADR-0032 does deliver for this case is the author's name: a column of
ServiceNow-style notes parsed as `transcript` with `preserve_prefix: false` puts the
work-note author in scope, at a published cost.*

### UC-04: Multilingual processing

Detect the likely language of eligible text and route it to a compatible recognition strategy.

### UC-05: Provider benchmarking

Run multiple PII providers against the same labeled corpus and compare entity-level quality, leakage, latency, and throughput.

### UC-06: Public-data demonstration

Create a portfolio-safe benchmark using public text plus deterministic synthetic PII injection.

### UC-07: Lakehouse persistence

Persist raw, normalized, reduced, audit, and benchmark outputs to Delta tables with configurable catalog/schema destinations.

## Initial PII scope

The first stable release should focus on four entity families:

- `PERSON`
- `EMAIL`
- `PHONE`
- `ADDRESS`

These cover both deterministic and NLP-heavy cases and are understandable to technical and non-technical reviewers.

> Amended by `docs/adr/0002-address-entity-deferred.md`: `ADDRESS` remains in the
> taxonomy, configuration, and benchmark ground truth from the start, but no
> provider claims to detect it until one measurably can (roadmap Phase 7).

Additional entity types belong in later phases unless required by a selected benchmark dataset.

## Required qualities

### Safety

The project must be safe to publish. Demo data and committed fixtures must not contain real confidential information.

### Reproducibility

A reviewer should be able to recreate demo data and benchmark results from documented commands and fixed seeds.

### Extensibility

Adding a new provider or source type should not require rewriting the central processor.

### Observability

The pipeline should expose what happened without logging the sensitive text it is trying to protect.

### Portability

Core functionality should run locally. Databricks should add scale, governance, orchestration, and visualization rather than becoming a hard dependency for every test.

> **Amended by ADR-0025 (session 10): Azure Databricks is the primary deployment
> target, not an optional surface.** The half of this quality that survives is the
> engineering constraint — the core library runs, tests and benchmarks locally with
> no workspace, no Spark on the runtime path, and no model in the default test
> tier. What no longer holds is the *product* reading: the deployment this project
> is built for is a Databricks one, and Databricks-facing capability outranks new
> providers or parsers until the platform path is usable end to end. Local
> runnability is kept because it is what makes the parity claim checkable, not
> because Databricks is optional.

## Non-functional requirements

### Performance

The architecture must avoid obvious anti-patterns such as loading a large NLP model for every row.

### Determinism

When given the same configuration, provider version, model version, and source data, outputs should be reproducible wherever the underlying provider supports deterministic inference.

### Idempotency

Re-running a deterministic job against the same input should not create duplicate logical results or progressively redact already-reduced text.

### Traceability

Every processed dataset should be associated with a run ID, configuration fingerprint, provider version, and timestamp.

### Failure isolation

One malformed record should not necessarily fail an entire large dataset. Error policy must be configurable and measurable.

## Out of scope for the first release

- claiming legal compliance certification,
- automated legal-basis determination,
- production secrets management beyond documented integration points,
- biometric anonymization,
- image/video redaction,
- OCR-centric document workflows,
- fully reversible token vaulting,
- enterprise master-data resolution,
- automatic deletion/retention policy enforcement,
- fine-tuning large language models from scratch,
- **PHI detection.** Recorded as a horizon for the same platform in ADR-0025 and
  deliberately not a scope item: it would need its own entity taxonomy, provider
  evidence, benchmark corpora and a legal/model-risk review. Nothing in this
  repository detects health identifiers today, and the *Initial PII scope* list
  above — as amended by ADR-0002, which leaves `ADDRESS` in the taxonomy and
  detected by nothing — is the whole claim.

## Design decisions to preserve

### Original data remains available

Reduced outputs should not silently overwrite the source text. A typical output schema will retain:

```text
description
description_pii_redacted
```

### Parsing happens before PII inference

When a document contains operational metadata that is explicitly out of scope, parsing must isolate the eligible region before sending text to the recognizer.

### Language is part of the processing contract

Language detection is not a UI feature. It affects provider selection, confidence interpretation, and benchmark segmentation.

### Evaluation is a product feature

Benchmark code is not an optional notebook. Quality metrics are part of the accelerator's core value proposition.

## Definition of done for a credible portfolio release

A release is portfolio-ready when a new reviewer can:

1. understand the problem in under five minutes from the README,
2. generate the demo data without private credentials,
3. run at least one provider locally,
4. see redaction working on plain text and structured transcripts,
5. inspect benchmark results by entity type and language,
6. see how the same pipeline maps to Databricks tables,
7. understand known failure modes,
8. verify tests and deterministic demo outputs,
9. see no proprietary information or secrets in the repository.

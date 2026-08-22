# Portfolio Story and Positioning

> **Written in session 2 as a plan; the README now exists and largely follows it.**
> Where the two differ, the README is what shipped and this document is the intent.
> Two things this plan asked for that were done differently, both deliberately:
>
> - **The architecture diagram** is a mermaid block in the README rather than an image
>   file, so it stays in the same diff as the text it describes and needs no asset
>   pipeline.
> - **The "before/after example"** leads with a *failure* as well as a success — the
>   Greek sentence where "please" was taken for a name and the real name survived. A
>   portfolio that only shows its wins is a portfolio a reviewer discounts; this
>   project's strongest claim is that it publishes what it gets wrong, and the README
>   opens with the evidence for that.
>
> `docs/22_EVIDENCE.md` is the executed record this document's *Proof* section calls for.

## Recommended positioning

Do not present the repository as:

> A Python script that uses Presidio to remove PII.

That undersells the engineering problem.

Present it as:

> **An open-source Databricks accelerator for multilingual PII reduction across operational text, with structure-aware parsing, provider benchmarking, reproducible public data, and lakehouse-native governance.**

## Why this framing is stronger

It demonstrates several disciplines at once:

- data engineering,
- NLP/ML integration,
- lakehouse architecture,
- configuration-driven software design,
- privacy engineering,
- benchmarking,
- Databricks platform knowledge,
- production-minded testing.

## Core narrative

### Problem

Structured tables often contain unstructured text. Column-level governance cannot automatically prevent a transcript or work-note field from containing names, phone numbers, emails, or addresses.

### Complication

PII reduction is harder than replacing email addresses:

- transcripts contain metadata that must remain,
- tickets contain IDs that look sensitive but are operationally important,
- languages vary,
- providers disagree,
- false negatives create privacy risk,
- false positives destroy analytical value.

### Solution

The accelerator separates:

```text
source -> parser -> language -> detector -> reducer -> validator -> output
```

and makes each layer configurable.

### Proof

Public-safe datasets receive deterministic synthetic PII injection, giving exact ground truth for precision, recall, F1, leakage, and over-redaction.

### Platform

Databricks provides:

- Delta persistence,
- Spark execution,
- Unity Catalog-compatible organization,
- governed audit/benchmark tables,
- scheduled workloads,
- optional dashboard/app presentation.

## README opening concept

A mature README might open with:

> Operational text is one of the hardest parts of a governed data platform. A ticket table may have clean schemas and controlled access while `description`, `work_notes`, and `transcript` fields still contain names, contact details, and addresses. This accelerator provides a reproducible way to detect, reduce, benchmark, and monitor that PII on Databricks without destroying the surrounding business context.

## Differentiators

### 1. Structure-aware

The system knows that a timestamp/speaker prefix and a conversation body are different processing regions.

### 2. Measured

Providers are compared against known truth rather than shown through cherry-picked examples.

### 3. Multilingual

Language affects routing and benchmark slices.

### 4. Provider-agnostic

Presidio is a baseline, not the architecture.

### 5. Lakehouse-native

The project is designed around governed tables and scalable processing, not only local text files.

### 6. Publicly reproducible

No employer/customer data is needed to reproduce the project.

## Portfolio metrics worth publishing

Use only metrics produced by actual runs.

Examples:

```text
X documents processed
Y languages evaluated
Z synthetic PII entities
PERSON F1: ...
EMAIL F1: ...
PHONE F1: ...
ADDRESS F1: ...
Leakage rate: ...
Rows/sec on Databricks: ...
Parser preservation: ...
```

Avoid fabricated performance claims in screenshots or README placeholders.

## Architecture diagram

The most useful public diagram is simple:

```text
Public/Synthetic Data
        ↓
Source Adapters
        ↓
Structure-Aware Parsers
        ↓
Language Routing
        ↓
PII Provider Layer
        ↓
Redaction / Pseudonymization
        ↓
Delta Outputs
        ↓
Evaluation + AI/BI
```

Do not make the first architecture diagram so detailed that the story disappears.

## GitHub repository presentation

Recommended top-level README flow:

1. one-paragraph problem statement,
2. architecture image,
3. before/after example,
4. benchmark summary,
5. feature list,
6. quickstart,
7. Databricks architecture,
8. supported providers/languages,
9. evaluation methodology,
10. project structure,
11. roadmap,
12. security/compliance disclaimer.

## Suggested repository topics

Examples:

```text
databricks
pii
privacy
presidio
nlp
named-entity-recognition
pseudonymization
data-engineering
delta-lake
unity-catalog
spark
multilingual-nlp
```

## Recruiter/hiring-manager interpretation

The repository should make it easy to infer:

- this person can turn ambiguous business requirements into data contracts,
- they understand local-vs-distributed implementation tradeoffs,
- they know when deterministic logic is better than AI,
- they understand model evaluation,
- they think about privacy beyond the happy path,
- they can package work as reusable infrastructure.

## Technical reviewer interpretation

A technical reviewer should see:

- clean interfaces,
- typed contracts,
- tests,
- benchmark methodology,
- safe handling of offsets and structure,
- model/runtime considerations,
- no notebook-only architecture.

## What not to claim

Avoid statements such as:

- "GDPR compliant PII removal" without legal validation,
- "100% anonymization",
- "supports 100 languages" solely because an underlying model lists them,
- "production ready" before distributed/runtime testing,
- "zero leakage" unless benchmark definition and support are shown.

## Suggested release story

### v0.1

"Reproducible multilingual PII reduction baseline"

- public demo generator,
- three parsers,
- deterministic + Presidio,
- local benchmark,
- Databricks Delta demo.

### v0.2

"Provider benchmark and multilingual expansion"

- multilingual NER,
- provider comparison,
- improved language coverage,
- benchmark report.

### v0.3

"Lakehouse operationalization"

- incremental processing,
- audit tables,
- AI/BI dashboard,
- job resources.

## Walkthrough message

A concise explanation for a video or interview:

> I built the project around the idea that PII reduction is a data-platform problem, not just a regex problem. The source layer can read files or governed tables, parsers isolate the part of each field that is actually eligible for reduction, language routing selects the appropriate recognizer, and providers normalize into the same entity contract. I then benchmark the predictions against synthetically injected ground truth and persist both reduced outputs and privacy-safe metrics in Delta. The result is reproducible with public data and extensible to real operational workloads.

# Architecture

## Architectural objective

The accelerator should separate *where text comes from*, *which part of the text is eligible*, *how PII is detected*, *how PII is transformed*, and *where results are written*.

This separation is the central design constraint. It allows the same pipeline to process a local Excel workbook during development and a large Unity Catalog Delta table in production without rewriting the PII logic.

## High-level components

```text
┌──────────────────────┐
│     Source Layer     │
│ Excel / CSV / Delta  │
└──────────┬───────────┘
           │ records
           v
┌──────────────────────┐
│   Dataset Contract   │
│ columns + policies   │
└──────────┬───────────┘
           │ configured fields
           v
┌──────────────────────┐
│ Parser / Segmenter   │
│ plain / transcript   │
│ notes / key-value    │
└──────────┬───────────┘
           │ processable segments
           v
┌──────────────────────┐
│ Language Resolution  │
└──────────┬───────────┘
           │ language + confidence
           v
┌──────────────────────┐
│    PII Providers     │
│ deterministic / NER  │
│ Presidio / hybrid    │
└──────────┬───────────┘
           │ candidate spans
           v
┌──────────────────────┐
│ Entity Reconciliation│
└──────────┬───────────┘
           │ approved spans
           v
┌──────────────────────┐
│ Reduction Strategy   │
│ redact / mask /      │
│ pseudonymize         │
└──────────┬───────────┘
           │ transformed segments
           v
┌──────────────────────┐
│    Reconstruction    │
└──────────┬───────────┘
           │ full field
           v
┌──────────────────────┐
│ Validation + Audit   │
└──────────┬───────────┘
           │ rows + metrics
           v
┌──────────────────────┐
│    Output Layer      │
│ file / pandas /      │
│ Spark / Delta        │
└──────────────────────┘
```

## Layer 1: source adapters

A source adapter owns source-specific concerns only.

### Responsibilities

- authenticate when necessary,
- load source metadata,
- enumerate datasets/sheets/tables where supported,
- load rows or partitions,
- preserve source column types where practical,
- attach source lineage metadata,
- expose a consistent dataset object to the processor.

### Non-responsibilities

A source adapter must not:

- recognize PII,
- decide which columns are sensitive,
- mutate text,
- select language models,
- implement redaction.

### Suggested adapters

```text
sources/
├── base.py
├── pandas_source.py
├── excel_source.py
├── csv_source.py
├── parquet_source.py
├── spark_source.py
└── databricks_table_source.py
```

## Layer 2: dataset contract

Each dataset should be described by configuration rather than hard-coded branches.

A dataset contract defines:

- source identifier,
- logical dataset name,
- row identity strategy,
- target text columns,
- parser for each column,
- PII entity policy,
- language policy,
- output naming,
- failure behavior,
- optional benchmark metadata.

Example concept:

```yaml
dataset: support_chat
row_id: conversation_id
columns:
  transcript:
    parser: transcript
    entities: [PERSON, EMAIL, PHONE, ADDRESS]
    output: transcript_pii_redacted
```

## Layer 3: parsers and segmenters

A parser transforms one source field into ordered segments.

Each segment should include at least:

- text,
- whether it is eligible for PII processing,
- original start/end location or reconstruction position,
- segment type,
- immutable metadata needed for reconstruction.

### Plain-text parser

One field becomes one processable segment — or one segment per line, with each line
break preserved as its own non-processable segment, when `split_lines` is set
(ADR-0016). The option exists because an NER model handed a multi-line key/value block
as a single segment runs entity boundaries across the line break; it is off by default
because splitting is wrong for prose that wraps mid-sentence.

### Transcript parser

A transcript may contain lines such as:

```text
2026-04-03 09:15:04 - Agent Smith: Hello Maria, how can I help?
2026-04-03 09:15:13 - Guest: My email is maria@example.test.
```

A policy may define speaker/timestamp prefixes as immutable metadata. The parser should therefore separate each line into:

```text
prefix = "2026-04-03 09:15:04 - Agent Smith:"
body   = " Hello Maria, how can I help?"
```

Only `body` is eligible.

The parser must preserve:

- order,
- exact line breaks,
- delimiter choice,
- prefixes,
- empty lines.

### Note-history parser

A single cell may contain multiple notes, for example:

```text
2026/01/07 04:00:12 PM - Agent A (Additional comments)
User asked to be called at +30 210 000 0000.

2026/01/07 12:05:30 PM - Agent A (Additional comments)
Issue resolved.
```

The header is a preserved segment; the note body is processable.

### Key/value parser

Useful for case summaries:

```text
User details:
Mobile number: +00 123...
Department: Support
Machine name: DEMO-PC-01
```

The parser can preserve labels and only process values, or process the full text depending on configuration.

## Layer 4: language resolution

Language resolution returns a normalized object rather than only a language code.

Suggested contract:

```python
LanguageResult(
    language="en",
    confidence=0.98,
    detector="fasttext",
    supported=True,
    reason=None,
)
```

Language resolution may operate on:

- a complete plain-text field,
- a note body,
- a transcript turn,
- an aggregate of several short segments.

Short-text handling is important. A three-word segment should not automatically trigger a strong language claim.

## Layer 5: PII provider interface

Provider implementations normalize their results into common spans.

Suggested interface:

```python
class PIIProvider(Protocol):
    def detect(
        self,
        text: str,
        *,
        language: str | None,
        entities: set[str],
    ) -> list[EntityMatch]: ...
```

Providers may be single-model systems or composites.

## Layer 6: entity reconciliation

When multiple recognizers are used, overlaps must be resolved before mutation.

Examples:

```text
"Maria Rossi"
provider A -> PERSON [0, 5]
provider B -> PERSON [0, 11]
```

or:

```text
"john@example.com"
provider A -> EMAIL [0, 16]
provider B -> PERSON [0, 4]
```

The reconciler needs deterministic policies such as:

1. entity-type priority,
2. higher confidence,
3. longer span,
4. provider priority,
5. exact recognizer override.

The selected policy must be documented and benchmarkable.

## Layer 7: reduction strategies

Detection and transformation are separate concerns.

### Redaction

```text
Maria Rossi -> <PERSON>
```

### Masking

```text
maria.rossi@example.com -> ma***@example.com
```

### Deterministic pseudonymization

```text
Maria Rossi -> PERSON_004812
```

The same input should map consistently within a configured scope when deterministic pseudonymization is enabled.

### Reversible pseudonymization

This is a later-stage feature. It requires secure key management and a protected mapping store and therefore should not be the default portfolio path.

## Layer 8: reconstruction

The reconstructor guarantees that non-processable structure remains unchanged.

A useful invariant is:

> If a parser marks a character region as immutable, reconstruction must preserve that region byte-for-byte where encoding permits.

This invariant should be tested.

## Layer 9: validation and audit

Validation occurs at multiple levels.

### Row-level

- source field present,
- output field present,
- parser succeeded or fallback recorded,
- reduction succeeded or failure recorded.

### Dataset-level

- row count preserved unless configured otherwise,
- original columns unchanged,
- configured output columns created,
- no duplicate row identities introduced.

### PII-level

- entity counts,
- leakage checks on known synthetic ground truth,
- over-redaction checks,
- unsupported-language counts.

## Layer 10: output adapters

Output responsibilities:

- preserve row grain,
- append reduced columns,
- persist optional structured audit events,
- support local and Spark/Delta modes.

Recommended outputs:

```text
raw dataset              optional / source-owned
normalized dataset       optional
reduced dataset          primary business output
pii_detection_audit      privacy-safe span metadata
pipeline_run_metrics     run-level metrics
benchmark_results        evaluation outputs
```

## Package dependency direction

Dependencies should flow inward toward shared contracts.

Bad:

```text
parsers -> databricks -> providers -> parsers
```

Preferred:

```text
contracts
  ^
  ├── sources
  ├── parsers
  ├── language
  ├── providers
  ├── reducers
  ├── outputs
  └── evaluation

processing/orchestrator depends on those interfaces.
```

`synthetic/` sits **beside** `processing/`, not under it: it is a build-time package
that generates the corpora and demo packs everything else is measured on. It may depend
on the interface layers (it uses `parsers/` so that injection respects the same
segmentation the pipeline will apply, and `entities/` for the taxonomy), and **nothing
on the runtime path may depend on it** — only entry points (`cli.py`, `benchmark.py`)
import it. It is also the one package that opens a network socket, in
`synthetic/fetch.py`, which retrieves public datasets at build time (ADR-0017). That is
deliberately not a source adapter: `sources/` is on the runtime path and returns
`SourceDataset`, while `fetch()` returns a file path and is never reachable from
`pipeline.process`.

## Local and Databricks parity

The local runner and Databricks runner should both construct the same processing pipeline.

Example:

```python
pipeline = build_pipeline(config)
result = pipeline.process(dataset)
```

The difference is the source/output adapter and execution strategy, not the entity logic.

## Scalability considerations

### Avoid row-by-row model loading

Model initialization must occur once per process or worker.

### Batch inference

Providers that support batching should expose a batch API.

### Spark execution

Potential strategies include:

- partition-level Python processing,
- pandas UDFs with worker-level model initialization,
- model serving endpoints for centrally hosted models,
- Spark-native functions where suitable,
- materialized intermediate Delta tables for restartability.

The repository should benchmark rather than assume one strategy is universally best.

## Failure strategy

Every dataset should configure one of:

- `fail_fast`
- `quarantine_row`
- `preserve_original_and_record_error`

For portfolio demos, `preserve_original_and_record_error` is often the safest default.

## Idempotency strategy

A processing run should carry:

- `run_id`
- source version/fingerprint
- configuration fingerprint
- provider/model version
- pipeline version

Output writes should be deterministic and merge/overwrite behavior should be explicit.

## Future extension points

The architecture should be able to accommodate:

- LLM-based entity detection,
- streaming sources,
- OCR-derived text,
- policy-specific entity scopes,
- reversible tokenization,
- human review queues,
- Databricks Apps review interface,
- AI/BI benchmark dashboards,
- Unity Catalog lineage and tags,
- provider cost accounting.

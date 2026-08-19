# Data Contracts

## Purpose

This document defines the canonical internal representations used by the accelerator. Source adapters and provider implementations may vary, but they should converge on stable contracts so components can be tested independently.

## 1. Dataset identity

Every dataset should have a logical name independent of its physical location.

Example:

```yaml
dataset_name: demo_support_chat
source_type: delta
source_reference: main.demo.support_chat
```

The logical name is used in metrics, configuration, and benchmark reporting.

## 2. Row identity

Every input row should have a stable identity.

Preferred order:

1. configured business key,
2. existing unique row identifier,
3. deterministic hash of selected stable source fields,
4. generated ordinal only for disposable demo data.

The row ID is not assumed to be PII.

Example internal metadata:

```python
RecordContext(
    dataset="demo_support_chat",
    row_id="conversation_000142",
    source_version="v1",
)
```

## 3. Text field policy

Each target column receives a policy.

Suggested model:

```python
TextFieldPolicy(
    column="transcript",
    parser="transcript",
    output_column="transcript_pii_redacted",
    entities={"PERSON", "EMAIL", "PHONE", "ADDRESS"},
    language_policy="detect",
    reducer="redact",
)
```

## 4. Segment contract

A parser should return ordered segments.

Suggested fields:

```text
segment_id
ordinal
text
processable
segment_type
source_start
source_end
metadata
```

Example:

```python
TextSegment(
    segment_id="turn_0003_body",
    ordinal=5,
    text=" My email is maria@example.com",
    processable=True,
    segment_type="transcript_body",
    metadata={"line_no": 3},
)
```

Immutable prefixes may be represented as non-processable segments.

## 5. Language contract

```text
language
confidence
detector
supported
fallback_used
reason
```

Example:

```python
LanguageResult(
    language="el",
    confidence=0.93,
    detector="fasttext",
    supported=True,
    fallback_used=False,
)
```

Unknown language should be represented explicitly rather than as a fake default.

## 6. Entity match contract

Canonical fields:

```text
entity_type
start
end
score
provider
recognizer
language
metadata
```

Required invariants:

```text
0 <= start < end <= len(text)
entity_type is normalized
score is null or numeric in the provider-defined range
```

Provider-native labels should be mapped to normalized taxonomy.

Example mappings:

```text
PER -> PERSON
PERSON_NAME -> PERSON
EMAIL_ADDRESS -> EMAIL
PHONE_NUMBER -> PHONE
STREET_ADDRESS -> ADDRESS
```

## 7. Reconciled entity contract

After overlap resolution, the result should include provenance.

```python
ResolvedEntity(
    entity_type="EMAIL",
    start=15,
    end=37,
    score=0.999,
    selected_provider="deterministic",
    supporting_matches=[...],
    resolution_rule="entity_priority_then_score",
)
```

## 8. Reduction operation contract

For each replaced span, record:

```text
entity_type
start
end
replacement
strategy
```

In privacy-safe audit mode, avoid recording the original matched value.

Example:

```python
ReductionOperation(
    entity_type="PHONE",
    start=40,
    end=57,
    replacement="<PHONE>",
    strategy="redact",
)
```

## 9. Processed field result

Suggested contract:

```python
ProcessedFieldResult(
    original_column="transcript",
    output_column="transcript_pii_redacted",
    output_text="...",
    language_summary={...},
    entity_counts={"EMAIL": 1, "PERSON": 2},
    parser="transcript",
    provider_chain=["deterministic", "presidio"],
    status="success",
    error=None,
)
```

The original text need not be duplicated inside the result object if it remains available on the source row.

## 10. Row processing result

A row result should make partial failures visible.

Example status values:

- `success`
- `success_with_fallback`
- `partial_failure`
- `failed`
- `skipped`

Fields:

```text
dataset
row_id
run_id
field_results
processing_ms
status
error_category
```

## 11. Run metadata

Every execution should produce a run record.

Recommended fields:

```text
run_id
pipeline_version
config_hash
source_dataset
source_version
started_at
completed_at
status
provider_versions
language_detector_version
pseudonymization_key_id
rows_read
rows_written
fields_processed
fields_failed
entities_detected
entities_reduced
```

`provider_versions` values carry the provider type plus the installed versions of
the libraries and models behind it (resolved via `importlib.metadata`, so nothing
is imported and no model is loaded), e.g.
`presidio (presidio-analyzer 2.2.364, spacy 3.8.15, en_core_web_md 3.8.0)`; on a
machine without the extra the value degrades to the bare type string.
`pseudonymization_key_id` is a non-secret truncated digest identifying the key a
pseudonymizing run used — never the key itself — so a rotation is visible in
provenance; it is null for runs without a pseudonymizing reducer, and comma-joined
when columns are configured with different keys.

## 12. Detection audit table

A privacy-safe Databricks audit table may use:

```text
run_id
row_id
column_name
segment_id
entity_type
start
end
score
provider
recognizer
language
resolution_rule
```

Do not store matched raw text by default.

If exact text is needed for controlled debugging, use an explicitly enabled secure debug mode with separate storage and retention policy.

## 13. Benchmark truth schema

```text
benchmark_id
document_id
segment_id
entity_id
entity_type
start
end
language
difficulty_tier
injection_rule
synthetic_value_id
```

## 14. Benchmark prediction schema

```text
benchmark_run_id
document_id
segment_id
entity_type
start
end
score
provider
language
latency_ms
```

## 15. Benchmark metric schema

Suggested grain:

```text
benchmark_run_id
provider
language
entity_type
document_type
difficulty_tier
strategy
metric_name
metric_value
support
```

`strategy` is in the grain because leakage is defined per reduction strategy
(ADR-0013 §5): a persisted mask row must never be indistinguishable from a redact
row, or the forbidden cross-strategy comparison happens the moment rows leave the
process.

Example metric rows:

```text
presidio | en | PERSON | transcript | 2 | precision | 0.92 | 1482
presidio | en | PERSON | transcript | 2 | recall    | 0.86 | 1482
presidio | en | PERSON | transcript | 2 | f1        | 0.89 | 1482
```

## 16. Business output schema

Default behavior should append transformed columns.

Input:

```text
conversation_id
transcript
language_source
channel
```

Output:

```text
conversation_id
transcript
transcript_pii_redacted
language_source
channel
pii_run_id
pii_status
```

Optional technical metadata can be excluded from business-facing views.

With `destination.projection: reduced_only` (ADR-0024, opt-in) the written
artifact omits the configured source columns (`transcript` above); in-memory
processing and the default artifact keep the full shape.

## 17. Parser reconstruction invariant

For every parser, define a round-trip invariant:

```python
reconstruct(parse(text), transformed_segments=None) == text
```

Before PII transformation, parsing and immediate reconstruction must reproduce the source string exactly.

This is a core test contract.

## 18. Output invariants

Unless configuration explicitly changes the grain:

- input row count equals output row count,
- business key values remain unchanged,
- original target fields remain unchanged (present in the written artifact only
  under the default `projection: full`, ADR-0024),
- reduced fields exist,
- null input produces null output,
- empty string handling is deterministic,
- repeated deterministic runs produce equivalent reduced text.

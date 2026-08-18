# Testing and Quality Assurance

## Objective

The test strategy should prove that the accelerator transforms PII correctly without corrupting document structure or silently changing business data.

## Test pyramid

```text
              end-to-end demo tests
          integration / Spark parity
       provider and parser contract tests
            focused unit tests
```

Most tests should be fast and local.

## 1. Unit tests

Cover pure functions such as:

- identifier normalization,
- entity label mapping,
- overlap resolution,
- replacement ordering,
- configuration merging,
- hashing/fingerprinting,
- synthetic injection offsets,
- metrics calculations.

## 2. Parser tests

Parsers deserve unusually strong coverage because structural damage can be subtle.

### Round-trip test

For every parser:

```python
segments = parser.parse(source)
assert parser.reconstruct(segments) == source
```

before any transformation.

### Transcript cases

Test:

- timestamp + agent + colon,
- speaker only + colon,
- multiple colons inside body,
- URLs in body,
- time values in body,
- empty speaker turn,
- malformed line,
- multiline customer message,
- mixed newline conventions,
- Unicode names in metadata,
- no delimiter.

Important: the parser should split on the correct structural delimiter, not every colon.

### Note-history cases

Test:

- one entry,
- multiple entries,
- blank lines,
- missing blank line,
- unknown note type,
- malformed header,
- body containing timestamp-like text,
- header containing a person name that must remain untouched if metadata is out of scope.

## 3. Language tests

Test:

- sufficiently long English,
- German,
- Greek,
- another supported language,
- very short text,
- numeric-only text,
- email-only text,
- mixed-language text,
- unsupported language.

Tests should focus on routing behavior unless language detection accuracy itself is under benchmark.

## 4. Provider contract tests

Every provider must:

- return normalized entity labels,
- return valid offsets,
- return spans that do not cross a line break, for entity types whose surface cannot
  contain one (`EntityDefinition.surface_may_span_lines`; ADR-0016),
- respect requested entity scope,
- handle empty text,
- handle null through caller contract,
- expose provider identity,
- not mutate source text.

## 5. Reducer tests

Test:

```text
single entity
multiple entities
adjacent entities
overlapping candidates after reconciliation
Unicode text
repeated entity
replacement at start of string
replacement at end of string
```

## 6. Negative tests

Protect non-PII data.

Fixtures should include:

```text
INC00128492
KB000002715
DEMO-PC-6915
v4.12.3
2026-04-03 09:15:04
Department: Support
```

Unless configured as a PII entity, these must remain.

## 7. Synthetic regression corpus

Maintain a committed small corpus with deterministic ground truth.

Example size:

- 50-200 documents,
- several languages,
- all entity types,
- all parser types,
- difficulty tiers.

This corpus powers CI benchmark gates without downloading large datasets.

## 8. Evaluation tests

Metrics functions should be tested against hand-verifiable cases.

Example:

Ground truth:

```text
PERSON [0,10]
EMAIL [20,40]
```

Prediction:

```text
PERSON [0,10]
PHONE [20,40]
```

Expected:

- PERSON TP = 1,
- EMAIL FN = 1,
- PHONE FP = 1.

## 9. Privacy tests

Capture logs and confirm raw synthetic values are absent.

Examples:

```python
assert "maria.rossi@example.com" not in captured_logs
assert "+302100000000" not in captured_logs
```

Test exception messages similarly.

## 10. Idempotency tests

A deterministic pipeline run on unchanged source/config should produce equivalent outputs.

Avoid running the redactor against its own reduced output unless explicitly testing that behavior.

## 11. Pandas/Spark parity

For a shared fixture, local pandas mode and Spark mode should produce equivalent reduced text for the same parser/provider configuration, allowing for explicitly documented differences.

## 12. Integration tests

Integration tests can initialize real providers such as Presidio or a small NER model.

Mark them separately because they may require:

- model downloads,
- more memory,
- longer execution.

Example markers:

```text
unit
integration
slow
databricks
```

## 13. Databricks tests

Tests requiring a workspace should verify:

- read configured table,
- write reduced Delta table,
- preserve row count,
- create run metrics,
- handle a small distributed batch,
- write benchmark outputs.

They should not be required for ordinary local CI.

## 14. Data-quality checks

Per dataset run:

- source row count,
- output row count,
- target columns found,
- null rate before/after,
- average text length,
- parser fallback count,
- language unknown rate,
- PII entity distribution,
- failure rate.

Unexpected shifts should be visible.

## 15. Performance regression

A small performance fixture can track major regressions.

Example:

```text
1,000 short texts
100 medium transcripts
20 long note histories
```

Do not use strict wall-clock CI gates across heterogeneous machines, but record relative benchmark history where useful.

## 16. Test naming

Prefer behavior-oriented names:

```text
test_transcript_parser_preserves_prefix_with_multiple_body_colons
test_note_parser_roundtrip_multiple_entries
test_reconciler_prefers_email_over_nested_person
test_redactor_applies_replacements_from_right_to_left
test_unknown_language_uses_safe_fallback_chain
```

## 17. Definition of quality-ready

A feature is not complete merely because it runs once.

Minimum expectation:

- appropriate tests added,
- no private data added,
- docs updated,
- existing tests pass,
- known limitation documented.

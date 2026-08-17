# Evaluation and Benchmarking

## Objective

The accelerator should make PII reduction measurable. A demo that only shows transformed text cannot establish whether sensitive entities were missed or harmless content was over-redacted.

The evaluation framework should answer:

1. What did the provider detect?
2. What should it have detected?
3. What did the reduction step actually remove?
4. What harmless content did it remove incorrectly?
5. How does quality vary by entity, language, and document structure?
6. What throughput and latency are required to achieve that quality?

## Evaluation levels

### Detection quality

Compares predicted entity spans against ground truth.

### Reduction quality

Checks whether ground-truth PII still exists in the reduced output.

### Preservation quality

Checks whether non-PII structure and operational identifiers remain intact.

### Runtime quality

Measures latency, throughput, failures, and resource behavior.

## Entity-level matching

Strict span match:

A prediction is correct only when:

```text
predicted entity type == true entity type
predicted start == true start
predicted end == true end
```

This is easy to interpret but harsh when boundaries differ slightly.

## Relaxed matching

Optional overlap-based metrics can complement strict metrics.

Examples:

- intersection-over-union threshold,
- any-overlap with correct entity type,
- containment.

Strict metrics should remain the primary benchmark because reduction requires accurate spans.

## Core metrics

### Precision

```text
TP / (TP + FP)
```

High precision means fewer harmless spans are removed.

### Recall

```text
TP / (TP + FN)
```

High recall means fewer PII entities are missed.

### F1

```text
2 * precision * recall / (precision + recall)
```

### Leakage rate

A reduction-centric metric:

```text
number of ground-truth PII entities still recoverable after reduction
/
total ground-truth PII entities
```

A system can have imperfect span F1 but still achieve low leakage if replacement covers the sensitive content. Conversely, boundary errors may leave partial leakage.

### Over-redaction rate

Measure how often protected negative examples or known non-PII tokens are modified.

### Document clean rate

Percentage of documents where all ground-truth PII is successfully removed.

This is operationally intuitive:

```text
clean documents / documents containing PII
```

## Metrics by slice

Always calculate quality by:

- entity type,
- language,
- document type,
- difficulty tier.

Optional slices:

- text length,
- channel,
- number of entities per field,
- noisy formatting,
- code-switching,
- provider route,
- language confidence band.

## Benchmark table

Recommended summary:

| Provider | Language | Entity | Precision | Recall | F1 | Leakage | Support |
|---|---|---|---:|---:|---:|---:|---:|
| ... | ... | ... | ... | ... | ... | ... | ... |

Support count is mandatory.

## Provider comparison

The repository should support running the same benchmark through several chains:

```text
deterministic_only
presidio_baseline
multilingual_ner
hybrid
```

This makes architectural tradeoffs visible.

## Benchmark run metadata

Each benchmark run should capture:

```text
benchmark_run_id
source_dataset_version
truth_version
pipeline_version
config_hash
provider_versions
model_versions
language_detector_version
execution_environment
started_at
completed_at
```

## Threshold calibration

Provider thresholds should be calibrated on a development/calibration split.

Example process:

```text
for threshold in candidate_thresholds:
    run on calibration split
    compute entity metrics
choose threshold based on objective
lock threshold
run final test split once
```

Possible objectives:

- maximize F1,
- minimum recall constraint,
- minimum precision constraint,
- minimize weighted privacy risk.

For PII reduction, recall may be weighted more strongly than in ordinary NER, but that increases over-redaction risk. The chosen policy should be explicit.

## Weighted risk metric

Optional metric:

```text
risk_score = FN_cost * false_negatives + FP_cost * false_positives
```

Entity types can have different weights.

Example:

```text
EMAIL false negative cost > PERSON false negative cost
```

This is domain-specific and should not replace standard precision/recall metrics.

## Reconstruction validation

For structured parsers, benchmark not only entity quality but structural fidelity.

Metrics/checks:

- timestamp preservation rate,
- speaker-prefix preservation rate,
- note-header preservation rate,
- line-count delta,
- parse fallback rate.

A perfect PII detector with broken transcript reconstruction is still an unacceptable pipeline.

## Negative-set evaluation

Create documents intentionally containing no configured PII.

Measure:

- percentage changed,
- number of false detected spans,
- commonly over-redacted token classes.

Important negative examples:

- ticket IDs,
- KB IDs,
- machine names,
- order numbers,
- software versions,
- dates and times,
- department names.

## Performance evaluation

Capture:

```text
cold start seconds
warm start seconds
rows per second
characters per second
segments per second
p50 latency
p95 latency
provider failures
memory footprint if practical
```

For distributed execution, also record worker/partition configuration.

## Cost evaluation

For providers with direct inference cost, record:

```text
cost per 1,000 fields
cost per million characters
cost per benchmark run
```

For local/open models, infrastructure cost may be represented as runtime/resource usage rather than API price.

## Regression gates

The test/CI pipeline should support benchmark gates on a small deterministic corpus.

Example:

```text
EMAIL recall >= 0.98
PHONE recall >= 0.97
PERSON F1 >= 0.85
ADDRESS F1 >= 0.75
transcript prefix preservation == 1.00
parser failure rate <= 0.01
```

These values are examples only. Real gates must come from observed baselines.

### As implemented

Gates live in `configs/benchmark_gates.yaml` and are checked by
`pii_reduction.evaluation.gates`:

```bash
pii-reduction benchmark --gates configs/benchmark_gates.yaml
```

The command exits 0 when every gate passes, 1 when one fails, and 2 when the gate
file itself cannot be read — a regression and a typo are different events and must not
look the same in a CI log.

Design points that are not obvious from the file:

- **One gate names exactly one row.** Selectors (`entity_type`, `language`,
  `document_type`, `difficulty_tier`) default to `"*"`, which selects the *aggregate*
  row the report emits for that dimension — not a wildcard.
- **Three things fail rather than pass:** a gate whose selector matches no row (the
  metric was renamed, the slice vanished, the chain never ran), a gate that matches
  several rows (ambiguous about which number it checked), and a slice whose support
  fell below what the gate was measured over. A gate that measures nothing is worse
  than no gate.
- **The gate set is selected by the provider chain that ran**, so a hybrid-chain
  result can never be scored against deterministic-only floors.
- **Values are stored at three decimals** — the precision the benchmark table and this
  documentation print — and compared with a tolerance of half that last digit, which
  is far below one missed entity in the smallest gated slice.
- **`measured:` records the provenance** of every value: corpus, seed,
  documents-per-language, splits, strategy, date, commit, and model versions.

These are **whole-corpus regression floors**, not an evaluation protocol. They exist so
a change that quietly makes detection worse fails a build. The split discipline of
ADR-0011 — calibrate on the calibration split, report test once — is a separate
concern owned by Increment E, and `--gates` refuses to run with `--split` so the two
cannot be confused. A remedy developed by repeatedly reading a gate value is tuning
against whatever split that gate covers; develop against dev/calibration and read the
test number once.

One example gate above has no implementation yet: `transcript prefix preservation`
has no metric in the report grain. The invariant is covered by parser and pipeline
round-trip tests, and `over_redaction_rate` (pinned at `max: 0.000`) is the closest
metric-level guard. It is the obvious next gate once a metric backs it.

## Benchmark artifact outputs

Generate machine-readable:

- predictions Parquet/Delta,
- metrics Parquet/Delta/JSON,
- run metadata JSON,
- errors/quarantine output.

Optional presentation artifacts:

- Markdown benchmark summary,
- CSV summary,
- Databricks AI/BI dashboard,
- local charts.

## Reproducibility

To reproduce a result, a reviewer should know:

- code commit,
- config hash,
- dataset/truth version,
- model/provider version,
- synthetic seed,
- environment dependencies.

## Benchmark honesty

The repository should clearly distinguish:

- synthetic benchmark performance,
- public annotated benchmark performance,
- production-like data observations.

Do not market synthetic F1 as proof of regulatory-grade anonymization.

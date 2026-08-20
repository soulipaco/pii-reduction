# Databricks Runtime and Lakehouse Design

## Objective

Databricks is the target execution and governance surface for larger workloads, while the core project remains runnable locally. The Databricks implementation should feel native to the lakehouse without creating a separate codebase.

> **ADR-0025 (session 10) sharpens "for larger workloads": Azure Databricks is the
> primary deployment target**, and this document describes the deployment surface
> rather than an optional one. Local runnability is unchanged and stays a hard
> constraint — it is what makes the parity claim checkable.

## Runtime modes

### Local mode

Purpose:

- unit tests,
- parser development,
- small public datasets,
- provider experimentation,
- deterministic benchmark fixtures.

Typical technologies:

- Python,
- pandas,
- local Parquet,
- local model cache.

### Databricks mode

Purpose:

- Spark-scale processing,
- Delta persistence,
- Unity Catalog governance,
- scheduled jobs,
- model serving/MLflow integration,
- larger benchmarks,
- dashboarding.

## Suggested lakehouse layout

The exact catalogs/schemas should remain configurable.

Conceptual structure:

```text
pii_demo.raw.*
pii_demo.normalized.*
pii_demo.reduced.*
pii_demo.audit.*
pii_demo.benchmark.*
```

### `raw`

Public or synthetic source material as ingested.

### `normalized`

Optional canonical versions after source-specific normalization.

### `reduced`

Business-facing datasets containing original and PII-reduced columns or controlled reduced-only views.

### `audit`

Privacy-safe pipeline metadata and detection span metadata.

### `benchmark`

Truth labels, provider predictions, metrics, performance measurements, and run comparisons.

## Table design

### Reduced table

Example:

```text
conversation_id STRING
channel STRING
transcript STRING
transcript_pii_redacted STRING
pii_run_id STRING
pii_status STRING
processed_at TIMESTAMP
```

### Detection audit

```text
run_id STRING
row_id STRING
column_name STRING
segment_id STRING
segment_start INT
entity_type STRING
start INT
end INT
score DOUBLE
provider STRING
recognizer STRING
language STRING
resolution_rule STRING
```

`AUDIT_COLUMNS` in `processing/field_processor.py` is the canonical statement of this
set, and a default-tier test pins it as a literal: every column is metadata about a
span, none carries the matched text, and none may (`AGENTS.md` rule 8).

### Run metrics

```text
run_id STRING
config_hash STRING
pipeline_version STRING
source_table STRING
source_version STRING            -- delta_v<N> when the source is a Delta table
provider_versions ...            -- per provider: type + library/model versions (docs/03 §11)
language_detector_version STRING -- when a detect-mode column ran
pseudonymization_key_id STRING   -- non-secret key digest; null unless pseudonymizing
rows_read BIGINT
rows_written BIGINT
fields_processed BIGINT
entities_detected BIGINT
entities_reduced BIGINT
fallback_count BIGINT
failure_count BIGINT
started_at TIMESTAMP
completed_at TIMESTAMP
```

The provenance columns were added in session 9 (docs/17 D2). A rerun in `append`
mode onto a metrics table written before then is a deliberate schema change: enable
schema evolution for that write or start a new table — the default `errorifexists`
mode is unaffected.

## Spark processing design

Heavy NLP inside Spark requires careful execution strategy.

### Anti-pattern: scalar UDF with model construction

Do not do:

```python
@udf("string")
def redact(text):
    model = load_large_model()
    return model(text)
```

This can initialize models repeatedly and create severe overhead.

### Better: worker-level initialization

Use lazy module-level or partition-level initialization so each Python worker loads the model once.

### Batch processing

Where supported, feed batches of text into the provider.

Potential Spark approaches:

- `mapInPandas`,
- pandas UDFs,
- `mapPartitions`,
- external/model-serving batch calls,
- native SQL/Spark expressions for deterministic recognizers.

The project should benchmark these choices rather than hard-code a universal answer.

## Hybrid Spark execution

A useful optimization is to separate cheap and expensive recognizers.

Conceptual flow:

```text
Spark-native deterministic detection
              +
   batched NLP candidate processing
              ↓
       reconcile spans
              ↓
        reconstruct text
```

For example, email and phone can often be detected efficiently without sending every string through a heavy NER model.

## Partition strategy

Partitioning should be based on source table characteristics, not on PII entities.

Possible dimensions:

- ingestion date,
- business date,
- source system,
- channel.

Avoid excessive small partitions.

## Restartability

For large datasets, consider staged Delta outputs:

```text
source selection
  ↓
normalized text segments
  ↓
PII predictions
  ↓
reduced output
```

Staging makes it possible to retry expensive model inference without rereading or reparsing everything.

For smaller workloads, an in-memory pipeline may be simpler.

## Incremental processing

Future production pattern:

- identify new/changed rows,
- process only affected records,
- merge results by stable row ID,
- retain source version and processing version.

Do not assume append-only semantics.

## Unity Catalog considerations

The project should be compatible with governed objects and configurable fully-qualified table names.

Potential governance surfaces:

- catalog/schema permissions,
- table ownership,
- comments and tags,
- lineage,
- row/column access controls where needed.

The open-source repo should not assume the user's workspace grants or catalog names.

## Secrets

Authentication should use supported environment/secret mechanisms.

Never commit:

- personal access tokens,
- service-principal secrets,
- workspace-specific passwords,
- pseudonymization keys.

Notebooks should not contain hard-coded secrets.

## Jobs

> **Shipped (session 10): `resources/pii_reduction_job.yml`, a skeleton that has
> never been deployed.** It is **one** task, not the five below — a
> `python_wheel_task` calling the same `pii-reduction-databricks run` entry point a
> person uses interactively, so there is no second implementation to drift
> (`AGENTS.md` rule 10). The five-task shape below remains the sketch for a *demo*
> pipeline that also builds ground truth and publishes benchmark metrics; nothing
> like it is built.

Recommended tasks for a mature demo job:

```text
1_prepare_demo_data
2_build_ground_truth
3_run_pii_reduction
4_evaluate_predictions
5_publish_metrics
```

These may be separate tasks or one parameterized entry point depending on complexity.

## Parameters

> **What the shipped job actually takes**, which is deliberately less than the list
> below: `run <dataset> --configs <path>`. The dataset config names the source table,
> the destination, the columns, the provider chain and the reduction strategy — so
> the parameters below that look like job settings (`provider_chain`, `run_mode`,
> `sample_fraction`) are either config keys or do not exist. A job that carried them
> could be retargeted in a browser with nobody reviewing it.

Useful job parameters:

```text
environment
config_path
dataset_name
provider_chain
run_mode
benchmark_enabled
sample_fraction
```

## Model lifecycle

If transformer models are used:

- pin model revision where possible,
- capture model name/version in run metadata,
- cache models appropriately,
- document licenses,
- avoid repeatedly downloading models on every job.

If MLflow is introduced, use it to track provider/model benchmark runs rather than as decoration.

## Databricks-native AI integration

The architecture may later add Databricks-hosted foundation models or model-serving endpoints as a provider. Keep this optional and provider-scoped.

The core benchmark should still include local/open baselines so the repository remains reproducible outside a specific workspace.

## Dashboarding

Benchmark and operational metrics can later be presented through Databricks AI/BI.

Potential dashboard pages:

1. Executive quality overview
2. Entity-level precision/recall/F1
3. Language comparison
4. Provider comparison
5. Leakage and over-redaction
6. Runtime and throughput
7. Parser failures / unsupported languages
8. Dataset profiling

The dashboard should read Delta metrics tables rather than recalculate NLP results.

## Databricks Apps

An optional Databricks App could provide:

- controlled sample viewer,
- side-by-side original/reduced synthetic demo text,
- provider selector,
- benchmark comparison,
- configuration explorer.

Never expose real production PII through a portfolio review interface.

## Deployment

`databricks.yml` and `resources/` hold the shipped skeleton (session 10): an Asset
Bundle plus a job definition, with a CLI-free path — UI job creation or a Jobs API
POST — for workspaces whose policy blocks the Databricks CLI. Never deployed; see
`resources/README.md`.

The repository may support multiple deployment methods:

- Databricks Asset Bundles,
- Databricks SDK/REST automation,
- workspace import from CI,
- manual notebook/script import for restricted environments.

No single deployment mechanism should be required for the core Python package to function.

## Performance benchmark

A useful benchmark should measure:

```text
rows/sec
characters/sec
segments/sec
provider latency
model initialization time
worker count
cost proxy
failure rate
```

Measure warm and cold behavior separately where model startup is significant.

## Production warning

Portfolio success on public synthetic data is not proof of production suitability. Production rollout requires sampling, privacy review, false-negative analysis, source-specific tuning, and monitoring for data drift.

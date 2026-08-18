# Configuration Contract

## Objective

The accelerator should be reusable without code edits for ordinary dataset onboarding. Configuration defines sources, destinations, target columns, parsers, languages, entity scope, providers, reduction strategy, failure behavior, and benchmark options.

## Configuration layers

Recommended hierarchy:

```text
project defaults
    ↓
environment overrides
    ↓
dataset configuration
    ↓
column configuration
```

More specific configuration overrides broader defaults.

## Suggested files

```text
configs/
├── project.yaml
├── entities.yaml
├── languages.yaml
├── providers.yaml
├── benchmark_gates.yaml   ← not part of this contract; see below
└── datasets/
    ├── demo_support_tickets.yaml
    ├── demo_transcripts.yaml
    └── demo_incident_notes.yaml
```

`benchmark_gates.yaml` is the exception in that directory. It holds benchmark
regression floors, lives in `configs/` because ADR-0009 requires the gate values to
sit in one versioned file, and is **not** read by `config/loader.py` — the loader
merges `project.yaml` plus the three side files above and ignores everything else.
Its schema and semantics belong to `docs/08_EVALUATION_BENCHMARKING.md`, not to this
contract.

## `project.yaml`

Conceptual example:

```yaml
project:
  name: databricks-pii-reduction
  environment: local
  seed: 42

processing:
  preserve_original: true
  output_suffix: _pii_redacted
  default_parser: plain_text
  failure_mode: preserve_original_and_record_error

language:
  mode: detect
  detector: fasttext
  min_chars: 20
  min_confidence: 0.70
  unknown_language: und

provider_chain: default_hybrid
reducer: redact

observability:
  log_level: INFO
  log_raw_text: false
  write_detection_audit: true
```

## Source configuration

### Excel

```yaml
source:
  type: excel
  path: data/input/demo.xlsx
  sheets: auto
```

Optional explicit sheets:

```yaml
source:
  type: excel
  path: data/input/demo.xlsx
  sheets:
    - Support Tickets
    - Chat Logs
```

### CSV

```yaml
source:
  type: csv
  path: data/input/support.csv
  options:
    encoding: utf-8
    delimiter: ","
```

Folder mode:

```yaml
source:
  type: csv_folder
  path: data/input/tickets/
  pattern: "*.csv"
```

### Parquet

```yaml
source:
  type: parquet
  path: data/input/support.parquet
```

### Databricks table

```yaml
source:
  type: databricks_table
  table: pii_demo.raw.support_transcripts
```

Credentials and workspace details must remain outside dataset files.

## Destination configuration

Local:

```yaml
destination:
  type: parquet
  path: data/output/
```

Databricks:

```yaml
destination:
  type: delta_table
  catalog: pii_demo
  schema: reduced
  table: support_transcripts
  mode: overwrite
```

For production-like jobs, prefer a controlled merge/replace strategy rather than unconstrained append.

## Dataset configuration

Example:

```yaml
dataset:
  name: demo_support_transcripts
  row_id: conversation_id

source:
  type: databricks_table
  table: pii_demo.raw.support_transcripts

columns:
  transcript:
    process: true
    parser: transcript
    output_column: transcript_pii_redacted
    entities:
      - PERSON
      - EMAIL
      - PHONE
      - ADDRESS
    language:
      mode: detect
    provider_chain: default_hybrid
    reducer: redact
```

## Plain-text parser options

```yaml
parser_options:
  split_lines: false
```

`split_lines` makes each line its own processable segment, with the line break kept as
non-processable structure. Set it for columns holding line-structured text — key/value
blocks, exported form fields, anything where a line is a record rather than a sentence.

It defaults to `false`, and that default is deliberate: splitting is wrong for prose
that wraps mid-sentence, where a name broken across the wrap would become undetectable.
Turn it on per column, never globally. See ADR-0016 for the measurement that motivated
it and for how it relates to the deferred `key_value` parser.

## Transcript parser options

```yaml
parser_options:
  line_mode: auto
  speaker_delimiters: [":"]
  preserve_prefix: true
  fallback: preserve_line
```

A production parser may support multiple transcript patterns. Configuration should describe intent rather than embed large regexes in YAML wherever possible.

## Note-history parser options

```yaml
parser_options:
  header_style: servicenow_history
  preserve_header: true
  blank_line_separates_entries: true
  fallback: plain_text
```

## Entity configuration

`entities.yaml` can define taxonomy and default replacements:

```yaml
entities:
  PERSON:
    replacement: "<PERSON>"
    priority: 50
  ADDRESS:
    replacement: "<ADDRESS>"
    priority: 60
  PHONE:
    replacement: "<PHONE>"
    priority: 90
  EMAIL:
    replacement: "<EMAIL>"
    priority: 100
```

## Provider configuration

Example:

```yaml
providers:
  deterministic:
    type: deterministic
    entities: [EMAIL, PHONE]

  presidio_en:
    type: presidio
    languages: [en]
    entities: [PERSON, EMAIL, PHONE, ADDRESS]
    threshold: 0.50

chains:
  default_hybrid:
    providers:
      - deterministic
      - presidio_en
    overlap_policy: priority_score_length
```

Provider-specific model names and versions should be configurable.

## Language configuration

```yaml
languages:
  en:
    chain: english_hybrid
  de:
    chain: german_hybrid
  el:
    chain: multilingual_hybrid
  und:
    chain: safe_fallback
```

## Reducer configuration

### Redact

```yaml
reducers:
  redact:
    type: redact
```

### Mask

```yaml
reducers:
  mask:
    type: mask
    rules:
      EMAIL: partial_email
      PHONE: last4
      PERSON: full
      ADDRESS: full
```

### Deterministic pseudonymization

```yaml
reducers:
  pseudonymize:
    type: deterministic_token
    key_env: PII_PSEUDONYMIZATION_KEY
    scope: dataset
```

Do not place secret keys in YAML.

## Validation configuration

```yaml
validation:
  require_row_count_match: true
  require_original_unchanged: true
  require_output_columns: true
  roundtrip_parser_test: true
  leakage_check:
    enabled: true
    benchmark_only: true
```

## Benchmark configuration

```yaml
benchmark:
  enabled: true
  truth_table: pii_demo.benchmark.entity_truth
  dimensions:
    - language
    - entity_type
    - document_type
    - difficulty_tier
  metrics:
    - precision
    - recall
    - f1
    - leakage_rate
    - over_redaction_rate
    - latency_ms
```

## Environment overrides

Environment-specific values should use environment variables or a local uncommitted file.

Examples:

```text
DATABRICKS_HOST
DATABRICKS_TOKEN
PII_DEFAULT_CATALOG
PII_DEFAULT_SCHEMA
PII_PSEUDONYMIZATION_KEY
HF_HOME
```

Never require secrets to parse configuration.

## Config validation

Configuration should be parsed into typed models and validated before processing begins.

Errors should be actionable:

Bad:

```text
KeyError: parser
```

Good:

```text
ConfigurationError: dataset 'demo_chat', column 'transcript': parser 'conversation_v9' is not registered.
```

## Configuration fingerprint

Create a stable hash from effective non-secret configuration.

Use this fingerprint in run metadata so benchmark results can be traced to exact settings.

Secrets must not be included in the hash material or persisted configuration snapshots.

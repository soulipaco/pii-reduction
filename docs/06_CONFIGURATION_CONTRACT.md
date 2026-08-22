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
├── service_templates.yaml ← the service layer's menus; see below
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

## Files in `configs/` that the loader does not read

Two files live beside the dataset contracts and are **not** part of the layered
merge, so `config/loader.py` never sees them:

- `benchmark_gates.yaml` and `pack_gates/*.yaml` — regression floors, read by
  `evaluation/gates.py`.
- `service_templates.yaml` — the service layer's dataset templates (ADR-0026,
  `docs/19_SERVICE_LAYER.md`). Unlike the gate files this one *is* inside this
  contract's model surface: a template embeds a `SourceConfig`, a
  `DestinationConfig`, and `ProcessingOverrides`/`LanguageOverrides` from
  `config/models.py`, so the fields below govern it and it cannot drift from them.
  What it adds is service policy — which columns, entity labels, parsers, chains,
  reducers and parser options a caller may choose (ADR-0034) — and the rule that a
  caller may choose *nothing* else. `docs/19` is the operator-facing description.

  One template key **reinterprets a governed field** rather than adding beside it, so
  it is called out here: `select_file: true` makes `source.path` a **directory**
  instead of a file, and the caller names one file inside it (ADR-0036). Every
  `path:` example in this document is a file, and that stays the meaning everywhere
  except in a template that sets this key. It applies to path-based sources only; a
  template setting it on a `spark_table` is refused at load.

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
  failure_mode: quarantine_row  # fail-closed default, ADR-0023

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

Folder mode — **not implemented.** `csv_folder` is not in `KNOWN_SOURCE_TYPES`, so
the loader rejects it; the block below is the intended shape, kept because the type
is still wanted, not because it works:

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

**Shipped (session 10, ADR-0025).** The type is `spark_table` — the adapter's own
`source_type`, not the `databricks_table` earlier drafts of this document guessed at:

```yaml
source:
  type: spark_table
  table: catalog.schema.table
```

**How the session gets there — the design point this document used to leave open.**
Configuration names the **table**; the **runtime** supplies the **session**. The two
cannot arrive together: a session is not a value a YAML file can hold, and a
`sources/` module that accepted one would put a Databricks dependency on the runtime
path (`docs/01_ARCHITECTURE.md`, *Package dependency direction*, pinned by three
tests). So the name is validated by the config layer like any other, and the adapter
is built by the one execution surface that has a session —
`databricks.runner.run_driver`, reachable from a shell as
`pii-reduction-databricks run <dataset>`.

`sources.registry.build_source` therefore still builds `csv` and `parquet` only, and
**refuses `spark_table` with an instruction rather than a "not registered"**: the
adapter exists, it is simply built elsewhere. A test pins that refusal set to exactly
the Databricks types, so a type cannot go missing from the registry and be explained
away.

Credentials and workspace details must remain outside dataset files. The table name
is a configuration value; credentials are environment variables — a CLI profile
(`DATABRICKS_CONFIG_PROFILE`), or `DATABRICKS_HOST` plus `DATABRICKS_TOKEN` or a
service principal, or nothing at all on Databricks compute. There is no config key
and no function parameter for a host or a token, deliberately.

## Destination configuration

Local:

```yaml
destination:
  type: parquet
  path: data/output/
  # projection: reduced_only   # write the artifact without the configured raw
  #                            # text columns (ADR-0024); default is full
```

Databricks — same shape and same split as the source above:

```yaml
destination:
  type: delta_table
  catalog: <catalog>
  schema: <schema>
  mode: errorifexists      # or overwrite / append — deliberately, never as a fallback
  # projection: reduced_only
```

There is **no `table` key**: one `catalog.schema` prefix serves a run's reduced,
audit and run-metrics tables, each named from the dataset (`<dataset>_reduced`,
`<dataset>_pii_audit`, `<dataset>_run_metrics`), which keeps them in one schema by
construction (`docs/07`).

**Field-level failure is not signalled by the process exit code alone.** A run that
completes with failed fields writes the table and exits 1 from
`pii-reduction-databricks run`; the durable record is `pii_status` on the row and
`fields_failed` in the run-metrics table (ADR-0023). A scheduler should read the exit
code; an analyst should read `pii_status`.

The write modes are the Delta writer's, not the local file ones, and they are **not
inherited across that boundary**: a local `mode: overwrite` means "replace a file",
while the same word against a Delta table replaces a governed dataset. A run whose
destination is not a `delta_table` falls back to `errorifexists` rather than
borrowing the local mode.

For production-like jobs, prefer a controlled merge/replace strategy rather than unconstrained append.

## Dataset configuration

Example:

```yaml
dataset:
  name: demo_support_transcripts
  row_id: conversation_id

source:
  type: spark_table
  table: catalog.schema.support_transcripts

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

> **`preserve_prefix: true` puts the speaker label out of scope for detection, and a
> speaker label is not always a role.** The prefix `2026-04-03 09:12:04 - Peter Novak:`
> is treated as structure, so under this setting that name is never offered to any
> provider and cannot be redacted by any provider, repair rule or reduction strategy.
> This is correct for `Customer`/`Agent`/`Πελάτης` and wrong for a work-note author, a
> signed email quote, or any transcript whose speakers are named people. Measured:
> PERSON recall is 0.000 at tier 4 in all three languages on the incident-notes corpus
> (ADR-0022), against 0.933–1.000 in the same documents' structured headers, and
> ADR-0028 attributes exactly 90 of that corpus's 315 ground-truth entities to it.
>
> **If your transcripts name their speakers, set `preserve_prefix: false` on that
> column.** The whole line becomes one processable body, so the author's name reaches a
> provider through the ordinary path. **ADR-0032 rules on this** and publishes what it
> costs in both directions, measured on the hybrid chain:
>
> | | speakers are people (incidents) | speakers are roles (benchmark corpus) |
> |---|---|---|
> | strict F1 | 0.761 → **0.844** | 0.910 → **0.902** |
> | leakage rate | 0.289 → **0.114** | 0.067 → **0.061** |
> | tier-4 PERSON recall (en/de/el) | 0.000 → **0.333 / 0.900 / 0.400** | n/a — no speaker is ground truth |
> | PERSON strict precision | — | 0.771 → **0.744** |
>
> Three things to know before setting it:
>
> - **It buys nothing without a model.** On `deterministic_only` every detection number
>   is identical either way; only `unreachable_entity_rate` changes.
> - **It re-cuts the model's input**, which is the failure class ADR-0016 exists to
>   avoid. On the benchmark corpus the two documents that change are Greek and the
>   changes are in the *body*, not the prefix — joining the prefix to the body changed
>   what the model saw.
> - **The timestamp survives because no shipped entity policy detects it**, not because
>   the parser still protects it. Adding a date-like entity to a column configured this
>   way would put `AGENTS.md` rule 5 ("timestamps must not be damaged") back in play.
>
> It is a **per-column** option for those reasons. Do not set it globally.

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
    # Per entity, never a single global threshold — provider scores are recognizer
    # constants, and one global value would silently drop whole entity types
    # (ADR-0005). `calibration` records the provenance of these values; it travels
    # into every run's metadata as `threshold_calibration`, and because it is part of
    # the configuration it also feeds the config fingerprint — rewording the note
    # changes `config_hash`, deliberately: provenance prose is load-bearing.
    thresholds:
      PERSON: 0.5
      EMAIL: 0.6
      PHONE: 0.3
    calibration: reviewed-s6-calibration-split-constants-locked

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
  require_markup_preserved: true
  roundtrip_parser_test: true
  leakage_check:
    enabled: true
    benchmark_only: true
```

**Two severities, and only one blocks.** Everything under `validation:` is a
*fidelity* check: it asserts that the output kept something it had to keep, and a
failure stops the run with a non-zero exit (ADR-0023's fail-closed posture). A
detector *missing* a name is a **recall** failure, which the benchmark reports and no
production run gates on — recall is never 1.0, so gating on it means nothing ever
ships, while not gating on fidelity means shipping structural damage that stays
invisible until something downstream tries to parse the output.

`require_markup_preserved` (ADR-0027) is the one that reaches *inside* an eligible
region: it counts known HTML and BBCode tag names that the reduction destroyed. Its
implementation deliberately shares nothing with the provider-boundary markup guard —
a validator that imports the detector's idea of markup rubber-stamps a shared mistake.
Turning it off is a decision, not a workaround: it says this dataset accepts
structural damage inside the text offered for reduction.

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

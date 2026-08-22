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
- **answer what columns it has without reading the rows** (`schema()`, ADR-0031) —
  a header line, a parquet footer, the metastore; never a scan,
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
└── parquet_source.py
```

The Spark/Delta adapter implements this layer's protocol but **ships under
`databricks/`**, not here (`databricks/source.py::SparkTableSource`). A module under
`sources/` that needs a Spark session would put a Databricks dependency on the runtime
path; see *Package dependency direction* below.

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

The Spark/Delta writer implements this layer's protocol but **ships under
`databricks/`** (`databricks/output.py::DeltaTableOutput`), for the same reason as the
Spark source adapter; see *Package dependency direction* below.

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

execution surfaces (cli.py, benchmark.py, databricks/) depend on processing/;
nothing on the runtime path depends on them. They may also reach an interface
layer directly — benchmark.py builds the configured parser to compute
reachability (ADR-0028) — because an execution surface sits above all of them.
An interface layer may not reach a sibling: that is the edge that would have
been created by computing reachability inside evaluation/.

service/ (rung 4, ADR-0026) sits above the execution surfaces. It may depend on
config/, processing/, contracts/ and observability/, and on databricks/ through
one named file; nothing outside it may import it.
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

`databricks/` sits at the **outermost edge of the engine**, beside `cli.py` and
`benchmark.py` rather than beside `sources/` or `outputs/` (`service/`, below, sits
above it — rung 4 is not part of the engine). It is an *execution surface*: it decides
where a run happens, not what a run does. It may import `processing/`, `config/`,
`sources/` and `contracts/`; the bad example above names it for the opposite reason,
the forbidden `parsers -> databricks` edge. **Nothing else in `src/` imports it**,
with exactly one named exception described in the `service/` paragraph below — so
removing it removes two ways to run the pipeline and no behaviour. It is also the only package permitted to import
`pyspark` or `databricks.connect`. Three tests hold that boundary, and each holds a
part the others cannot:

- `test_core_layers_import_without_any_provider_extra` imports the core packages in a
  fresh subprocess and fails if an optional runtime was pulled in *eagerly*. It
  imports `databricks/` among them, which is what proves the surface stays importable
  with no `pyspark` installed at all — the property the lazy-session design rests on.
- `test_only_the_databricks_surface_names_spark` parses every module under `src/` and
  fails on a **static** Spark import outside `databricks/`, at any nesting depth.
- `test_nothing_outside_the_databricks_surface_imports_it` pins the direction, over
  every import form that can name a submodule (`from pii_reduction import databricks`
  included — reading only the module of a `from ... import ...` would miss it). It
  exempts exactly one path, `service/runtimes/databricks.py` (ADR-0026), and asserts
  that the path exists so a rename cannot retire the exemption into a blanket
  allowance. The Spark-name guard above is **not** exempted for it: the one file that
  may import the Databricks surface still may not name `pyspark`.

Neither AST scan can see `importlib.import_module("pyspark")`, and the subprocess
check cannot see a function-local import; that is why all three exist rather than one.

Its Spark-facing pieces (`SparkTableSource`, `DeltaTableOutput`) implement the
`sources/` and `outputs/` protocols but live here rather than there, because a
`sources/` module that needs a Spark session would put a Databricks dependency on the
runtime path — the inversion this section exists to forbid. Neither imports the
protocol it satisfies; conformance is structural, and asserted by
`TestProtocolConformance` so that a protocol gaining a member cannot break it
silently.

`service/` sits **above** every one of them — rung 4 of ADR-0025's ladder, a thin
HTTP API (ADR-0026) that since ADR-0035 also serves a static control panel. It builds
and validates dataset configurations, triggers runs through the same two entry points a
human uses (`build_pipeline(config).run()` and `run_driver`), and answers with metadata.

It reads the **configuration** directory, and — for a template that opts in with
`select_file` — lists **names** in the data directory that template declares
(ADR-0036). That is a widening of what this package touches and is stated rather than
left to be discovered: it never opens a data file, and going through `sources/` was not
the alternative, because listing names needs no adapter and inventing a
`SourceAdapter.list()` for one consumer would put a capability in the engine that no
engine consumer wants. Like `synthetic/` it is a package nothing
on the runtime path may depend on and whose removal removes a capability rather than
a behaviour — but it is *narrower* than `synthetic/`, which may import `parsers/` and
`entities/` and is imported by `cli.py`. `service/` may do neither.

It owns **no reduction logic** — no detection, no reconciliation, no reduction — and
that is enforced rather than asserted: no module under `service/` may import
`providers/`, `reducers/`, `parsers/`, `language/`, `entities/`, `evaluation/`,
`sources/`, `outputs/` or `synthetic/`. What is left to it is `config/`, `contracts/`,
`observability/`, `processing/` **through `processing/pipeline.py` only** (the bare
package is closed too, because its `__init__` re-exports `FieldProcessor`), and the
one Databricks file. A
service that cannot name a provider or a reducer cannot quietly *reuse* one, and any
attempt to reimplement one is visible in the diff rather than hidden behind an
import. (The guard bounds what the service may name; it cannot stop somebody writing
a regex inside `service/`, and does not claim to.) A capability the service needs
that the engine lacks becomes a change to the engine — the
entity taxonomy a column picker must enumerate is the first such case, and it is met
by `config/` re-exporting `known_labels`, not by `service/` reaching into
`entities/`. Note what the rule is: a **naming** rule, not runtime isolation.
`processing/pipeline.py` imports every one of those packages, so the service process
loads them all transitively. The guard stops the service *writing* reduction logic;
it is not a sandbox.

The direction is asymmetric on purpose, and both halves are pinned by
`tests/test_package.py` from the increment that creates the package:

- **The engine never learns the service exists.** Nothing in `src/pii_reduction`
  outside `service/` may import `pii_reduction.service`, at any nesting depth. This
  is the literal form of ADR-0025's rung rule.
- **The service may depend downward, through one named file.** `service/runtimes/`
  holds one module per execution runtime; `service/runtimes/databricks.py` is the
  *only* path outside `databricks/` permitted to import the Databricks surface, and
  the guard names that exact relative path — compared as a POSIX string, because
  `WindowsPath` equality is case-insensitive and a `Databricks.py` would otherwise be
  exempt on a laptop and rejected on CI — rather than exempting a directory or a
  filename. Every other file in `service/` is held to the same rule as the engine, so
  the Databricks surface gains exactly one importer outside itself and `pyspark`
  gains none.

`processing/` is reachable, but only through `processing/pipeline.py`; the guard
closes the rest, because `field_processor.py` is the per-field
parse → detect → reconcile → reduce orchestrator and a service reaching for it is
reaching into the engine. `config/` is left fully open, which makes it the sanctioned
relay for anything the service needs from below — `known_labels` and `TAXONOMY` are
exactly such re-exports — so `config/`'s own edges are pinned in turn: it may reach
`contracts/` and `entities/` and nothing else.

`service/api.py` is the only module that imports the ASGI framework, which is an
optional extra (`service`). The rest of `service/` is framework-free and testable
without it — but note the difference from `providers/presidio_provider.py`, whose
defining property is that `pii_reduction.providers` imports fine with no extra
installed. Route decorators run at import time, so `service/api.py` cannot defer its
import the way the Presidio adapter defers its engine. The contract is therefore on
the package: **`service/__init__.py` must not import `api`**, or
`pii_reduction.service` stops being importable in a core install. The subprocess
guard **will check** it, with `fastapi` added to the optional-module list — otherwise
the check is blind on a developer machine that has it — in the increment that creates
the package.

## Local and Databricks parity

The local runner and Databricks runner both construct the same processing pipeline.

Example:

```python
pipeline = build_pipeline(config)
result = pipeline.process(dataset)
```

The difference is the source/output adapter and execution strategy, not the entity logic.

As shipped (Increment F), `databricks/` offers two execution strategies over that one
pipeline:

- `run_driver` — read a table through Spark, *or* a configured file through the
  ordinary local adapter (which on Databricks compute includes a `/Volumes` path),
  run `pipeline.process` on the driver, write the reduced rows, the privacy-safe
  audit spans and the run metrics back as Delta. Works on any compute that can run SQL, including serverless-only workspaces.
- `distributed_frame` — the `mapInPandas` strategy, with the pipeline built once per
  worker from a cache keyed on the driver-generated run id *plus* the config hash. The
  run-id half is load-bearing: keyed on config alone, a warm worker would stamp a
  previous job's `pii_run_id` onto a new run. It produces the reduced frame only; audit
  rows and run metrics are a second output channel and are out of scope for v1.

Both call the byte-identical `pipeline.process`, which is what makes parity an
assertion rather than an aspiration: the reduced column hashes from a Databricks run
equal a local run's on the same fixture.

## Scalability considerations

### Avoid row-by-row model loading

Model initialization must occur once per process or worker.

### Batch inference

Providers that support batching should expose a batch API.

**The pipeline batches a row's segments, and deliberately not across rows** (ADR-0033).
`FieldProcessor` makes one `detect_batch` call per provider per row; the Presidio
adapter routes it through one `nlp.pipe`, which is worth 1.6–1.8× on a column whose
rows hold several segments and nothing on a column whose rows hold one.

Two structural rules follow, and both are about keeping this from becoming a second
implementation:

- **A provider overrides `_detect_batch`, below the repair chain**, never the public
  `detect_batch`. Validation, line-bounding, span extension, the markup clip and
  de-duplication are properties of one text and live once, in `BaseProvider._finalize`,
  which both entry points call.
- **Batching may not change output.** `detect_batch` must return exactly what the same
  texts produce one at a time.

**Across-row batching is refused, not deferred.** It would move detection outside the
per-row failure isolation that ADR-0023's `quarantine_row` depends on, so one malformed
row would take its whole batch with it.

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

The default is `quarantine_row` (ADR-0023): on failure the field carries no reduced
value, so nothing unreviewed can be mistaken for reduced output. An earlier revision
of this document recommended `preserve_original_and_record_error` as a portfolio-demo
default; ADR-0023 supersedes that advice — under it, any provider, parser, or model
error writes the raw original text into the reduced column, which is the wrong
default for a privacy boundary. `preserve_original_and_record_error` remains
available as an explicit per-dataset or per-column opt-in for demos that want a
best-effort pass-through, and the row still carries `pii_status = partial_failure`
when it is used.

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

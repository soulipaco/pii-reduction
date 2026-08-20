# Runbook: run the reduction on your own Databricks table

The ten-minute path from a Unity Catalog table to a reduced Delta table, an audit
table and a run-metrics table. Nothing here needs Python written; everything is a
dataset config plus one command.

> **Verification status (session 10, 2026-08-20).**
>
> **Verified on the workspace, twice, by two people.** The owner ran
> `pytest -m databricks` from their own PowerShell session on 2026-08-20 over the
> token route (`env_token`); it was then re-run in-session over a **named CLI
> profile** (route `profile`) against the schema the owner configured. Both runs:
> **2 passed, 5 skipped** (69–74s). The marked tier holds four tests — 2 passed, 2
> skipped; the other three skips are module-level collection skips in the
> presidio/language suites, which fire in `.venv-dbx17` (no such extras) even though
> the marker deselects them. A reviewer read 2 + 5 against a four-test tier and
> called it impossible; the second run settled it first-hand, which is why the
> arithmetic is spelled out here. Incidentally this also exercised **two different
> authentication routes** against the same workspace, which nothing had done before. The two that passed are the driver-path Delta round-trip — reduced-column
> hashes equal between the workspace run and the local one — and the audit/metrics
> metadata-only check. That run also carried the first execution **against a real
> workspace** of two things previously covered only locally and against fake
> sessions: the **reduced-only projection** of §4 (ADR-0024) and the **run-metrics
> provenance columns** of §5 (`run_source_version` resolving to `delta_v<N>`), both
> asserted inside those tests. Note what the projection check did and did not cover:
> it was written into the *same* throwaway schema, so what is verified is that the
> table exists and drops the raw column — the separate-prefix grant boundary §4
> describes is still covered by unit tests only.
>
> **Still unverified, and skipped in that run for stated reasons:** **volume
> ingestion (§6)** — `/Volumes` is not mounted on a local Databricks Connect client,
> so it must be run from a notebook or job; and the **distributed `mapInPandas`
> path** — the workspace's serverless Python sandbox still fails with
> `ISOLATION_STARTUP_FAILURE`, open since session 7 (plan §8 F).
>
> **This runbook's own path has now run, end to end** (2026-08-20). A synthetic
> 20-row table was staged in Unity Catalog, a dataset config was pointed at it, and
> `pii-reduction-databricks run <dataset> --configs <dir>` was executed exactly as
> §3 describes: **exit 0**, three Delta tables written, metadata-only summary. Read
> back: 20 rows, the source column intact beside the reduced one (rule 4), every row
> `success` under a single run id, 16 of 20 rows carrying `<EMAIL>`/`<PHONE>`
> placeholders, the audit table's column set exactly `AUDIT_COLUMNS`, and run metrics
> showing `run_rows_read=20` with `run_source_version=delta_v0`. Everything created
> was dropped afterwards.
>
> **That run found a real defect, which is why it was worth doing.** The shipped
> default write mode, `errorifexists`, is **rejected by Databricks Connect**
> (`[UNSUPPORTED_OPERATION]`), so every config-driven Delta write failed with exit 2.
> The parity suite never saw it because it passes `mode="overwrite"` explicitly. The
> adapter now sends Spark's equivalent alias `error`, and the coverage gap that let
> it ship is closed at both levels: a default-tier test pins the translation, and a
> new **workspace** test writes under the *default* mode and asserts that a second
> write refuses. That test passes — the marked tier is now **3 passed, 2 skipped**.
>
> Still untested: step 1's combined `[databricks,presidio,language]` install, which
> has never been performed in any environment here. The run above used the
> deterministic chain (EMAIL and PHONE only) because `.venv-dbx17` carries the
> databricks extra alone — so it does **not** demonstrate PERSON detection.

---

## 0. Before you start

You need:

- a Databricks workspace and credentials by any of the routes in §1b — a CLI
  profile, a token or service principal in the environment, or nothing at all when
  you run on Databricks compute,
- permission to read your source table and to **create** tables in a destination
  schema,
- a source table with at least one free-text column and a stable row id.

You do **not** need a cluster: the driver path runs on serverless compute, which is
the only compute some workspaces have (ADR-0006).

## 1. Install into a dedicated environment

Databricks Connect couples client and server versions, so it does not share the core
venv (ADR-0006). Create its own once:

```bash
uv venv .venv-dbx --python 3.12
```

```bash
VIRTUAL_ENV=.venv-dbx uv pip install -e ".[databricks,presidio,language]"
```

**Take all three extras, and install the spaCy models** per `docs/15_PROVIDERS.md`.
They are not optional for the configuration in §2, and the two ways of skipping them
both fail quietly:

- **Without `presidio` and its models, nothing detects PERSON.** The deterministic
  recognizers still find EMAIL and PHONE, every row reports `success`, and every
  person's name stays in the text. Installing the extra is necessary but **not
  sufficient** — the provider chain in §2 is what actually selects the detector, and
  the project default is deterministic-only.
- **Without `language`, the template's `mode: detect` fails every field long enough
  to reach the detector.** It raises on first use, and under the fail-closed default
  that quarantines the field — so you get a mostly-null reduced column and exit 1.
  Short fields survive: the short-text gate returns `und` before the detector is
  touched, and they fall back to the deterministic chain. If you cannot install the
  extra, use `mode: static` with `static_language: en` and accept that every row is
  treated as that language.

## 1b. Authenticate

Three routes. The tooling tries them in this order and uses the first that is
complete:

**A named CLI profile** — nicest when your organisation allows the CLI:

```bash
export DATABRICKS_CONFIG_PROFILE=<your-profile-name>
```

**A token or service principal in the environment** — the route to use when policy
blocks the Databricks CLI:

```bash
export DATABRICKS_HOST=https://<your-workspace-host>
export DATABRICKS_TOKEN=<your-personal-access-token>
```

or, for an OAuth service principal, `DATABRICKS_HOST` plus `DATABRICKS_CLIENT_ID` and
`DATABRICKS_CLIENT_SECRET`.

**Nothing at all**, when the process already runs on Databricks compute — a notebook
or a job authenticates itself.

Set these in your shell or pull them from a secret store at run time. Never put a
token in a config file, a notebook cell, a job definition, or this repository
(`AGENTS.md` rule 1) — and note that the tooling has no `host` or `token` *parameter*
anywhere, deliberately: a value passed as an argument ends up in tracebacks, shell
history and job JSON. Credentials are read from the environment or not at all.

## 2. Describe your table in a dataset config

Copy `configs/datasets/databricks_table_example.yaml` and edit it. The whole contract:

```yaml
dataset:
  name: my_tickets              # names every output table: my_tickets_reduced, ...
  row_id: ticket_id             # a stable identifier column that already exists

source:
  type: spark_table
  table: my_catalog.my_schema.tickets

processing:
  failure_mode: quarantine_row  # the default, and the one this runbook assumes

destination:
  type: delta_table
  catalog: my_catalog
  schema: my_reduced            # NOT the same schema as the source
  mode: errorifexists           # refuses to touch an existing table

columns:
  description:                  # one block per column you want reduced
    parser: plain_text          # or `transcript` for speaker-prefixed text
    entities: [PERSON, EMAIL, PHONE]
    # REQUIRED for PERSON. The project default is `deterministic_only`, which finds
    # EMAIL and PHONE and cannot find names — with no warning, because listing an
    # entity does not make a provider capable of it. Needs the `presidio` extra and
    # the spaCy models.
    provider_chain: deterministic_presidio
    output_column: description_pii_redacted
    language:
      mode: detect              # needs the `language` extra; else `static` + static_language
```

Four things the config decides for you. Three of them refuse the run rather than do
something surprising; the first silently decides what a failed field contains, which
is why it is listed first:

- **`failure_mode` decides what a failed field contains**, and it is the one setting
  that can invert everything below. `quarantine_row` (the default) writes null;
  `preserve_original_and_record_error` writes **the raw source text** into the column
  named "reduced". It is a supported opt-in (ADR-0023), it can be set at project,
  dataset or column level, and an inherited config may already have it. Check it
  before a real run.
- **Entity scope is never inferred.** List `entities:` explicitly; the tool will not
  guess that a ticket number is sensitive or that it is not (`AGENTS.md` rule 7).
  **And listing an entity does not make anything detect it.** `entities:` declares
  scope; `provider_chain:` decides capability, and nothing checks the two against
  each other. `PERSON` under the default `deterministic_only` chain is silently
  undetected — measured recall 0.000. After your first run, confirm names are
  actually gone before you trust the output.
- **Output columns never overwrite source columns** unless you deliberately configure
  a replacement workflow (rule 4).
- **A run cannot write over the table it reads.** Give the destination a different
  schema.

Validate the config before you touch the workspace — this needs no session:

```bash
python -c "from pathlib import Path; from pii_reduction.config import load_resolved_dataset; load_resolved_dataset(Path('configs'), 'my_tickets')"
```

## 3. Run it

```bash
pii-reduction-databricks run my_tickets --configs configs
```

Useful overrides, none of which require editing the file: `--source-table`,
`--destination-prefix`, `--mode`, `--reduced-only-prefix`, `--profile`.

Start small. There is no `--limit`: a sampling flag that silently reduced part of a
table is the kind of half-done output this project refuses to make look like success.

If you make a filtered copy to try it on, that copy **is** production text: create it
in the same governed schema as the source, never in a scratch or personal one, and
drop it when you are done. A convenience copy in a widely-granted schema is the
easiest way to undo every control below.

## 4. Where things land

Under `destination.catalog` + `destination.schema`, named from `dataset.name`:

| table | contents | who should read it |
|---|---|---|
| `<dataset>_reduced` | every source column **plus** the reduced columns | same audience as the raw table |
| `<dataset>_pii_audit` | one row per detection: entity type, offsets, score, provider, language | privacy/governance |
| `<dataset>_run_metrics` | one row: run id, config hash, counts, provenance | operations |

The metrics table's **columns depend on the run**: provider versions and dropped
labels flatten to one column each (`run_provider_versions_<provider>`,
`run_dropped_labels_<label>`), so two runs with different providers produce different
schemas. That is fine for `errorifexists` and `overwrite`, and it is why an `append`
rerun onto an older metrics table needs schema evolution enabled (`docs/07`).

**The reduced table still contains the original text.** That is the non-destructive
default (rule 4), and it means `<dataset>_reduced` must be governed like the source,
not handed to a wider audience. For that audience write the projection instead:

```bash
pii-reduction-databricks run my_tickets --reduced-only-prefix my_catalog.my_shared
```

That writes `my_tickets_reduced_only` — the frame **without** the configured raw text
columns — into a schema you can grant separately (ADR-0024). Two things it is not: it
is not anonymous (undetected entities survive — the leakage rate is the measure of
how many), and it says nothing about columns you did not configure. Whether those
carry PII is your scope declaration, not the tool's.

The audit table discloses **span offsets and lengths**, which leak the shape of a
value even though it never stores the value itself. Govern it like reduced output,
not like ordinary telemetry (`docs/09`).

## 5. Reading the result

```sql
SELECT pii_status, count(*) FROM my_catalog.my_reduced.my_tickets_reduced GROUP BY 1;
```

- `pii_status` is per row. Under the default `failure_mode: quarantine_row` a failed
  field is **null**, not raw text (ADR-0023), so a reduction that could not be
  completed never passes the original through under a column named "reduced". Under
  the `preserve_original_and_record_error` opt-in it holds the raw text instead and
  the row is `partial_failure` — verify which mode your config resolves to before
  you rely on either sentence.
- The command **exits 1** when any field failed, so a scheduler sees a partial run as
  a failure. **Exit 2** means the run could not be completed — usually before
  anything was written, but a write that fails part-way through also lands here, so
  check which of the tables exist rather than assuming none do.
- `<dataset>_run_metrics` carries the run's provenance under flat, prefixed column
  names — `run_config_hash`, `run_source_version`, `run_language_detector_version`,
  `run_rows_read` — so a result can be traced to the exact configuration that
  produced it. (Flat rather than dotted so no SQL query needs backticks.) The
  per-provider versions flatten one column *per provider*,
  `run_provider_versions_<provider>`, and are absent entirely when nothing was
  configured — so select the table's columns before writing a query against them.

## 6. Files in a Unity Catalog volume

A volume file needs **no new adapter** — a volume path is a filesystem path, so the
ordinary CSV source reads it:

```yaml
source:
  type: csv
  path: /Volumes/my_catalog/my_schema/my_volume/tickets.csv
```

**This works where the volume is mounted, which is on Databricks compute** — a
notebook or a job. A local Databricks Connect client has no `/Volumes` on its own
filesystem, so the same config run from your laptop will not find the file. The
`databricks`-marked test `tests/test_databricks_parity.py::TestVolumeIngestion`
asserts the read and skips with that explanation when the mount is absent.

**Status: unverified.** Skipped as expected on the 2026-08-20 workspace run, but note
what that proves: the guard is a local `Path("/Volumes").exists()` check, so it would
skip identically with no workspace at all. The server-side-mount explanation below is
still untested. To close it,
run the `databricks`-marked tests where a volume is actually mounted — that means on
Databricks compute, since the mount is server-side:

```bash
pytest -m databricks tests/test_databricks_parity.py
```

The module's session fixture takes any of the three routes in §1b, and prefers a
session that already exists, so it works from a notebook without a CLI profile. Run
from a local client the volume assertion skips with "no /Volumes mount" while the
parity tests still run.

**These tests create and drop objects in whatever workspace the session belongs to.**
They use one throwaway `catalog.schema` and drop it afterwards, refusing to adopt one
that already exists — but name it yourself with `PII_PARITY_SCHEMA` before running,
and on Databricks compute that variable is **required**: there is no credential to
withhold there, so naming the schema is the only deliberate gesture left.

## 7. Rules for real data

The tooling is built so that real data can flow through it without any of it landing
somewhere it should not. Those properties are only true if you do not work around
them:

1. **Nothing real enters the repository, or anything committed alongside it.** Not
   as a fixture, not as a test case, not pasted into an issue, a doc, a commit
   message, a CI log, or an agent session transcript under `.claude/`. If you need a case to reproduce
   a bug, describe its *shape* — "a transcript whose speaker prefix is a person's
   name" — and generate a synthetic example.
2. **Logs are metadata only.** The pipeline logs dataset, row id, column, counts,
   categories and timings, never text or detected values (`AGENTS.md` rule 8) —
   `observability/logging.py` filters through an allowlist, so an unlisted field is
   dropped rather than printed. Span offsets are **not** logged; they are disclosed
   by the audit table (§4). Two notes on `observability.log_raw_text`: the loader
   refuses it unless `project.environment` is `local`, and **nothing currently reads
   it**, so it is a guard rather than a working switch. Set `project.environment` to
   something other than `local` for workspace runs — otherwise that guard is inert
   for you.
3. **Errors carry a class, not a message — through the CLI.** Third-party
   exceptions can quote a cell value, and Databricks Connect errors carry the
   workspace URL; `pii-reduction-databricks` reduces both to an exception class
   before printing. That protection is the front door's, not the library's: the
   adapters wrap with `raise ... from error`, so calling `run_driver` bare in a
   **notebook cell** prints the whole chain — workspace URL and any quoted value
   included — into notebook output and its revision history. Call the CLI, or catch
   and print `type(error).__name__` yourself. Never add `print(text)` to debug; add
   a counter.
4. **The audit table is not a debugging copy of your data.** It stores spans, never
   surfaces. Two default-tier tests hold that: one asserts no known fixture email or
   phone appears anywhere in serialized audit rows, the other pins the column set as
   a literal, so adding a field that could carry a value has to be a deliberate edit
   with rule 8 in view. Grant and retain it accordingly: offsets and lengths disclose
   the shape of a value even though the value is absent, so it belongs with
   privacy/governance, on the same retention clock as the reduced output, not with
   ordinary telemetry.
5. **Reduced is not anonymous.** Treat every output as pseudonymous at best, and
   measure what got through: the leakage rate on your own data is unknown until you
   sample and look. The published numbers are measured on synthetic and public
   corpora, not on yours.
6. **Never render a frame in a notebook or job cell.** `display(df)`, `df.show()`
   and a bare `toPandas()` all persist source text into notebook output, notebook
   revision history and job-run output — durable copies governed differently from the
   table you were careful about. Inspect counts, not rows; if you must read text,
   read it in the table through SQL, under the grants that table carries.
7. **Overwriting does not erase.** `--mode overwrite` replaces the current version of
   a Delta table; earlier versions stay readable through time travel until `VACUUM`
   and the retention window pass. A run that lands the wrong thing in a
   broadly-granted schema is not undone by running it again correctly — fix the
   grants first, then deal with the history.
8. **If you use `reducer: pseudonymize`, the key is a re-identification secret.**
   `PII_PSEUDONYMIZATION_KEY` must come from a Databricks secret scope, never from a
   config file or a notebook cell. Its stability is the point — the same value maps
   to the same token, which is what makes the output joinable and also what makes the
   key worth stealing. Rotating it changes every token; the run metrics record a
   non-secret key digest, so a rotation is visible as a provenance change
   (ADR-0013, R2).
9. **This is not a compliance control.** It is an engineering accelerator; production
   use needs your own legal, privacy and model-risk review
   (`docs/00_PROJECT_CHARTER.md` non-goals).

## 8. When something goes wrong

Databricks failures are reported as `ClassName: CONDITION` — the condition is a
fixed Spark identifier carrying no data, and it is what tells a "table already
exists" rerun apart from a genuine fault. The message itself is deliberately never
shown: Connect messages can quote the workspace URL and an analysis error can quote a
value.

| symptom | cause | fix |
|---|---|---|
| `error: no Databricks credentials found` | no profile, no `DATABRICKS_HOST`+token, not on compute | set one of the three routes in §1b |
| `Databricks Connect is not installed` | credentials found, but running from a venv without the extra | use the venv from step 1 (not needed on Databricks compute, where the existing session is reused) |
| `source type 'spark_table' … run_driver` | ran `pii-reduction` instead of `pii-reduction-databricks` | use the Databricks front door |
| a pydantic `String should match pattern` on `table` | a bare or two-part name **in the dataset file** | use `catalog.schema.table` |
| `table name … must be fully qualified` | a bare or two-part name passed to `--source-table` | same, on the command line |
| `could not write … (AnalysisException: TABLE_OR_VIEW_ALREADY_EXISTS)` | a rerun against a destination whose `mode` is the default `errorifexists` | intended — choose `overwrite` deliberately, or write to a new schema |
| `prefix … must be catalog.schema` | `--destination-prefix` given one part or three | give exactly `catalog.schema` |
| `would write over the table it reads` | destination resolves to the source | give the destination its own schema |
| `no entities configured` | a column block without `entities:` | list them explicitly |
| exit 1, `fields_failed=N` | some fields could not be reduced | query `pii_status`; under the default `failure_mode` those values are null, not raw |
| most reduced values null, only short fields succeeding | language detection unavailable — the `language` extra is missing | install it, or switch the column to `mode: static` |
| emails and phones redacted, **names still present**, no error | the column resolved to the `deterministic_only` chain, or the spaCy models are missing | set `provider_chain: deterministic_presidio` and install the models (§1) |
| `ISOLATION_STARTUP_FAILURE` | the distributed path on a workspace whose serverless Python sandbox is broken | use the driver path; the incident is tracked in plan §8 F |

## 9. What this runbook does not cover

- **Scheduling.** `databricks.yml` and `resources/` hold an Asset Bundle and job
  skeleton, with a CLI-free path (UI or Jobs API) for workspaces where policy blocks
  the Databricks CLI — see `resources/README.md`. It has never been deployed, and it
  ships without a schedule on purpose.
- **The distributed path.** `distributed_frame` (`mapInPandas`) is shipped and
  unit-tested but has never executed on a workspace — see plan §8 F. The driver path
  is what this runbook uses, and it processes on the driver, so very large tables
  should be run in filtered batches until that changes.
- **Incremental/merge processing.** Every run reads the table it is pointed at.

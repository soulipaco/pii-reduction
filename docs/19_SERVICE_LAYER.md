# The service layer (rung 4)

A thin HTTP API over the engine: **build a validated dataset configuration, trigger a
run, read run metadata.** Decided in [ADR-0026](adr/0026-service-layer-is-a-thin-api.md);
positioned by [ADR-0025](adr/0025-databricks-is-the-primary-deployment-target.md),
whose ladder puts it above the engine, the runbook and the job.

It owns **no reduction logic**, and cannot: no module under `src/pii_reduction/service/`
may import `providers/`, `reducers/`, `parsers/`, `language/`, `entities/`,
`evaluation/`, `sources/`, `outputs/` or `synthetic/`, nor anything under
`processing/` except `pipeline`. It assembles configurations that the
configuration layer validates, and calls the same two entry points a person calls by
hand. A capability it needs that the engine lacks is a change to the engine.

## What it will not do, and why that is the design

**No endpoint accepts text, and none returns, streams, redirects to or vends a URL for
text.** Not source text, not reduced text, not a detected value. This is satisfied by
absence rather than by filtering — the request and response models have no field that
could carry any, and a test asserts that over every model by reflection. A filter can
be wrong; an absent field cannot.

Reduced text is included deliberately. Reduction is measured, not guaranteed: the
published leakage rate is 0.067 on the hybrid chain and 0.433 on the deterministic one
over the committed corpus, and on your own data it is unknown until you sample and
look. A surface that displays reduced text displays whatever leaked.

Six endpoint shapes are forbidden **by name**, because each will be proposed and each
looks reasonable:

| shape | why not |
|---|---|
| `GET /sources/{table}/preview` | "five rows so the user can pick columns" is Class B disclosure, and a caller-named table is a confused deputy besides |
| `POST /detect` / `POST /reduce` | leaks in both directions; in a query string it lands in every access log on the path |
| `GET /runs/{id}/failures` | returns relayed error messages. Return the category and the row id |
| `GET /runs/{id}/result` or a download link | the transport loophole — same disclosure, different pipe |
| `GET /runs/{id}/audit` | carries no values, but carries offsets and lengths, which `docs/09` governs at least as strictly as reduced output |
| `sample_reduced` on the status response | the one somebody adds the day before a demo |

The compact form: **the service may return numbers about text and names of things; it
may not return text, and it may not name a place the caller chose.**

`docs/09_SECURITY_PRIVACY_GOVERNANCE.md`, *Display surfaces, API responses, and
request payloads*, is the governing document. A side-by-side original/reduced view
over anything but Class A data is a governed change with seven conditions and an ADR,
not a UI task.

## Templates: the half of a configuration a caller may not choose

The service runs with **its own** credentials. A request that could name a
`catalog.schema.table` would therefore let a caller read a schema they cannot, and
land the output — which by default still carries the source columns — somewhere they
can. So the source and destination come from a server-side **template**, and so do the
three switches that move a privacy boundary rather than expressing a preference:

| switch | why it is server-side |
|---|---|
| `processing.failure_mode` | `preserve_original_and_record_error` is ADR-0023's raw-text pass-through: it writes source text into a column an operator governs as reduced |
| `processing.preserve_original` | `false` is the controlled replacement workflow `AGENTS.md` rule 4 requires a configuration to define explicitly |
| `destination.projection` | ADR-0024's grant boundary — `full` keeps the raw columns beside the reduced ones |

A template also declares the menu the caller *does* pick from: which columns, which
row-id columns, which entity labels, parsers, chains and reducers.

Templates live in `<configs>/service_templates.yaml`. The shipped one,
`synthetic_corpus`, is Class A throughout — it points at the committed synthetic
corpus and a local output directory, and it is what the service's own end-to-end test
runs. A Unity Catalog template is included commented out, because a real catalog,
schema and table are workspace values and this repository holds none.

**Column discovery is declared, not read.** The service never opens a source to find
out what columns it has: a preview endpoint is forbidden, and `sources/` exposes only
`load()`, which materialises the whole frame. A schema-only path would be a change to
the engine, and is deliberately not improvised in the service.

## Running it

```bash
pip install -e ".[service]"
pii-reduction-service --configs configs
```

Then, against the shipped Class A template:

```bash
curl -s localhost:8000/templates
```

```bash
curl -s -X POST localhost:8000/configs -H 'content-type: application/json' -d '{"template":"synthetic_corpus","dataset_name":"my_dataset","row_id":"document_id","columns":[{"column":"text","entities":["EMAIL","PHONE"]}],"save":true}'
```

```bash
curl -s -X POST localhost:8000/runs -H 'content-type: application/json' -d '{"dataset":"my_dataset","runtime":"local"}'
```

```bash
curl -s localhost:8000/runs
```

`POST /runs` answers `202` immediately with a `pending` record; poll `GET /runs/{id}`
for the state. Runs execute one at a time on a single worker thread, because two
reductions in one process would each build their own providers and NLP models.

### The Databricks runtime

```bash
pii-reduction-service --configs configs --databricks --profile <profile>
```

Adds a `databricks` runtime that executes the driver path (`run_driver`) — the same
one `pii-reduction-databricks run` uses, with the same authentication routes
(profile, `DATABRICKS_HOST` plus a token or service principal, or ambient credentials
on Databricks compute). It needs the `databricks` extra, which lives in its own
virtual environment (ADR-0006), so start the service from that environment.

Two failure modes, both answered at the point they occur rather than inside a run:
without the flag the runtime is not offered and asking for it answers `409`; **with**
the flag in an environment that lacks the extra, the service refuses to start and
prints the install instruction. The second check exists because the runtime module
imports fine without `databricks-connect` — the session is resolved lazily — so
without it the service would accept a run, fail it on the worker thread, and record a
bare error category with the instruction discarded.

No table, prefix or write mode is passed to `run_driver`: the dataset configuration
decides, which is what keeps rule 4 true at the last place it could be broken.

## Endpoints

| method | path | answers |
|---|---|---|
| `GET` | `/health` | version and the runtimes this process offers |
| `GET` | `/entities` | the entity labels a configuration may name, each with its taxonomy-default replacement and `detected_at_baseline` — `ADDRESS` is in the taxonomy and nothing detects it (ADR-0002). A project's `entities.yaml` may override a replacement; the run uses the override, this endpoint reports the default |
| `GET` | `/templates` | the menus, and whether each needs Databricks |
| `GET` | `/datasets` | configured dataset names |
| `GET` | `/datasets/{name}` | row id, types, columns, entities, chain, reducer, projection, per-column failure mode and preservation flag, config hash |
| `POST` | `/configs` | a validated dataset configuration as YAML, optionally saved |
| `POST` | `/runs` | `202` and a `pending` record |
| `GET` | `/runs` · `/runs/{id}` | run metadata, newest first |

A run record's `outputs` names the **server-chosen** destinations the run wrote —
the reduced artifact, the audit table and the metrics table. Those are
configuration-derived names, which `docs/09` permits under `destination`; they are
not places the caller chose, and no endpoint returns their contents. On a Unity
Catalog deployment they are `catalog.schema.table` strings, so a caller learns where
a run landed without necessarily holding a grant to read it.

Errors answer `{"error": {"category": ..., "message": ...}}`, including the
framework's own 404 and 405 — they are routed through the same envelope rather than
left as `{"detail": ...}`. The category is stable; a message is relayed only where
**this** layer or the configuration layer composed it. There is deliberately no
handler for `PiiReductionError` as a whole: that tree includes `DatabricksError`,
whose messages exist precisely because Databricks Connect quotes the workspace URL.
Everything else becomes `unexpected_<ClassName>` and nothing more — the same doctrine
`databricks/cli.py` applies.

That governs the **response**. Starlette re-raises after the handler runs, so an
unexpected exception's traceback still reaches the server's own log. That is the
operator's channel, not a caller's, and it is subject to the same `docs/09` rules as
any other log.

A schema violation answers `422` with the field path and the reason, and **not** with
the value that was sent: pydantic puts the rejected value in its error dicts and the
framework would serialize it, so the service installs its own handler. Names a caller
supplies — a template, a dataset, a runtime, an entity label — are pattern-bounded so
that an unknown one is refused by that handler rather than quoted back in a 404
message; the field path of an unexpected key is still echoed, which is a key name and
not a value. Debug mode is off, always
— a debug traceback in a response body is a display surface carrying whatever the
exception held.

## Two limits, stated rather than discovered

**No authentication.** Run locally it is a developer tool: the default bind is
`127.0.0.1`, and **any other bind is refused by the console script** unless
`--i-provide-authentication` is passed as well. Note the scope — it is `main()` that
refuses, so a hosting wrapper calling `create_app` directly never passes through it,
which is exactly why the platform's authentication is a *precondition* of hosting
rather than a bonus. With no auth the bind address is the entire control, so a warning
printed into a container log nobody reads would not be one — the acknowledgement is
explicit and the exit code is 2.

Hosted as a Databricks App, authentication is the platform's. **Authorization is a
separate question and this project has not verified the answer:** Apps authenticate
the end user, but data access defaults to the App's *service principal*, and
on-behalf-of-user authorization is a separate opt-in. That distinction matters here
because `docs/09`'s conditions for a Class B display surface require reading under
the end user's identity, and because the whole server-side-template design exists
precisely because the service runs with credentials that are not the caller's.

**Run state is in memory.** A process-local store is honest for v1 and wrong for a
multi-replica App; a restart forgets. The durable record of a run is the
`<dataset>_run_metrics` artifact the engine already writes, which is where a status
view should eventually read from. Persisting service-side state is a named later
increment.

## Verified, by running it

Two paths, both executed rather than reasoned about — which is the argument ADR-0026
makes for choosing an API over an App in the first place.

**The local path, over real HTTP** (2026-08-21). The service was started through its
own console entry point on `127.0.0.1`, then driven with an ordinary HTTP client:
`POST /configs` built and saved a dataset from the shipped Class A template,
`POST /runs` answered `202 pending`, and polling `GET /runs/{id}` reached `succeeded`
with 102 documents read and written, 102 entities reduced, zero fields failed — the
`deterministic_only` chain, so the 102 are the corpus's EMAIL and PHONE occurrences,
the same ones the referential-consistency metric counts. The
refusal paths were exercised in the same session: an unknown dataset (404 with the
menu), an unavailable runtime (409), a second save under the same name (400), an
off-menu column (400), a request carrying `source` or `projection` (422, "Extra
inputs are not permitted"), and a malformed dataset name (422 whose body does not
contain the name). The default test tier repeats all of it over a real ASGI
transport.

**The Databricks path, on the workspace** (2026-08-21). A 25-row synthetic table was
staged in Unity Catalog from the head of the committed corpus — a different slice and
a different chain from session 10's 25-row Volumes run, so the two sets of counts are
not expected to match — a workspace-pointing template was
written **outside the repository** (a real catalog and schema must never be
committed), and the service was started from the `databricks`-extra virtual
environment with `--databricks`. `GET /health` reported both runtimes;
`GET /templates` reported `requires_databricks: true`; `POST /runs` with
`runtime: databricks` answered `202`, and the status view reached `succeeded` in
about 22 seconds.

What the workspace held afterwards, read back and checked:

| claim | what was found |
|---|---|
| rows | 25 read, 25 written, every row `pii_status = success` |
| non-destructive (rule 4) | `text` still present beside `text_pii_redacted`, plus `pii_run_id` and `pii_status` |
| detection | the audit table recorded PERSON 22 / EMAIL 13 / PHONE 12 — the hybrid chain, chosen through the API |
| audit is metadata-only | the audit table's column set is exactly `AUDIT_COLUMNS` — no values. Note it carries `start`, `end` and `score`, so it stays governed like reduced output (`docs/09`), and no endpoint returns it |
| reduction happened | 23 of 25 rows carry at least one placeholder |
| provenance | `run_source_version = delta_v0`, `run_pipeline_version = 0.1.0`, real library **and** model versions per provider, `run_threshold_calibration` naming the locked review |
| the status view agrees with the engine | the `config_hash` the API returned equals `run_config_hash` in the Delta metrics table |

The staged table and the three tables the run wrote were dropped afterwards; the
schema was left as it was found.

**Not yet done, and recorded as such:** this service has never been *hosted* — no
Databricks App has been created, and `bundle deploy` remains blocked by the Databricks
CLI's expired Terraform signing key. Running the API from a terminal against the
workspace and hosting it inside the workspace are different claims.

## Hosting it as a Databricks App

ADR-0026 decides that a Databricks App is how this gets hosted, not a second surface
to build. Databricks Apps run an ASGI application directly, so the App's entry point
is a small wrapper that calls `pii_reduction.service.api.create_app` with a
`RunStore` holding the Databricks runtime — `create_app` takes a configuration
directory and a store, so it is not itself a zero-argument ASGI factory. A UI, if one
is ever built, is a client of these endpoints rather than a reimplementation of them.

If that increment instead points the App's start command at the console script, the
command must pass `--i-provide-authentication`: the script refuses a non-loopback
bind, and a container is where that refusal is least fun to debug. Passing it there
is honest — on an App, the platform *is* the authentication.

**This has not been done**: `bundle deploy` is blocked by
the Databricks CLI's expired Terraform signing key (session 10), and no App has been
created. That is an environment blocker with a named remedy, recorded here so the
distance between "decided" and "deployed" stays visible.

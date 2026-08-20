# The service layer (rung 4)

A thin HTTP API over the engine: **build a validated dataset configuration, trigger a
run, read run metadata.** Decided in [ADR-0026](adr/0026-service-layer-is-a-thin-api.md);
positioned by [ADR-0025](adr/0025-databricks-is-the-primary-deployment-target.md),
whose ladder puts it above the engine, the runbook and the job.

It owns **no reduction logic**, and cannot: no module under `src/pii_reduction/service/`
may import `providers/`, `reducers/`, `parsers/`, `language/`, `entities/`,
`evaluation/`, `sources/` or `outputs/`. It assembles configurations that the
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

**No authentication.** Hosted as a Databricks App, authentication and Unity Catalog
authorization are the platform's, applied as the end user. Run locally it is a
developer tool: the default bind is `127.0.0.1`, and any other bind needs `--host`
explicitly and prints a warning, because with no auth the bind address is the entire
control. Exposing this on a network without something in front of it is a deployment
error.

**Run state is in memory.** A process-local store is honest for v1 and wrong for a
multi-replica App; a restart forgets. The durable record of a run is the
`<dataset>_run_metrics` artifact the engine already writes, which is where a status
view should eventually read from. Persisting service-side state is a named later
increment.

## Hosting it as a Databricks App

ADR-0026 decides that a Databricks App is how this gets hosted, not a second surface
to build. Databricks Apps run an ASGI application directly, so the App's entry point
is a small wrapper that calls `pii_reduction.service.api.create_app` with a
`RunStore` holding the Databricks runtime — `create_app` takes a configuration
directory and a store, so it is not itself a zero-argument ASGI factory. A UI, if one
is ever built, is a client of these endpoints rather than a reimplementation of them. **This has not been done**: `bundle deploy` is blocked by
the Databricks CLI's expired Terraform signing key (session 10), and no App has been
created. That is an environment blocker with a named remedy, recorded here so the
distance between "decided" and "deployed" stays visible.

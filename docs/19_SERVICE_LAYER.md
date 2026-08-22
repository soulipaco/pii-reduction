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
row-id columns, which entity labels, parsers, chains, reducers — and, since ADR-0034,
which **parser options**.

### Parser options: the accuracy knobs, offered from the menu (ADR-0034)

The two settings most likely to change a result on somebody's real column are
`split_lines` (ADR-0016) and `preserve_prefix` (ADR-0032), and until ADR-0034 neither
was reachable through the API. They are now, under one rule:

> A caller may choose anything whose worst outcome is a **measurable quality result**.
> A caller may never choose anything whose worst outcome is data in a place, or raw
> text in a column, that the operator did not sanction.

The five switches in the table above are the second kind and stay server-side. Parser
options are the first kind, and are offered with three constraints:

1. **A selection, never a free-form value.** `parser_options` is typed
   `dict[str, bool]`, so a delimiter, a path or a policy name is a 422 before the
   builder is entered. Only the booleans in `service/knobs.py` are offerable;
   every other parser option stays template-side.
2. **The template opts in, per option**, and the default is an empty menu — the
   operator is the one who knows whether their text wraps mid-sentence.
3. **A bad combination is refused at build time.** `parser_options` requires `parser`
   in the same request, and the option must be one that parser accepts, so
   `split_lines` on a `transcript` column is a `400` here rather than a `201` followed
   by a failed run.

`GET /templates` reports which parser accepts each offered option, so a client can
attach a control to the right parser instead of guessing, and `GET /datasets/{name}`
reports what a saved dataset resolved to.

**Neither option is an improvement, and a client must not present it as one.** Both
change what the model *sees*: ADR-0032 measured `preserve_prefix` recovering the
work-note author on one corpus while inventing a false positive on another, and §8's
Q2 measured the same of `split_lines` twice. The honest framing is "this matches the
shape of my text".

**Thresholds are deliberately not offered**, even though they are quality knobs: they
were calibrated on a held-out split and locked, and a slider on a calibrated constant
invites someone to move a published number by hand. ADR-0034 records the shape that
would work — named server-side profiles, each with its own measurement.

Templates live in `<configs>/service_templates.yaml`. The shipped one,
`synthetic_corpus`, is Class A throughout — it points at the committed synthetic
corpus and a local output directory, and it is what the service's own end-to-end test
runs. A Unity Catalog template is included commented out, because a real catalog,
schema and table are workspace values and this repository holds none.

**Column discovery is declared, not read.** The service never opens a source to find
out what columns it has. A preview endpoint is forbidden (ADR-0026), and although the
**engine can now answer the question** — `SourceAdapter.schema()` reads column names
without reading a row (ADR-0031) — `service/` may not import `sources/`. Consuming it
needs a sanctioned relay, and there is a second reason to take that slowly; see *Why
the column menu is hand-written* below.

## Running it

```bash
pip install -e ".[service]"
pii-reduction-service --configs configs
```

Add `--run-journal` for anything longer-lived than a terminal session, so run history
survives a restart instead of 404-ing (ADR-0030). Put the file **outside the
repository**:

```bash
pii-reduction-service --configs configs --run-journal ~/.pii-reduction/runs.jsonl
```

Then, against the shipped Class A template:

```bash
curl -s localhost:8000/templates
```

```bash
curl -s -X POST localhost:8000/configs -H 'content-type: application/json' -d '{"template":"synthetic_corpus","dataset_name":"my_dataset","row_id":"document_id","columns":[{"column":"text","entities":["EMAIL","PHONE"]}],"save":true}'
```

With a parser option (ADR-0034) — note that naming the option means naming the parser
it belongs to:

```bash
curl -s -X POST localhost:8000/configs -H 'content-type: application/json' -d '{"template":"synthetic_corpus","dataset_name":"my_dataset","row_id":"document_id","columns":[{"column":"text","entities":["EMAIL","PHONE"],"parser":"plain_text","parser_options":{"split_lines":true}}],"save":true}'
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

## The control panel (ADR-0035)

`pii-reduction-service` serves a **control panel** at `/` and `/ui`: pick a template,
choose columns, entities, parser, options, chain and reduction, preview the generated
YAML, save it, trigger a run and watch it finish. It is the same page locally and on a
Databricks App, because it is one static file compiled into the wheel — no build step,
no asset server, no environment difference.

**It is a client, in the sense ADR-0026 meant.** It holds no logic the API does not, it
computes nothing, and every value it shows it fetched from an endpoint a `curl` user can
call. Since no endpoint returns text, **the page cannot display data even by mistake**.

Five properties, each pinned by a test in `tests/test_service_ui.py`:

| property | why |
|---|---|
| one file, no build step | a Databricks App runs a Python process — no npm, no bundler |
| no external request | no CDN, no font host. It renders fully with zero egress, and no third-party script runs on an origin that can call this API |
| byte-identical for every caller | read once at startup, served verbatim — a page that is *assembled* could assemble a caller's input into itself |
| `textContent`, never `innerHTML` | a configuration value is not markup |
| no client-side storage | a shared browser cannot leak one operator's dataset names to the next person at it |

### A template may offer a directory, so an uploaded file becomes a run (ADR-0036)

Setting `select_file: true` makes a template's `source.path` a **directory**, and the
caller names one file inside it:

```yaml
uc_volume_inbox:
  source:
    type: csv
    path: /Volumes/<catalog>/<schema>/<volume>/inbox/
  select_file: true
```

`GET /templates/{name}/files` lists what is currently there — **names only, one level
deep, filtered to what the source type can read**, and it never opens a file.
`POST /configs` takes `source_file`, and the built configuration records the resolved
absolute path, so `pii-reduction run` reads it later with no memory of the template.

**The caller still cannot name a source, and the service still never receives the
file.** The operator chose the directory; the caller chose among its contents — the
same shape as picking a column from a declared menu. There is no multipart endpoint and
no upload buffer: `source_file` is a *name*, so the reflection test proving no request
model can carry content is untouched.

Two defences on that name, because it is the only caller string in this service that
becomes part of a filesystem path:

1. **it is a name** — no separator, no `..`, no leading dot, bounded and
   pattern-checked, so a traversal attempt is a 422 that does not echo it;
2. **the joined path is resolved and must land inside the declared directory** — which
   is what catches a *symlink*, the one route a pattern cannot see.

**Filenames become visible to everyone who may use that template.** That is the
disclosure this adds, it is `select_file`-gated per template so it is the operator's
decision, and it is worth saying plainly: an inbox is a shared surface, so do not name
files after individuals.

**When staging for an App, remove or repoint the shipped `corpus_inbox` template.**
The staging step copies the whole `configs/` tree, and that template points at
`data/inbox/` and `data/output/` — *relative to the container's working directory*. If
anyone got a file where the picker could see it, the run would write source and reduced
text to ephemeral container-local disk, outside Unity Catalog. That is exactly the
objection ADR-0036 uses to refuse multipart upload, so shipping it unremarked would be
arguing both sides. The template says so in place, and it is marked local-development
only.

**Unverified: whether a Databricks App can see `/Volumes`.** The runbook's verified
route for volume ingestion is a serverless job (`docs/18` §6), and the App's runtime is
`local`. The mechanism is path-based, so it works wherever the process can see the
path — check with `ls /Volumes/...` from the App before relying on it.

### What a hosted panel shows every principal the platform admits

Worth stating before you host it, because the *audience* changes even though the
disclosure does not.

Opening the page fetches the run history unprompted, and a selected run renders its
`summary.outputs` — **the destination path of every artifact it wrote**. On a workspace
that means a Volume path or table name, which names the catalog and schema. That is
permitted: `docs/09` lists `destination` as the one key under which a
configuration-derived file or table name may appear on a display surface, and a `curl`
user could already read the same thing.

What changes is that they had to know to ask, and a panel makes it the first screen.
Two consequences for an operator:

- **Scope App access to people who may know those names.** The App authorizes as its
  own service principal (measured — see below), so Unity Catalog grants on those
  objects do **not** filter this list.
- **The history is process-wide, not per-user**, and with `--run-journal` it spans
  restarts. Everyone admitted sees every run anyone triggered.
- **The same applies to an inbox listing** (ADR-0036): a `select_file` template shows
  its directory's filenames to everyone who may use it.

**Turn it off with `--no-ui`.** The API is unchanged in that mode; an HTML surface is a
decision an operator may decline, and this is one of the reasons they might.

```bash
pii-reduction-service --configs configs            # panel at http://127.0.0.1:8000/
pii-reduction-service --configs configs --no-ui    # API only
```

### Two other surfaces, and how they differ

`GET /docs` is FastAPI's generated API explorer, built from the same models that
validate the requests, and `GET /openapi.json` is the machine-readable contract behind
it. Both are useful and neither replaces the panel:

- `/docs` is **complete** — every endpoint, every field — and is the right place to
  learn the API or try a call by hand. It **loads Swagger UI from a CDN**, so it is
  blank on a deployment with no egress, and it runs third-party JavaScript on an origin
  that can call this API.
- `/ui` is **partial** by design — the things an operator actually does — and needs
  nothing but this process.

### Editing the page

It is read **once at startup**, like the configuration, so a change needs a restart. A
per-request read would turn a deleted or unreadable file into a 500 on somebody's first
visit rather than a service that refuses to start.

## Endpoints

| method | path | answers |
|---|---|---|
| `GET` | `/health` | version and the runtimes this process offers |
| `GET` | `/entities` | the entity labels a configuration may name, each with its taxonomy-default replacement and `detected_at_baseline` — `ADDRESS` is in the taxonomy and nothing detects it (ADR-0002). A project's `entities.yaml` may override a replacement; the run uses the override, this endpoint reports the default |
| `GET` | `/templates/{name}/files` | file **names** a `select_file` template currently offers (ADR-0036) — one level, filtered to the source type, never opened |
| `GET` | `/templates` | the menus — columns, row ids, entities, parsers, chains, reducers, and which parser accepts each offered parser option (ADR-0034) — plus whether the template needs Databricks |
| `GET` | `/datasets` | configured dataset names |
| `GET` | `/datasets/{name}` | row id, types, columns, entities, chain, reducer, projection, per-column failure mode, preservation flag and resolved parser options, config hash |
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
message. Debug mode is off, always — a debug traceback in a response body is a display
surface carrying whatever the exception held.

> **The field path is caller-supplied too, and until session 14 it was echoed raw.**
> This paragraph used to say the path of an unexpected key "is a key name and not a
> value". That was wrong: an unknown key is an **unbounded string a caller chose**, and
> pydantic puts a rejected mapping key into the error location *before* the constraint
> that rejected it applies. ADR-0034's `parser_options` made that a place callers are
> meant to send keys — turning "somebody sent junk" into "a client mapped a column's
> content into an options map" — and the privacy audit demonstrated a 65-character
> string of synthetic PII coming back verbatim in a 422 body. The handler now renders
> only path segments that are integers or declared field names, substituting `<key>`
> for anything else, which also closes the pre-existing `extra="forbid"` route. Both
> directions are pinned by test.

### Why the column menu is hand-written

A template lists the columns a caller may choose from, and an operator writes that list
by hand. The engine can now answer the same question — `SourceAdapter.schema()`
(ADR-0031) reads a source's column names without reading a row, and
`pii-reduction describe <dataset>` prints them — but **the service does not consume
it**, and that is a boundary rather than an omission.

`service/` may not import `sources/`: one of the four static guards that make ADR-0026's
rung rule code rather than prose. Routing schema through a relay is a design decision,
not a wiring change, and there is a second reason to take it slowly: an endpoint that
returned *every* column of a configured source would let a caller enumerate the columns
a template deliberately withheld, which is the disclosure the server-side-template
design exists to prevent. The useful shape is probably an **intersection** — "of the
columns this template offers, here are the ones the source actually has" — which
validates a template without enumerating a schema. Until then, `describe` is the
operator's tool and the template is still written by hand.

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

**Run state survives a restart only if you ask for it, and never survives a second
replica.** By default the store is process-local, which is honest for a run from a
terminal. `--run-journal PATH` appends every state transition to a JSON-lines file and
loads it at startup, so the first thing a hosted user does — `POST /runs`, then poll
`GET /runs/{id}` — keeps answering after a restart instead of 404-ing a run that
really happened.

Three properties of it are deliberate:

- **Metadata only, by construction.** The journal serializes `RunRecord`, the same
  model the API returns, so the reflection guard that proves no response carries text
  proves it of the file. A test also asserts the written bytes hold exactly that
  model's fields and nothing more.
- **The path is the operator's, never a caller's.** Same doctrine as the templates: a
  request that could name a path would make the service write wherever *its*
  credentials reach. No request model has a path field, and a test enforces it.
- **An interrupted run is reported as interrupted, not as running.** A record loaded
  as `pending` or `running` belongs to a process that no longer exists, so nothing
  will ever advance it — and `running` is the one state a caller waits on. Recovery
  rewrites it to `failed` with category `interrupted`. It does **not** guess whether
  the reduction wrote anything first: that is what the engine's
  `<dataset>_run_metrics` artifact is for, and the two remain different claims.

**Single writer.** Two replicas appending to one file would interleave partial writes.
The journal refuses any history with **a gap in the middle** rather than serving part of
one; a truncated *final* record — what a crash mid-append leaves — is dropped with a
warning and the file is repaired, so the fragment cannot be welded onto the next write.
A hosted deployment stays **single-replica** until something better exists: a
constraint, stated here rather than discovered.

**Three costs, stated because they are real** (ADR-0030 carries the reasoning):

- **A lost terminal write misreports a success.** If the fsync of the final transition
  fails, the file ends at `running` and the next process says `failed`/`interrupted` for
  a run that succeeded. The reconciliation is `<dataset>_run_metrics`, which is the
  argument for keeping the two records rather than against it.
- **fsync happens under the store's lock**, so `GET /runs` blocks for the flush. Three
  transitions per run makes that invisible on local disk. On a Volumes/FUSE path — which
  is what hosting intends — fsync latency is tens to hundreds of milliseconds and every
  status poll stalls behind it. Measure before hosting at volume.
- **Nothing bounds growth.** Every run ever submitted is retained in memory and on disk,
  startup reads the whole file, and `GET /runs` is unpaginated. **Rotate the file**; a
  missing journal is an empty history, so rotation is safe and needs no downtime.

Write the journal **outside the repository**. On the Databricks path
`RunSummary.outputs` holds real `catalog.schema.table` names, which must never be
committed; `.gitignore` carries `*.jsonl` as a backstop rather than a licence.

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

**A restart, over real HTTP** (2026-08-22, session 12). The console script was
started with `--run-journal`, `POST /runs` answered `202 pending`, polling reached
`succeeded` with 102 rows read — and then **the process was killed and a second one
started over the same journal**. `GET /runs/{id}` answered **200 `succeeded`** with the
same row count and the same `config_hash`, where without the journal it is a 404;
`GET /runs` returned the history. The journal held exactly three lines,
`pending → running → succeeded`, in order.

The interrupted path was driven the same way, which is the half that matters more: a
run was submitted and the process **killed mid-run**, leaving the journal ending at
`running`. The next process answered **200 `failed` / `interrupted`** — not `running`,
which would have been a lie about work nobody was doing.

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

**As of session 11, and superseded below:** the service had never been *hosted* — no
Databricks App existed, and `bundle deploy` was blocked by the Databricks CLI's expired
Terraform signing key, which was recorded as the reason. Running the API from a
terminal against the workspace and hosting it inside the workspace are different
claims, and only the first had been made. **Session 12 made the second** — see
*It is hosted* below, including why the blocker never applied to Apps.

## Hosting it as a Databricks App

ADR-0026 decides that a Databricks App is how this gets hosted, not a second surface
to build. Databricks Apps run an ASGI application directly, so the App's entry point
is a small wrapper that calls `pii_reduction.service.api.create_app` with a
`RunStore` holding the Databricks runtime — `create_app` takes a configuration
directory and a store, so it is not itself a zero-argument ASGI factory. A UI is a
client of these endpoints rather than a reimplementation of them — and since ADR-0035
one ships with the package, served by the same process (see *The control panel*
above).

### It is hosted (2026-08-22, session 12)

**Done, and the blocker was never a blocker.** Two sessions recorded hosting as
blocked by the Databricks CLI's expired Terraform signing key. That bug is specific to
`bundle deploy`; **Apps have their own deployment path and need no bundle at all**:

```bash
databricks apps create pii-reduction-service --no-compute
databricks workspace import-dir <staged-dir> /Workspace/Users/<you>/pii-reduction-app
databricks apps start  pii-reduction-service
databricks apps deploy pii-reduction-service \
  --source-code-path /Workspace/Users/<you>/pii-reduction-app --mode SNAPSHOT
```

The staged directory holds four things: the built wheel, a `requirements.txt` naming
it (`./pii_reduction-<version>-py3-none-any.whl[service]`), the `configs/` tree, and an
`app.yaml` whose `command` is the console script. The deployment reported
`SUCCEEDED — App started successfully`, and `apps get` reports `compute: ACTIVE`,
`app: RUNNING`.

The start command points at the console script rather than a wrapper, so it passes
`--i-provide-authentication` — the script refuses a non-loopback bind and an App must
bind `0.0.0.0`. That is honest here rather than a workaround: on an App the platform
*is* the authentication, which the next section establishes by measurement rather than
by assumption.

**Driven over real HTTPS through the App proxy**, authenticated with the SDK's own
credential resolution:

| request | answer |
|---|---|
| `GET /health` | 200, version, `runtimes: ['local']` |
| `GET /entities` | 200, the four taxonomy labels |
| `GET /templates` | 200, the shipped Class A template *(one, as of session 12 — `corpus_inbox` was added in session 14; this row records what that run saw)* |
| `GET /datasets` | 200, the three configured datasets |
| `GET /runs` | 200, empty history |
| `POST /runs` carrying a `source` field | **422 `invalid_body`** — the guard is live |
| `POST /runs` naming an unknown dataset | 404 with the menu (bounded name — see below) |

Two facts the deployment carries that are not defects but are limits:

- **`runtimes` is `['local']`.** The App installs the `service` extra, not
  `databricks`, so the hosted process cannot trigger a driver-path run. Adding it means
  a larger image and a decision about which credentials that run uses — see the identity
  finding below, because those are the same question.
- **The run journal is on the container's own disk** (`/tmp`), so it survives a restart
  of the process and **not** a redeploy. A Volume path is the next step, and the fsync
  cost noted above is the thing to measure before taking it.

### What the platform actually does about identity — measured, not assumed

Pickup item 3, and the answer confirms the concern rather than dissolving it. Read
straight off the created App:

```text
service_principal_id            present   (created automatically with the App)
service_principal_client_id     present
user_api_scopes                 None
effective_user_api_scopes       ['iam.access-control:read', 'iam.current-user:read']
```

**The App authenticates the end user, and authorizes data access as its own service
principal.** The default on-behalf-of-user scopes are *identity-only* — they let the
app learn who is calling and read access control, and they carry **no data scope** at
all: no SQL, no files, no catalog. On-behalf-of-user access to data is an explicit
opt-in that adds scopes to `user_api_scopes`, and nothing here has done that.

Three consequences, all of which were previously stated as expectations and are now
facts:

1. **`docs/09`'s condition for a Class B display surface — "read under the end user's
   identity" — is not satisfied by hosting**, and would not be satisfied by hosting
   plus a UI. It needs the opt-in, and then it needs the run path to actually use the
   user's token rather than the service principal's.
2. **The server-side-template design is load-bearing rather than cautious.** A caller
   who could name a `catalog.schema.table` would make the service principal read it —
   the confused deputy ADR-0026 rule 4 exists to prevent — and the identity model above
   is exactly why that is true in the deployed shape, not only in principle.
3. **Whoever grants this App data access is granting it to the service principal**, so
   the grant is the security boundary. Grant it the reduced-only projection's
   destination (ADR-0024) rather than a raw source wherever that split is available.

### The 404 that names a dataset is deliberate

`POST /runs` with an unknown but **well-formed** dataset name answers 404 quoting the
name and listing the menu. That is the designed behaviour, not a leak: the name matched
`DATASET_NAME_PATTERN` before it reached the catalog, so it is bounded, it is the
caller's own string, and the menu is what `GET /datasets` returns to the same caller
anyway. An **unbounded** path segment takes the other route — a 422 that echoes
nothing — and `test_a_malformed_run_id_never_reaches_the_404_message` pins the
distinction.

### Its current state: stopped, and recoverable

**The App exists and its compute is stopped** (2026-08-22). An App holds compute for as
long as it runs, and the deployment had already proved what it was created to prove, so
it was stopped rather than left burning:

```bash
databricks apps stop pii-reduction-service     # compute STOPPED, app UNAVAILABLE
```

**Stopping loses nothing.** Verified after the stop: the App object survives, its
`SUCCEEDED` SNAPSHOT deployment is retained, and the staged source is still at
`/Workspace/Users/<you>/pii-reduction-app` (four entries — wheel, `requirements.txt`,
`app.yaml`, `configs/`). Bringing it back is:

```bash
databricks apps start  pii-reduction-service
databricks apps deploy pii-reduction-service   --source-code-path /Workspace/Users/<you>/pii-reduction-app --mode SNAPSHOT
```

`databricks apps delete pii-reduction-service` removes it **and its service
principal**, which is the one action that would need the whole sequence repeating.

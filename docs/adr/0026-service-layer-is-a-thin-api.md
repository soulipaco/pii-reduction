# ADR-0026: the service layer is a thin HTTP API, and a Databricks App is how it gets hosted

**Status:** accepted · **Extended by [ADR-0034](0034-what-a-caller-may-choose.md)** (which knobs a caller may move) and **[ADR-0035](0035-the-control-panel-ships-with-the-service.md)** (a client now ships with it) · **Date:** 2026-08-21 · **Session:** 11

## Context

ADR-0025 records the platform ladder and names rung 4 — "service layer (Databricks
App / API: pick a table, choose columns, run)" — with a slash in it. The slash was
honest at the time: the owner's goal was stated as "a Databricks App or an API", and
nothing below rung 4 existed yet to choose from. Ten sessions later everything below
it exists and is verified on the workspace (`docs/14_IMPLEMENTATION_PLAN.md` §8's
evidence table), so the slash has to become a decision — two surfaces built to the
same brief would be two implementations of rung 4, and `AGENTS.md` rule 10 exists to
stop exactly that.

The two candidates are not symmetric, and the asymmetries are the whole argument.

**A Databricks App** is a workspace-hosted process (Streamlit, Dash, Gradio or a
plain ASGI app) that authenticates the end user, with a URL inside the workspace. It
is the shortest distance to something an internal user can click. *(Amended session
11: an earlier draft of this paragraph said Unity Catalog permissions apply as the
end user rather than as a service principal. That is the **opt-in**, not the default —
data access defaults to the App's service principal, and on-behalf-of-user
authorization is a separate setting nobody here has verified. The asymmetry the
decision rests on is still real, but it is smaller than first written, and it matters
because `docs/09`'s conditions for a Class B display surface require reading under
the end user's identity.)*

**A thin HTTP API** is an ASGI application: typed request and response models, no
rendering, callable by anything — a notebook, a job, `curl`, a future UI.

## Decision

**Rung 4 is a thin HTTP API.** It ships as `src/pii_reduction/service/`, is served by
a third console script (`pii-reduction-service`), and exposes three capabilities and
nothing else in v1:

1. a **config builder** — pick a dataset identity, pick columns, pick entities, get
   a *validated* dataset configuration back (as YAML, optionally saved into
   `configs/datasets/` under a server-derived name); source, destination,
   `failure_mode`, `preserve_original` and `projection` come from a server-side
   template, per rule 4 below,
2. a **run trigger** over the existing entry points — `build_pipeline(config).run()`
   locally, `run_driver` on Databricks — and
3. a **metadata-only status view** of the runs the service started.

**A Databricks App is the hosting decision, not a second surface.** Databricks Apps
run an ASGI application directly, so the App's entry point is this API's
`create_app()` with a Databricks-backed runtime; a UI is a client of these endpoints.
Recorded now so that a later "let's ship the App" is a deployment task rather than a
rewrite.

> **One now ships with the package** — ADR-0035, session 14. The rule above is
> unchanged and is what the panel obeys: it `POST`s to `/configs` rather than
> assembling YAML, and to `/runs` rather than calling `build_pipeline`. What ADR-0035
> settles is the question this sentence left open — *which* client, shipped by whom.

Five reasons, in the order they actually decided it:

1. **Only one of the two can be run end to end today.** This is session 10's most
   expensive lesson: six defects, every one found by running something, none by a
   unit test or an audit, on code both auditors had reviewed
   (`.claude/SESSION_HANDOFF.md`, session 10). An HTTP API can be started, driven and
   asserted against in the default test tier, with no workspace, no Spark and no
   models — over a real ASGI transport, not a mock. A workspace-hosted UI can be
   proved to work only by deploying it and clicking it. A surface whose correctness
   is verifiable on the machine that builds it is worth more than one that is not,
   and this repository has already paid to learn that.
2. **The App's deployment path is the blocked one.** `databricks bundle deploy` fails
   on CLI v0.280.0's expired Terraform signing key, and the owner's organisation
   restricts the CLI besides (session 10). Apps are deployed by the same CLI or by
   hand in the workspace UI. Choosing the App first would put rung 4's *first*
   increment behind rung 3's *unresolved* blocker — the ladder inverted.
3. **The choice is one-way in only one direction.** An ASGI API becomes an App by
   being hosted; a Streamlit App does not become an API without being rewritten. When
   two options differ in reversibility and the evidence is thin, take the reversible
   one.
4. **ADR-0025's rung rule is testable against a typed response and not against a
   rendered page.** "The service layer owns no reduction logic and the engine never
   learns it exists" becomes, for an API: response models a test can assert carry no
   source text, and a static import guard asserting that nothing in `pii_reduction`
   outside `service/` imports `pii_reduction.service`. Both are required by this decision and
   ship with its first increment. A rendered UI would need the same guarantees
   enforced over HTML.
5. **The owner's stated need is "upload a file or pick a table, choose columns, run
   with pre-configured parameters"** (ADR-0025). Every one of those is a request with
   a typed body and a metadata answer. None of them requires rendering.

### The five rules v1 obeys by construction

Written as rules rather than as intentions, because each is a property of a data
structure or of an absent capability rather than a filter that can be wrong:

1. **No endpoint accepts text.** No upload endpoint, no `POST /detect`, no pasted
   sample. Text that never enters the process cannot leave it, and that is what makes
   rule 2 hold without a filter. "Upload a file and reduce it" is already served, by
   a lower rung: a file in a Unity Catalog volume is a filesystem path the ordinary
   CSV source reads (verified on the workspace, session 10), so the *upload* is the
   platform's and the service names the resulting path only through a configured
   dataset. An endpoint that accepts bytes is a governed change under `docs/09`'s
   inbound rules, not a v1 convenience.
2. **No endpoint returns, streams, redirects to, or vends a URL for text.** The
   transport matters as much as the field: a download, a 302 to a volume path and a
   signed URL are the same disclosure as a string in a response body.
3. **The run store holds a service-owned metadata record, never an engine or
   adapter object.** *(Amended during implementation: this originally named
   `ProcessingOutcome.metrics_payload()` and `RunMetadata`. What shipped is narrower
   — a `RunSummary` the runtime builds at the boundary, carrying the run id, config
   hash, status, row/field/entity counts and the configured destinations. It
   deliberately drops `provider_versions`, `pipeline_version`,
   `pseudonymization_key_id`, `dropped_labels` and the `detail` distributions: those
   are provenance the engine already writes to its own metrics artifact, and a
   service-side copy would be a second record to keep true. The reason below is
   unchanged and is what forced the boundary conversion.)* That object carries `frame` — the full pandas
   frame, source text included — and `row_results`, whose `ProcessedFieldResult`
   carries `output_text` (the reduced text) and a relayed error message. Retaining it
   would put Class B and Class C text in the service process, one careless
   `response_model=` away from the wire. The engine already exposes the right object
   and documents it "Metadata only"; the service keeps that one, plus
   `ProcessingOutcome.written` for the destination names, which `metrics_payload()`
   and `RunMetadata` do not carry and the Databricks result does. `audit` is on the
   same object and is the field most likely to *look* safe to retain — it carries no
   values, but it carries the offsets and lengths `docs/09` governs at least as
   strictly as reduced output. `DriverRunResult` is metadata-only by construction,
   but its type lives in `databricks/runner.py`, so only
   `service/runtimes/databricks.py` may name it — even in a `TYPE_CHECKING` block,
   which the AST guard also sees. The runtime adapter converts it to the service's own
   record at the boundary; the run store never holds an engine or adapter type.
4. **The caller chooses a configured dataset, not a table — and not a privacy
   switch.** Source and destination resolve from server-side configuration;
   free-form `catalog.schema.table` and destination-prefix strings are not accepted
   from a request, and a saved config gets a server-derived filename. The same bound
   covers three fields that are neither locations nor text and each of which moves a
   privacy boundary: `processing.failure_mode` (whose
   `preserve_original_and_record_error` value is ADR-0023's raw-text pass-through),
   `processing.preserve_original` (whose `false` value is rule 4's controlled
   replacement workflow) and `destination.projection` (the ADR-0024 grant boundary).
   The builder fills a server-side template; it does not deserialize a
   `DatasetConfig` from a request body. A service runs with its own credentials, so a
   caller-named source is a confused deputy — threat T4 in `docs/09`, executed
   through impeccably clean response bodies.
5. **Errors are categories, not relayed messages**, and the framework's own defaults
   are covered: a custom validation-error handler (pydantic echoes the offending
   input into a 422 body by default) and debug mode off.

**Endpoint shapes forbidden by name**, because each will be proposed and each looks
reasonable: `GET /sources/{table}/preview` ("just five rows, so the user can pick
columns" — what a column picker needs is schema introspection **over a configured
dataset**, never over a caller-named table, which would be rule 4 violated ninety
lines after it is written; note also that `sources/` today exposes only
`load() -> SourceDataset`, which materialises the frame, so a schema-only path is a
change to the engine rather than something the service may improvise);
`POST /detect` or `POST /reduce` ("paste text, see what would happen");
`GET /runs/{id}/failures` returning field error *messages* rather than categories;
`GET /runs/{id}/result`, or any download or signed URL for the output;
`GET /runs/{id}/audit`, which carries no values but carries the offsets and lengths
`docs/09` governs at least as strictly as reduced output; and a `sample_reduced`
field on the status response, which is the one somebody adds the day before a demo.

The compact form: **the service may return numbers about text and names of things; it
may not return text, and it may not name a place the caller chose.**

**What this deliberately does not include: no side-by-side original/reduced view.**
The privacy auditor flagged that surface when ADR-0025 landed, and it is a Class B
display surface — showing original text to a browser is a disclosure whether or not
it was ever written to disk. Before one is built,
`docs/09_SECURITY_PRIVACY_GOVERNANCE.md` and `AGENTS.md` rule 8 must cover rendered
output and API responses, which they now do, extended in the same commit as this ADR
and ahead of any endpoint being written. The rule those documents now carry: **no
service response may contain source text, reduced text, or a detected value.** v1
obeys it by having no endpoint that could.

## Consequences

- **A `service` extra — the fifth optional group — and an amendment to ADR-0008.**
  `fastapi` is the ASGI framework; it is an extra, never a core dependency (the core
  install stays `pydantic`/`PyYAML`/`pandas`/`phonenumbers`). `fastapi` **and
  `httpx`** are *also* added to `dev`, deliberately, so the HTTP surface is covered by
  the **default** test tier rather than by a tier nobody runs — `httpx` because both
  `TestClient` and `ASGITransport` need it, and reason 1's "a real ASGI transport, not
  a mock" is not deliverable without it. It is currently present in the development
  venv by accident, declared by nothing, so CI's `pip install -e ".[dev]"` would not
  have had it. The cost is real and larger than one line suggests: the push tier now
  resolves fastapi, starlette, anyio, sniffio, httpx, httpcore, h11, certifi and idna
  — all pure Python, none a model, none needing the network at test time. ADR-0009's
  constraint is that the default tier is model-free and offline, not that it is
  dependency-free. ADR-0008 enumerates the extras and the `dev` list, so it is
  **amended in place** here, exactly as session 3 amended it when `parquet` was added
  and `pyarrow` went into `dev` for this same reason.
- **The Databricks runtime is one named file, and the import guard says so.**
  `tests/test_package.py` asserted that *nothing* outside `databricks/` imports the
  Databricks surface. That statement was a proxy for the real rule — nothing on the
  **engine path** may reach for a Spark-backed adapter — and rung 4 is not on the
  engine path. The guard is amended to exempt exactly one file,
  `service/runtimes/databricks.py`, and gains a companion guard in the opposite
  direction (nothing outside `service/` imports `service/`) which is strictly
  stronger than what it replaces. A ladder rung may depend downward; the amendment
  encodes that, and the containment to one file keeps it from becoming a licence.

  Three implementation constraints keep the exemption narrow, and they are part of
  the decision rather than an implementation detail: the guard matches the **exact
  relative path** `service/runtimes/databricks.py` (a filename match would exempt any
  future file called `databricks.py` anywhere in the package); it **asserts that the
  exempt path exists**, so a rename cannot silently retire the exemption into a
  blanket allowance; and `test_only_the_databricks_surface_names_spark` is **not**
  exempted — the one file that may import the Databricks surface still may not name
  `pyspark` or `databricks.connect`. The exemption lands in the commit that creates
  the file, never before: an exemption for a file that does not exist is a hole with
  a name on it.

  One correction to the obvious summary of this: the pair is **not** "strictly
  stronger" than the guard it replaces. It permits one edge the old guard forbade and
  forbids a family of edges the old guard never mentioned; neither ordering holds. It
  is strictly stronger on the direction that matters, at the cost of one named edge.
- **Three console scripts.** `pii-reduction` (engine, no Spark),
  `pii-reduction-databricks` (driver path), `pii-reduction-service` (rung 4). The
  third is *forced*, not merely preferred: a `pii-reduction serve` subcommand would
  make `cli.py` import `pii_reduction.service`, and `cli.py` is outside `service/`,
  so the new reverse guard would fail. A lazy import inside the subcommand would not
  help either — the guard walks the AST and catches function-local imports. The guard
  does real work on its first day.
- **The service binds `127.0.0.1` by default**, and any other bind is *refused*
  rather than merely flagged — see the amended bullet below. Since no authentication
  is implemented, the bind address is the entire control, so it belongs in the
  console script rather than in a deployment note.
- **Both runtimes land in the same increment.** `service/runtimes/` holding one
  module would be a factory around a single implementation — the abstraction this
  repository warns against in the other direction. Local and Databricks ship
  together, or `runtimes/` does not exist yet.
- **The service holds run state in memory, and says so.** A status view over a
  process-local store is honest for v1 and wrong for a multi-replica App; the durable
  record of a run is the `<dataset>_run_metrics` table the engine already writes.
  Persisting service-side run state is a named later increment, not an oversight.
- **No authentication is implemented, and the API must not be exposed without it.**
  Run locally it is a developer tool bound to localhost. Hosted as a Databricks App,
  *authentication* is the platform's; **authorization is a separate question with an
  unverified answer** — see the amendment in *Context* above.

  *Amended (session 11, close-out):* this bullet originally said "shipping an
  unauthenticated service on a network is a deployment error, and the documentation
  says so rather than the code pretending otherwise", and the console script printed
  a warning. **The code now refuses it**: any `--host` other than `127.0.0.1` exits 2
  unless `--i-provide-authentication` is passed as well, checked before the
  application or the run store is built. The architecture audit's argument was the
  deciding one — a warning on stderr is invisible in a container log nobody reads,
  and with no authentication the bind address is the entire control, so this belongs
  with ADR-0023's failure mode and the Delta writer's `errorifexists` rather than
  with advice. The refusal is a property of the **console script**; a hosting wrapper
  that calls `create_app` directly does not pass through it, which is why the
  platform's authentication is a precondition of hosting rather than a bonus.

## Alternatives rejected

- **Build the Databricks App (Streamlit) first, add an API later.** Fastest to a
  screenshot, and the screenshot is the thing this decision is least interested in.
  It puts the first rung-4 increment behind an environment blocker, produces a
  surface that cannot be tested where it is built, and — because Streamlit's natural
  idiom is to render a dataframe — makes the side-by-side Class B view the *default*
  thing to build rather than a decision someone has to make.
- **Both, from the start.** Two surfaces to the same brief with no shared contract is
  the drift AGENTS.md rule 10 forbids. With the API first an App is a client; with
  both at once they are two implementations racing.
- **A CLI-only service (extend `pii-reduction` with a `build-config` command).**
  Cheapest, and it genuinely delivers the config builder — but a run trigger and a
  status view over a process that exits are not a service layer, and the users this
  is for are not at a terminal.
- **A generic job-submission API that posts to the Databricks Jobs API.** That is
  rung 3 wearing rung 4's clothes: the service would own orchestration detail and
  still not give anyone a config builder.

Three ways to avoid the import exemption entirely were considered, because the
exemption is the part of this decision a reviewer will challenge. All three are
worse:

- **Invoke the existing console script as a subprocess** (`pii-reduction-databricks
  run <dataset>`). Zero imports, no exemption, and arguably a more literal reading of
  "the same entry points a human uses". Rejected because it trades a typed
  `DriverRunResult` for an exit code and stdout parsing, destroys the injectable
  `session_factory` seam that lets the trigger be tested in the default tier, and
  re-introduces the exact defect class session 10 paid for — a caller ignoring a
  return value and reporting a failed run green.
- **Put the runtime in `databricks/service_runtime.py`** and let `databricks/` import
  `service/`. Rejected because it inverts the ladder (rung 2/3 depending on rung 4)
  and needs a whole **directory** exempted from the new service guard — strictly
  worse than one file exempted from the old one.
- **Wire it in a composition root outside `src/`** (the App's start command).
  Rejected because it puts the one edge that matters where no import guard, no mypy
  run and no test can see it.

## Addendum (2026-08-22, session 12): hosted, and the identity question answered

**Hosted.** `databricks apps create` + `apps deploy --source-code-path` needs no
bundle, so the expired-Terraform-key bug that this ADR and two sessions of notes
recorded as the blocker never applied to Apps at all. The App runs the console script
with `--i-provide-authentication`. Evidence in `docs/19`.

**The identity assumption this ADR reasoned from is now measured, and it holds.** The
App carries its own service principal, `user_api_scopes` is `None`, and
`effective_user_api_scopes` is `['iam.access-control:read', 'iam.current-user:read']` —
identity only, **no data scope**. So the platform authenticates the end user and
authorizes as the App, exactly as rule 4's server-side-template design assumed. That
design is not caution: in the deployed shape a caller who could name a
`catalog.schema.table` would make the *service principal* read it.

It also fixes the price of the Class B display surface `docs/09` describes: its
"read under the end user's identity" condition needs an explicit on-behalf-of-user
opt-in **and** a run path that uses the caller's token, neither of which hosting
provides by default.

## What would revisit this

An internal user needing a rendered surface before an integration exists — at which
point the App gets built *over* these endpoints, which does not revisit this ADR. It
would be revisited if the API turned out to be unhostable as a Databricks App (the
platform requiring a specific framework this one is not), or if the owner's users
turned out to be exclusively notebook users, in which case a documented Python façade
would beat an HTTP one and this decision should be superseded explicitly.

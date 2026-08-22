# Session handoff

A running record of what each working session established, so a later session can
build on evidence instead of re-deriving it. Append a new section per session.
Keep it factual: what was verified, how, and what is still unknown.

Sessions 1–8 are archived verbatim in
[`docs/archive/SESSION_HANDOFF_S1-S8.md`](../docs/archive/SESSION_HANDOFF_S1-S8.md);
the index below says what each established. The newest session's block is the live
"start here" — currently **session 14**, at the end of this file.

> **The project was finished and tagged `v0.1.0` in session 13.** Session 14 opened a
> **new line of work on top of it**: making the shipped engine usable — its accuracy
> knobs reachable through the API, a control panel that renders them, and an upload
> path. That is additive; `v0.1.0` remains a complete release and everything parked
> stays parked. `CHANGELOG.md` is still the entry point for someone arriving cold, and
> `docs/14` §8's *Parked, with the condition that would reopen it* is still the
> complete register of what is unbuilt.

---

## Sessions 1–8 — evidence index (full text in docs/archive/SESSION_HANDOFF_S1-S8.md)

- **Session 1 (2026-08-17) — environment and harness.** Repo rooted at the working
  directory, `git init`, `.gitattributes` marks `tests/fixtures/**` and `demo/**`
  binary (byte-exact round-trip tests vs CRLF), venv deliberately empty until the
  stack decision. No source code.
- **Session 2 (2026-08-17) — assessment, probes, decisions.** Throwaway `uv` probe
  environment (Presidio, spaCy, lingua) built and discarded; produced
  `docs/14_IMPLEMENTATION_PLAN.md` and the first twelve ADRs. All probe text synthetic.
- **Session 3 (2026-08-17/18) — increments A1–A6, B, C.** Package foundation through
  parsers, deterministic provider, reconciliation/reducers, pipeline, synthetic corpus
  + evaluation, Presidio provider, language routing. Ended at 730 default / 73
  integration tests, CI green.
- **Session 4 (2026-08-18) — Q1: CI and benchmark regression gates.** Both chains
  re-measured before any gate was locked; every published number reproduced exactly
  (ADR-0009: gate values must come from a run someone actually did).
- **Session 5 (2026-08-18) — Q1 closed, Q2 solved, D started.** Q2's English tier-3
  PERSON 0.333 was a span-boundary bug, not detection: Presidio ran entity boundaries
  through line breaks. Span repair at the provider boundary, `key_value` parser,
  identifier guard (ADR-0016).
- **Session 6 (2026-08-18) — Increment D closed.** Three public-dataset packs from
  pinned checksummed sources (ADR-0017, ADR-0018), pack gate sets; Q4 diagnosed the
  Greek PERSON gap (span absorption, label confusion, άνω τελεία — ADR-0019) and the
  mechanisms reproduce on GitHub's runner.
- **Session 6 overnight (2026-08-19) — Increment E complete.** Leakage variants,
  strategy in the metric grain, run provenance, threshold calibration locked, the
  one-time test-split read, the 10k two-chain comparison
  (`docs/16_BENCHMARK_REPORT_10K.md`).
- **Session 7 (2026-08-19) — Increment F: Databricks execution.** Parity met on the
  real workspace (Delta up, `SparkTableSource` back, byte-identical local processing,
  `DeltaTableOutput`, audit/metrics tables metadata-only). Workspace is
  **serverless-only**; the distributed path shipped but is infra-blocked
  (ISOLATION_STARTUP_FAILURE). Dedicated venv `.venv-dbx17`; auth was
  `DATABRICKS_CONFIG_PROFILE`-only until session 10 added the token route.
- **Session 8 (2026-08-19) — the Greek call shipped.** ADR-0020 (label promotion,
  scoped to the Greek provider instance) and ADR-0021 (structurally-safe span
  extension). Published numbers moved deliberately: strict F1 0.902 → 0.910, leakage
  0.117 → 0.067, Greek PERSON recall 0.154 → 0.500, over-redaction still 0.000, en/de
  numerically unchanged. Token-level surgery was measured and deliberately not
  shipped; Presidio discards spaCy's `MISC` before the adapter sees it.

---

## Session 9 — 2026-08-19 — Two external reviews reconciled; the R1–R6 sequence shipped

**Start here:** the external-review work is **done** — reconciliation, decision,
and all six approved increments. The queue in plan §8 is empty again. The next
real decisions are the ones docs/17's decision table deferred: the next major
phase (residual verification vs the Phase-7 Greek model — D7 vs D18), the
speaker-prefix ADR (still the most serious open design item), and the
distributed path whenever the sandbox incident closes.

**What this session was.** Two independent external assessments existed
(`..\pii_reduction_review_claude`, reviewed through `985e8ea`;
`..\pii_reduction_review_codex`, reviewed at `2b9c64d`), neither author with
commit access, neither having executed anything. The brief: decide what the
repository should do about them — not implement their lists.

**Phase 1–2 (`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md`).** Every load-bearing
claim verified against the code before classification. Both reviews proved
factually reliable; they converged independently on the same top findings, which
is the strongest signal either produced. Decision table: **6 ACCEPT, 14 DEFER
with named reopening conditions, 4 REJECT, 3 DISPUTED.** Three claims were
factually wrong (the largest: codex's capability matrix asserts a CLI `run`
entry point that did not exist). Five findings both reviews missed were surfaced
from inside, including that the fail-open default was pinned by a test as
intended behaviour, and that a future residual scanner can be validated against
the manifests this repo already owns. Where the reviews disagreed, the code
settled it in docs/17 §2 — read that section before re-litigating anything.

**Phase 3 — six commits, every one through /qa and both auditors:**

| commit | increment | what changed |
|---|---|---|
| `d85fa46` | R1 + docs/17 | **Fail-closed default** (ADR-0023): `quarantine_row` in model + shipped config; pass-through is explicit opt-in; no-fail-open-row property pinned by test. 41/41 gates before and after — no number moved. |
| `5d65aa8` | R2 | **Run provenance**: real library+model versions via importlib.metadata (degrades to the old bare type string without the extra), detector version, `delta_v<N>` source version (fake-session tested; parity asserts it next workspace run), HMAC-derived non-secret `pseudonymization_key_id`. |
| `a687f61` | R3 | **Reduced-only projection** (ADR-0024): `destination.projection: reduced_only` locally, `run_driver(reduced_only_prefix=...)` on Databricks — docs/09's grant model is realisable with shipped code. In-place-replacement combination refused at validation. |
| `f73f5ee` | R4 | **Docs honesty**: "discovering" out of the tagline; audit-table span-length disclosure stated and governance tightened (docs/09 + docs/03 §12); pseudonymize frequency/co-occurrence limit + correct birthday-bound sizing; UC-03 status; stale registries comment. |
| `c98caf8` | R5 | **Referential consistency measured**: consistency 1.000, distinctness 1.000 over all 102 EMAIL/PHONE occurrences per dataset scope, and scope isolation verified end to end (same value, different tokens across the two dataset configs). Test-tier by design; docs/08 defines the metric. |
| `a216935` | R6 | **`pii-reduction run <dataset>`**: the reduction's first CLI front door; metadata-only output pinned on stdout and stderr, both paths; exit 1 on any failed field. |

**State:** 956 default-tier tests (917 at session start), 95 deselected; ruff and
`mypy src tests` clean; all 41 benchmark/incident gates green after every
increment; **no published benchmark number moved, and none was allowed to** —
the R sequence changed what the system can honestly claim, not what it scores.
Two new numbers were published (R5's consistency pair). Not pushed in this
session.

**Working lessons this session paid for:**

1. **The auditors caught something real on every single increment**, including a
   numerically wrong birthday bound in the docs-honesty increment itself (both
   caught it independently), a silent bad composition between the projection and
   the rule-4 replacement workflow, and ADR-0021-style sizing undercounts.
   Session 5's rule stands: run them every time, even on docs-only diffs.
2. **Parallel edits to one file race the ruff autofix hook** — it strips
   just-added imports as unused between edits. Sequential edits, or add the
   using code before the import.
3. **Verify a reviewer's claim before classifying it, even when it flatters the
   repo.** Both reviews were reliable, but three claims were wrong, and one of
   the wrong ones (the phantom CLI command) pointed at the most useful small
   gap this session closed.

**Deferred with conditions (docs/17 §7 is the record):** residual verification
(D7 — reopens when the owner picks the next major phase), distributed evidence
fan-out (D8 — sandbox), key rotation/KMS (D9 — first real pseudonymize
consumer), batching (D10 — Phase 7), rejected-candidates audit (D11), long-text
guard (D12), note-history parser (D13 — after the speaker-prefix ADR),
publication + NOTICE (D14 — owner call). A chip was also raised for the
pre-existing last-wins row-status edge across multi-column failures
(`pipeline.py` ~line 253), found by the R1 privacy audit; it is more visible now
that ADR-0023 makes `pii_status` load-bearing.

### Session 9 addendum — the direction, made official

The owner stated the project's real target (2026-08-19, recorded in plan §8's
**platform queue** and in project memory): **an internal Databricks-first
platform** for AI analysis of ServiceNow/case data — PII now, PHI later — with a
service layer over this engine. Azure Databricks is mandatory, not optional.
Clarified in the same conversation: data does **not** have to live in Delta —
UC tables work via `run_driver` today, and Volumes files are plain paths the CSV
source should read as-is (one verification run owed, queue item P3).

**Next session: start at plan §8 "The platform queue" (P0 → P4, P5 stretch).**
P0 includes collapsing sessions 1–8 of THIS file into `docs/archive/` — when
that happens, this addendum and the session-9 block above stay in place as the
newest live record.

---

## Session 10 — 2026-08-20/21 — The platform queue shipped, then verified on the workspace

**Start here — the platform is built and verified on the workspace; the next move is
the service layer, not more plumbing.**

Everything the platform queue set out to do is done, and the Databricks half is no
longer theoretical: the engine runs on the workspace from a dataset config, through
its own console entry point, on serverless job compute, reading either a Unity
Catalog table or a file in a volume, detecting PERSON, and writing reduced/audit/
metrics Delta tables with complete run provenance. Ten sessions of foundation are
finished. **What has never been built is rung 4 of ADR-0025's ladder — the service
layer someone actually uses.** That is the next session's work; see "Where to go
next" at the end of this section.

**Verified on the workspace (2026-08-20/21), each by an actual run:**

| claim | evidence |
|---|---|
| driver-path parity | reduced-column hashes equal to the local run |
| audit/metrics metadata-only | exact `AUDIT_COLUMNS` set, asserted |
| the runbook's own CLI path | `pii-reduction-databricks run <dataset>` → exit 0, three Delta tables |
| PERSON detection | audit recorded PERSON 28 / EMAIL 15 / PHONE 15 over 30 rows |
| Volumes ingestion | a serverless job read `/Volumes/.../tickets.csv` through the ordinary CSV source |
| the job shape (P4) | the same wheel task + entry point ran on serverless compute |
| `bundle validate` | Validation OK |
| R2 provenance, every column a redact run can fill | library + model versions, `delta_v<N>`, and `lingua (…2.2.0)` from a `mode: detect` run. `pseudonymization_key_id` stays unexercised — every workspace run used `redact` (docs/17 D9) |
| reduced-only projection (R3) | written and read back without the raw column |
| the default write mode | a workspace test writes under it and asserts the second write refuses |

**Still blocked, both environmental, both with named remedies:**

- **`bundle deploy`** — Databricks CLI v0.280.0 cannot verify HashiCorp's Terraform
  signature (`openpgp: key expired`). The wheel builds and the bundle files upload
  first, so this is the CLI, not the bundle. **Remedy: upgrade the CLI.**
- **The distributed `mapInPandas` path** — `ISOLATION_STARTUP_FAILURE`, unchanged
  since session 7. The `databricks`-marked test flips from skip to assertion by itself
  the day the sandbox works.

**Six defects this session, every one found by running something rather than reading
it.** This is the session's main lesson and it is worth carrying:

1. **The default Delta write mode never worked.** `errorifexists` is rejected by
   Databricks Connect outright, so every config-driven write failed. The only
   workspace test overrode the mode, so the default path had zero coverage.
2. **A failed reduction was reported as a green job.** A `python_wheel_task` calls the
   entry point as a function and ignores its return value.
3. **…and raising `SystemExit` unconditionally broke the other direction**, because
   the task runs under IPython where `SystemExit(0)` is also an error.
4. **The front door refused file sources**, so it could not run the volume config the
   runbook publishes.
5. **The bundle's build command** ran with PATH `python`, which had no `build` backend.
6. **The bundle's wheel path** was resolved against the declaring file, so `./dist`
   meant `resources/dist`.

Every one is now fixed, covered, and — where the behaviour is Databricks-side —
re-confirmed against a real job. Note the shape: unit tests and audits caught none of
these six, and both auditors reviewed the code that carried defects 1, 5 and 6.
**Component tests prove a component; only an end-to-end run proves a path.**

**A harness note that cost two wrong conclusions:** environment variables set at User
scope do **not** reach shells this harness spawns unless the harness process restarted
after they were set. Read them back with
`[Environment]::GetEnvironmentVariable(name,'User')` and inject them, rather than
concluding they are absent.

### The push failed CI, and that is the third time this session the lesson repeated

`mypy src tests` was clean locally and failed on **both** runners: `uvicorn` is in the
`service` extra and **not** in `dev`, so CI could not resolve the import — and my
machine could, because I had installed uvicorn by hand to run the service. Exactly
session 4's finding ("a green local run does not prove the push tier is green") and
session 10's ("a local gate that does not match the remote one is not a gate"), on a
line of packaging I wrote in this same session while explicitly reasoning about which
optional modules need a mypy override.

The fix is ADR-0008's rule unchanged — the type checker models what the packaging
says — but the useful part was *how* it was fixed. Rather than patching and
re-pushing, I built a throwaway `.[dev]` venv, which is what CI provisions, and it
immediately found **two more failures the developer venv hides**: the bind tests call
`main()`, which imported `uvicorn` even though they inject their own `serve`. That
produced a better design than the one CI rejected — `main` now *probes* for a server
instead of importing one, and only when it is going to start it, so a caller who
supplies `serve` needs no server installed at all.

**Carry this:** when a change touches packaging, run the throwaway environment
*before* the push, not after CI says so. Three commands, and it is strictly stronger
than the local gate.

### Where to go next

**Do not start with P5 (batching).** It is real work, but it optimises a path nobody
is using yet, and the gate on it is now only the two environment blockers above.

**Build rung 4: the service layer.** ADR-0025 records the ladder and the owner's goal
— an internal platform where someone picks a table or uploads a file, chooses columns,
and runs, with the engine underneath. Every piece that layer needs now exists and is
verified: config-nameable IO, a console entry point, a job shape, volume ingestion,
the reduced-only projection for the grant boundary, and provenance. What is missing is
the surface. The rung rule from ADR-0025 governs it: **the service layer owns no
reduction logic**, and the engine must never learn it exists.

The smallest useful version: a config *builder* (pick source, pick columns, pick
entities → a validated dataset config), a run trigger over `run_driver`, and a
metadata-only status view. `AGENTS.md` rule 3 applies to a UI exactly as it does to a
notebook, and `docs/09` governs what such a surface may display — a side-by-side
original/reduced view is a Class B display surface, which the privacy auditor already
flagged as needing rule 8 extended to rendered output when this gets built.

**Ten commits — five for the queue, five after it closed — each through the gate and
each reviewed by both auditors** (the table below lists the queue's five; `git log`
carries the rest, whose messages record their own auditor passes) (P0–P3
record the verdict in their commit messages; P4's records the findings it fixed but
not the verdict — noted so the evidence and the claim match):

| commit | increment | what changed |
|---|---|---|
| `890cb4a` | P0 | Handoff sessions 1–8 → `docs/archive/` behind an evidence index. Nothing else pruned; no ADR touched. |
| `309d79a` | P1 | **ADR-0025: Azure Databricks is the primary deployment target.** README/charter/roadmap/docs-07 amended in the same commit. Records the platform ladder and PHI as a horizon, not a promise. |
| `acefb64` | P2 | **A dataset YAML names a UC table end to end.** Typed `spark_table`/`delta_table` config, registries that refuse them with an instruction, `run_driver` reading config, and `pii-reduction-databricks` as the front door. |
| `f0481fe` | P3 (part) | `docs/18_RUNBOOK_DATABRICKS.md`, and **auth that does not require the Databricks CLI**. |
| `0f1c6bc` | P4 | `databricks.yml` + `resources/` — bundle and job skeleton, CLI-free path documented, never deployed. |

**State:** 1029 default-tier tests (956 at session start), 97 deselected; the
`databricks` tier **3 passed / 2 skipped on the workspace** (plan §8 F's re-check log
carries the rows — pytest reports 5 skipped because 3 are module-level
presidio/language collection skips outside the tier); `bundle validate` OK;
ruff clean;
**`mypy src tests` clean** — see lesson 1. No published benchmark number was touched,
so none moved. Not pushed at the time this section was written; the push is the last
step of the session.

### The two findings worth carrying forward

**1. The local gate was weaker than CI, and it hid a real breakage for two
increments.** `/qa` and `/gate` ran `mypy src`; CI runs `mypy src tests`. My P2 and P3
commits introduced **21 type errors in `tests/`** — 20 in `test_databricks_adapters.py`,
one in `test_pipeline.py`, none in `src` — and both gates stayed green. (I first wrote
28 here; that was the working-tree count, which included the not-yet-committed P4 test
file. The committed P2 and P3 states each measure 21.) At `890cb4a` the CI invocation
was clean, so this was self-inflicted and invisible.
Both skill files now run `mypy src tests`. The general lesson: **a local gate that
does not match the remote one is not a gate**, and the way to find that out is to
run the remote command, not to trust the local wrapper.

**2. The owner's environment invalidated an assumption nobody had written down.**
They reported mid-session that their organisation blocks the Databricks CLI and that
they authenticate with a token. The CLI
was never a *code* dependency — nothing shells out to it, and the extra is
`databricks-connect`, a library — but `get_session` accepted only a named profile and
the parity fixture gated on `DATABRICKS_CONFIG_PROFILE`, so **every workspace test
would have skipped silently** under token auth, and the whole Databricks surface would
have looked broken for no discoverable reason. ADR-0006's original text already said
"CLI profiles **or env**"; only the env half had ever been implemented. Four routes
now resolve, ambient before the profile variable so a stale variable in a notebook
cannot route a process that already has a session through Connect.

### What the auditors caught that the tests did not

Every increment, again. The ones that mattered:

- **A local `mode: overwrite` was inherited by the Delta writer** (P2). Any dataset
  config written for local files would have made *overwriting a governed Delta table*
  the default. Now only a `delta_table` destination's own mode reaches Delta.
- **A run could write over the table it reads** (P2) — read via `toPandas()`, then
  replace. `errorifexists` made it fail closed *by default*, which is not the same as
  "cannot happen". Refused now under every mode, before anything is read.
- **The runbook's config template omitted `provider_chain`** (P3). The project
  default is `deterministic_only`. An operator following the runbook exactly would
  have redacted emails and phones, seen `success` on every row, and left **every
  person's name in the text** — the precise failure this project exists to prevent.
  Fixed in the runbook and the shipped example, and pinned by a test.
- **"Failed fields are null, not raw" was stated unconditionally** (P3). True under
  the default `failure_mode`, false under the `preserve_original_and_record_error`
  opt-in, which an inherited config may already carry.
- **The bundle's `configs_path` could not resolve for a wheel task** (P4), and its
  dependency list **cannot install spaCy models**, so the job would have missed every
  name silently. Neither was a substitute for validating the bundle — `bundle
  validate` was run on 2026-08-21 and passes; `bundle deploy` is a separate claim and
  is still blocked.

### Deliberately not done

- **P5 (batching).** Its original gate — P3 unverified — has expired: P3 is met and
  `bundle validate` passes. It stays unstarted for a better reason: it optimises a
  path nobody uses yet, and the next increment is the service layer (see "Where to go
  next" above).
- **Any workspace claim I did not have evidence for.** During most of the session
  that meant all of them. By the end, ten are evidenced (the table above). Two remain
  unexecuted anywhere and are recorded as such in the runbook, `resources/README.md`,
  the bundle and plan §8: **`bundle deploy` completing** and the **distributed
  path** — both environment blockers with named remedies, neither a design problem.
- **A `VolumeSource` adapter.** A volume path is a filesystem path, so `CsvSource`
  reads it unchanged — on Databricks compute, where the FUSE mount is. Building an
  adapter would have carried a Databricks concept into `sources/` for nothing.

### Open, unchanged by this session

The speaker-prefix ADR (still the most serious open design item), the Phase-7 Greek
model, the distributed path whenever the serverless sandbox incident closes, and the
deferred items in `docs/17` §7.

---

## Session 11 — 2026-08-21 — Rung 4 built, decided by ADR, and run on both runtimes

**Start here — the service layer exists and has been executed. It has never been
hosted.** That *was* the next increment; the owner has since set a different course
for session 12 — see the addendum at the end of this section before picking anything
up.

Someone can now pick a configured dataset, choose columns and entities, and run it —
over HTTP, locally or on the workspace, with the engine underneath and no reduction
logic anywhere above it. What has *not* happened is hosting: no Databricks App has
been created, and `bundle deploy` is still blocked by the CLI's expired Terraform
signing key. Running the API from a terminal against the workspace and hosting it
inside the workspace are different claims; only the first has been made.

### The decision, and why it went that way

**ADR-0026: rung 4 is a thin HTTP API, and a Databricks App is how it gets hosted
rather than a second surface to build.** ADR-0025 left a slash in "Databricks App /
API"; ten sessions later everything below rung 4 existed, so the slash had to become
a decision. Five reasons, and the first is this project's own most expensive lesson:
an API can be started, driven and asserted against on the machine that builds it,
with no workspace, no Spark and no models — a workspace-hosted UI can be proved to
work only by deploying it and clicking it. The App's deployment path is also the one
currently blocked, and the choice is one-way in only one direction: an ASGI app
becomes an App by being hosted, a Streamlit app does not become an API without a
rewrite.

### Two increments, in this order deliberately

**S1 — the contract, before any endpoint existed** (`e31063d`). The privacy auditor
asked for this when ADR-0025 landed, and doing it first is what made the rest
checkable. `AGENTS.md` rule 8 and a new `docs/09` section — *Display surfaces, API
responses, and request payloads* — extend the observability rule from logs to every
channel that crosses the process boundary, and to the inbound half nobody had
written down: uploads, query strings, access-logged request bodies, and a framework's
own 422 echoing the input it rejected. A future side-by-side view now carries seven
conditions instead of five (added: read under the **end user's** identity, and record
each disclosure as metadata), scoped explicitly to Class B/C so the Phase 9 demo
surface stays legal.

**S2 — the code** (`0759d1a`, with the close-out increment on top). `src/pii_reduction/service/`: a config builder over server-side templates, a run
trigger over both entry points, a metadata-only status view, and
`pii-reduction-service` as a third console script. 61 new tests.

### What makes the rung rule real rather than stated

Four static guards in `tests/test_package.py`, each of which I confirmed fails on the
violation it describes:

1. **Nothing outside `service/` imports it** — ADR-0025's "the engine never learns a
   service layer exists", in its literal form. It is also *why* there is a third
   console script: a `pii-reduction serve` subcommand would need `cli.py` to import
   the package, and a function-local import would not help, because the guard walks
   the AST.
2. **`service/` may not name the engine's internals** — providers, reducers, parsers,
   language, entities, evaluation, sources, outputs, synthetic, and anything
   under `processing/` except `pipeline`. This is what makes "owns no reduction logic" checkable. It is a
   *naming* rule, not a sandbox: `processing/` imports all of them, so the process
   still loads them.
3. **Exactly one file may import the Databricks surface** —
   `service/runtimes/databricks.py`, matched by exact POSIX relative path (Windows
   path equality is case-insensitive) and asserted to exist, so a rename cannot turn a
   named exemption into a blanket one. The Spark-name guard is **not** exempted: that
   file still may not say `pyspark`.
4. **`config/` is bounded to `contracts/` and `entities/`** — because the allowlist
   works by leaving `config/` open, which makes it one convenience re-export away from
   being routed around. `known_labels` and `TAXONOMY` are exactly such re-exports.

### The design decision worth carrying: what a caller may *not* choose

The service runs with its own credentials, so a request that could name a
`catalog.schema.table` would let a caller read a schema they cannot. Source and
destination therefore come from a server-side **template** — and so do three switches
that move a privacy boundary rather than express a preference:
`processing.failure_mode` (whose `preserve_original_and_record_error` is ADR-0023's
raw-text pass-through), `processing.preserve_original`, and
`destination.projection`. The request models have nowhere to put them, so a request
carrying one is a 422 rather than a policy check that could be forgotten.

Same doctrine on the way out: **no endpoint accepts text, and none returns, streams,
redirects to or vends a URL for any.** Enforced by a reflection test over every
model — a filter can be wrong, an absent field cannot — and six endpoint shapes are
forbidden by name in ADR-0026, because each will be proposed and each looks
reasonable.

### Verified by running it, which was the point

- **Local, over real HTTP** (three times during the increment, through the console
  entry point): build a config, save it, run 102 corpus documents, poll to
  `succeeded`, plus every refusal path — unknown dataset, unavailable runtime,
  duplicate save, off-menu column, a request carrying `source` or `projection`, and a
  malformed name whose 422 body does not contain the name.
- **On the workspace**: a 25-row synthetic table staged in Unity Catalog from the
  head of the committed corpus — a different slice and a different chain from session
  10's 25-row Volumes run, so those counts are not expected to match — a
  workspace-pointing template written **outside the repository**, the service started
  from the `databricks`-extra venv with `--databricks`. `POST /runs` with
  `runtime: databricks` → `succeeded` in ~22s. Read back: 25 rows all `success`, the
  source column intact beside the reduced one, the audit table's column set exactly
  `AUDIT_COLUMNS` (no values — though its offsets and scores keep it governed like
  reduced output), PERSON 22 / EMAIL 13 / PHONE 12 detected by the hybrid chain,
  `run_source_version = delta_v0`, real library **and** model versions per provider,
  and — the check worth repeating — the `config_hash` the API returned equals
  `run_config_hash` in the Delta metrics table. Staged and written tables dropped
  afterwards; the schema left as found.

### The auditors found real defects on every pass, again — four passes this session

Session 5's rule keeps paying. The ones that changed the design rather than the
prose:

- **The run trigger was a confused deputy** and the first draft's "no endpoint returns
  text" reasoning did not see it: a caller who names the source and destination makes
  the *service's* credentials read and write on their behalf. That produced the
  server-side template, which is now the load-bearing idea in the whole layer.
- **A build could take a name another dataset declares**, which made that dataset
  unreachable with the 404 blaming the innocent file. `open("x")` guards the file
  name; nothing guarded the *declared* name, which is what decides where output lands.
- **Two path parameters echoed caller input** into a 404 body and the access log,
  while the body models were carefully bounded so the 422 handler would not.
- **The reflection guard was blind to `error`, `message`, `start` and `end`** — the
  names this codebase actually uses. A guard that matches the wrong tokens reads
  exactly like one that works.
- **`--databricks` in an environment without the extra** accepted a run, failed it on
  the worker thread, and discarded the install hint — because the runtime module
  imports fine without `databricks-connect`. Now probed at startup.
- **The executor submit sat outside the lock its own comment claimed it was inside.**
- Docs-side: span offsets and per-entity confidence had been on *Safe to log* since
  the document was written, contradicting `docs/18`, the new section, and the shipped
  `ALLOWED_FIELDS`, which never contained them.

### State

1090 default-tier tests (1029 at session start), 97 deselected; ruff clean;
`mypy src tests` clean (151 files). No published benchmark number was touched, so
none moved. `configs/service_templates.yaml` is Class A throughout, with the Unity
Catalog variant commented out — the workspace-pointing template used for the run
lived outside the repository, deliberately.

### Where to go next

1. **Host it.** A Databricks App is the decided hosting; `create_app` needs a small
   wrapper plus a `RunStore` carrying the Databricks runtime. Blocked on the CLI
   unless the App is created through the workspace UI, which is untried. This is the
   increment that turns a decision into a deployment, and it carries two exit
   conditions of its own: it is scoped to a **single replica** (item 2 is why), and
   it must **verify** what the platform does about identity (item 3) rather than
   assume it. If it starts the console script rather than a wrapper, the command
   needs `--i-provide-authentication` — the script refuses a non-loopback bind.
2. **A durable run store** — part of hosting being correct rather than a follow-up
   to it. The store is process-local, so the first thing a hosted user does
   (`POST /runs`, then poll `GET /runs/{id}`) returns 404 from a second replica or
   after a restart.
3. **Settle the identity question against the platform, not from memory.** Databricks
   Apps authenticate the end user, but data access defaults to the **App's service
   principal**; on-behalf-of-user authorization is a separate opt-in. S1 just added
   "read under the end user's identity" to `docs/09`'s conditions for a Class B
   display surface, so hosting does *not* satisfy that condition by default, and
   nobody here has checked which mode this workspace's Apps run in.
4. **Batching (P5)** — its old reason for waiting ("it optimises a path nobody uses")
   has expired, but it is the only item with nobody waiting on it, so it sits behind
   the three above. Bring the measurement obligation with it: rows/s before and after
   on the 10k pack.
5. **Schema introspection in the engine**, so a column picker can read a source's
   columns without reading the source. Last, because the workaround is documented and
   works.

Unchanged: the speaker-prefix ADR, the Phase-7 Greek model, the distributed path
(`ISOLATION_STARTUP_FAILURE`), and `docs/17` §7's deferred items.

### Session 11 addendum — the owner set a new course for session 12

**Read this before the "Where to go next" list above: that list is paused, not
cancelled.** The owner's next instruction (2026-08-21) is a different kind of work
from the pickup list, and it comes first.

**The task.** A separate reference implementation and a private source workbook exist
at `..\pii_alternative`:

```text
pii_alternative/
├── Combined-Files_WorkCopy.xlsx        <- Class B. See the rules below.
└── project_reference_handsoff/
    ├── README.md · HANDOFF_BRIEF.md · ADOPTION_CHECKLIST.md
    ├── knowledge/        (9 files)
    ├── portable/         (11 files)
    ├── reference-data/   (5 files, incl. configs/)
    └── source-docs/      (4 files)
```

Session 12 compares this repository against that reference, decides whether it holds
evidence-backed capabilities, safeguards or lessons this repository lacks, and
**implements only what it judges justified** — not a merge, not a list of
suggestions. The alternative is not assumed superior: this repository's contracts,
architecture, privacy rules and ADRs take precedence, and "no change is warranted" is
a legitimate outcome if the evidence says so.

**This is a fresh judgement, and it is not session 9 again.** Sessions 9's external
reviews were *assessments of this repository*; this is a comparison against a working
implementation with its own corpus and its own measured history. Different question,
different failure mode: the risk here is absorbing an architecture rather than
absorbing a critique. `docs/17_EXTERNAL_REVIEW_RECONCILIATION.md` is the shape of the
output to aim for — a decision table with reasons, not a diff.

**Class B rules, restated because this is the first time real data is within reach.**
`Combined-Files_WorkCopy.xlsx` is production-like. `docs/09`'s *Display surfaces, API
responses, and request payloads* governs it, and so does `AGENTS.md` rule 2 — nothing
from it becomes a fixture, an example, a log line, a doc snippet, or a committed
artifact. Metadata only: sheet names, configured column names, row and field counts,
aggregate entity counts, parser fallback counts, language distributions, timings,
error categories. **Not** cell values, not text fragments, not span offsets or
lengths, not per-entity confidence. Prefer the already-sanitized files under
`project_reference_handsoff/reference-data/` over reopening the workbook at all. Any
temporary validation output lives outside both repositories and is deleted afterwards.

**Two environment facts session 12 will hit in its first hour:**

1. **This repository cannot open that workbook, and should not learn to.** `openpyxl`
   is not installed and is not a dependency; `docs/06` records Excel as deferred with
   the note-history parser, so there is no Excel source adapter either. If the
   workbook genuinely must be opened to check a structural claim, build a **throwaway
   venv outside both repositories** — never add an Excel reader to `pyproject.toml`
   to satisfy a one-off inspection. The same applies to running the alternative's
   portable smoke test: its dependencies are unknown, and `.venv` is not the place to
   find out.
2. **The throwaway `.[dev]` venv is now a standing technique, not a one-off.** It
   caught two failures at the end of session 11 that the developer venv hides, after
   CI caught a third. Build it before any push that touches packaging:
   `uv venv <scratch>/venv-devtier --python 3.11` then
   `VIRTUAL_ENV=<scratch>/venv-devtier uv pip install -e ".[dev]"`, and run ruff, mypy
   and pytest in it. It is strictly stronger than the local gate.

**Starting state, stated because the owner's brief describes an older one.** The tree
is **clean** at `28979b8`, pushed, CI green. Session 11's work — including
`pyproject.toml`, `src/pii_reduction/service/cli.py` and
`tests/test_service_databricks_runtime.py` — is **committed**, not pending. A brief
that says those files carry uncommitted user-owned modifications is describing the
state before the session-11 close-out; there is nothing in the working tree to
preserve or work around. Verify with `git status --short` rather than trusting either
statement.

**Unchanged by the new course:** every rule in `AGENTS.md`, the ADR record, the rung
rule, the entity taxonomy, the CPU-only constraint (ADR-0015), the local/Databricks
parity contract, and the standing prohibition on moving a published benchmark number
without re-running it. An adopted idea that changes any of those needs its own ADR in
the same change, as ADR-0026 did.


---

## Session 12 — 2026-08-21/22 — The alternative implementation, compared and partly adopted

**Start here:** the comparison the owner asked for is **done**, and
[`docs/20_ALTERNATIVE_RECONCILIATION.md`](../docs/20_ALTERNATIVE_RECONCILIATION.md)
is the deliverable — every item classified with its evidence, **including the
rejections**. Four changes landed. The session-11 pickup list (plan §8, headed by
*host the service*) is **live again**; `docs/20` §9 adds four ranked follow-ons that
sit beside it rather than in front of it.

**What this session was.** A second implementation of the same problem exists at
`..\pii_alternative` — a different author, a different design, built and run against
a real 45,366-row ServiceNow/chat workbook on Databricks serverless, with a transfer
pack written for "a different repo with a different design". The brief: decide what
of it this repository should do, and implement only that. Not a merge, not a list.

**Totals: 4 adopted · 19 already covered · 9 deferred with named conditions · 8
rejected · 1 disputed · 1 place where they were right about us · 4 recorded as docs.**

### What landed, and why each was invisible before

| what | evidence that it matters here |
|---|---|
| **ADR-0027 — markup is machine syntax.** A model-inferred span is clipped out of HTML/BBCode/URLs/entities at the provider boundary, and `validation.require_markup_preserved` (on by default) checks the *written output* with a deliberately independent assertion | Their single most damaging failure: spaCy returns `[code]<div` as a **PERSON at 0.85**, and redaction destroys the tag. **2,687 of 105,279 cells.** Here: the round-trip invariant cannot see it (the damage is *inside* an eligible segment), the over-redaction gate cannot see it (a `<div>` is not a protected token), and **no corpus here contains markup at all** |
| **Delta column mapping**, set only when a column name needs it | `DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES`. A ServiceNow export puts a space in nearly every column; `docs/18` invites an operator to name one; every fixture here is a plain identifier, so the runbook's **first real write would have failed** |
| **ADR-0028 — reachability decomposition of recall** | Their whole-cell recall check reported 8,346 "misses" where 24 were real — ~500×, because the rest sat in regions the parser is required to preserve. Here: **90 of 315 incident-corpus entities are unreachable**, and hybrid recall over what *was* offered is **0.996 against an overall 0.711** |
| **Parquet engine preflight at construction** | Their `pyarrow`-missing-at-write killed a run after 18 minutes. Ours raised the same error at the same moment. Five lines |

### The three most useful things to carry forward

1. **The failure classes that mattered were the ones with zero corpus support.** All
   three substantive adoptions are for shapes no fixture, pack or stress corpus here
   contains. Everything the corpora *do* cover was already handled, usually better.
   Coverage of the measured surface said nothing about the unmeasured one.
2. **"Already implemented" needed probing, not reading.** Nineteen items were verified
   against the code, three by running something: the reconciler's behaviour on their
   two motivating overlap failures (impossible here, by priority rather than by
   length), pydantic's refusal of a YAML-boolean language code, and the timing of the
   parquet import.
3. **Their strongest single claim is wrong here and it took a probe to say so.**
   "Longest span wins is the only correct overlap rule" — both failures behind it are
   impossible under ADR-0005's priority ordering. One residual asymmetry is real,
   recorded as `docs/20` D9, and unmeasured on any corpus.

### What was deliberately *not* adopted, in one line each

Case augmentation, the row-scoped gazetteer and protected terms, per-segment language
detection (**43–46% of their transcript cells are multilingual** — that is the evidence
this repository's standing deferral never had), and segment batching: all real, all
**unmeasurable on any corpus here**, all deferred with the condition that reopens them.
Rejected outright: their multilingual PERSON denylist (corpus-tuned word list in five
languages we do not ship), the labelled-address recognizer (ADR-0002, `AGENTS.md` rule
6), a `PII` type for untyped spans (closed taxonomy, rule 7), and `ai_mask` as a
provider — **on their measurement, which is worth reading before anyone proposes it**:
no offsets, no types, and not reproducible across rows.

Their two owner-ruled policy decisions were **not inherited**. One of them is real
input to *our* open speaker-prefix ADR: a production deployment chose "preserve", and
measured what it cost.

### Privacy

The workbook was **never opened** — `openpyxl` is not installed, no Excel adapter
exists, and none was added. Every alternative figure quoted anywhere in this repository
comes from their sanitized counts-only reports. **One thing to know if you read their
pack:** its prose uses person names from its own corpus and its `knowledge/01` §4.2
says those are real agent names. Four had reached this repository's new fixtures and
docstrings before that was noticed; all were replaced with this project's own synthetic
pool. Check any example you lift from there.

### Both auditors found the markup guard leaking, and that is the session's lesson

Session 5's rule paid again, harder than usual. **Three variants of one mistake**, all
in `_clip_out_of_markup`, all in the direction ADR-0027's own decision 1 forbids —
*a guard against over-redaction that causes under-redaction has made the trade
backwards*:

1. `<Grace Okafor>` was read as a tag (the pattern matched any bracketed word run), so
   a chat-style display name fell "wholly inside markup" and the span was discarded.
   Fixed by requiring a **known** element name.
2. A name inside a URL path (`…/u/Grace.Okafor`) was discarded for the same reason.
   Fixed: a span wholly inside a region is now *judged* — dropped only when its own
   surface carries a bracket, is a tag/attribute name, or holds fewer than two letters.
3. An untouched quoted surname (`"Small"`) and a digit-only ADDRESS were deleted
   because the "did the clip shorten this?" flag was computed **after** the punctuation
   trim, so trimming a quote counted as clipping. On a real ServiceNow column, where a
   URL somewhere in the cell is near-universal, this would have removed candidates
   silently on most rows.

**None was visible to a corpus, a gate or a metric** — no corpus here has markup. They
were found by reading the diff against the doctrine it claimed to follow. A fourth,
smaller: clipping last can produce a widened span clipped back to its origin, so
`detect()` now drops exact duplicates rather than letting a provider corroborate itself.

Two review suggestions were **not** taken, with the reason recorded where someone would
look: adding `pyarrow` to `test_package.py`'s `OPTIONAL_MODULES` (pandas imports pyarrow
itself, so the guard can never be clean — measured, and the comment there says so), and
moving `processing/fidelity.py` to `outputs/` (it runs before anything is written).

Still open and **pre-existing**, raised by the architecture review and deliberately not
fixed here: `BaseProvider._extend_left` takes a `siblings` argument that its only
production caller does not pass, so ADR-0021's sibling-conflict refusal never fires in
production and `test_span_extension.py`'s comment claiming otherwise is wrong. Passing
it would change detection behaviour and needs its own measurement.

### State

**1187 default-tier tests** (1090 at session start), 97 deselected; 92 integration;
ruff clean; `mypy src tests` clean (156 files). **56 gates across three corpora and both
chains** — 41 existing, re-run after every increment and again after each audit round,
plus 15 new ones on the markup corpus. **No published number moved, and none was
touched**; the incident corpus rebuilds byte-identical after the `PLAIN`/`TRANSCRIPT`
constant change. New: `tests/test_markup_guard.py` (50), `tests/test_markup_corpus.py`
(19), `tests/test_reachability.py` (14), plus additions to the Databricks-adapter,
outputs and incident-corpus suites.

**Six commits**, all clean: the markup guard (ADR-0027), the reachability decomposition
(ADR-0028), the Delta/parquet fixes, the reconciliation record (`docs/20`), the markup
corpus (ADR-0029), and its gates plus the review fixes.

### The markup corpus paid for itself on its first run

ADR-0029 exists because ADR-0027 shipped a detection change with **no corpus support at
all**. Its first run found something **neither implementation had recorded**: markup does
not merely cause the false positives the reference catalogue documents — **it destroys
PERSON recall**, 0.322 against 0.821 on the committed corpus. Isolated by changing one
thing at a time: `From: <name>` is found, `<b>From:</b> <name> &lt;…&gt;<br>` returns
**no span at all**. That is the leak direction, and it sits upstream of every remedy
either project built — no guard, repair or reconciler rule can reach a span the model
never emits.

**Both reviewers found the increment's claims outrunning its automation** (CI rebuilt
two corpora while the ADR said three; the gate file was never validated; nothing ran the
gates; the dispatch duplicated the profile table's keys), and the privacy audit caught an
honest-reporting defect: the placement claim was true of en/de and silently omitted
Greek, which runs the other way. All fixed.

Not run: Databricks (no session opened this session — A2's column-mapping options are
**unit-tested and unverified on a workspace**, and every place that claim appears says
so), and no pack benchmark (they need a download).

### Where to go next

1. **The session-11 list, unchanged** — host the service, the durable run store, the
   identity question, batching (P5), schema introspection.
2. **`docs/20` §9's four**, of which the first is the one this session most wants:
   **a markup-bearing corpus slice**, so ADR-0027 stops being a capability with no
   measurement of its own. Second: the **shape-only source profiler**, so an operator
   pointing `docs/18` at a real table can see eligible share, parser-fallback rate and
   language mix *before* configuring instead of guessing.
3. If P5 (batching) is picked up, read `docs/20` D5/D6 **first**: joining segments into
   one document per (cell, language) is a 4.7× win *and* makes Spark partitioning,
   ordering and intermediate-landing part of the answer. All three produced
   successful, clean-looking runs with wrong output for them, in ~50% of cells.

### Session 12 addendum — pushed, then pickup item 2 built (ADR-0030)

**Pushed.** Seven commits, `7349151..87dae69`, and **CI green on both platforms**
(run 32568286681) — including the new markup gates and the three-corpus byte-for-byte
rebuild check.

**Then the durable run store**, pickup item 2, chosen because it is the only part of
hosting that is pure local code and item 1 is CLI-blocked. `--run-journal PATH` appends
every run-state transition to JSON lines and reloads it at startup.

**Verified over real HTTP, twice, because the store-level test cannot cross a process
boundary:**

```
POST /runs -> 202 pending ; polled -> succeeded rows_read = 102
--- process killed ---
after restart GET /runs/{id} -> 200 succeeded rows_read = 102   (was: 404)
journal states: ['pending', 'running', 'succeeded']
```

and the half that matters more — killed **mid-run**:

```
killed mid-run; journal held: ['pending', 'running']
after restart -> 200 failed / interrupted
```

**ADR-0030 was written because the reviewer was right that this diverged from a
recorded direction without one.** The plan said `<dataset>_run_metrics` is the record
that already survives a restart. True, and insufficient: it cannot see a run submitted
and never started, refused at shutdown, killed mid-flight, or crashed at second three —
and it has never heard of a service `run_id`, which is a `uuid4` this layer minted. So:
the service journals **what it was asked**, the engine records **what a run did**, they
join on `engine_run_id`/`config_hash`, and `_interrupted` refuses to guess which.

**Both reviewers found real defects again — three of them mine, one of them serious:**

1. **The operator's journal path was relayed into an HTTP 500 body.** Under the plan's
   own hosting design that path is `/Volumes/<catalog>/<schema>/...`, so a full disk
   would have handed catalog and schema to an unauthenticated caller. The path now goes
   to the operator log under `destination`; the body carries the category alone.
2. **A chained pydantic error carried the malformed line.** That branch fires precisely
   when the line's provenance is *unknown*. `from None`, and the test now checks the
   cause and the rendered traceback rather than only the message.
3. **A tolerated truncated tail was never repaired** — the worst of the three. `record()`
   appends, so the fragment welds onto the next line, turning a tolerated *trailing*
   fragment into a malformed line in the *middle*; the next load refuses the whole
   history, `RunStore.__init__` raises, and the console script exits 2. **The service
   stops starting**, days after an ordinary crash, blaming a second writer that never
   existed. The tail is now truncated back to the last complete record, with a test for
   the crash-then-carry-on sequence.
4. `interrupted()` duplicated `RunStore.TERMINAL` as a second literal. Moved into the
   store as `_interrupted`, reading the one definition.

Also from the reviews: `*.jsonl` in `.gitignore` (on the Databricks path
`RunSummary.outputs` holds real `catalog.schema.table`), `runs_recovered` added to
`ALLOWED_FIELDS` rather than overloading `rows_read`, `runtime_checkable` dropped
(it compares method *names*; mypy already checks conformance), and three costs written
into `docs/19` rather than left to be found — a lost terminal write misreporting a
success, fsync under the store lock stalling `GET /runs` on a FUSE path, and unbounded
growth with rotation as the operator's job.

**State:** 1207 default-tier tests (+20), 56 gates unchanged, ruff and `mypy src tests` clean.

**Next:** hosting (item 1) now has something to pass a wrapper — `--run-journal` on a
volume path. Still blocked on the Databricks CLI unless the App is created through the
workspace UI, which is untried, or over the REST Workspace Import route the reference
implementation used (`docs/20` §6), which is also untried.

### Session 12 addendum — pickup item 5: schema introspection (ADR-0031)

`SourceAdapter.schema()` returns a source's column names **without reading a row** —
header line for CSV, footer for parquet (a partitioned directory included, because
`load()` accepts one), the metastore for a Delta table where `load()` would have pulled
the whole thing to the driver. `pii-reduction describe <dataset>` is the front door,
and it checks **all three** of `Pipeline._validate_source`'s schema preconditions ahead
of the load: configured columns present, row id present, output column not already
taken.

**The tested property is the negative one.** Any adapter can return column names by
loading everything; the value is entirely in not doing that. Each is pinned by a reader
that fails if data is touched — an unparseable second line and an ignored `nrows` for
CSV, `read_table`/`read_row_group`/`pd.read_parquet` all patched to raise for parquet,
and a fake session whose frame raises on any attribute but `schema` for Spark, with a
companion test proving `load()` *does* trip it.

**The service still does not consume it, deliberately.** `pii_reduction.sources` is one
of the nine names in `ENGINE_INTERNALS_CLOSED_TO_THE_SERVICE`. ADR-0031 names two shapes
for whoever picks it up and says the second is better: an intersection endpoint (which
still leaks one bit per offered column), or **validating every template against
`schema()` at `create_app` startup** and exposing no endpoint at all — same typo caught,
earlier, nothing crossing HTTP.

**Both reviewers found real defects again, and one was a claim outrunning the code:**

1. **`describe` did not check `row_id`** while ADR-0031, `docs/14` and `docs/18` all
   said it caught that failure class. A typo in `row_id` got exit 0 and died after the
   table was read. Now checked, with the output-column collision alongside.
2. **The refusal named a subcommand that does not exist** — `pii-reduction-databricks`
   registers `run` and nothing else — and my own test pinned the inaccuracy by asserting
   only the console-script name.
3. **`ParquetSource.schema()` refused a partitioned directory that `load()` reads
   happily.** A pre-flight check that reports a broken dataset which works is worse
   than no check. `pyarrow.dataset` instead of `parquet.read_schema`.
4. **A test passed while proving nothing** — it asserted four substrings were absent and
   never checked the exit code, so any failure path (wrong cwd) produced empty output
   and a green test. Replaced with a positive assertion about the output's shape.
5. **Two translators of `SourceConfig` → adapter**, where `sources/base.py` says there is
   one owner. Factored into `build_source_from_config`.
6. **`CsvSource.schema()` duplicated `load()`'s option handling**, so adding to
   `CSV_OPTIONS` could make the two disagree about the column set silently. One `_read`
   now serves both — and it closes a pre-existing hole where `EmptyDataError`
   (a `ValueError`, not a `ParserError`) escaped `SourceError` as a pandas traceback.
7. `docs/19` contradicted itself and two service comments asserted the engine had no
   schema path. Fixed in the same change.

Also recorded, from the privacy audit: **a parquet footer carries per-column min/max
statistics — real values.** Only `.names` is taken, and ADR-0031 now states that as a
rule, so a later "add types for the adapters that can answer honestly" increment meets
it rather than rediscovering it.

**State:** 1226 default-tier tests, 56 gates unchanged, ruff and `mypy src tests` clean.

**Not verified against a real Unity Catalog table** — the Spark path is fake-session
tested only, and the metastore-cost claim is Spark's contract rather than our
measurement.

### Session 12 addendum — rung 4 is HOSTED, and the identity question is answered

**The blocker was never a blocker.** Two sessions recorded hosting as blocked by the
Databricks CLI's expired Terraform signing key. **That bug is specific to
`bundle deploy`. Apps have their own deployment path and need no bundle at all:**

```
databricks apps create pii-reduction-service --no-compute
databricks workspace import-dir <staged> /Workspace/Users/<you>/pii-reduction-app
databricks apps start  pii-reduction-service
databricks apps deploy pii-reduction-service --source-code-path <that> --mode SNAPSHOT
```

Deployment: `SUCCEEDED — App started successfully`. `apps get`: `compute: ACTIVE`,
`app: RUNNING`. The staged directory is four things — the built wheel, a
`requirements.txt` naming it with the `[service]` extra, the `configs/` tree, and an
`app.yaml` whose command is the console script with `--i-provide-authentication`.

**Driven over real HTTPS through the App proxy** (SDK credential resolution):
`/health`, `/entities`, `/templates`, `/datasets`, `/runs` all 200 — and a `POST /runs`
carrying a `source` field is a **422**, so the confused-deputy guard is live in the
hosted process, not just in the test suite.

**Two limits, neither a defect.** `runtimes` is `['local']` (the App installs the
`service` extra, not `databricks`), and the run journal is on container-local disk, so
it survives a restart and not a redeploy — a Volume path is next, and `docs/19` records
the fsync cost to measure before taking it.

### Item 3: measured, and it confirms the concern

Read straight off the created App:

```
service_principal_id        present   (created automatically with the App)
user_api_scopes             None
effective_user_api_scopes   ['iam.access-control:read', 'iam.current-user:read']
```

**An App authenticates the end user and authorizes data access as its own service
principal.** The default on-behalf-of-user scopes are identity-only and carry **no data
scope** — no SQL, no files, no catalog. Three consequences, now facts rather than
expectations:

1. `docs/09`'s Class B display-surface condition — "read under the end user's identity"
   — is **not satisfied by hosting**, and would not be by hosting plus a UI. It needs
   the explicit opt-in *and* a run path using the caller's token.
2. The server-side-template design is **load-bearing, not cautious**: in the deployed
   shape a caller who could name a `catalog.schema.table` would make the service
   principal read it.
3. Whoever grants this App data access grants it to the service principal, so **the
   grant is the security boundary** — prefer the ADR-0024 reduced-only destination.

Recorded in `docs/19` (evidence), `docs/09` (the condition, with the measurement),
ADR-0026 (addendum), and plan §8 items 1 and 3.

### The App is left running

It holds compute. `databricks apps stop pii-reduction-service` stops it without
deleting; `apps delete` removes it and its service principal. Nothing else was created
in the workspace, and the staged source lives under the owner's own `/Workspace/Users/`
path — no catalog, schema, table or volume was touched.

**Pickup list: 1, 2, 3 and 5 are done. Only 4 (batching) remains.**

---

## Session 13 — the finalization session (2026-08-22)

**The brief is: finish this project.** Read
[`docs/21_FINALIZATION.md`](../docs/21_FINALIZATION.md) first — it is the whole course,
and it is deliberately short. Then plan §8 only if you need detail on something it
names.

### The state you are inheriting

The tree is **clean and pushed** at `d76d21d`, CI green on Linux and Windows.

- **1226 default-tier tests**, 92 integration, 97 deselected.
- **56 regression gates** across three corpora (benchmark, incidents, markup), both
  chains. `ruff format --check`, `ruff check`, `mypy src tests` all clean.
- **31 ADRs.** Every non-obvious choice has one.
- **No published benchmark number has ever moved without being re-measured**, and none
  moved in session 12.

**Everything below rung 4 is executed, and rung 4 is now hosted.** A Databricks App
serves the API over HTTPS. The pickup list that has driven the last three sessions is
down to one item (batching), and `docs/21` says whether to do it or park it.

### What session 12 did, in one paragraph each

1. **Compared this repository against the reference implementation** at
   `..\pii_alternative` (`docs/20_ALTERNATIVE_RECONCILIATION.md`): 4 adopted, 19 already
   covered, 9 deferred with conditions, 8 rejected, 1 disputed, 1 place where they were
   right about us. The adoptions were the markup guard (ADR-0027), the reachability
   decomposition of recall (ADR-0028), Delta column mapping, and a parquet preflight.
2. **Built the markup corpus** (ADR-0029) because ADR-0027 shipped a detection change
   with no corpus at all. Its first run found something **neither implementation had
   recorded**: markup does not merely cause false positives, **it destroys PERSON
   recall** — 0.322 against 0.821 — because the model returns *no span* on markup-dense
   clauses, upstream of every remedy either project built.
3. **Built the durable run store** (ADR-0030) and verified it across a real killed
   process, including a kill *mid-run*, which the next process reports as
   `failed`/`interrupted` rather than as `running`.
4. **Added schema introspection** (ADR-0031): `SourceAdapter.schema()` and
   `pii-reduction describe`, column names without reading a row.
5. **Hosted rung 4 and answered the identity question** — see below.

### The two findings worth carrying into any future work

**Markup destroys detection, not just structure** (ADR-0029). The reference
implementation's twenty-failure catalogue documents only the false-positive direction.
The leak direction is worse and nobody had it. `tests/fixtures/markup` now exists to
measure any remedy.

**A Databricks App authenticates the end user and authorizes as itself.** Measured off
the deployment: the App carries its own service principal, and its default
on-behalf-of-user scopes are `iam.access-control:read` and `iam.current-user:read` —
identity only, no data scope. So `docs/09`'s "read under the end user's identity"
condition for a Class B display surface is **not met by hosting**, and the
server-side-template design is load-bearing rather than cautious.

### Two operational facts

- **The Databricks App exists and is stopped** (2026-08-22). It proved what it was
  created to prove, so its compute was stopped rather than left burning. Nothing was
  lost: the App, its `SUCCEEDED` deployment and the staged workspace source all survive,
  so `apps start` + `apps deploy` brings it back. Only `apps delete` would destroy the
  service principal and force the whole sequence again. **Nothing to decide here.**
- **Nothing else was created in the workspace.** No catalog, schema, table or volume was
  touched; the staged source lives under the owner's own `/Workspace/Users/` path.

### The working rules that paid for themselves twelve sessions running

1. **Run both auditors on every increment, including docs-only ones.** In session 12
   they found a leak in the markup guard three separate ways, a journal path relayed
   into an HTTP 500 body, a truncated-tail bug that would have stopped the service
   starting days after a crash, a `describe` that did not check the thing three
   documents said it checked, and two tests that passed while proving nothing.
2. **A claim in a document must be pinned by a test**, or it will drift. Most of what
   the reviewers caught was prose that had outrun the code.
3. **The throwaway `.[dev]` venv** is what CI provisions and is stronger than the local
   gate: `uv venv <scratch>/venv-devtier --python 3.11`, then
   `VIRTUAL_ENV=<scratch> uv pip install -e ".[dev]"`.
4. **Never move a published number without re-running it.** Three corpora exist so the
   numbers stay honest, not so they can be improved.

---

## Session 13 — 2026-08-22 — **the project is finished and tagged `v0.1.0`**

**Start here if you are picking this up later: there is nothing queued.** `CHANGELOG.md`
is the entry point. `docs/14_IMPLEMENTATION_PLAN.md` §8 has a new section, ***Parked,
with the condition that would reopen it***, which is the complete register of everything
unbuilt — each item with the condition under which someone should pick it up. No item in
this repository is open without a recorded disposition.

The brief was `docs/21_FINALIZATION.md`: finish the project. All three of its parts were
done, not the two that would have sufficed. That document is left as written, with an
executed banner at the top, so the plan and its execution can be compared.

### 1. The speaker-prefix question is decided — ADR-0032

Open since session 8 and called "the most serious open design item" in three documents.

**The decision was easier than four sessions of prose made it look, and the reason is a
documentation defect.** `docs/06_CONFIGURATION_CONTRACT.md` stated *"there is no
configuration that currently fixes it."* **That was false.** `preserve_prefix: false` has
shipped on `TranscriptParser` since Increment A2, is per column, and does exactly this.
Nobody had measured it, so nobody knew what it cost. So the session measured it, on both
corpora and both chains, before ruling.

| | incidents (speakers are people) | benchmark corpus (speakers are roles) |
|---|---|---|
| strict F1 | 0.761 → **0.844** | 0.910 → 0.902 |
| leakage | 0.289 → **0.114** | 0.067 → 0.061 |
| unreachable entities | **90/315 → 0/315** | 0 either way |
| tier-4 PERSON recall (en/de/el) | 0.000 → **0.333/0.900/0.400** | n/a — no speaker is ground truth |
| PERSON strict precision | — | 0.771 → **0.744** |

**The ruling: preserve stays the default, and `preserve_prefix: false` is the named,
measured, per-column opt-in.** Two reasons, and the second is the interesting one.

1. Preserve is the only setting under which `AGENTS.md` rule 5 and the README's
   "preserves speaker metadata exactly" hold *unconditionally*.
2. **The error the opt-in introduces is the one this repository's instrumentation cannot
   see.** Preserving a person's name leaks a span that the corpus, the gates and
   `unreachable_entity_rate` all report out loud. The opt-in's cost is invisible:
   `over_redaction_rate` stays **0.000** through it.

**Two findings nobody predicted.** The expected cost was destroyed role labels. Role
labels are *not* destroyed — `Support Agent`, `Guest`, `Automation`, `Πράκτορας`,
`Πελάτης` all survive. The two documents that change are Greek and change in the
**body**: joining the prefix to the body changes the model's input, so `Καλημέρα` becomes
a false-positive PERSON and a span extends left across `Ονομάζομαι`. That is the **same
failure class §8's Q2 measured twice** (`split_lines`, `key_value`), now measured a third
time — which is why ADR-0016 repairs spans instead of re-cutting input.

### 2. Batching is done — ADR-0033, the last pickup-list item

`docs/21` said "do it or park it". It was done, because three measurements changed the
picture:

- **96% of a Presidio detection is the spaCy pass** (1.57 s of 1.64 s over 272 segments).
  Nothing else is worth batching.
- **`BatchAnalyzerEngine` really does batch it.** An earlier reading of it as "just a
  loop" was **wrong**: `analyze_iterator` runs `NlpEngine.process_batch` — one
  `nlp.pipe` — then calls the ordinary `analyze` with artifacts already computed.
- **Segments per row decides everything.** Plain columns are **1.00** segments/row;
  transcripts are 3–5. Within-row batching is worth 1.87× on a 5-segment row and
  **nothing** on a 1-segment one.

Shipped: `_detect_batch` as a hook **below** the repair chain (`_finalize` extracted so a
batching provider cannot acquire a second copy of ADR-0016/0021/0027), a Presidio
override, and `FieldProcessor` calling it once per provider per row.

| corpus | type | segments/row | before | after | |
|---|---|---|---|---|---|
| benchmark | plain | 1.0 | 181.5 rows/s | 181.8 | unchanged |
| benchmark | transcript | 3.0 | 76.6 rows/s | **119.7** | **1.56×** |
| incidents | transcript | 5.0 | 46.2 rows/s | **81.7** | **1.77×** |
| markup | transcript | 4.0 | 51.5 rows/s | **81.2** | **1.58×** |

**Output identity was verified before the wiring was written** — 576 segments, every
processable segment of all three corpora, three languages, both Presidio instances,
0 differences — and is now asserted by test. All 56 gates unchanged.

**Two things were refused rather than deferred.** Across-row batching (worth a further
~1.35×) would move detection outside the per-row `try`/`except` that ADR-0023's
`quarantine_row` depends on: one bad row would take its whole batch. And a single text is
routed to the scalar path, because the batch machinery costs ~3% on it and a plain-text
column is that case on every row.

### 3. The release is cut

`CHANGELOG.md` (which did not exist), tag `v0.1.0`, README front-page pass, roadmap
Phase 11 marked done with its three unshipped deliverables parked in place rather than
dropped. `NOTICE` is still **not owed** — nothing is published — and that is stated with
the condition that makes it real.

### What did not change, and that is the point

**No published number moved. No shipped default changed.** ADR-0032 changes no
configuration file; ADR-0033 is output-identical by construction and by assertion. The
56 gates hold at the same floors on both chains across all three corpora.

Final state: **1240 default-tier tests** (+14), **97 integration** (+5), 56 gates,
**33 ADRs**, `ruff format --check`, `ruff check`, `mypy src tests` all clean.

### The one lesson worth carrying

**Two of this session's three items were blocked by a claim, not by work.** The
speaker-prefix decision waited four sessions behind a sentence saying no configuration
could fix it — the configuration had shipped in Increment A2. Batching waited three
sessions behind a reading of `BatchAnalyzerEngine` as a loop — it is not one. Both were
resolved by an hour of measurement. **When an item has been open for several sessions,
check the claim that is holding it before doing the work it seems to need.**

---

## Session 14 — 2026-08-22 — **the engine became usable: knobs, a panel, an upload path**

**Start here:** the project is still finished at `v0.1.0`. This session built *on* it,
at the owner's direction, in three increments — ADR-0034, ADR-0035, ADR-0036. **No
published number moved and no shipped default changed in any of them.** Everything
parked in §8 is still parked.

The owner's brief, in their words: they had never worked on a front end or with
FastAPI, wanted to be guided while it was built, and wanted the configuration surface
exposed because *"those features could be quite a big advantage for the accuracy."*
They also said their private data comes **after** this and they did not want the app
built around it — so nothing here assumes their dataset.

### 1. ADR-0034 — what a caller may choose

`split_lines` (ADR-0016) and `preserve_prefix` (ADR-0032) — the two settings most
likely to change a result on a real column — were unreachable through the API. They are
now settable per column, from a template menu the operator opts into per option.

**A rule proposed in conversation did not survive the measurements, and the ADR says
so.** "Safe when moving it can only redact more" is wrong three ways: `split_lines` can
lose a name that wraps mid-sentence, `preserve_prefix` was measured trading one error
for another, and `entities` — caller-choosable since ADR-0026 — is not monotone either.
What holds: *a caller may choose anything whose worst outcome is a measurable quality
result, and never anything whose worst outcome is data in a place, or raw text in a
column, the operator did not sanction.*

**Validity and policy went to different layers after review.** `config/registries.py`
holds `KNOWN_PARSER_OPTIONS` (what a parser accepts); `service/knobs.py` holds what may
cross HTTP. The first draft put both in `service/` and justified it with a
non-sequitur. Moving it **fixed a pre-existing bug for all four entry points**: a
`parser_options` typo in a hand-written YAML used to survive config validation and die
when the pipeline built the parser — after the source was resolved and, on Databricks,
after a session existed.

### 2. ADR-0035 — the control panel

One static HTML file at `/` and `/ui`, served by the same FastAPI process, on by
default, `--no-ui` off. No build step, no CDN, no npm — a Databricks App runs a Python
process. Six properties, each pinned: in the wheel, no external request, byte-identical
per caller, `textContent` never `innerHTML`, no client storage, **and it remembers
nothing the server knows**.

**Two rendering defects surfaced only by driving it in a browser** — a nested `outputs`
object printing as `[object Object]`, and a history column reading a timestamp field
that does not exist. Neither was visible in review. That ratio is the lesson: front-end
work has far more "looks right, isn't" than backend work does.

### 3. ADR-0036 — a template may offer a directory

`select_file: true` makes `source.path` a directory; the caller names one file in it.
So an uploaded volume file becomes a run **without the service ever receiving the
file** — it is told which one to read, from a directory the operator chose. No
multipart, no upload buffer, and the caller still cannot name a source.

The confused-deputy argument genuinely does not apply to an upload (the caller pushes
data they already hold); what survives is operational, and the volume route avoids it
entirely. `docs/18` §6 already had the fact that makes it work: a volume path is a
filesystem path.

### What the auditors found this session — six real defects, three of them live

Both ran on all three increments. In severity order:

1. **A clickjacking hole** (ADR-0035). The panel has two state-changing buttons and no
   framing headers; a hostile frame plus one tricked click from an authenticated
   operator triggers a run under the service's credentials. Now CSP +
   `X-Frame-Options: DENY`, with `connect-src 'self'` making the no-egress property
   browser-enforced rather than only grep-asserted.
2. **A live 422 echo** (ADR-0034). `parser_options` is the first `dict` in a request
   model, and pydantic puts a rejected *key* into the error location **before** the
   pattern that rejects it — so an unbounded caller string came back verbatim. The test
   meant to catch it passed throughout, because it exercised the *value* path only.
3. **The offer and the acceptance were different sets** (ADR-0036). The listing
   filtered by suffix; the builder did not. ADR-0036's whole argument is "the caller
   chose from what the place contains", which is only true if both directions agree.
4. **The response echoed the joined absolute path** — three lines from where
   `saved_path` is deliberately relativized for that reason. On a workspace it names a
   catalog and a schema.
5. **`.gitignore` negations are case-insensitive** on Windows and macOS, so
   `!data/inbox/README.md` also un-ignored `readme.md` — committable, into a directory
   inside the repo tree.
6. **The shipped `corpus_inbox` template gets staged to the App** (`docs/19` copies the
   whole `configs/` tree), pointing at container-local disk — *verbatim* the objection
   ADR-0036 uses to refuse multipart. Shipping it unremarked would have been arguing
   both sides. Now marked local-development-only, in the template and the staging step.

Also: a "ships in the wheel" test that compared a file to itself under an editable
install, with packaging relying on hatchling's `.gitignore`-honouring default; and the
panel keeping its own copies of `preserve_prefix: true` and "ADDRESS is undetected",
which it *transmitted* as explicit settings.

### Two found by probing rather than reasoning

**Windows reserved device names** (`NUL`, `COM1`) pass the filename pattern *and* the
resolve-and-contain check, because they resolve inside the directory — but opening one
reaches a device. **Trailing dots** are stripped by Windows, so `report.csv.` opens
`report.csv`: two names, one file. Both refused on every platform, so a config built on
Linux and run on Windows cannot mean two things.

### The mistake worth carrying, because it is the second time

**CI failed on both platforms, and the dev venv could not have caught it.** The
`corpus_inbox` template uses `language: mode: detect`, which needs the `language`
extra; the push tier installs core + dev only, so every row failed with
`LanguageNotAvailableError`.

§8's Q1 already records this, in as many words: *"A green local run does not prove the
push tier is green — check a clean core-only environment when touching anything the
extras reach."* It was read at the start of this session and not applied. The fix was
verified in a real core-only venv (`uv venv`, `uv pip install -e ".[dev]"`, extras
genuinely absent) across every CI step, and CI is green.

**Do this before pushing anything that touches an optional dependency.** It has now
cost two CI failures on this repository.

### State

**1380 default-tier tests, 97 integration, 1 packaging, 56/56 gates unchanged across
three corpora and both chains, 36 ADRs.** `ruff format --check`, `ruff check`,
`mypy src tests` clean — re-verified in the core-only tier, not just the dev one.

Four surfaces now: `pii-reduction` (CLI), `pii-reduction-databricks`,
`pii-reduction-service` (HTTP API), and the control panel.

### Two things left unverified, stated rather than implied

- **Whether a Databricks App can see `/Volumes`.** The runbook's proven route for
  volume ingestion is a serverless job; the App's runtime is `local`. One
  `ls /Volumes/...` from the App settles it.
- **The inbox listing is a shared surface.** Filenames are visible to everyone who may
  use that template, and a file named after a person puts that name in a listing. It is
  the first **data-derived** entry on `docs/09`'s display-surface allowlist, recorded
  there with what bounds it and what does not.

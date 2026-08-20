# Session handoff

A running record of what each working session established, so a later session can
build on evidence instead of re-deriving it. Append a new section per session.
Keep it factual: what was verified, how, and what is still unknown.

Sessions 1–8 are archived verbatim in
[`docs/archive/SESSION_HANDOFF_S1-S8.md`](../docs/archive/SESSION_HANDOFF_S1-S8.md);
the index below says what each established. The newest session's block is the live
"start here".

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

## Session 10 — 2026-08-20 — The platform queue: P0 → P4 shipped, P3's workspace half outstanding

**Start here:** the platform queue is done, and after the close-out **the owner ran
the workspace tests themselves** (2026-08-20, their own PowerShell session, over the
new `env_token` route): `pytest -m databricks` → **2 passed, 5 skipped**. Driver-path
parity holds on the workspace, and that run carried the first execution **against a
real workspace** of the reduced-only projection (R3) and the run-metrics provenance
columns (R2) — both previously covered only locally and against fakes. The owner then
configured a named profile (`pii-reduction`) at User scope and the suite was **re-run
in-session over the `profile` route**, same result: 2 passed, 5 skipped. Two
authentication routes, one workspace, identical outcome. (The first run was the owner's; the second I ran myself, once they had set a profile
at User scope. Note for future sessions: variables set at User scope do **not** reach
shells this harness spawns unless the harness process restarted after they were set —
read them back with `[Environment]::GetEnvironmentVariable(name,'User')` and inject
them into the command instead of concluding they are absent.)

**P3's exit criterion is now MET.** The runbook's own path ran end to end on the
workspace: synthetic table staged, dataset config pointed at it,
`pii-reduction-databricks run` → exit 0, three Delta tables, verified on read-back,
everything dropped afterwards. It used the **deterministic chain only** (EMAIL and
PHONE; `.venv-dbx17` has no presidio), so it proves the path, not PERSON detection. **It found a defect no test could have**: the shipped
default write mode `errorifexists` is rejected by Databricks Connect, so every
config-driven Delta write had been failing — invisible because the parity suite, the
only workspace test, overrides the mode. Fixed by translating to Spark's `error`
alias, pinned by a default-tier test **and** by a new workspace test that exercises
the default mode end to end (tier: 2 passed → 3 passed). Volumes ingestion still needs a notebook; the
distributed path is still `ISOLATION_STARTUP_FAILURE`.

**Five commits, each through the gate, and each reviewed by both auditors** (P0–P3
record the verdict in their commit messages; P4's records the findings it fixed but
not the verdict — noted so the evidence and the claim match):

| commit | increment | what changed |
|---|---|---|
| `890cb4a` | P0 | Handoff sessions 1–8 → `docs/archive/` behind an evidence index. Nothing else pruned; no ADR touched. |
| `309d79a` | P1 | **ADR-0025: Azure Databricks is the primary deployment target.** README/charter/roadmap/docs-07 amended in the same commit. Records the platform ladder and PHI as a horizon, not a promise. |
| `acefb64` | P2 | **A dataset YAML names a UC table end to end.** Typed `spark_table`/`delta_table` config, registries that refuse them with an instruction, `run_driver` reading config, and `pii-reduction-databricks` as the front door. |
| `f0481fe` | P3 (part) | `docs/18_RUNBOOK_DATABRICKS.md`, and **auth that does not require the Databricks CLI**. |
| `0f1c6bc` | P4 | `databricks.yml` + `resources/` — bundle and job skeleton, CLI-free path documented, never deployed. |

**State:** 1015 default-tier tests (956 at session start), 96 deselected; the
`databricks` tier **2 passed / 2 skipped on the workspace** (owner's run,
2026-08-20; plan §8 F's re-check log carries the row — pytest reported 5 skipped
because 3 are module-level presidio/language collection skips outside the tier);
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
  name silently. Neither is a substitute for validating the bundle, which nobody has.

### Deliberately not done

- **P5 (batching).** Gated on everything else being done *and verified*. P3 is now
  partly verified on the workspace but its config-named CLI path is not, so the gate
  still holds — starting a performance increment while a correctness one is
  unfinished would have been the wrong trade.
- **Any workspace claim I did not have evidence for.** During the session that meant
  all of them; the owner's 2026-08-20 run then supplied evidence for driver-path
  parity, the reduced-only projection (R3) and the provenance columns (R2). Still
  unexecuted anywhere, and still recorded as such in the runbook, ADR-0025,
  `resources/README.md`, the bundle and plan §8: **Volumes ingestion**, the
  **distributed path**, the **bundle deploy**, and the runbook's own
  `pii-reduction-databricks run <dataset>` invocation.
- **A `VolumeSource` adapter.** A volume path is a filesystem path, so `CsvSource`
  reads it unchanged — on Databricks compute, where the FUSE mount is. Building an
  adapter would have carried a Databricks concept into `sources/` for nothing.

### Open, unchanged by this session

The speaker-prefix ADR (still the most serious open design item), the Phase-7 Greek
model, the distributed path whenever the serverless sandbox incident closes, and the
deferred items in `docs/17` §7.

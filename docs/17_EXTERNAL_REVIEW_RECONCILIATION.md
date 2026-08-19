# External review reconciliation

Two independent external assessments of this repository were produced on 2026-08-19,
by reviewers without commit access. Neither executed any test, benchmark, or linter —
both state so explicitly — so every factual claim they make was treated here as a
hypothesis with a file path attached and verified against the code before being
classified. This document is the reconciliation; the decision table in §7 is what the
repository will do about it.

| | review A ("claude") | review B ("codex") |
|---|---|---|
| location | `..\pii_reduction_review_claude` | `..\pii_reduction_review_codex` |
| repo state reviewed | `2b9c64d` → `985e8ea` (saw both incident-notes commits) | `2b9c64d` only (saw the incident corpus as uncommitted working-tree files, and its ADR not at all) |
| executed anything | no | no |
| read the other review | no (stated, and consistent with content) | no (predates A) |

The snapshot difference matters in exactly one place: review B does not mention the
incident-notes stress corpus, ADR-0022, or the speaker-prefix finding. Where B is
silent on those, the silence is timing, not a blind spot, and is treated as such
below.

Verification for this document: every file:line citation below was read in this
session at commit `985e8ea` (working tree clean). No test or benchmark was run for
this reconciliation; where a published number is cited, it is the repository's own
(plan §8, `docs/16_BENCHMARK_REPORT_10K.md`), consistent with the rule that numbers
in documentation come from a run someone actually did.

---

## 1. Findings both reviews agree on, verified

Agreement between two independent readers is signal, not proof. Each row below was
re-verified against the code; **all of them hold.**

### 1.1 The default failure mode is fail-open — confirmed

Both reviews rank this first. Verified:
`FailureMode.PRESERVE_ORIGINAL_AND_RECORD_ERROR` is the model default
([models.py:86](../src/pii_reduction/config/models.py)) and the shipped project
default ([project.yaml:14](../configs/project.yaml)); on any exception
`Pipeline._handle_failure` writes the raw original string to the output column
([pipeline.py:411-416](../src/pii_reduction/processing/pipeline.py)). The failure is
visible (`pii_status = partial_failure`, error category counted, privacy-safe warning
logged) but nothing forces a consumer to filter on it.

Review A adds an amplifier both the code and this session confirm: the Presidio
engine is built lazily at first `detect`
([presidio_provider.py:139-169](../src/pii_reduction/providers/presidio_provider.py)),
so a missing or broken spaCy model raises `ProviderNotAvailableError` *per field*,
which the default mode converts into silent raw-text pass-through for the entire run.
The most likely production failure and the fail-open default compose into the worst
case.

One nuance neither review states (see §6): the pass-through behaviour is pinned as
intended by [test_pipeline.py:295-298](../tests/test_pipeline.py), so flipping the
default is a deliberate behaviour change with a test rewrite, not just an enum edit.
Still small.

### 1.2 The reduced output retains the source columns — confirmed

`Pipeline.process` copies the source frame and appends reduced columns;
`_validate_output` actively requires the originals unchanged
([pipeline.py:193, 306-309, 467-474](../src/pii_reduction/processing/pipeline.py)).
`run_driver` writes reduced, audit and metrics tables under **one** `catalog.schema`
prefix ([runner.py:85-101](../src/pii_reduction/databricks/runner.py);
[output.py:23-46](../src/pii_reduction/databricks/output.py) validates exactly that
shape). `docs/09_SECURITY_PRIVACY_GOVERNANCE.md:158` specifies
"reduced schema → broader analytics consumers" — a governance model the shipped
writer cannot realise, because granting the reduced table grants the raw text. This
is the clearest doc-vs-code divergence with a privacy consequence, and both reviews
found it independently.

Note the cause is a deliberate rule, not an accident: AGENTS.md rule 4
(non-destructive by default) is why originals survive. The fix is an *additional*
projection artifact, not a change to that rule.

### 1.3 The only scalable execution path produces no evidence — confirmed, already recorded

`distributed_frame` yields the reduced frame and discards per-worker audit rows and
run metrics ([runner.py:191-196](../src/pii_reduction/databricks/runner.py)), and the
audited path (`run_driver`) materialises the table to the driver via `.toPandas()`
([source.py:58](../src/pii_reduction/databricks/source.py)). Both reviews present
this as scale-versus-evidence mutual exclusion. Correct — and the repository already
records it as a deliberate v1 scope cut (plan §8 F, the runner docstring). The
distributed path is additionally infra-blocked (`ISOLATION_STARTUP_FAILURE`,
re-checked twice), which neither review disputes.

### 1.4 Detection is row-at-a-time; `detect_batch` has no caller — confirmed

Grep confirms `detect_batch` appears only at its definitions
([base.py:148, 284](../src/pii_reduction/providers/base.py)); the field processor
calls `detect` once per processable segment. The dataset is materialised three times
on the driver path (`frame.copy()`, `frame.to_dict(orient="records")`, and
`.toPandas()` on Spark reads). No chunker, no length cap, no retry, no checkpoint,
no streaming anywhere in `src/` (grep: `readStream|foreachBatch|retry|backoff|chunk`
matches only the unrelated file-download chunking in `synthetic/fetch.py`). All
as both reviews describe. AGENTS.md's own "batch-oriented inference" rule is not met,
which plan §8 already lists among deferrals.

### 1.5 Run provenance records provider *types*, not versions — confirmed

`metrics.provider_versions = {name: settings.type}`
([pipeline.py:204-206](../src/pii_reduction/processing/pipeline.py)). A spaCy,
Presidio or lingua upgrade leaves the run record unchanged — while
`integration.yml` pins model versions precisely because a bump can move a gate.
`SparkTableSource` never populates `source_version`
([source.py:68-73](../src/pii_reduction/databricks/source.py)) even though the field
exists on `SourceDataset`. Both reviews call this the missing half of
reproducibility; the benchmark artifacts record versions in prose, the run record
does not.

### 1.6 Pseudonymization has no key lifecycle — confirmed

Verified in [pseudonymize.py](../src/pii_reduction/reducers/pseudonymize.py):
HMAC-SHA256, env-only key, `MIN_KEY_LENGTH = 32`, default `token_length: 6`
documented as demo-scale, in-process collision detection over digests (`_seen`), no
key identifier anywhere, no rotation path, per-process collision scope. Review A
ranks this P0, review B P1 — a priority disagreement, not a factual one (§2.2). Both
correctly note that rotation silently and irreversibly breaks referential
consistency with no signal, since no mapping exists by design.

### 1.7 Every privacy number rests on injected ground truth — confirmed

`leakage_metrics` matches manifest surfaces against reduced text; there is no
residual scan that works without a manifest. Native PII in public pack text is
invisible to recall and appears as precision loss — the repository itself documents
the 21 Bitext example-address "false positives"
([docs/16_BENCHMARK_REPORT_10K.md:49-56](16_BENCHMARK_REPORT_10K.md)) and the
eight-name-pool limitation (plan §8). Both reviews independently conclude the system
cannot report its own effectiveness on data it did not construct, and both name a
residual-verification capability as the most important missing one. They disagree on
whether the architecture anticipates it (§2.1).

### 1.8 The rest of the shared list — all confirmed, none new to the repository

- **Policy is configuration, not a policy engine.** No role/purpose/consumer/
  jurisdiction dimension exists in `config/models.py`. True; `docs/06` claims to be
  a configuration contract, nothing more.
- **No quasi-identifier model; output is pseudonymous, never anonymous.** True and
  already stated in the charter and `docs/09`.
- **`ADDRESS` is in the taxonomy and detected by nothing.** ADR-0002, deliberate,
  published as 0.000 rather than omitted.
- **Language is a per-field scalar** (`language_summary={language: 1}`,
  [field_processor.py:208](../src/pii_reduction/processing/field_processor.py)).
  Recorded in plan §8 deferrals.
- **Rejections are counted in aggregate; individual `RejectedMatch` objects never
  reach the audit table** ([field_processor.py:175-176](../src/pii_reduction/processing/field_processor.py)).
- **`KNOWN_SOURCE_TYPES = {csv, parquet}`** — Spark/Delta cannot be named in a
  dataset contract; `PandasSource` is programmatic only
  ([registries.py:36](../src/pii_reduction/config/registries.py)).
- **README's word "discovering" overstates.** [README.md:3](../README.md) — the one
  word both reviews independently flag as misleading in an otherwise
  annotated-honest README. No discovery capability exists.
- **Positioning:** both land on the same category (in-tenant, structure-preserving,
  span-level reduction of known free-text columns), the same complement-to-Unity-
  Catalog framing, the same "evaluation harness is the differentiator" reading, the
  same "essentially no moat, portfolio-band top" verdict, and near-identical
  preserve lists (contracts carry no surface strings, closed audit set, allowlisted
  logging, adapter-boundary labels, gates that fail on shrunken support, the
  MultiWOZ rejection, corpus-not-made-easier). Nothing in either preserve list
  contradicts an ADR; they are restatements of the repository's own rules, which is
  corroboration that those rules are legible from outside.
- **Repair-rule accumulation is the main architectural risk** (four repairs, two
  Greek-scoped, capitalisation assumption documented as non-transferable at
  [base.py:104-108](../src/pii_reduction/providers/base.py)). Both reviews accept
  the current per-instance scoping as the right mitigation and both note no
  governing rule exists for when a repair should become a different provider.
- **The greedy reconciler will strain under more providers.** Both cite the
  `_extend_left` both-spans workaround as evidence the design is already
  compensating. Consistent with ADR-0021's session record.

---

## 2. Findings where the reviews disagree

### 2.1 Does the architecture anticipate residual verification?

- Review A (P0-5): "there is nowhere in the current architecture to put it."
- Review B (P0-2): "Architecture anticipation: **Strong.** Evaluation, manifests,
  slicing, gates, and audit outputs are built for extension."

**The code supports B's reading on placement and A's on substance.** `evaluation/`
depends only on `contracts`, is imported only by benchmark entry points, and the
provider-chain machinery is reusable outside `processing/` — a residual scanner
composed of an independent detector chain reading *reduced* output is expressible as
a new entry point beside `benchmark.py` without violating any layer rule. So "nowhere
to put it" is wrong as architecture. What A gets right is that no *capability*
exists: nothing scans without a manifest, and `docs/10` §10 / ADR-0013 correctly
forbid pointing the reducer at its own output, so a verification pass is a distinct
design, not a flag. Verdict: a real design increment with a natural home — neither
"no place" nor "mostly built".

One concrete point in the repo's favour that neither review makes: a residual
scanner can be *validated* against the corpora this project already owns — run it
over reduced benchmark output and compare its findings to the manifests. The
measurement path for the new capability already exists.

### 2.2 Priority of the pseudonymization key lifecycle

Review A: P0 ("moves this from usable-in-production to usable-in-a-demo"). Review B:
P1 (#8). The code cannot settle a priority, but it bounds the risk: `pseudonymize`
is not the default strategy, nothing published or committed relies on it, and the
module already documents the 6-hex default as demo-scale. The *cheap* half (a
non-secret key identifier in `RunMetadata`, so a run is attributable to a key) is
priority-independent and worth taking; rotation, KMS integration and re-tokenization
are production work with no current consumer. Split accordingly in §7.

### 2.3 Priority of distributed evidence fan-out

Review A: P0-3. Review B: P1 (#4). Here the repo state settles it: the distributed
path cannot execute at all on the available workspace
(`ISOLATION_STARTUP_FAILURE`, plan §8 F, re-checked twice, watched by a
databricks-marked test). A fan-out design that cannot be validated against a real
cluster would violate this repository's own "no Databricks claim without execution"
rule (AGENTS.md). B's lower priority is the one consistent with repo discipline:
blocked-on-infrastructure, design when it can be measured.

### 2.4 Size of the fail-closed change

Review A: "trivial — one enum default, one YAML line, one test; an afternoon."
Review B: "Medium. The code change is modest; designing publish/quarantine/access
semantics and compatibility is harder."

Both are right about different objects. The minimal flip is nearly as small as A
says (the mechanism exists and `quarantine_row` is already tested,
[test_pipeline.py:339-359](../tests/test_pipeline.py)) — though slightly larger than
"one test", because the current pass-through behaviour is itself pinned by a test
that must be rewritten, and `docs/01_ARCHITECTURE.md:505` plus `docs/06` examples
carry the old advice. B's "publication gate / approved-run-manifest" concept is a
genuinely different, larger item and should not be allowed to inflate the small one.
§7 takes the small one now and defers the large one.

### 2.5 The recommended next step

Review A: one surgical change (flip the default, add the test). Review B: a
six-part "production-shaped acceptance path" vertical slice (fail-closed +
reduced-only view + persisted evidence + representative gates + full provenance +
incremental restart). A's sequencing matches this repository's increment discipline
(one finishable unit, measured before and after); B's slice bundles at least four
increments, two of which (representative acceptance data, incremental restart) are
majors. The plan in §8 follows A's granularity while covering the same ground in
order.

### 2.6 Scores

The two verdicts differ on production potential (A: 5/10, B: 7/10), open-source
potential (7 vs 8), commercial potential (3 vs 5), differentiation (5 vs 6) and
technical idea (7 vs 8), and agree exactly on portfolio strength (9) and current
maturity (6). These are opinions, recorded here for completeness and settled by
nothing; no action follows from them.

---

## 3. Findings unique to one review

A single reader's finding is a single reader's finding; each is verified before use.

### Unique to review A (all verified except where noted)

1. **presidio-evaluator overlap.** The detector-evaluation half of this project's
   harness (template generation, split discipline, P/R/F1, error analysis) is
   duplicated upstream by `presidio-research`; only the *reduction*-side metrics
   (leakage, fragment leakage with ambient exclusion, over-redaction against
   protected tokens, gate enforcement) have no upstream counterpart. External claim,
   not verifiable offline here, but the framing consequence is real: positioning
   should lead with the reduction metrics, not "evaluation" generically.
2. **Azure Conversation PII overlaps the transcript-awareness differentiator**
   commercially. External, unverified here, plausible; same consequence — the
   durable differentiators are in-tenant execution and gated reduction measurement,
   not structure-awareness alone.
3. **The audit table restores span lengths that redaction removed.** Verified:
   `AUDIT_COLUMNS` carries field-relative pre-reduction `start`/`end`
   ([field_processor.py:34-45](../src/pii_reduction/processing/field_processor.py)),
   while `docs/09:223` positions audit metadata as *less* sensitive ("retained
   longer because it excludes raw values"). The offsets are a narrowing signal for
   short fields. A second-order channel, correctly ranked low — but the docs/09
   retention framing should not survive as written.
4. **Model-unavailability × fail-open amplification** (T16). Verified, §1.1.
5. **Rejected candidates never reach the audit trail** as individual records —
   A alone proposes persisting them ("what was decided *not* to redact is the more
   important question"). Factually verified; the proposal has real costs (§7).
6. **The repository is private**, so every open-source claim is conditional on a
   publication step, and pack NOTICE emission is owed at first distribution.
   Verified (plan §8 Q1; the NOTICE deferral is already recorded in plan §8 known
   deferrals).
7. **`LabelledLineParser` exists**, making a note-history parser cheap. Verified —
   [lines.py:58](../src/pii_reduction/parsers/lines.py), with `transcript` and
   `key_value` already subclassing it.
8. **Deterministic tokens are frequency-analysable regardless of key**, and this
   inherent limitation is absent from the module documentation (which covers
   dictionary resistance and collisions but not frequency/co-occurrence linkage).
   Verified against the module docstring.
9. **Speaker-prefix names** (T8) — unique to A only because of B's snapshot; this
   is the repository's own ADR-0022 finding, already the most serious open item in
   the session-8 handoff. A's review independently ranks it the same way.

### Unique to review B (verified except where noted)

1. **Surface-variant subjects**: `Maria`/`MARIA`/accented forms pseudonymize to
   different tokens because no normalization precedes hashing. True — and the
   no-normalization choice is deliberate and documented (ADR-0013); B presents as
   an unstated risk what is in fact a recorded decision, but the *consequence for
   referential consistency* (one person, several tokens) is fair and unrecorded.
2. **Tenant/environment mix-up threat** (write to the wrong catalog.schema).
   Partially mitigated in code B does not credit: fully-qualified three-part names
   are enforced and bare names refused
   ([source.py:20-36](../src/pii_reduction/databricks/source.py)). No environment
   guard beyond that; fair as a residual.
3. **No processing timestamp on the business output rows.** True (the frame gains
   only `pii_run_id` and `pii_status`), but `pii_run_id` joins to run metrics that
   carry both timestamps. Rejected in §7 with that reason.
4. **Only one overlap policy is registered.** Verified
   ([registries.py:40](../src/pii_reduction/config/registries.py)). The
   configurability is currently vestigial; it becomes real at a third provider.
5. **LLM-provider threat detail** (prompt injection, offset verification, payload
   caps, egress policy) — the most thorough treatment of Phase-7-future risk in
   either review; nothing to verify today because no such provider exists, but the
   list belongs in the Phase 7 design inputs.
6. **"Approved-run-manifest" consumption model** — downstream consumers should
   depend on an accepted run record, not table existence. A control-plane concept
   with no current consumer; deferred.
7. **UC-classification *integration* (tags → dataset configs) rather than
   discovery reinvention** — B frames as P2 what A puts at P3; both agree building
   discovery itself is out of category.

---

## 4. Claims that are factually wrong about this codebase

1. **Review B, capability matrix ("Interface | CLI — Run/benchmark/corpus/pack
   entry points"): there is no `run` entry point.** The CLI registers exactly
   `build-corpus`, `build-incidents`, `fetch-dataset`, `build-pack`, `benchmark`
   ([cli.py:62-113](../src/pii_reduction/cli.py)). A production reduction cannot be
   launched from the CLI at all — only via the Python API or the Databricks runner.
   The error is small; what it reveals is not (§6.1).
2. **Review B, threat 12 ("no general automated PII/content review before
   publishing derived packs")** — overstated as written. The registry is a gate
   that refuses unregistered datasets, non-permissive licences and any source whose
   `contains_real_pii` is not `False`; retrieval is pinned and checksummed with
   refusal on digest mismatch; and a pre-write hook blocks real-looking
   emails/credentials in the working harness. What is true: those controls are
   heuristic and gate *sources*, not a content scan over *derived* pack text. The
   claim as stated ignores three implemented controls.
3. **Review A, §A.8: "`Pipeline` is currently ~380 lines"** — it is 502. Trivial;
   the point it supports (the row loop will be rewritten, not extended) stands.
4. **Review A, P0-1 sizing ("one enum default, one YAML line, one test")** —
   undercounts: the current fail-open behaviour is pinned by an existing test that
   must be rewritten, and two documents carry the old advice. Still small (§2.4).

Nothing else either review asserts about this codebase failed verification. In
particular, every quoted number (ADR-0021's global-extension 0.962→0.885, the 10k
report's 0.373/0.333 fragment split, 21 EMAIL false positives, 2,147/29/5 rows/s,
over-redaction 0.024 on the incident corpus, 768 test functions) reproduced exactly
from the committed artifacts.

---

## 5. External claims not verifiable from inside the repository

Both reviews cite vendor documentation (Databricks UC classification/ABAC GA dates,
Azure Conversation PII, GCP transformation families, Presidio/presidio-research,
Macie, BigID) with retrieval dates. None of that is checkable offline in this
session and none of it is treated as settled fact here. The positioning conclusions
that rest on it are directionally consistent between two independent researchers,
which is the only weight given to them.

---

## 6. What both reviews missed, visible from inside the repository

1. **The CLI cannot run a reduction.** `Pipeline.run()` exists and is tested, but no
   CLI command wires it; the quickstart runs `benchmark`, and the only production
   front doors are the Python API and `databricks/runner.py`. Review B assumed a
   `run` command into existence; review A listed the commands correctly and drew no
   conclusion. For the "reusable toolkit" step both reviews describe, this is a
   material gap — an accelerator whose reduction path requires writing Python.
2. **The fail-open default is pinned by a test as intended behaviour**
   ([test_pipeline.py:295-298](../tests/test_pipeline.py)) — the flip both reviews
   want is a recorded behaviour change (ADR), not a default correction.
3. **`RunMetadata.language_detector_version` exists and nothing ever populates
   it** — the exact sibling of the `provider_versions` gap both reviews found;
   neither named it. One provenance increment should close both.
4. **A stale registry comment promises what never arrived:**
   [registries.py:35](../src/pii_reduction/config/registries.py) still says
   "`excel` arrives with Increment D, Spark/Delta with Increment F". Both
   increments are complete; neither added a source type. Trivial, but it is
   exactly the kind of doc-drift this repository elsewhere hunts down.
5. **The measurement path for a residual scanner already exists** (§2.1): the
   committed corpora and manifests can validate a manifest-free scanner before it
   ever sees real data. Neither review noticed that the thing they rank as the
   hardest missing capability has its acceptance test already built.

---

## 7. Decision table

Every material finding, classified. Bias applied toward REJECT and DEFER: an
accepted item must change what the system can honestly claim, be measurable on an
existing corpus, and have its costs recorded.

| # | Finding | Decision | Disposition |
|---|---|---|---|
| D1 | Fail-open default failure mode (both, top-ranked) | **ACCEPT** | Increment R1. Flip default to `quarantine_row`; ADR supersedes `docs/01`'s "often the safest default" advice; rewrite the pinned test; add the no-fail-open-row-in-reduced-artifact test; re-run both chains on benchmark + incident corpora to demonstrate no published number moves. |
| D2 | Run provenance: real model/library versions, `language_detector_version`, `source_version`, pseudonymization key id (A P1-5, B #7, §6.3) | **ACCEPT** | Increment R2. Populate what CI already knows matters. Non-secret key identifier (digest of the key) in `RunMetadata` only — not in tokens. No published number moves; metrics-schema drift handled deliberately. |
| D3 | Reduced-only projection / per-artifact destinations (A P0-2, B P0-3) | **ACCEPT** | Increment R3, ADR required. Opt-in reduced-only artifact locally + separate destination prefix support in `run_driver`. Makes `docs/09`'s grant model realisable. AGENTS rule 4 untouched — the projection is an additional artifact. Structural tests; no benchmark number. |
| D4 | README "discovering", docs/09 audit-sensitivity framing (§3.A3), pseudonymize frequency/`token_length` guidance, charter UC-03 unmet pointer, stale registries comment (§6.4) | **ACCEPT** | Increment R4, docs-only sweep. Each item is this repository's own honesty standard applied to its own text. |
| D5 | Referential consistency asserted but unmeasured (A E.2, B #12 partial) | **ACCEPT** (small) | Increment R5. A token-consistency/join-cardinality metric for the `pseudonymize` strategy over the committed corpus (repeated names exist by construction). Publishes a number for a currently unmeasured claim. |
| D6 | No CLI front door for a reduction (§6.1) | **ACCEPT** (owner may drop) | Increment R6. `pii-reduction run <dataset>` wiring over the existing `Pipeline.run()`. Small; changes the toolkit claim. |
| D7 | Residual verification without ground truth (A P0-5, B P0-2 — both call it the most important missing capability) | **DEFER** | Reopens when the owner selects the next major phase. It competes with the Phase-7 Greek model for that slot and needs its own design doc: a second-detector scan over reduced output, validated against the existing manifests (§6.5), never the reducer re-pointed at its own output (docs/10 §10). |
| D8 | Distributed audit/metrics fan-out (A P0-3, B #4) | **DEFER** | Condition: the serverless sandbox incident closes (a databricks-marked test already watches). Designing an unexecutable path would break this repo's own Databricks evidence rule. |
| D9 | Key rotation, KMS integration, re-tokenization, cross-worker collision authority (A P0-4 remainder, B #8) | **DEFER** | Condition: first real consumer of pseudonymized output. Key *identity* is D2; lifecycle without a consumer is speculative construction. Charter keeps reversible mapping out of scope. |
| D10 | Provider batching / `detect_batch` wiring / row-loop rewrite (A P1-1, B #5) | **DEFER** | Condition: Phase 7 provider work (where batching becomes load-bearing for transformer providers) or a demonstrated throughput need. Throughput is context, never a gate (ADR-0009); nothing published is dishonest today. |
| D11 | Rejected candidates persisted to the audit table (A P1-6) | **DEFER** | Condition: a consumer who needs per-candidate rejection data. Costs an audit-schema change that `append` reruns and the parity test depend on; aggregate counts exist and are published. |
| D12 | Long-text cap / chunker (A P2, B #5 partial) | **DEFER** | Condition: evidence of over-long documents in a target corpus. With D1 done, an over-long failure quarantines visibly instead of leaking, which removes the privacy half of the risk. |
| D13 | Note-history parser (A P1-3; charter UC-03) | **DEFER** | Condition: the speaker-prefix ADR decision (session 8's most serious open item) lands first — both concern prefix semantics and the second must not prejudge the first. `LabelledLineParser` makes the eventual cost low. |
| D14 | Publication + NOTICE emission (A P1-8) | **DEFER** | Owner decision, not an engineering increment. NOTICE-on-distribution is already recorded in plan §8. |
| D15 | Incremental/merge/checkpoint/restart, streaming, scheduling/SLOs, deployment bundle (both P1/P2) | **DEFER** | Roadmap Phase 10 territory, unchanged by the reviews. |
| D16 | Policy engine with role/purpose/consumer dimensions; approval lifecycle; human review queue; approved-run-manifest consumption (both P2) | **DEFER** | Both reviews agree this is new construction ("a second product built beside this one"). Condition: an actual adopter with a governance consumer. |
| D17 | UC tag integration (B P2 #13, A P3) | **DEFER** | Phase 9+; needs workspace features and an executing distributed path to matter. |
| D18 | Third provider / ADDRESS / broader taxonomy (both) | **DEFER** | Already ADR-0002 and roadmap Phase 7; the reviews add urgency, not evidence. B's LLM-threat checklist (§3.B5) is recorded as Phase 7 design input. |
| D19 | Alternative overlap policies / ensemble voting (B) | **DEFER** | Condition: a third provider exists. One policy for two providers is not a deficiency; ADR-0005's no-cross-provider-score rule stands. |
| D20 | Per-segment language / code-switching (both) | **DEFER** | Already in plan §8 deferrals; no corpus exists to measure it. |
| D21 | Estate discovery, DLP, multi-tenancy, RBAC, retention enforcement (both, as category boundaries) | **REJECT** | Out of category by charter and by both reviews' own positioning sections. Building any of them would be the "irrelevance by absorption" trap review A names. |
| D22 | Reversible tokenization vault (both mention) | **REJECT** | Charter non-goal, restated by ADR-0013. Both reviews concur it would be a different product. |
| D23 | Timestamp column on business output rows (B) | **REJECT** | `pii_run_id` joins to run metrics carrying both timestamps; a new output column changes the frame contract and parity surface for no honesty gain. |
| D24 | "No automated PII review before publishing packs" (B threat 12) | **DISPUTED** (partially) | Three implemented controls exist (registry-as-gate with `contains_real_pii`, pinned checksums with refusal on mismatch, pre-write hook); the residual truth — no content scan over derived pack text — is folded into D7's design scope. |
| D25 | CLI has a `run` entry point (B capability matrix) | **DISPUTED** | False; see §4.1. The corrected fact becomes D6. |
| D26 | "Nowhere in the architecture to put residual verification" (A P0-5) | **DISPUTED** | The evaluation layer and entry-point pattern are exactly the place (§2.1); the missing thing is the capability, not the location. Does not change D7's classification. |
| D27 | Global versions of the Greek repairs, cross-provider score comparison, corpus softening, threshold tuning — none demanded by either review, listed to close them | **REJECT** | Measured and rejected: ADR-0020/0021 (globals), ADR-0005 (scores), ADR-0019 (corpus), plan §8 (thresholds are constants). Any future change routes through superseding ADRs. |

Counts: 6 ACCEPT (four of them small), 14 DEFER with named conditions, 4 REJECT,
3 DISPUTED. The accepted set changes what the system can honestly claim (fail-closed
by default, attributable runs, a grantable reduced artifact, one honest tagline, one
measured claim that was previously asserted) and moves no published benchmark
number.

---

## 8. Proposed sequence (approved by the owner in session 9; written before any code changed)

> **Landing record.** File:line citations in this document are pinned to commit
> `985e8ea`, the tree both reviews and this reconciliation examined — R1's own
> commit moves some of them (the pinned fail-open test it rewrites, the
> `models.py` default line). R1 landed alongside this document as ADR-0023;
> later increments land as their own commits and are recorded in plan §8, not by
> editing this snapshot.

Ordered by leverage per unit of work, one increment at a time, each with
measure-before/measure-after and its own commit:

1. **R1 — fail-closed default** (D1, ADR-0023). The single highest-leverage change
   in either review; both chains re-run on both gated corpora to show zero movement.
2. **R2 — run provenance** (D2): model/library/detector versions, source version
   where available, pseudonymization key id. Trivial risk, closes the
   reproducibility half both reviews flagged plus §6.3.
3. **R3 — reduced-only projection** (D3, ADR-0024): the governance story becomes
   realisable instead of documented.
4. **R4 — docs honesty sweep** (D4): tagline, docs/09 audit framing, pseudonymize
   limitations, UC-03 pointer, stale comment.
5. **R5 — referential-consistency metric** (D5): cheapest unmeasured-claim fix,
   entirely inside `evaluation/`.
6. **R6 — CLI `run` command** (D6): optional; owner may drop.

Explicitly *not* in this sequence, flagged as separate projects rather than
increments: residual verification (D7 — the strongest candidate for the next major
phase, competing with the Phase-7 Greek model), distributed evidence (D8 —
infra-blocked), and everything in D15–D18.

The speaker-prefix ADR (session 8's own open item, corroborated by review A's T8)
remains the most serious *design* decision open and is deliberately not bundled
here: it needs its own session and its own ADR, per ADR-0022's reasoning that a
corpus must not motivate and validate a fix in the same commit.

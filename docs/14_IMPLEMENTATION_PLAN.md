# Implementation Plan

Produced by session 2 (2026-08-17) after repository assessment and empirical probes.
Decisions referenced as `ADR-NNNN` are recorded under `docs/adr/`. Probe evidence is
summarized in `docs/archive/SESSION_HANDOFF_S1-S8.md` (session 2 section).

This plan is the executable input for the implementation sessions. It respects
`AGENTS.md` (canonical agent policy), `docs/01_ARCHITECTURE.md` (layer boundaries),
and `docs/11_ROADMAP.md` (phasing), and records every deviation from them explicitly.

> **Start here: [§8 Status and work queue](#8-status-and-work-queue).** Sections 1–7
> are the original plan as written in session 2. §8 is the live state — what is built,
> what it measures, and what to do next. Sections 1–7 are amended in place where
> reality diverged; §8 is authoritative when they disagree.

---

## 1. Committed stack

| Concern | Choice | Where declared | Evidence / ADR |
|---|---|---|---|
| Core contracts/config | `pydantic` v2, `PyYAML` | core | ADR-0008 |
| Local execution | `pandas >=1.5,<3` | core | ADR-0006 (Spark parity pin) |
| Deterministic PHONE | `phonenumbers` | core | ADR-0001 |
| Deterministic EMAIL | stdlib `re` pattern | core | ADR-0001, ADR-0003 |
| NER provider | `presidio-analyzer` + spaCy | extra `presidio` | ADR-0001 |
| spaCy models | `en_core_web_lg`/`md`, `de_core_news_lg`/`md`, `xx_ent_wiki_sm` (el + fallback) | documented install, never a pip dependency | ADR-0001, ADR-0007 |
| Language detection | `lingua-language-detector` | extra `language` | ADR-0012 |
| Synthetic generation | `Faker` | extra `dev` | ADR-0010 |
| Spark runtime | Databricks Connect (workspace), `pyspark` optional | extra `databricks` | ADR-0006 |
| Repo licence | MIT | `LICENSE` (Increment A1) | ADR-0007 |

Explicitly rejected, with reasons in ADR-0001 and ADR-0012: `langdetect`
(probe: wrong on short strings — `Danke`→`da`, `Call me`→`it`), fastText LID
(model licence CC BY-SA; Windows build friction), `el_core_news_lg/md`
(**CC BY-NC-SA 3.0 — non-commercial; incompatible with MIT**, found by probe, not
recorded in any doc), transformer NER / GLiNER (deferred to roadmap Phase 7, not
rejected), stanza (heavier, no baseline advantage demonstrated).

## 2. Detection scope correction

`PERSON`, `EMAIL`, `PHONE` are the v0.1 *detected* baseline. `ADDRESS` stays in the
taxonomy, configuration, fixtures, and benchmark schema, but no shipped provider
claims it until a capable provider exists (roadmap Phase 7). Probes confirmed no
available permissively-licensed model emits an address-shaped label, and composing
one from `LOC`/`GPE` context rules failed on probe examples (German street number and
postal code not covered; Greek street tagged `ORG`). Shipping a weak ADDRESS detector
would poison the benchmark story. See ADR-0002. This corrects the Phase 2 exit
criteria in `docs/11_ROADMAP.md` and the "initial baseline" lists in `README.md` /
`docs/00_PROJECT_CHARTER.md`, which assumed ADDRESS was deliverable from the first
NLP provider.

## 3. Module layout

`src` layout. Modules follow `AGENTS.md`'s suggested boundaries with two adjustments:
a `contracts/` package is added as the dependency hub (`docs/01_ARCHITECTURE.md`
already requires "dependencies flow inward toward shared contracts"), and
`databricks/` is **not created** until Phase 6 work starts (no placeholder modules).
Phase 6 has since started and finished: `databricks/` exists as of Increment F and is
listed below.

```text
src/pii_reduction/
├── contracts/        # typed core objects: TextSegment, LanguageResult, EntityMatch,
│                     # ResolvedEntity, ReductionOperation, ProcessedFieldResult,
│                     # RowResult, RunMetadata. No imports from any other package.
├── config/           # pydantic models for project/dataset/provider/language config,
│                     # YAML loading, layered merge, validation, config fingerprint.
├── entities/         # normalized taxonomy, the label-mapping *machinery*
│                     # (the per-model tables themselves live with their provider
│                     # adapters — ADR-0004 supersedes this line, resolved in A1),
│                     # deterministic overlap reconciler.
├── sources/          # SourceAdapter protocol + pandas/CSV adapters (Excel later).
├── parsers/          # Parser protocol + PlainTextParser + TranscriptParser,
│                     # each with reconstruct() and the round-trip invariant.
├── language/         # LanguageDetector protocol, explicit/static resolver,
│                     # lingua adapter, short-text policy (Increment C).
├── providers/        # PIIProvider protocol, DeterministicProvider (EMAIL, PHONE),
│                     # PresidioProvider adapter (Increment B). Provider-native
│                     # labels never cross this boundary.
├── reducers/         # Reducer protocol + Redact/Mask/Pseudonymize reducers
│                     # (mask + pseudonymize pulled into A4 by ADR-0013).
├── processing/       # pipeline builder + field processor: parse → resolve language
│                     # → detect → reconcile → reduce → reconstruct; failure policy.
├── outputs/          # OutputAdapter protocol + local parquet/pandas writers.
├── evaluation/       # strict/relaxed span matching, P/R/F1, leakage, over-redaction,
│                     # manifest-driven ground truth loading. Never imported by
│                     # processing/.
├── observability/    # run metrics accumulation, privacy-safe logging helpers.
├── synthetic/        # build-time: corpus generation, injection, the public-dataset
│                     # registry, retrieval and the demo pack builder. Added in A6 and
│                     # extended in D; §3 originally put this under `demo/`, which
│                     # AGENTS.md rule 3 correctly overrode — `demo/` holds runnable
│                     # front doors only. Depends on the interface layers; nothing on
│                     # the runtime path depends on it (docs/01_ARCHITECTURE.md).
└── databricks/       # the Databricks *execution surface* (Increment F): session,
                      # SparkTableSource, DeltaTableOutput, run_driver and the
                      # mapInPandas distributed_frame. Sits at the outermost edge
                      # beside cli.py/benchmark.py, not beside sources/outputs — it
                      # decides where a run happens, not what a run does. The only
                      # package allowed to import pyspark/databricks.connect, asserted
                      # by an AST scan over src/ (test_package.py), which a subprocess
                      # import check cannot do. Nothing in src/ imports it; only its
                      # own tests do.
```

Repo level, created only when their first content lands: `configs/` (YAML shipped
with the demo), `tests/`, `demo/` (runnable front doors for corpus and pack builds; the logic
lives in `synthetic/`), later `notebooks/`,
`resources/`.

Dependency direction (enforced by architecture-guardian review at each increment):
everything imports `contracts/`; `providers/` and `processing/` import `entities/`
(taxonomy and reconciler); `processing/` additionally imports the protocols of
sources/parsers/language/providers/reducers/outputs; nothing imports `processing/`
except entry points; `evaluation/` is imported by benchmark entry points only.
Entry points (the A6 demo/benchmark runner CLI) live under `demo/` and a thin
`pii_reduction.cli` module — never inside `processing/`, which keeps `processing/`
free of any `evaluation/` import. `databricks/` joins them as an execution
surface: like the CLI it may import `processing/`, and like the CLI nothing on the
runtime path imports it, so the dependency direction is unchanged by its arrival.

## 4. The first vertical slice

One end-to-end path, local only, no NLP model required (roadmap Phases 0 + 1 subset,
plus a thin slice of Phases 4 + 5 pulled forward — deviation recorded in §6):

```text
committed synthetic corpus (en/de/el, built by demo/ generator with seed + manifest)
  → CSV/pandas source adapter
  → dataset contract from configs/datasets/demo_smoke.yaml
  → PlainTextParser / TranscriptParser
  → static language resolution (language column from corpus; detector comes in C)
  → DeterministicProvider (EMAIL, PHONE)
  → reconciler → RedactReducer → reconstruction
  → validation (row count, originals unchanged, round-trip) 
  → local parquet output + run-metrics JSON
  → evaluation against the injection manifest → metrics table printed/persisted
```

This proves every architectural boundary with the cheapest possible providers, gives
the benchmark a working skeleton from day one, and leaves PERSON quality to
Increment B where Presidio joins.

## 5. Increments

Each increment is one finishable, verifiable unit ending with `/qa` green and the
listed tests passing. No increment starts before the previous one's exit criteria
hold.

### A1 — Package foundation
- `pyproject.toml` (core deps only, extras declared: `presidio`, `language`,
  `databricks`, `dev`), `LICENSE` (MIT), `src/pii_reduction/{contracts,config,entities}`.
- Contracts implement the invariants of `docs/03_DATA_CONTRACTS.md`
  (`0 <= start < end <= len(text)`; normalized labels only). Field name is
  `supported` on `LanguageResult` — `docs/01_ARCHITECTURE.md`'s `is_supported`
  variant is superseded by `docs/03`'s `supported` (inconsistency resolved here).
- Config loader: layered merge (project → dataset → column), actionable
  `ConfigurationError` messages, config fingerprint hash excluding secrets.
- **Tests:** contract invariant unit tests; config validation (unknown parser name,
  missing column, bad entity label → actionable errors); fingerprint stability;
  taxonomy mapping tables (`PER`→`PERSON`, `EMAIL_ADDRESS`→`EMAIL`, …).
- **Exit:** `pip install -e .[dev]` + `pytest` green in a fresh venv with no NLP
  model or provider extra installed.

### A2 — Parsers
- `PlainTextParser`; `TranscriptParser` handling `timestamp - speaker: body` and
  `speaker: body` forms, prefix preserved as non-processable segment.
- **Tests (the parser list from `docs/10_TESTING_QA.md` §2):** round-trip
  `reconstruct(parse(text)) == text` for every fixture; multiple colons in body;
  URLs and times in body; empty turns; malformed lines (fallback: whole line becomes
  one processable segment, fallback recorded); mixed `\n`/`\r\n` (byte-exact —
  fixtures under `tests/fixtures/` are `.gitattributes`-binary already); Greek/German
  names in prefixes; no-delimiter input; empty string; None handled at caller
  contract.
- **Exit:** round-trip invariant holds on all fixtures including CRLF and NFD ones.

### A3 — Deterministic provider
- `DeterministicProvider`: EMAIL via anchored regex (accepts any dot-TLD ≥2 alpha,
  including `.test` — broader than Presidio's default, see ADR-0003), PHONE via
  `phonenumbers.PhoneNumberMatcher` with configurable default regions.
- **Tests (provider contract, `docs/10_TESTING_QA.md` §4):** normalized labels;
  valid offsets (slice equality); entity-scope respected (asking for EMAIL only
  returns no PHONE); empty text; no source mutation; provider identity exposed;
  phone formats: `+30`/`+49` international, `0030` prefix, parenthesized US,
  extension suffix; email at string start/end, punctuation-adjacent, `.test` and
  `example.com` domains both detected.
- **Exit:** contract tests green; offsets verified by slice equality on Greek text
  containing an email (non-Latin prefix shifts offsets — probe-verified codepoint
  semantics).

### A4 — Reconciliation, reduction, reconstruction
- Deterministic reconciler implementing the 7-step algorithm of
  `docs/04_PII_ENGINE.md` (priority: EMAIL/PHONE > ADDRESS > PERSON, then score,
  span length, provider priority; all configurable).
- `RedactReducer` with right-to-left replacement; reconstruction of transformed
  segments into the full field.
- **Tests:** overlap fixtures (email-inside-person, nested person fragments,
  identical spans from two providers); adjacent entities; replacement at string
  start/end; repeated entity; Unicode (Greek + NFD combining chars + emoji before
  entity — spans stay codepoint-true, probe-verified); non-processable segments
  byte-identical after reduction; idempotency (redacting already-redacted text
  changes nothing when tokens aren't PII-shaped).
- **Exit:** transcript demo case from `docs/12_DEMO_SCENARIOS.md` Demo 2 passes
  with prefixes byte-identical.

### A5 — Pipeline, sources, outputs, observability
- pandas + CSV source adapters; local parquet/pandas output adapter; pipeline
  builder `build_pipeline(config)`; failure mode
  `preserve_original_and_record_error` (default changed to `quarantine_row` by
  ADR-0023 — the mode itself remains); run metrics (rows, fields, entities
  detected/reduced, failures, fallbacks, timing) as metadata only.
- **Tests:** null input → null output; empty string deterministic; row count
  preserved; originals unchanged; output column created; duplicate row-id detection;
  a failing parser on one row doesn't fail the run and is counted; **privacy test**:
  captured logs and raised exceptions contain no fixture PII values
  (`docs/10_TESTING_QA.md` §9).
- **Exit:** `pipeline.process(dataset)` runs end-to-end on a 20-row fixture; run
  metrics JSON matches schema; log capture clean.

### A6 — Synthetic corpus + minimal evaluation (first slice complete)
- `demo/build_corpus.py`: template + Faker generation, seeded, en/de/el, difficulty
  tiers 1–4 of `docs/02_PUBLIC_DATA_STRATEGY.md`, negative examples (INC/KB/machine
  IDs), plain + transcript forms. Emits corpus CSV + injection manifest (exact
  spans recorded at injection time against the exact emitted string — no Unicode
  normalization anywhere, ADR-0011). Commit a small generated corpus
  (~100 docs) under `tests/fixtures/corpus/` as the deterministic regression set.
- `evaluation/`: strict span match (primary), relaxed IoU≥0.5 + type match
  (secondary), P/R/F1, leakage rate, over-redaction rate, document clean rate, by
  entity × language × tier, support counts mandatory.
- **Tests:** metrics functions against hand-computed cases (`docs/10_TESTING_QA.md`
  §8); manifest loader rejects spans that don't slice-match their document — and
  its rejection error reports document id and offsets only, never the expected
  surface string (privacy-safe even against non-fixture data; covered by the A5
  log/exception privacy test); regenerating the corpus with the same seed is
  byte-identical.
- **Exit:** one command runs the slice end-to-end and prints the benchmark table;
  EMAIL/PHONE strict recall on the committed corpus ≥0.95 (deterministic providers
  on synthetic text should be near-perfect; if not, the corpus or provider has a
  bug — this is the first honest gate). PERSON rows report zero detection —
  expected and displayed, not hidden.

### B — Presidio provider (roadmap Phase 2)
- `PresidioProvider` adapter: multi-language `AnalyzerEngine` (en=`en_core_web_lg`,
  de=`de_core_news_lg`, el=`xx_ent_wiki_sm`), model names configurable, engine built
  once per process, per-recognizer thresholds from config (defaults per ADR-0005:
  PERSON ≥0.5, EMAIL ≥0.6, PHONE ≥0.3 — a single global threshold is forbidden
  because PhoneRecognizer emits 0.40, probe-verified). Presidio-native labels
  (`EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `URL`) mapped/dropped at the
  adapter boundary; `URL` discarded (probe: partial-match noise like `maria.ro`).
- Provider chain: deterministic + presidio, reconciler resolves.
- **Tests:** integration-marked (need models): PERSON detected in en/de/el
  fixtures; label normalization; threshold filtering; engine-reuse (constructing
  provider twice doesn't reload models — timing assertion with generous bound);
  contract tests run against it via the shared provider test suite.
- **Exit:** benchmark table from A6 rerun with `deterministic_only` vs
  `deterministic+presidio` chains; PERSON F1 now nonzero for en/de/el; German PER
  → PERSON confirmed via shared suite; limitations documented (Greek boundary
  fuzziness — probe showed `Ονομάζομαι` absorbed into the PERSON span — visible in
  relaxed-vs-strict gap).

### C — Language detection and routing (roadmap Phase 3)
- `LinguaDetector` restricted to configured languages; short-text policy: min 20
  chars **and** min 12 alphabetic chars after stripping emails/URLs/digits
  (probe: `maria@example.com` alone yields a spurious `en`
  0.95), min confidence 0.70, else `und`; `und` routes to the safe fallback chain
  (deterministic-only by default). Confidence recorded per segment; aggregate
  scope for multi-segment fields.
- **Tests:** routing behavior per `docs/10_TESTING_QA.md` §3 (long en/de/el,
  short strings route to fallback, email-only text routes to fallback, mixed text
  takes dominant language, unsupported language recorded); determinism of detector
  results; no text in logs.
- **Exit:** three languages end-to-end with detection instead of the static column;
  language distribution + fallback counts appear in run metrics; README claims
  match measured coverage.

### D — Public dataset demo builder (roadmap Phase 4)
- Dataset registry (`demo/registry.yaml`) with licence/provenance per
  `docs/02_PUBLIC_DATA_STRATEGY.md`; download scripts (no raw data committed):
  Bitext support tickets (CDLA-Sharing-1.0; template placeholders become injection
  points), MultiWOZ 2.2 (**rejected in session 6 — real PII in its published text, ADR-0018**; the transcript pack is rendered from Bitext instead), MASSIVE de/el
  (CC BY 4.0; multilingual short text). Injection at scale reusing the A6 engine.
- **Exit:** each demo pack reproducible from documented commands; provenance
  registry complete; injected ground truth validates against documents.

### E — Benchmark framework hardening (roadmap Phase 5) — **complete, see §8**
- Slice metrics by document type; runtime metrics (cold/warm init, rows/sec);
  Markdown benchmark report generator; benchmark run metadata (config hash,
  model versions); splits are 20% dev / 20% calibration / 60% test per `docs/02`
  and ADR-0011 — thresholds are calibrated on the **calibration split only**, then
  locked, and the test split is reported exactly once (`AGENTS.md` benchmark
  integrity).
- **Exit: met** (session 6). Two chains compared end-to-end on a 10,000-document
  pack, committed report at `docs/16_BENCHMARK_REPORT_10K.md`, gate values chosen
  from that baseline in `configs/pack_gates/support_tickets_10k.yaml`. Two written
  deviations from the wording above: "cold/warm init" became process-time
  measurement recorded as such, because model loading is lazy and the code has no
  init phase to time separately; and the 10k gates run on demand rather than in CI,
  because building the pack needs a download and CI is deliberately offline
  (ADR-0017) — the CI floors remain `configs/benchmark_gates.yaml`, which now also
  gate the fragment-leakage variant. Threshold calibration turned out to be a
  null operation with reasons (§8): every score is a recognizer constant, so the
  thresholds were reviewed and locked rather than moved.

### F — Databricks execution (roadmap Phase 6)
- Via Databricks Connect against the authenticated workspace (ADR-0006; local JDK
  path blocked — Java 22 only, probe-verified). Spark source/Delta output adapters,
  batched inference via `mapInPandas` with worker-level model init, run-metrics
  and audit Delta tables, catalog/schema names from config/env only.
- **Exit:** local vs Databricks parity on the shared 100-row fixture
  (deterministic chain, output hash equality — Demo 8); no per-row model loading;
  `databricks`-marked tests excluded from CI.

### Explicitly deferred
- Note-history parser (after C, when transcript parser has proven the contract —
  deviation from roadmap Phase 1, §6).
- Excel source adapter (with D; needs `openpyxl` only then).
- ADDRESS detection (Phase 7 provider work, ADR-0002); ~~masking + pseudonymization
  (Phase 8)~~ — **built in A4 instead, ADR-0013**; transformer/GLiNER/LLM providers
  (Phase 7); dashboards, Databricks App, notebooks (Phase 9+); reversible
  pseudonymization (out of scope per charter).

## 6. Deviations from the roadmap, with reasons

1. **Minimal evaluation moves into the first slice (A6)** instead of waiting for
   Phases 4–5. Phase 2's exit criteria already demand precision/recall on a
   synthetic corpus, which is impossible without an evaluator — the roadmap is
   internally inconsistent there. Pulling a thin evaluator forward resolves it and
   honors the roadmap's own prioritization rule ("prefer better evaluation").
2. **Note-history parser and Excel adapter leave Phase 1.** Baseline scope for this
   plan is PlainText + Transcript; a third parser and third source before the first
   measured baseline is breadth without evidence.
3. **ADDRESS leaves the Phase 2 exit criteria** (ADR-0002).
4. **Phase 6 targets Databricks Connect first**, not local Spark (ADR-0006).

## 7. Risks that would invalidate parts of this plan

- If Databricks Connect version constraints conflict with the local `pandas` pin,
  Phase 6 needs an isolated extra or a dedicated environment (mitigation: the
  `databricks` extra is already isolated; parity tests run on fixtures, not on
  shared interpreter state).
- If Bitext's CDLA-Sharing-1.0 share-alike terms prove awkward for redistributing
  *derived* injected corpora — **the MultiWOZ (MIT) fallback this line proposed no
  longer exists.** Session 6 rejected MultiWOZ for carrying real PII (ADR-0018), and
  Bitext now renders both English packs. Since no pack is committed, the obligation
  travels no further than the machine that built one; publishing a pack would need a
  new permissively-licensed source.
- Greek NER quality via `xx_ent_wiki_sm` may be too weak to present honestly; the
  benchmark will show it, and the honest fallback is reporting Greek as
  deterministic-entities-only until Phase 7 adds a multilingual transformer.

---

## 8. Status and work queue

**This section is the live one.** Sections 1–7 are the session-2 plan as written;
where reality diverged, the divergence is recorded here and in the ADR it produced.
Update this section at the end of every session.

Last updated: session 11 (2026-08-21) — **rung 4 is built: the service layer
exists, and both of its runtimes have been executed.** ADR-0026 decided its shape (a
thin HTTP API, hosted later as a Databricks App rather than built as one), the
privacy contract was extended to rendered output, API responses and request payloads
*before* any endpoint was written, and the surface was then driven over real HTTP —
locally over 102 corpus documents, and on the workspace over a 25-row Unity Catalog
table with the hybrid chain. What remains **blocked** is unchanged and
environmental, and there are two of them: `bundle deploy` needs a newer CLI, and the
distributed path is still `ISOLATION_STARTUP_FAILURE`. What remains **open** is
design work — the five-item list at the end of this section, headed by *hosting the
service*, which is undone rather than blocked (no Databricks App has been created;
the workspace-UI route is untried). Running the API against the workspace and hosting
it inside the workspace are different claims, and only the first has been made.
**Session 12 has a different course**, set by the owner after this section was
written: compare this repository against the separate reference implementation at
`..\pii_alternative` and implement only what that comparison justifies. The five-item
pickup list at the end of this section is **paused, not cancelled** — see the session
11 addendum in `.claude/SESSION_HANDOFF.md` for the task, the Class B rules that come
with it, and the two environment facts it will hit immediately. Previously: session 10
(2026-08-20/21) — the platform queue's P0–P4 shipped and the Databricks half was
verified by real workspace runs. Previously: session 9 (2026-08-19) — two independent external reviews reconciled
(`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md`: every load-bearing claim verified
against the code, decision table of 6 ACCEPT / 14 DEFER / 4 REJECT / 3 DISPUTED, the
R1–R6 sequence approved by the owner), and the R increments started landing — see
the session-9 rows in the Complete table and the queue below.

### Complete

| Increment | What landed | Evidence |
|---|---|---|
| A1 | `pyproject.toml`, MIT `LICENSE`, `contracts/`, `config/`, `entities/` | 90 tests |
| A2 | `parsers/` — plain text + transcript, byte-exact round trip | 183 tests |
| A3 | `providers/` — deterministic EMAIL/PHONE, shared provider contract suite | 244 tests |
| A4 | `entities/reconcile.py`, `reducers/` — redact **+ mask + pseudonymize** (ADR-0013) | 316 tests |
| A5 | `sources/`, `outputs/`, `observability/`, `processing/` — `build_pipeline` runs | 378 tests |
| A6 | `synthetic/`, `evaluation/`, `benchmark.py`, `cli.py`, `configs/`, committed corpus | 447 tests |
| B | `providers/presidio_provider.py`, `docs/15_PROVIDERS.md`, chain comparison | +45 integration |
| C | `language/` — lingua detector, ADR-0012 gate, per-language provider routing | 480 default / 71 integration |
| Q1 | `.github/workflows/{ci,integration}.yml`, `evaluation/gates.py`, `configs/benchmark_gates.yaml` | 511 default / 72 integration |
| Q2 | span repair at the provider boundary, identifier guard, `key_value` parser, `split_lines` (ADR-0016) | 682 default / 73 integration |
| D (part) | `synthetic/injection.py`, `synthetic/registry.py`, `demo/registry.yaml` | 730 default / 73 integration |
| D | `synthetic/fetch.py`, `synthetic/public.py`, `synthetic/packs.py`, `fetch-dataset` + `build-pack`, three demo packs and their gate sets (ADR-0017, ADR-0018) | 807 default / 73 integration (799 when D first landed; the audit-fix commit added 8) |
| Q4 | Greek PERSON diagnosed: span absorption, label confusion, άνω τελεία (ADR-0019). No number moved — the corpus is deliberately not made easier | 809 default / 87 integration |
| E (part) | ADR-0013 §5's two leakage variants: `fragment_leakage_rate` beside `leakage_rate` (now gated: 0.433 det / 0.067 hybrid), `strategy` in the metric-row grain, `--strategy` on the CLI, `with_reducer`; gates compare the run's strategy to the file's recorded one at the data level | 828 default / 87 integration |
| E | Run provenance (`RunMetadata` + `RuntimeMetric` on the outcome, config hash + rows/s in the summary), threshold calibration reviewed on the calibration split and locked (constants — nothing to tune), the one-time test-split read, and the 10k-document two-chain comparison with its own gate set (`docs/16_BENCHMARK_REPORT_10K.md`, `configs/pack_gates/support_tickets_10k.yaml`) | 838 default / 87 integration |
| F | `databricks/` package (see the F section below) — parity met on the workspace, distributed path shipped and infra-blocked, audits applied (run identity across warm workers, exact-set audit-schema assertion, schema-drift test, Spark-free guard extended) | 854 default / 90 deselected incl. 3 databricks |
| Review | `docs/17_EXTERNAL_REVIEW_RECONCILIATION.md` — two external assessments reconciled against the code; both factually reliable, three claims disputed with evidence, five findings both missed surfaced from inside | no code changed by the reconciliation itself |
| R1 | Fail-closed default: `failure_mode` defaults to `quarantine_row` in the model and the shipped config (ADR-0023); pass-through is an explicit opt-in; fixture runs the true default; fail-closed property pinned by test | 919 default (917 before), 41/41 gates re-run before and after — no published number moved |
| R2 | Run provenance: `provider_versions` carries real library **and model** versions (importlib.metadata — nothing imported, no model loaded, degrades to the bare type without the extra), `language_detector_version` populated for detect-mode columns, `SparkTableSource` records `delta_v<N>` best-effort (fake-session unit tests; the parity test asserts it on the next workspace run), and `pseudonymization_key_id` — a non-secret HMAC-derived key digest, so rotation is a visible provenance change. `provider_distributions` lives in `providers/registry.py` (provider knowledge stays with providers); `key_id` is a `BaseReducer` contract attribute | 937 default (+18), 41/41 gates — no published number moved |
| R3 | Reduced-only projection (ADR-0024): opt-in `destination.projection: reduced_only` writes the artifact without the configured raw text columns; `run_driver(reduced_only_prefix=...)` writes `<dataset>_reduced_only` to a separate `catalog.schema` — docs/09's grant model is now realisable with shipped code. In-memory processing unchanged (rule 4 holds); the confused combination with in-place replacement is refused at config validation; parity test asserts the projection on its next workspace run | 944 default (+7), 41/41 gates — no published number moved |
| R4 | Docs honesty sweep (docs/17 D4): README tagline no longer claims "discovering"; docs/09 and docs/03 §12 now state the audit table's span-length disclosure and govern it like reduced output; pseudonymize documents the frequency/co-occurrence limit and correct birthday-bound sizing (both auditors independently caught a wrong first draft of the 12-hex figure — fixed before commit); charter UC-03 carries its unmet status; the stale registries comment is corrected | docs/comments only — 944 default unchanged, no behavior change |
| R5 | Referential consistency of pseudonymization, **measured** (docs/17 D5): `evaluation/consistency.py` + an end-to-end test over the committed corpus, deterministic chain, `pseudonymize` strategy. **Result: consistency 1.000, distinctness 1.000 over all 102 EMAIL/PHONE occurrences, per dataset scope — and the same value gets different tokens across the two dataset scopes, so scope isolation holds end to end.** Test-tier by design (the pipeline outcome retains no per-operation replacements for the benchmark to consume); pinned on every push by the default tier | 951 default (+7), docs/08 records the metric |
| P3/P4 hardening | Three real job runs found what no unit test could: a wheel task **ignores the entry point's return value** (a failed reduction was reported as a green job), raising `SystemExit` unconditionally then broke the opposite direction (Databricks runs the task under IPython, where `SystemExit(0)` is also an error, so a successful run was marked failed), and `run_driver` refused non-table sources so the front door could not run the volume config the runbook publishes. All three fixed and both exit directions re-confirmed against real jobs | 1029 default (+14); databricks tier 3 passed / 2 skipped; `bundle validate` OK; `bundle deploy` blocked by the CLI's expired Terraform key |
| R6 | `pii-reduction run <dataset>` — the reduction finally has a CLI front door over the existing `Pipeline.run()` (one external review's capability matrix asserted this command existed; it did not). Metadata-only summary; exit 1 when any field failed, so partial output looks like a failure to a scripted caller | 956 default (+5) incl. metadata-only stderr guards on the failure path |
| P0 | Handoff sessions 1–8 archived to `docs/archive/SESSION_HANDOFF_S1-S8.md` behind a per-session evidence index; two stale plan pointers retargeted. Nothing else pruned, no ADR touched | 956 default, unchanged — docs only |
| P1 | **ADR-0025: Azure Databricks is the primary deployment target.** README gains a Deployment target section, the charter's *Portability* quality is amended in place, the roadmap records that it is no longer the live sequence, docs/07 sharpens "for larger workloads". Records the platform ladder and the PHI horizon as a horizon, not a promise | 956 default, unchanged — docs only |
| P2 | **A dataset YAML names a Unity Catalog table end to end.** `spark_table`/`delta_table` become typed config models and registry names; the local registries refuse them with an instruction naming the driver path; `run_driver` resolves table, prefix and mode from config (explicit args still win); `pii-reduction-databricks` is the front door, inside the surface because the import guard forbids a flag on the core CLI. Three defects found in review, two destructive: local `mode: overwrite` was inherited by the Delta writer, a run could write over the table it reads, and the CLI leaked Connect's message (workspace URL) on its crash path | 990 default (+34) |
| P3 (part) | `docs/18_RUNBOOK_DATABRICKS.md`, and **authentication that does not require the Databricks CLI** — profile, `DATABRICKS_HOST` + token or service principal, or ambient compute credentials (ADR-0006 amended; its original text always said "profiles or env"). The parity fixture no longer gates on the profile variable, so token auth no longer silently skips every workspace test. **Workspace execution outstanding** at the time of this commit; partly met on 2026-08-20 — see the queue | 1001 default (+11) |
| P4 | `databricks.yml` + `resources/` — one job, one task, the same entry point; CLI-free path documented; zero hard-coded workspace values, pinned by a glob-discovered guard. **Never deployed.** Also caught here: `mypy src tests` (the CI invocation) had been broken by P2/P3 for two increments — 21 errors, all in `tests/` — because `/qa` ran only `mypy src`; both skills were aligned with CI in the session close-out | 1015 default (+14); `mypy src tests` clean |
| S1 | **ADR-0026: rung 4 is a thin HTTP API**, and a Databricks App is how it gets hosted rather than a second surface to build. `AGENTS.md` rule 8 and a new `docs/09` section extend the observability rule from logs to every channel crossing the process boundary — rendered output, response bodies, error payloads, redirects, downloads — and to the **inbound** half (uploads, query strings, access-logged bodies, a framework's own 422 echoing the input it rejected). Span offsets and per-entity confidence moved off *Safe to log*, where the prose had been wrong since it was written and the shipped `ALLOWED_FIELDS` never agreed with it. A Class A carve-out keeps the Phase 9 demo surface legal without creating a service endpoint; a future side-by-side view now carries seven conditions (added: read under the end user's identity, record each disclosure) instead of five | 1029 default, unchanged — docs only; landed **before** any endpoint existed, which is the order the privacy auditor asked for when ADR-0025 shipped |
| S2 | **The service layer** (`src/pii_reduction/service/`): a config **builder** over server-side templates, a run **trigger** over both entry points, a metadata-only **status view**, and `pii-reduction-service` as a third console script. Four static guards make the rung rule code rather than prose — nothing outside `service/` imports it; `service/` may not name providers, reducers, parsers, language, entities, evaluation, sources, outputs, synthetic, or anything under `processing/` except `pipeline`; exactly one file may import the Databricks surface and still may not name `pyspark`; and `config/`, now the sanctioned relay, is bounded to `contracts/` and `entities/`. No endpoint accepts text and none returns, streams or links to any — enforced by a reflection test over every model rather than by a filter | 1090 default (+61); driven over real HTTP three times during the increment, and on the workspace once (docs/19 *Verified, by running it*) |

### Measured baseline (regenerate with `pii-reduction benchmark`)

102 documents, 180 injected entities, en/de/el, tiers 1–4, `redact`:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | 0.910 |
| relaxed F1 | 0.723 | 0.921 |
| leakage rate | 0.433 | 0.067 |
| fragment leakage rate | 0.433 | 0.067 |
| document clean rate | 0.161 | 0.871 |
| over-redaction rate | 0.000 | 0.000 |
| PERSON precision / recall | 0.000 / 0.000 | 0.771 / 0.821 |

PERSON strict recall by language and tier, hybrid chain:

| language | tier 1 clean | tier 2 noisy | tier 3 structured | tier 4 transcript |
|---|---|---|---|---|
| en | 1.000 | 0.889 | 1.000 | 1.000 |
| de | 1.000 | 1.000 | 1.000 | 1.000 |
| **el** | **0.556** | **0.667** | **0.333** | **0.000** |

Language detection against the corpus's known language: 99/102 agreement, **zero**
confident misclassifications, 3 abstentions to `und`.

The hybrid column moved in session 8 with ADR-0020's label promotion and ADR-0021's
span extension; the
deterministic column has not moved since session 4, when every number here was
re-measured and reproduced exactly. They are all enforced: `configs/benchmark_gates.yaml`
holds them as gates, so this table and that file must agree.

**What ADR-0020 and ADR-0021 traded, in one place.** Promotion cost strict F1
0.902 → 0.899 and PERSON precision 0.833 → 0.747; the span extension then returned
both and more, to 0.910 and 0.771. Net against the pre-promotion baseline: strict F1
0.902 → 0.910 and PERSON precision 0.833 → 0.771, against leakage 0.117 → 0.067,
document clean rate 0.774 → 0.871,
relaxed F1 0.914 → 0.921, PERSON recall 0.705 → 0.821, and Greek tier 1/2 recall
0.222 → 0.556 and 0.111 → 0.667. Over-redaction stays 0.000 and **English and German
are numerically unchanged** — promotion is scoped to the Greek provider instance,
because the global version was measured and rejected.

### Public-dataset packs, measured beside the synthetic corpus

**Beside, not instead of.** The table above is the committed regression corpus and the
floors in `configs/benchmark_gates.yaml` still guard it. Each pack below is a *new*
gate set on its own corpus (`configs/pack_gates/<pack>.yaml`) and is never a reason to
loosen a synthetic floor.

No pack is committed. Each is rebuilt from a pinned, checksummed source (ADR-0017):

```bash
python demo/download_datasets.py                  # fetch and verify, or let build-pack do it
python demo/build_pack.py support_tickets
pii-reduction benchmark --corpus demo/packs/support_tickets     --chain deterministic_presidio --gates configs/pack_gates/support_tickets.yaml
```

| pack | source | type | tier | documents | entities | protected |
|---|---|---|---|---|---|---|
| `support_tickets` | Bitext (CDLA-Sharing-1.0) | plain | 1 | 200 | 600 | 56 |
| `support_conversations` | Bitext, same rows as turns | transcript | 4 | 200 | 600 | 56 |
| `multilingual_utterances` | MASSIVE de/el (CC BY 4.0) | plain | 2 | 200 | 400 | 0 |

Measured 2026-08-18, seed 42, `redact`, whole pack:

| metric | tickets det. | tickets hybrid | conversations det. | conversations hybrid | utterances det. | utterances hybrid |
|---|---|---|---|---|---|---|
| strict precision | 1.000 | 0.995 | 1.000 | 0.998 | 1.000 | 0.926 |
| strict recall | 0.667 | **1.000** | 0.667 | **1.000** | 0.667 | 0.935 |
| strict F1 | 0.800 | 0.998 | 0.800 | 0.999 | 0.801 | 0.930 |
| relaxed F1 | 0.800 | 0.998 | 0.800 | 0.999 | 0.801 | 0.930 |
| leakage rate | 0.333 | **0.000** | 0.333 | **0.000** | 0.333 | 0.065 |
| document clean rate | 0.000 | 1.000 | 0.000 | 1.000 | 0.335 | 0.870 |
| over-redaction rate | 0.000 | 0.000 | 0.000 | 0.000 | n/a | n/a |

PERSON strict recall by language, hybrid chain:

| | en (tickets) | en (conversations) | de | el |
|---|---|---|---|---|
| recall | 1.000 | 1.000 | **1.000** | **0.606** |
| precision | 0.985 | 0.995 | — | — |

Five things these numbers say that the synthetic corpus cannot:

1. **The deterministic recognizers did not merely fit the corpus they were built
   against.** EMAIL and PHONE hold at 1.000 precision *and* recall on 1,600 entities in
   public prose, in three languages and two scripts, including lower-case unpunctuated
   Greek.
2. **Greek PERSON recall is 0.727 here against 0.556–0.667 on the synthetic corpus**
   (session-6 reading: 0.606 against 0.111–0.222; ADR-0020 and ADR-0021 moved both
   sides, and the gap narrowed without closing),
   with the same `xx_ent_wiki_sm` model and the same name pool, while German is 1.000.
   The two corpora are not comparable slice for slice — different phrasing, different
   tier mix, and a pack's names sit in well-formed injected sentences — so this is not
   a claim that Greek detection improved. It is evidence that the *synthetic Greek
   templates* account for part of a gap that has been treated as a pure licensing limit
   since ADR-0007, and it is the most valuable lead this increment produced.
3. **Precision is where public text is hard.** Recall is 1.000 on both English packs;
   the only detection errors are false positives in prose nobody wrote for us (PERSON
   precision 0.985 and 0.995). A template corpus cannot show this, because its non-PII
   text was written by the same hand as its entities.
4. **The transcript parser survives text it was not designed against.** Same sentences,
   same entities, two parsers: the conversation pack scores 0.999 to the ticket pack's
   0.998, and every speaker prefix reconstructs. PERSON precision is *higher* under
   line-scoped segments (0.995 vs 0.985) — the mirror image of ADR-0016's finding that
   line-scoping costs context where a name genuinely spans a break.
5. **Over-redaction stays 0.000 on identifiers that came from the source**, not from a
   template of ours: the 56 order numbers substituted into the Bitext text.

Limitations, stated so the numbers are not read as more than they are:

- **The two English packs are one measurement, not two.** Same source rows, same
  document ids, same injected values; only the rendering and the parser differ.
- **Injected values come from the same pools as the synthetic corpus** (eight names per
  language, ADR-0014). A pack measures the realism of the surrounding *text*, not the
  diversity of the values, so high recall partly reflects names the provider has
  already seen in the committed corpus.
- **Names sit in well-formed injected sentences.** "My name is …" is an easier context
  than a bare name in a signature block, which is why recall is 1.000 while precision
  is not.
- **`multilingual_utterances` has no over-redaction number.** MASSIVE carries no
  identifiers, so the metric has zero support and no gate is written for it — a gate
  that measures nothing must never be green.
- **No pack runs in CI.** Building one needs a download, and the default tier is
  deliberately offline as well as model-free (ADR-0009, ADR-0017). The pack gate files
  are checked for validity by the test suite; their *numbers* are run on demand.

### Threshold calibration, and the split protocol's one test read (Increment E)

**The thresholds were reviewed against the calibration split and locked unchanged,
because there is nothing to tune on that axis.** Every score the shipped chains emit
is a recognizer constant on this corpus: the deterministic recognizers emit 1.0
(their `possible` tier, which emits 0.85, never fires here), and the spaCy NER path
emits a flat 0.85 for true and false positives alike (19 calibration-split
PERSON predictions: 15 TP and 4 FP, every one at 0.85). A per-entity threshold can
only sit below a constant — keeping everything that recognizer emits — or above it,
dropping everything. The configured values sit below deliberately and gate
hypothetical sub-constant scores; improving PERSON precision is reconciler work
(the identifier guard, span repair), not threshold work. The review is recorded in
`configs/providers.yaml` and travels into every run's metadata as
`threshold_calibration`, replacing `default_uncalibrated`.

**The test split was read once** (ADR-0011's protocol), hybrid chain, `redact`,
session 6 — after all session-6 detection changes and before any future ones:

| split | documents | entities | strict F1 | relaxed F1 | leakage | over-redaction |
|---|---|---|---|---|---|---|
| dev | 18 | 33 | 0.875 | 0.906 | 0.121 | 0.000 |
| calibration | 27 | 48 | 0.882 | 0.903 | 0.125 | 0.000 |
| **test** | **57** | **99** | **0.921** | **0.921** | **0.111** | **0.000** |

The test split scores *above* the working splits, which is the direction that says
nothing was tuned onto it. These are per-split observations under the split-scoped
scoring fixed in session 5; the whole-corpus gates in `configs/benchmark_gates.yaml`
remain the regression floors, and a future change that wants to claim test-split
improvement must re-run this protocol rather than iterate on the test number.

### Reduction strategies, measured (Increment E, ADR-0013 §5)

Whole corpus, both chains, all three strategies from one configuration via
`--strategy`. Full-value leakage cannot tell the strategies apart — every strategy
covers the exact surface — which is precisely why ADR-0013 required the second
variant. `fragment_leakage_rate` counts any surviving whitespace-free 4-character
window of the value, minus windows that occur in the source text outside entity spans
(ambient prose is not evidence: `…schneider@…` shares `chne` with *Rechnername*).

| chain | strategy | leakage | fragment leakage | over-redaction |
|---|---|---|---|---|
| deterministic | redact | 0.433 | 0.433 | 0.000 |
| deterministic | mask | 0.433 | **0.922** | 0.000 |
| deterministic | pseudonymize | 0.433 | 0.433 | 0.000 |
| hybrid | redact | 0.067 | 0.067 | 0.000 |
| hybrid | mask | 0.067 | **0.556** | 0.000 |
| hybrid | pseudonymize | 0.067 | 0.067 | 0.000 |

Three readings, stated so the table is not misused:

1. **Mask's fragment rate is configured behaviour, not a defect** — `last4` keeps four
   digits and `partial_email` keeps the domain, and this metric is where that retention
   becomes visible instead of invisible. Comparing it to redact's rate as one number is
   forbidden (ADR-0013 §5); the gate runner refuses `--gates` with `--strategy` for the
   same reason.
2. **Redact's fragment rate equalling its full rate is a finding, not a tautology —
   and this session proved it by breaking and repairing it.** ADR-0020's promotion
   separated them (0.078 against 0.067) by detecting two Greek surnames without their
   given names: a boundary error that leaves half a name pushes the fragment rate above
   the full rate while the full-surface metric holds still, which is the exact blind
   spot session 5 found. The divergence was investigated rather than absorbed — no
   entity leaked that had not leaked before — and ADR-0021's span extension then closed
   it. Both rates are 0.067 again on both chains, and a test pins the equality on the
   deterministic one. If either gate fails while `leakage_rate` holds, a partial leak
   has reappeared: investigate before touching the metric.
3. **Pseudonymize retains nothing** at this window length: tokens are digests, so both
   its rates equal redact's. Its leakage still reflects only *undetected* entities.

### Queue

Not a menu. Each has an exit criterion; do not start the next before the current one
meets it.

#### Q1. CI workflows (ADR-0009) — **complete**

- `.github/workflows/ci.yml` — every push and PR, `ubuntu-latest` **and**
  `windows-latest`, Python 3.11, core + `dev` only: `ruff format --check`,
  `ruff check`, `mypy src tests`, `pytest -q`, the deterministic benchmark gates, a
  corpus-reproducibility check (`build-corpus` must reproduce the committed corpus
  byte for byte), and an assertion that no provider extra is importable.
- `.github/workflows/integration.yml` — nightly (03:17 UTC), `workflow_dispatch`, or
  a PR labelled `integration`: `presidio` + `language` extras with **pinned** md
  models (3.8.0, wheel-cached), `pytest -m "integration or slow"`, then the benchmark
  gates for both chains. Models are pinned rather than resolved by `spacy download`
  so a model bump cannot move a gate on a night nobody changed anything.
- `databricks`-marked tests never run in CI — no job installs the extra, and the
  marker expressions exclude them.
- Gates live in `configs/benchmark_gates.yaml`, checked by
  `pii_reduction.evaluation.gates` via `pii-reduction benchmark --gates <file>`
  (exit 1 on failure). The gate set is selected by the chain that ran, so a hybrid
  result can never be scored against deterministic floors. A gate that matches no
  row, matches several rows, or whose slice support shrank is a **failure**, not a
  pass — a gate that measures nothing is the failure mode this design exists to stop.

**Exit: met.** Remote `soulipaco/pii-reduction` (private), both workflows run:

- `CI` green on `ubuntu-latest` and `windows-latest` (run 32080834089).
- `Integration` green via `workflow_dispatch` (run 32081004870), 1m6s including the
  model download: 72 integration tests, then 9/9 deterministic and 12/12 hybrid gates.
- The gate file's values match this section, checked by a test rather than by eye; a
  deliberately broken gate fails and exits non-zero, and a malformed gate file exits 2.

**The first push failed, which is the point.** `mypy src tests` failed on both
platforms: strict mode cannot resolve `lingua` or `presidio_analyzer` in the push
tier, which installs core + `dev` only. Every local run had passed because the dev
machine has the extras installed. Fixed by declaring both as optional in the mypy
overrides — the type checker now models what the packaging already said (ADR-0008) —
and verified in a throwaway core-only venv. **A green local run does not prove the
push tier is green**; check a clean core-only environment when touching anything the
extras reach.

Every hybrid gate value **as it stood at Q1** reproduced exactly on GitHub's runner
(strict F1 0.886, PERSON 0.820/0.641, en tier 3 0.333, el tier 1 0.222), so the
baseline is machine-independent rather than an artifact of one laptop. Q2 moved those
numbers and its floors have been verified locally only — the nightly integration run
is the first cross-runner check of them.

#### Q2. English tier-3 PERSON recall — **complete** (0.333 → 1.000)

**The cause was a span boundary, not detection.** Presidio found every name; handed a
multi-line key/value block it ran the entity boundary through the line break and
returned `Peter Novak` + newline + `Mobile`, which strict matching counts as a miss
*and* a false positive. It also destroyed the next line's label in the output — a
structure-preservation failure the over-redaction metric cannot see, because labels
are not protected tokens.

**The fix repairs the span instead of re-cutting the input** (ADR-0016): a PERSON span
crossing a line break is trimmed back to the line, at the provider boundary. Detection
is untouched, so no context is lost and no configuration changes.

Three remedies were built and measured whole-corpus on the hybrid chain:

| | shipped | `split_lines` | `key_value` | **span repair** |
|---|---|---|---|---|
| strict F1 | 0.886 | 0.902 | 0.915 | **0.902** |
| relaxed F1 | 0.921 | 0.913 | 0.927 | **0.914** |
| en tier-3 PERSON | 0.333 | 1.000 | 1.000 | **1.000** |
| el tier-3 PERSON | 0.000 | 0.000 | 0.000 | **0.167** |
| PERSON precision / recall | 0.820 / 0.641 | — | — | **0.833 / 0.705** |
| over-redaction | 0.000 | 0.000 | 0.000 | **0.000** |
| leakage | 0.117 | 0.122 | 0.122 | **0.117** |
| document clean rate | 0.774 | 0.763 | 0.763 | **0.774** |

**Exit criterion met:** English tier-3 PERSON recall improved 0.333 → 1.000,
over-redaction stayed 0.000, and **no slice regressed** — Greek tier 3 improved as
well. Gate floors were raised to these numbers, so the fix is now protected.

The two segmentation remedies remain available per column and are enabled nowhere.
Both fixed the span by re-cutting the input and both paid for it in lost context: each
leaked a Greek name, and `key_value` also turned one provider call per document into
one per line, which matters under ADR-0015. The lesson is general — the model's
accuracy depends on the text it is shown, so a remedy that changes the input trades
one error for another, while one that changes the output cannot.

Also shipped: the **identifier guard** (PERSON-scoped), which refuses a PERSON span
whose surface is a machine identifier. It was built to unblock `key_value` and is not
needed by the remedy that won, but it is correct in its own right and a verified no-op
on the shipped configuration.

Eliminated candidate, recorded so nobody repeats it: Presidio's `context=` cannot
recover a missed name. It boosts scores of candidates a recognizer already produced;
PERSON comes from the spaCy NER reading the text it was given.

Still open, and unchanged by this: Greek PERSON is weak (0.222 / 0.111 / 0.167 /
0.000 by tier) and licence-bound to `xx_ent_wiki_sm` until roadmap Phase 7 (ADR-0007).

#### Q3. Increment D — public datasets (§5 above) — **complete**

Three packs, built from two sources, measured on both chains, published above beside
the synthetic numbers. **MultiWOZ is out** — the session-5 privacy audit found real
Cambridge landlines and postcodes in its published utterance text, so it moved to the
registry's `rejected:` block and Bitext now renders both English packs (ADR-0018).

What landed:

- **`synthetic/fetch.py`** — files fetched at a pinned commit revision and verified
  against a SHA-256 recorded in `demo/registry.yaml`. Stdlib only, no new extra
  (ADR-0017 chose this over a `datasets` extra; ADR-0008's list is unchanged).
  A cached file that fails its digest is refused rather than re-downloaded, because a
  cache that repairs itself hides a tampered one as well as a truncated one.
- **`synthetic/registry.py`** gained the `retrieval:` block and `load_rejected`, so a
  rejected dataset is answered with *why* rather than "unknown dataset" — the
  difference between a decision and an oversight.
- **`synthetic/public.py`** — Bitext and MASSIVE readers. Selection is a seeded shuffle,
  not the head of the file (Bitext ships sorted by category). Rows carrying any
  `{{Placeholder}}` other than `{{Order Number}}` are excluded; that one is filled with
  a synthetic identifier **recorded as a protected token**, which is what makes
  over-redaction measurable on public text.
- **`synthetic/packs.py`** — the pack specs and `build_pack`, the first real caller of
  `inject()`.
- **`inject()` gained `protected=`**: spans recorded against the base text are shifted
  by the same arithmetic as the injected entities and verified the same way. Offset
  arithmetic belongs in one place; a second implementation is a second chance to drift.
- **`eligible_offsets` now offers each processable region's start.** Without it a
  transcript's only candidates are sentence breaks, so every name in a two-turn document
  landed in whichever turn was longest, and nine documents received nothing at all.
- **`pii-reduction fetch-dataset` and `build-pack`**, with `demo/download_datasets.py`
  and `demo/build_pack.py` as front doors beside `demo/build_corpus.py`.

**Exit criteria, met:**

- *Reproducible from documented commands* — `demo/build_pack.py <pack>` against a
  pinned revision with recorded checksums; the pack's `meta.json` names the repository,
  revision and per-file digest it was built from.
- *Provenance registry complete* — every field `docs/02_PUBLIC_DATA_STRATEGY.md`
  requires, plus the retrieval pin and the transformation performed before use.
- *Injected ground truth validates against its documents* — every span slices back to
  its own surface, checked at build time, again on write, and again on load.
- *Numbers published beside the synthetic ones* — the section above. The synthetic
  gates in `configs/benchmark_gates.yaml` are untouched; each pack has its own gate set
  under `configs/pack_gates/`, and a test asserts no workflow gates on a pack.

**Deliberately not done at the time:** the `incident_notes` pack. ADR-0010 named three
families and this delivers two; incident metadata combined with generated work notes
needs no public source. **Delivered in session 8 as something else** — ADR-0022 makes
it a generated *over-redaction stress corpus* rather than a pack, because a source-less
corpus cannot go in a registry that exists to record public-data licences, and because
a generated corpus can say nothing honest about detection realism. What it can say is
whether identifiers survive, and it found two things nothing else could.

**One superseded constraint, recorded because the old advice is still in the session-5
handoff.** That handoff said to share **one** `ValueProvider` across a pack, or a
repetitive corpus would give every row the same name. The injector solved it the other
way instead: values derive from `(seed, document_id)`, so a document regenerates
identically without replaying the pack, and two documents with identical base text still
receive different entities. Sharing a provider would now *break* that property, because
a document's values would depend on where its row sat in the run. A test pins it.

#### Q4. Why Greek scores 0.606 on public text and 0.111-0.222 on ours — **complete**

**Answered, and the answer replaces the one-line explanation this project has used
since ADR-0007.** Full reasoning and measurements in ADR-0019; pinned by
`tests/test_greek_person_diagnosis.py` (integration tier).

**Greek PERSON is not a detection failure.** Probed directly against
`xx_ent_wiki_sm` with the committed eight-name pool, the model almost always returns a
span covering the name — and then gets the label or the boundary wrong. "Nothing
found" is the rare case. Counts out of 8:

| carrier | exact PER | wrong label | wrong span | nothing |
|---|---|---|---|---|
| the name alone | 3 | 1 | 2 | **2** |
| `Ο πελάτης είναι {name}.` | **6** | 2 | 0 | 0 |
| synthetic tier-1 (name + email + ticket) | 2 | 1 | 5 | 0 |
| synthetic tier-3 `Από: {name}` | 1 | 1 | 4 | 2 |
| synthetic tier-4 (`Ονομάζομαι {name}`) | **0** | 0 | 8 | 0 |
| German `Der Kontoinhaber ist {name}.` | **8** | 0 | 0 | 0 |

Three mechanisms, three different remedies:

1. **Span absorption — the whole of tier 4.** `Ονομάζομαι {name}` returns
   `PER 'Ονομάζομαι Ελένη Παππά'` for 7 of 8 names: a capitalised token immediately
   before the name is swallowed. Measured both on that clause alone and on the full
   template line with its `2026-04-03 11:20:24 - Πελάτης: ` prefix — 0 exact spans and 8
   wrong spans either way. Strict matching scores that as a miss *and* a false
   positive — ADR-0016's English tier-3 bug, but *within* a line, so line-boundary span
   repair cannot see it. Lower-casing the verb recovers 5/8. **Greek tier-4 0.000 is a
   boundary failure, not a detection failure.**
2. **Label confusion.** Two of the eight names come back with an *exact span* and a
   non-`PER` label even in a neutral sentence — one `ORG`, one `LOC`; other carriers add
   `MISC`. ADR-0004's mapping correctly refuses all three, so the name is found and then
   dropped — and note *where*: the adapter asks Presidio for its three native labels
   only, so these never arrive rather than arriving and being unmapped. A promotion
   remedy has to change the **request**, not the mapping table. **There is no
   morphological rule** either: three of the pool's five genitive surnames are
   labelled `PER` correctly, so which names fail is a property of the model's
   training data, not of Greek grammar.
3. **The άνω τελεία flips the label.** `…Παππά, δεν…` gives 6/8; `…Παππά· δεν…` gives
   3/8 — exactly half. Comma, semicolon and full stop are all 6/8; only the middle dot.
   With U+0387 rather than the corpus's U+00B7 the tokenizer glues it to the surname as
   well, so the span is wrong too.

**Why the pack scores higher:** MASSIVE utterances are single short clauses with no
adjacent entity strings, no field label, no άνω τελεία and no capitalised verb before
the name. They avoid all three. The synthetic templates hit all three *by being more
realistic Greek*.

**Decision: the corpus is not changed** (ADR-0019). Each mechanism has an obvious
corpus-side "fix" that would raise the published number by making the text easier —
tuning the benchmark to the model, which `AGENTS.md` forbids. The synthetic Greek is
legitimately harder than the public Greek; both numbers are correct measurements of
different text, and the pack's 0.606 must not be quoted as *the* Greek result.

**Exit criterion met:** the answer is attributable and measured on a constructed
comparison rather than on the two corpora as they stand, each mechanism isolated by
changing one thing at a time, and the finding is recorded with a test that fails if a
model bump changes it. No published number moved, because none should have.

**What it opens** (ranked by what the measurement supports): Greek span
absorption as an ADR-0016-family remedy — repair the output, and the rule must be
structural rather than a list of Greek words; evidence-gated promotion of `LOC`, `ORG` **and**
`MISC` — which one appears varies by carrier, so a one-label remedy would miss the
rest — which trades leakage for over-redaction and needs a measurement before an
implementation; and a better-licensed Greek model at Phase 7, now with a benchmark that
can say which of the three it fixed.

**Both of the first two were then measured in this session** (offline simulation of
the full provider-boundary stack against the committed corpus's Greek slice, using
the real metric functions; scratchpad only, nothing shipped):

| Greek slice (26 PERSON, 34 protected tokens) | PERSON recall | leakage | over-redaction |
|---|---|---|---|
| baseline (PER only, line-bound + guard) | 0.154 | 0.350 | **0.000** |
| promote `LOC`/`ORG`/`MISC`, naive | 0.385 | 0.133 | 0.706 |
| … + the identifier guard | 0.385 | 0.133 | 0.324 |
| … + ADR-0016 line-bounding | 0.423 | 0.133 | 0.206 |
| … + colon-trim | 0.423 | **0.133** | **0.147** |

**Superseded by ADR-0020 — read that first.** The offline stack above reported
promotion cutting Greek leakage 62% while destroying 5 of 34 protected identifiers,
and concluded that reaching the 0.000 gate needed token-level coverage surgery inside
promoted spans. **Session 8 measured the same question against the real pipeline and
the premise did not hold: promotion through the shipped adapter destroys nothing.**
Two causes, both verified — Presidio discards spaCy's `MISC` label before this
project's adapter sees it (21 of the 22 model spans that overlap a protected token are
`MISC`), and the real reconciler removes the rest. Surgery was built and measured on
the one arm that does contain destroyers, works there, and is **not shipped**: reaching
that arm needs a new provider path around Presidio and halves precision. The numbers
below are kept as the record of what the offline simulation said; where they disagree
with ADR-0020, ADR-0020 is the measurement to trust. One nuance reverses an earlier note:
colon-trim alone is a verified no-op (nothing reaches it today), but **inside the
promotion stack it is load-bearing** (0.206 → 0.147) and a measured no-op on the
unpromoted path — both facts from the same probe.

**The first of those was scoped in this session and found unshippable as stated.**
Two structural trim rules were examined at the provider boundary. Colon-trim — a
PERSON span containing `:`/`·` is trimmed to the value side, safe because no name
contains a colon — **fires zero times on the corpus**: the label-absorbed spans
arrive as `MISC`/`LOC`, which ADR-0004 drops before any PERSON repair could see
them, so there is nothing for the rule to repair. And leading-token-trim — drop a
capitalised token ahead of the name — can always be cutting the first token of a
real three-token name, which is a leak, the invisible error ADR-0016 chose the
visible one over. The absorbed tier-4 spans also *redact the whole phrase including
the name*, so mechanism 1 costs metrics and a swallowed verb, not privacy. **The
next concrete Greek step is therefore the mechanism-2 measurement** (what would
requesting Greek `LOC`/`ORG`/`MISC` from the model and reconciling them do to
leakage and over-redaction?), not more span repair.

**Narrowed rather than ruled out:** treating Greek as a *pure* detection problem. Only
4 of the 40 Greek probes returned no span at all, and tier 4 is 100% boundary error — detection
work cannot touch it. But 2 of 8 do go silent in the tier-3 `Από:` form, so better
detection would move tier 3; it is simply the smallest of the three effects.

#### Increment F — Databricks execution — **complete on the driver path; distributed path infra-blocked**

Run against the real workspace (serverless-only — classic cluster creation is
refused, so ADR-0006's Connect decision was the only path, now amended with what
was found).

**Exit criterion met:** local vs Databricks parity on the shared fixture — the
committed corpus's plain documents went up as a Delta table, were read back through
`SparkTableSource`, processed by the *byte-identical* local `Pipeline.process`,
written to Delta by `DeltaTableOutput`, read back, and the reduced column hashes
equal the local run's. Audit and run-metrics Delta tables written and verified
metadata-only (no surface, no text — AGENTS.md rule 8). The parity tests create one
throwaway schema and drop it afterwards. `databricks`-marked tests never run in CI.

**No per-row model loading:** the `mapInPandas` partition processor builds the
pipeline once per worker via a cache keyed on the driver-generated run id plus the
config hash, and that init-once property
is asserted by default-tier unit tests driving the function with plain iterators —
no Spark required, so the Databricks path's logic is regression-guarded on every
push even though the workspace itself never is.

**The distributed path produces the reduced frame only** — per-worker audit rows
and run metrics are discarded; fanning them out of `mapInPandas` is a second output
channel, deliberately out of scope for v1. A run needing the audit/metrics Delta
tables uses `run_driver`. Run identity is driver-generated and part of the worker
cache key, so one distributed run stamps one `pii_run_id` and a warm worker cannot
stamp a previous job's id onto a new one.

**The distributed path is also shipped but cannot execute on this workspace:** serverless
Python-UDF sandboxes fail server-side (`ISOLATION_STARTUP_FAILURE` — the channel's
aarch64 image cannot exec its own Python; reproduced across client generations 15.4
and 16.4, so it is Databricks infrastructure, not client skew). A `databricks`-marked
test watches it: it skips today naming the incident, and asserts real distributed
parity with no code change the day the sandbox works.

**Sandbox re-checks** (same command against the workspace; the code underneath is
*not* constant across rows — the 2026-08-20 run exercised R2's provenance columns,
R3's projection and a fourth test that did not exist in sessions 7–8):

| date | driver-path parity | distributed path |
|---|---|---|
| 2026-08-19 (session 7, Increment F) | 2 passed | skipped — ISOLATION_STARTUP_FAILURE |
| 2026-08-19 (session 8) | 2 passed | skipped — incident still open |
| 2026-08-20 (session 10, run by the owner, `env_token` auth) | 2 passed | skipped — incident still open |
| 2026-08-20 (session 10, re-run in-session, `profile` auth) | 2 passed | skipped — incident still open |
| 2026-08-20 (session 10, after the write-mode fix; tier gained a default-mode test) | 3 passed | skipped — incident still open |

Environment facts recorded for reuse: dedicated venv (`.venv-dbx17`, Python 3.12,
`databricks-connect` 16.4) per ADR-0006's isolation; authentication by named profile
(`DATABRICKS_CONFIG_PROFILE`) **or** `DATABRICKS_HOST` plus a token — the `env_token`
route added in session 10, which is how the 2026-08-20 run authenticated; the extra pins `databricks-connect>=15.4`.

### The review queue (session 9, from docs/17 §8 — approved sequence)

One increment at a time, measure before and after, own commit each:

- **R1 — fail-closed default (ADR-0023)** — **complete**, see the Complete table.
- **R2 — run provenance** — **complete**, see the Complete table.
- **R3 — reduced-only projection (ADR-0024)** — **complete**, see the Complete table.
- **R4 — docs honesty sweep** — **complete**, see the Complete table.
- **R5 — referential-consistency metric** — **complete**, see the Complete table.
- **R6 — CLI `run` command** — **complete**, see the Complete table. The R queue
  is finished: every increment the owner approved from docs/17 §8 has landed.

Deferred with conditions, rejected, and disputed items: the decision table in
`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md` §7 is the record; nothing there is
re-litigated here.

### The platform queue (session 9 addendum — the owner's stated direction)

**Azure Databricks is the primary deployment target — a must, not a feature.**
The owner's goal, stated 2026-08-19: an internal platform for analyzing
ServiceNow / case-description records with AI — PII reduction now, PHI later if
feasible — with a service layer (Databricks App / API: upload a file or pick a
table, choose columns, pre-configured parameters) built *over* this engine. The
library stays the engine; the platform is a shell on top, which is the split
both external reviews endorsed. **Near-term exit criterion: the owner can run
real workspace data using only a runbook, one day after this queue starts.**

**Session 10 executed P0 → P4, then verified the Databricks half on the workspace.**
P5 was deliberately not started: the work order gated it on everything else being
"done and verified", and by the time that was true the better reason to defer it was
that it optimised a path nobody used yet. *(Session 11 built that path; see the
pickup list at the end of this section.)* Status of each below; the shipped detail is in the Complete table.

- **P0 — repo tidy. Complete.** Sessions 1–8 archived behind an evidence index,
  CLAUDE.md's read order re-checked, default tier green. Original brief: `.claude/SESSION_HANDOFF.md` is ~2,000 lines; collapse
  sessions 1–8 into a short evidence index (what each established, one link
  each) and move the full text to `docs/archive/SESSION_HANDOFF_S1-S8.md`.
  Prune nothing else by default: **ADRs are the decision record and are not
  deleted or thinned**; numbered docs stay unless demonstrably superseded (then
  a one-line pointer replaces content, never silent removal). CLAUDE.md's
  read order must still resolve afterwards.
- **P1 — ADR-0025. Complete.** Written and indexed; README, charter, roadmap and
  docs/07 amended in the same commit. It *amends* the "feature among surfaces"
  framing rather than superseding an ADR — no ADR ever asserted it; the framing
  lived in charter/README/roadmap prose.
- **P2 — config-nameable Databricks IO.** `spark_table` source and
  `delta_table` destination become registrable config types. Design point to
  resolve in the ADR or a companion: config names the table; the runtime
  supplies the session (`build_source` takes a path today — `docs/06` records
  the structural reason; superseding it is deliberate, not a drive-by).
  Exit: a dataset YAML can name a UC table end to end on the driver path.
  **Met.** `configs/datasets/databricks_table_example.yaml` resolves end to end and
  `run_driver` needs no table arguments. The design point is resolved and recorded in
  docs/06 and ADR-0025: **config names the table, the runtime supplies the session**.
  They cannot arrive together — a session is not a value a YAML file can hold, and a
  `sources/` module that accepted one would invert the dependency direction that
  three tests in `test_package.py` pin. So the registries refuse the Databricks types
  with an instruction rather than a misleading "not registered".
- **P3 — real-data readiness.** Verify UC **Volumes** file ingestion on the
  workspace (a `/Volumes/...` path through the existing CSV source,
  databricks-marked test), then write `docs/18_RUNBOOK_DATABRICKS.md`: the
  ten-minute "run it on your own table" path — profile env var, dedicated
  venv, dataset config, `run_driver`/CLI invocation, where reduced /
  reduced-only / audit / metrics land, and the privacy rules for real data
  (nothing real ever enters the repo, fixtures, or logs — the tooling is
  fail-closed and metadata-only by construction, ADR-0023 / AGENTS rule 8).
  Exit: the runbook executed once end to end against the workspace on
  synthetic data. **MET (2026-08-20).**

  **The runbook's own path ran end to end.** A synthetic 20-row table was staged in
  Unity Catalog, a dataset config named it, and `pii-reduction-databricks run
  <dataset>` was executed as §3 describes: exit 0, three Delta tables, metadata-only
  summary; read back as 20 rows with the source column intact beside the reduced one,
  every row `success`, 16 of 20 carrying placeholders, the audit table's column set
  exactly `AUDIT_COLUMNS`, and `run_rows_read=20` / `run_source_version=delta_v0`.
  That first run was deterministic-chain only. **Repeated on 2026-08-21 with the
  hybrid chain**, after performing the runbook's step-1 install for the first time:
  30 rows, exit 0, audit recording **PERSON 28 / EMAIL 15 / PHONE 15**, 28
  `<PERSON>` placeholders written, 27 of 30 rows changed, and run provenance carrying
  real library *and* model versions (`presidio-analyzer 2.2.364, spacy 3.8.15,
  en_core_web_md 3.8.0`) — R2's provenance working end to end for the first time,
  since every earlier run lacked the models. **PERSON detection is therefore
  demonstrated on the workspace**, and step 1 is no longer untested.

  Step 1 has a trap worth carrying: `python -m spacy download` shells out to an
  installer, and a `uv` venv has no `pip`, so spaCy falls back to `uv pip install` —
  which targets `$VIRTUAL_ENV`, or the `.venv` it discovers in the current directory
  when that is unset. Run from the repository root, three models "downloaded" for
  `.venv-dbx17` landed in the core `.venv` while the command reported success. The
  runbook (§1) carries the mechanism and the remedy.
  All created objects were dropped. The dataset config lived outside the repository
  because it names real catalog/schema values.

  **It found a defect that had gone unseen since Increment F.** `errorifexists` — the
  shipped default write mode, published in `docs/06` and the runbook — is rejected
  outright by Databricks Connect (`[UNSUPPORTED_OPERATION]`), so **every**
  config-driven Delta write failed with exit 2. Nothing caught it: the parity suite
  is the only workspace test and it passes `mode="overwrite"` explicitly, so the
  default path had no coverage at all. The adapter now translates to Spark's alias
  `error`, with a default-tier test pinning every accepted mode to a translation
  **and** a new workspace test that writes under the *default* mode and asserts the
  second write refuses — the coverage that did not exist, which is why the defect
  shipped. The marked tier went 2 passed → **3 passed**. **This is the argument for
  end-to-end runs over component tests**, recorded here rather than learned twice.

  **Earlier the same day, before that run:**

  **Verified on the workspace** (owner's run, 2026-08-20, from their own PowerShell
  session over the new `env_token` route, against a fresh timestamped schema):
  `pytest -m databricks` -> **2 passed, 5 skipped**, reproduced in-session over the
  *profile* route (the owner's run used the token route, so the same workspace has
  now been reached by two different authentication routes). The marked tier is 2
  passed / 2 skipped; the other three are module-level collection skips from the
  presidio/language suites, which fire in `.venv-dbx17` despite being deselected. Driver-path Delta round-trip
  parity holds — reduced-column hashes equal between the workspace run and the local
  one — and the audit and run-metrics tables are metadata-only. That run also
  executed, **for the first time against a real workspace**, the **reduced-only
  projection** (R3 / ADR-0024) and the **run-metrics provenance columns** (R2,
  `run_source_version` resolving to `delta_v<N>`), both asserted inside those tests
  and previously covered only locally and against fake sessions. The projection was
  written into the same throwaway schema, so the separate-prefix grant boundary
  remains unit-tested only. First workspace evidence since session 8.

  **Not yet verified at that point.** The parity suite drives `run_driver` with
  explicit table arguments, so the runbook's own path had not yet run against a
  workspace — that invocation is what the end-to-end run above then performed. Also outstanding at
  the time — Volumes ingestion has since been verified (see above), leaving: Volumes ingestion (skipped as expected on a local client — though
  the guard is a local filesystem check, so the skip proves nothing about the
  workspace; it needs a notebook or job) and the distributed path
  (skipped — `ISOLATION_STARTUP_FAILURE`, unchanged since session 7). The local half
  of the runbook was executed as written; step 1's combined
  `[databricks,presidio,language]` install has never been performed in any
  environment here — performed on 2026-08-21, see above.

  **Authentication no longer assumes the Databricks CLI**, which the owner raised
  mid-session: their organisation blocks it and they authenticate with a token. The
  CLI was never a code dependency — nothing shells out to it, and the extra is
  `databricks-connect`, a library — but `get_session` accepted only a named profile
  and the parity fixture gated on that variable, so **token auth would have skipped
  every workspace test silently**. Four routes now resolve in order: explicit
  `profile=`, ambient credentials on Databricks compute, `DATABRICKS_CONFIG_PROFILE`,
  then `DATABRICKS_HOST` plus a token or service principal. Ambient is checked before
  the profile variable because a stale one inherited into a notebook would route a
  process that already has a session through Connect. ADR-0006 amended. Still no
  host or token parameter in any signature, pinned by a test.

  **Volumes ingestion is now verified too (2026-08-21), on compute.** The wheel and
  a dataset config were uploaded to a volume and the console entry point was
  submitted as a serverless job: it read `/Volumes/.../tickets.csv` through the
  ordinary CSV source, reduced 25 rows, wrote three Delta tables (source column
  intact, 20 of 25 changed, `PHONE 13 / EMAIL 12`, audit column set exact,
  `run_rows_read=25`, `run_source_version` null as a file has no Delta version), and
  everything was dropped. The configs directory was read from the volume as well.

  **That run found two defects, both invisible to every other kind of test:**

  1. **A failed reduction was reported as a green job.** Databricks calls a
     `python_wheel_task` entry point as a *function* and ignores what it returns, so
     the CLI's exit code — the whole point of R6 and of ADR-0023's fail-closed
     posture — never reached the scheduler. The entry point is now a wrapper that
     raises `SystemExit` on a failing code.
  2. **…and raising unconditionally broke the opposite direction.** Databricks runs
     the task under IPython, where *any* `SystemExit` including `SystemExit(0)` is an
     error, so a successful reduction was marked failed after it had already written
     its tables. The wrapper now raises only on a non-zero code. Both directions were
     then confirmed against real jobs: failure → task failed, success → task SUCCESS.

  **A third finding was a capability gap, not a defect:** `run_driver` refused any
  source that was not a `spark_table`, so the Databricks front door could not execute
  the volume config this runbook publishes in §6. A file source is now read through
  the ordinary local adapter — which on compute is what makes a volume path work —
  and the destination stays Delta. This is the "upload a file, reduce it" half of the
  platform's rung-4 story, and it now runs.

  **`language: mode: detect` closed too** (2026-08-21): a workspace run over 30 rows
  resolved `en` and `und` (the short-text gate abstaining per ADR-0012) and recorded
  `run_language_detector_version = lingua (lingua-language-detector 2.2.0)` — the last
  provenance column a *detect-mode* run populates. `pseudonymization_key_id` remains
  unexercised on the workspace: only a `pseudonymize` run fills it, and every
  workspace run so far used `redact` (docs/17 D9).

  **`bundle deploy` is environment-blocked, and the attempt was still worth it.** Two
  real defects surfaced before the blocker: the artifact build command
  `python -m build --wheel` runs with whatever `python` is on PATH — the system
  interpreter here, which has no `build` backend — and the wheel dependency
  `./dist/*.whl` is resolved *relative to the file that declares it*, so it looked for
  `resources/dist/*.whl` and failed with "no files match pattern". Both fixed (`uv
  build --wheel`, `../dist/*.whl`). The deploy then reached Terraform provisioning and
  stopped there:

  ```text
  Error: error downloading Terraform: unable to verify checksums signature: openpgp: key expired
  ```

  That is Databricks CLI v0.280.0's expired-key bug, not this repository — the wheel
  built and the bundle files uploaded first. **Remedy: a newer CLI**; the same
  version also warns it is too old for the SDK's `--force-refresh`. Recorded like
  `ISOLATION_STARTUP_FAILURE`: an environment blocker with a named fix, not a design
  problem, and `bundle validate` still passes.

  **What remains:** the distributed path (`ISOLATION_STARTUP_FAILURE`, unchanged since
  session 7) and `bundle deploy` (CLI upgrade). Neither blocks the runbook, and the
  job *shape* is proven by real runs.
- **P4 — deployment skeleton. Complete as a skeleton; never deployed.**
  `databricks.yml` + `resources/`, one task calling the same entry point, plus a
  CLI-free path (UI or Jobs API) since `bundle deploy` *is* the CLI. **Exit criterion
  met (2026-08-21): `databricks bundle validate -t dev` → Validation OK**, against a
  real workspace with CLI v0.280.0. That proves the file is well-formed and its
  variables resolve; it does not prove a deploy, a run, or that this workspace serves
  the serverless `client` version the environments block names. Three things in it would have broken a first run and
  were fixed in review — a `configs_path` a wheel task cannot resolve, a dependency
  list that cannot install spaCy models (so PERSON would be missed silently), and an
  empty notification recipient the Jobs API rejects — but **none of that is a
  substitute for validating it**.
- **P5 (stretch) — batching. Not started.** *Its gate is superseded by the
  session-11 pickup list at the end of this section, where it is item 4.* Wire
  `detect_batch`
  (docs/17 D10 reopens: the platform direction is the condition arriving). Measure
  rows/s before and after on the 10k pack. The work order gated this on everything
  else being done *and verified*. P3 is now met and P4's validate criterion with it,
  so the original reason has expired. Its position is now set by the
  session-11 list at the end of this section, where it is item 4 — it is the only
  entry with nobody waiting on it. Measure rows/s before and after on the 10k pack
  when it is picked up.

Rules unchanged by urgency: gates never weaken, workspace results only from
actual workspace runs, real data never becomes a fixture. All three held: no
published benchmark number moved this session (none was touched), no workspace
result is claimed, and the local gate was found *weaker* than CI and strengthened
rather than left alone.

### Rung 4, the service layer — **built** (session 11)

**Built in session 11, in two increments, and executed on both runtimes.** The rung
ADR-0025 names as the point of all of it now exists: someone picks a configured
dataset, chooses columns and entities, and runs — over HTTP, with the engine
underneath and no reduction logic anywhere above it. `docs/19_SERVICE_LAYER.md` is
the operator-facing description and carries the evidence; ADR-0026 carries the
decision and the five rules v1 obeys by construction.

What it does **not** do, recorded so the gap between decided and deployed stays
visible: it has never been hosted. No Databricks App has been created, and
`bundle deploy` is still blocked by the CLI's expired Terraform signing key. Running
the API from a terminal against the workspace and hosting it inside the workspace are
different claims, and only the first has been made.

The framing this section carried *before* the increment is kept below, because two
of the endpoint shapes it implied are ones ADR-0026 went on to forbid by name.

**ADR-0026 decides the shape: a thin HTTP API, hosted later as a Databricks App
rather than built as one.** Read it before implementing — it names the endpoint shapes
that are forbidden, and two of them are the ones this paragraph used to imply. In
particular: **no endpoint accepts text**, so there is no upload endpoint (a file in a
volume is a path the CSV source already reads — that half of "upload a file or pick a
table" is served a rung lower); and **the caller names a configured dataset, never a
`catalog.schema.table`**, because the service runs with its own credentials.

*Kept as written before the increment, in the imperative it was written in:*

Smallest useful version: a config **builder** (dataset identity, columns, entities →
a validated dataset config, with source/destination/failure-mode/projection coming
from a server-side template), a run trigger over both entry points
(`build_pipeline(config).run()` locally, `run_driver` on the driver path), and a
metadata-only status view. Constraints that already apply: the service layer owns
**no** reduction logic and the engine never learns it exists (ADR-0025's rung rule,
`AGENTS.md` rule 3); a side-by-side original/reduced view is a Class B display
surface, so `docs/09` and rule 8 needed extending to rendered output and API responses
before one is built — the privacy auditor raised exactly this when ADR-0025 landed,
and that extension is the first thing session 11 shipped.

**P5 (batching) is no longer gated by "nobody uses this path" — there is now a
surface that uses it.** It is **fourth** in the pickup order below, not first; the
list is ordered by what makes the thing just built correct, and batching is the only
entry with nobody waiting on it. It keeps its measurement obligation: rows/s before
and after on the 10k pack, published beside the existing numbers.

### What session 11 left open, in the order it would pick them up

> **Paused for session 12, not cancelled.** The owner set a different course — a
> comparison against the reference implementation at `..\pii_alternative` (see the
> status line above and the session-11 addendum in `.claude/SESSION_HANDOFF.md`).
> This list is the queue to return to, and item 1 is still the one that turns a
> decision into a deployment.

1. **Host the service.** Everything below rung 4 is executed; rung 4 itself has been
   *run* and never *hosted*. A Databricks App is the decided hosting (ADR-0026) and
   needs `create_app` behind a small wrapper plus a `RunStore` carrying the Databricks
   runtime. Blocked on the same Databricks CLI issue as `bundle deploy` unless the App
   is created through the workspace UI, which is untried. **This is the increment that
   turns a decision into a deployment**, and it has two exit conditions of its own:
   it is scoped to a **single replica** (see 2), and it must **verify** what the
   platform actually does about identity (see 3) rather than assume it.
2. **A durable run store.** Not a follow-up to hosting — part of hosting being
   correct. The store is process-local, so the first thing a hosted user does
   (`POST /runs`, then poll `GET /runs/{id}`) returns 404 from a second replica or
   after a restart. Either the hosting increment states single-replica-and-restarts-
   forget as a constraint, or this lands with it. The
   `<dataset>_run_metrics` table is the record that already survives a restart.
3. **Settle the identity question, in writing and against the platform.** The service
   implements no authentication. Databricks Apps authenticate the end user — but data
   access defaults to the **App's service principal**, and on-behalf-of-user
   authorization is a separate opt-in. That distinction is load-bearing here, because
   S1 added "read under the end user's identity" to `docs/09`'s conditions for a
   Class B display surface, and the whole server-side-template design exists precisely
   because the service runs with its own credentials. Hosting does not satisfy that
   condition by default, and nobody here has verified which mode this workspace's Apps
   run in.
4. **Batching (P5).** `detect_batch` still has no caller; the platform direction that
   `docs/17` D10 named as its reopening condition has now arrived twice over.
5. **Schema introspection in the engine.** The service declares its column menus in a
   template because `sources/` exposes only `load()`, which materialises the frame. A
   schema-only path would let a column picker read the source's columns without
   reading the source — an engine change, deliberately not improvised in the service,
   and last because the workaround is documented and works.

Unchanged and unsequenced: the speaker-prefix ADR (still the most serious open design
item), the Phase-7 Greek model, the distributed path, and the deferred items in
`docs/17` §7.

### After the queue

The `docs/11_ROADMAP.md` build order (…, E, F) is **complete through Phase 6**. What
remains, none of it sequenced yet:

- ~~**The Greek decision**~~ — **taken and shipped in session 8**, as two ADRs.
  ADR-0020 promotes `LOCATION`/`ORGANIZATION` to PERSON for Greek (token-level surgery
  measured and deliberately not built); ADR-0021 extends a PERSON span left over one
  token when that is structurally safe. Net against the pre-promotion baseline: strict
  F1 0.902 → 0.910, leakage 0.117 → 0.067, Greek PERSON recall 0.154 → 0.500, PERSON
  precision 0.833 → 0.771, over-redaction still 0.000, en and de unchanged.

  **What remains is mostly beyond span and label work, which is the useful finding.**
  Classifying all 26 Greek PERSON entities on the shipped chain: 13 matched, and of the
  13 misses **8 SILENT** (the model returns no span at all), **4 DROPPED** under a
  refused label (3 of them `MISC`), **1 ABSORBED**, and **0 PARTIAL** — ADR-0021
  emptied that bucket. So 12 of the 13 never reach the reconciler as a usable span.
  Mechanism 1 — the target plan §8 named before this session — is worth one entity of
  twenty-six now that promotion has converted most absorbed spans into approved ones.
  **A better-licensed Greek model at Phase 7 is the next real move**, not another
  repair rule.
- **Distributed-path re-verification** the day the workspace's serverless sandbox is
  fixed: the databricks-marked test flips from skip to assertion by itself.
- Two parked ideas with their rationale in the session-3 handoff (archived in
  `docs/archive/SESSION_HANDOFF_S1-S8.md`): MLflow trace
  redaction, and GLiNER for the Greek gap — the latter subject to **ADR-0015
  (CPU-only)**.

Also open from Increment D: a
permissively-licensed public transcript corpus free of real PII, to replace the one
MultiWOZ's rejection removed (ADR-0018).

### The incident-notes stress corpus (ADR-0022)

`tests/fixtures/incidents/` — 90 documents, 315 entities, **585 protected tokens across
seven kinds at 6.5 per document**, en/de/el, generated and committed. Built because the
over-redaction metric was thinly supported: 102 tokens at 1.00 per document on the
benchmark corpus, 56 of a single kind on `support_tickets`, **zero** on
`multilingual_utterances`. It is **not a pack** and carries no realism claim.

| chain | strict F1 | leakage | fragment | clean rate | over-redaction |
|---|---|---|---|---|---|
| `deterministic_only` | 0.727 | 0.429 | 0.463 | 0.000 | **0.000** |
| `deterministic_presidio` | 0.761 | 0.289 | 0.314 | 0.489 | **0.024** |

PERSON strict recall, hybrid chain: tier 3 is 1.000 (en) / 1.000 (de) / 0.933 (el);
**tier 4 is 0.000 in all three**. EMAIL and PHONE are 1.000 everywhere on both chains.

**Two findings, neither visible to any earlier corpus:**

1. **Over-redaction is not 0.000.** 14 of 585 tokens destroyed, all Greek tier-4 ticket
   ids inside a PERSON span covering `Περιστατικό INC…`. **Attribution corrected during
   review:** re-running the whole corpus with `promote: []` still destroys 13, so those
   are native `PERSON` labels from the base model and owe nothing to either ADR; exactly
   one is promotion-attributable and none to ADR-0021. The first draft blamed promotion
   on the strength of one document — generalizing from a single case was the error. The
   identifier guard passes these by design: it refuses only when *no* token is
   name-like, and the Greek word is.
2. **A work-note author is never offered to a provider.** The transcript parser treats
   `2026-04-03 09:12:04 - Peter Novak:` as structure — right for a role label, wrong for
   a person — so those names cannot be redacted by anything. Verified structurally by a
   test. Not fixed here: redacting inside a speaker prefix collides with the
   reconstruction guarantee and needs its own decision.

Also exposed: `fragment_leakage_rate` exceeds `leakage_rate` on *both* chains here, and
unlike ADR-0020's gap it is an attribution artefact — name-derived emails mean a leaked
PERSON carries an unrelated EMAIL's windows, and the ambient exclusion does not remove
windows sitting inside another unredacted entity. The metric is not changed to suit a
corpus introduced alongside it.

### Known deferrals carried forward

- Greek PERSON is licence-bound to `xx_ent_wiki_sm` until Phase 7 (ADR-0007), **the
  gap is diagnosed** (Q4, ADR-0019) as span absorption, `LOC`/`MISC` label confusion
  and the άνω τελεία, and **two of the three are now acted on**: ADR-0020's promotion
  and ADR-0021's span extension. Greek PERSON recall by tier went 0.222/0.111/0.167/0.000
  to 0.556/0.667/0.333/0.000. Tier 4 has not moved and is not expected to — it is span
  absorption, which neither remedy reaches. The corpus is deliberately not made easier
  to improve any of these numbers.
- **Presidio drops spaCy's `MISC` label entirely**, before this project's adapter. It
  bounds every future label-level remedy: on the Greek slice the model emits 41 `MISC`
  spans and Presidio surfaces none of them under any requested entity name. Reaching
  them needs a spaCy recognizer registered into Presidio or a separate provider
  adapter — neither built, both scoped in ADR-0020.
- **Licence obligations are recorded but not emitted.** MASSIVE is CC BY 4.0 and Bitext
  is share-alike; both facts reach a pack's `meta.json` (`license`, `share_alike`,
  `attribution_required`, `source_url`, `transformation`), but no NOTICE file is
  written. Nothing is published today, so nothing is owed yet — this becomes real the
  moment a pack is distributed.
- ADDRESS stays in the taxonomy, undetected, until a capable provider exists (ADR-0002).
- Pseudonymization collision detection is per process, not global (ADR-0013 §4).
- Language detection is per field, not per segment; code-switching would need the
  per-segment form.
- The pipeline is row-at-a-time; `detect_batch` exists and **still has no caller** — Increment F shipped without one, and wiring it is P5.

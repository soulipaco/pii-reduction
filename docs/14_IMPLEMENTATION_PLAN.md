# Implementation Plan

Produced by session 2 (2026-08-17) after repository assessment and empirical probes.
Decisions referenced as `ADR-NNNN` are recorded under `docs/adr/`. Probe evidence is
summarized in `.claude/SESSION_HANDOFF.md` (session 2 section).

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
└── observability/    # run metrics accumulation, privacy-safe logging helpers.
```

Repo level, created only when their first content lands: `configs/` (YAML shipped
with the demo), `tests/`, `demo/` (corpus build + injection), later `notebooks/`,
`resources/`.

Dependency direction (enforced by architecture-guardian review at each increment):
everything imports `contracts/`; `providers/` and `processing/` import `entities/`
(taxonomy and reconciler); `processing/` additionally imports the protocols of
sources/parsers/language/providers/reducers/outputs; nothing imports `processing/`
except entry points; `evaluation/` is imported by benchmark entry points only.
Entry points (the A6 demo/benchmark runner CLI) live under `demo/` and a thin
`pii_reduction.cli` module — never inside `processing/`, which keeps `processing/`
free of any `evaluation/` import.

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
  `preserve_original_and_record_error`; run metrics (rows, fields, entities
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
  points), MultiWOZ 2.2 (MIT; rendered into transcript format), MASSIVE de/el
  (CC BY 4.0; multilingual short text). Injection at scale reusing the A6 engine.
- **Exit:** each demo pack reproducible from documented commands; provenance
  registry complete; injected ground truth validates against documents.

### E — Benchmark framework hardening (roadmap Phase 5)
- Slice metrics by document type; runtime metrics (cold/warm init, rows/sec);
  Markdown benchmark report generator; benchmark run metadata (config hash,
  model versions); splits are 20% dev / 20% calibration / 60% test per `docs/02`
  and ADR-0011 — thresholds are calibrated on the **calibration split only**, then
  locked, and the test split is reported exactly once (`AGENTS.md` benchmark
  integrity).
- **Exit:** two chains compared end-to-end on a generated 10k-row pack with a
  committed report; CI regression gate values chosen from this baseline (ADR-0009).

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
  *derived* injected corpora, fall back to MultiWOZ (MIT) for the ticket-style demo
  too (registry keeps both; decision point at Increment D).
- Greek NER quality via `xx_ent_wiki_sm` may be too weak to present honestly; the
  benchmark will show it, and the honest fallback is reporting Greek as
  deterministic-entities-only until Phase 7 adds a multilingual transformer.

---

## 8. Status and work queue

**This section is the live one.** Sections 1–7 are the session-2 plan as written;
where reality diverged, the divergence is recorded here and in the ADR it produced.
Update this section at the end of every session.

Last updated: session 4 (2026-08-18), after queue item Q1.

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

### Measured baseline (regenerate with `pii-reduction benchmark`)

102 documents, 180 injected entities, en/de/el, tiers 1–4, `redact`:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | 0.886 |
| relaxed F1 | 0.723 | 0.921 |
| leakage rate | 0.433 | 0.117 |
| document clean rate | 0.161 | 0.774 |
| over-redaction rate | 0.000 | 0.000 |
| PERSON precision / recall | 0.000 / 0.000 | 0.820 / 0.641 |

PERSON strict recall by language and tier, hybrid chain:

| language | tier 1 clean | tier 2 noisy | tier 3 structured | tier 4 transcript |
|---|---|---|---|---|
| en | 1.000 | 0.889 | **0.333** | 1.000 |
| de | 1.000 | 1.000 | 1.000 | 1.000 |
| **el** | **0.222** | **0.111** | **0.000** | **0.000** |

Language detection against the corpus's known language: 99/102 agreement, **zero**
confident misclassifications, 3 abstentions to `und`.

Every number above was re-measured in session 4 and reproduced exactly. They are now
also enforced: `configs/benchmark_gates.yaml` holds them as gates, so this table and
that file must agree.

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

Every hybrid gate value reproduced **exactly** on GitHub's runner (strict F1 0.886,
PERSON 0.820/0.641, en tier 3 0.333, el tier 1 0.222). The published baseline is
therefore machine-independent, not an artifact of one laptop.

#### Q2. English tier-3 PERSON recall (currently 0.333) — **diagnosed, remedy partial**

**The cause is not what this section assumed.** Presidio detects every name in the
failing documents; the *span* is wrong. Given a multi-line key/value block as one
segment, spaCy runs the entity boundary through the line break — `Peter Novak\nMobile`
where truth is `Peter Novak` — which strict matching counts as a miss and a false
positive. Tier 4 scores 1.000 with the same model and names because the transcript
parser is line-oriented. It is not merely a scoring artifact: reduction currently
destroys the field label (`Customer: <PERSON> number: …`), a structure-preservation
failure the over-redaction metric cannot see because labels are not protected tokens.

Two remedies are built and tested (ADR-0016): `split_lines` on `PlainTextParser`, and
the `key_value` parser, now registered. **Neither is enabled in any shipped config, and
Q2 is not complete.** Both fix the span and both fail the exit criterion:

| whole corpus, hybrid chain | shipped | `split_lines` | `key_value` |
|---|---|---|---|
| en tier-3 PERSON recall | 0.333 | 1.000 | 1.000 |
| strict F1 | 0.886 | — | 0.910 |
| leakage | 0.117 | — | 0.122 |
| **over-redaction** | **0.000** | 0.000 | **0.020** |
| new false positives | — | German `Rechnername` | identifiers (below) |

Holding the label out of processing removes the context that was *suppressing* false
positives on bare identifiers:

```text
'KB Article: KB000002739'    → ' KB000002739'  tagged PERSON → redacted
'Rechnername: DEMO-PC-6963'  → ' DEMO-PC-6963' tagged PERSON → redacted
```

**Note for the next session: dev+calibration did not reveal this.** Both destroyed
identifiers are in the test split, and the development splits reported over-redaction
0.000 with no slice regressing. Developing against dev/calibration is still right — it
is what stops iterating on the test split — but it is not sufficient evidence to
enable a change. Run the whole-corpus gates before claiming a remedy works.

**Remaining work is not a third parser.** Both remedies need identifier
false-positive suppression: a way to refuse a PERSON span whose surface is ticket-,
KB-, machine-, version- or order-shaped. That belongs with the reconciler or a
provider-level guard, applies to both segmentation forms, and is useful independently
— the same false positives can occur in prose. Then re-measure, enable whichever
remedy wins, and raise the floors.

Also fixed here, because Q2 depends on it: `run_benchmark` scored a subset against the
**whole** corpus's ground truth, so a dev+calibration run reported over-redaction 0.627
against a true 0.000. Any split-scoped number measured before this fix is not
comparable with one measured after.

The weakest slice that is **not** licence-bound, so the cheapest real quality win.
Structured key/value text (`Customer: Maria Rossi` on its own line) gives the NER
model no sentence context.

Investigate before changing anything: confirm on the failing tier-3 documents whether
the misses are context-window effects, the transcript/plain parser splitting the
label from the value, or Presidio's recognizer configuration. Candidate remedies in
increasing cost: a key/value parser that marks labels non-processable and passes the
value with context, per-tier provider options, or a custom recognizer. Any change is
judged by the benchmark, not by inspection.

**How to work it without tuning on the test split.** The gate value for this slice is
a whole-corpus number and CI re-reads it on every run, so iterating "change it, read
the gate, change again" is tuning against a set that is 60% test split — precisely what
ADR-0011 and `AGENTS.md` forbid. Develop the remedy against `--split dev` and
`--split calibration`, read the whole-corpus number **once** when you are done, and
raise the floor then. `--gates` refuses to run with `--split` so the two cannot be
mixed up by accident.

**Exit:** English tier-3 PERSON strict recall measurably improved with no regression
in over-redaction (must stay 0.000) and no drop in any other slice; the new numbers
replace those in this section and in `docs/15_PROVIDERS.md`, and the
`en_tier3_person_strict_recall` floor in `configs/benchmark_gates.yaml` is raised to
the new measured value. The other gates are what enforce "no drop in any other
slice" — if a remedy trades Greek or precision for English, the hybrid gate set fails
and says which gate.

#### Q3. Increment D — public datasets (§5 above)

Bitext (CDLA-Sharing-1.0), MultiWOZ 2.2 (MIT), MASSIVE de/el (CC BY 4.0) with the
provenance registry, download scripts committing no raw data, and injection at scale
reusing `pii_reduction.synthetic`. This is the first honest test of the transcript
parser's speaker heuristic on text nobody wrote for it, and of the phone/email
recognizers outside a corpus built to suit them.

Injected values must come from the ADR-0014 pools — never invented ad hoc, never
lifted from the source data.

**Exit:** each demo pack reproducible from documented commands; provenance registry
complete per `docs/02_PUBLIC_DATA_STRATEGY.md`; injected ground truth validates
against its documents; benchmark rerun and the numbers published beside the synthetic
ones rather than replacing them. The synthetic gates in `configs/benchmark_gates.yaml`
stay as they are — a public-dataset pack is a **new** gate set measured on its own
corpus, not a reason to loosen the ones that guard the committed regression set.

### After the queue

`docs/11_ROADMAP.md` order still holds: Increment E (benchmark hardening, split
discipline, mask-vs-redact leakage variants per ADR-0013 §5), then F (Databricks
Connect). Two parked ideas with their rationale are in the session-3 handoff:
MLflow trace redaction, and GLiNER for the Greek gap — the latter subject to
**ADR-0015 (CPU-only)**.

### Known deferrals carried forward

- Greek PERSON is licence-bound to `xx_ent_wiki_sm` until Phase 7 (ADR-0007).
- ADDRESS stays in the taxonomy, undetected, until a capable provider exists (ADR-0002).
- Pseudonymization collision detection is per process, not global (ADR-0013 §4).
- Language detection is per field, not per segment; code-switching would need the
  per-segment form.
- The pipeline is row-at-a-time; `detect_batch` exists but nothing calls it until F.

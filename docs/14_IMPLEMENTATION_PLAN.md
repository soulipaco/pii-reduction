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
├── observability/    # run metrics accumulation, privacy-safe logging helpers.
└── synthetic/        # build-time: corpus generation, injection, the public-dataset
                      # registry, retrieval and the demo pack builder. Added in A6 and
                      # extended in D; §3 originally put this under `demo/`, which
                      # AGENTS.md rule 3 correctly overrode — `demo/` holds runnable
                      # front doors only. Depends on the interface layers; nothing on
                      # the runtime path depends on it (docs/01_ARCHITECTURE.md).
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
  points), MultiWOZ 2.2 (**rejected in session 6 — real PII in its published text, ADR-0018**; the transcript pack is rendered from Bitext instead), MASSIVE de/el
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

Last updated: session 6 (2026-08-18), after Increment D (Q3) and the Greek diagnosis (Q4).

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

### Measured baseline (regenerate with `pii-reduction benchmark`)

102 documents, 180 injected entities, en/de/el, tiers 1–4, `redact`:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | 0.902 |
| relaxed F1 | 0.723 | 0.914 |
| leakage rate | 0.433 | 0.117 |
| document clean rate | 0.161 | 0.774 |
| over-redaction rate | 0.000 | 0.000 |
| PERSON precision / recall | 0.000 / 0.000 | 0.833 / 0.705 |

PERSON strict recall by language and tier, hybrid chain:

| language | tier 1 clean | tier 2 noisy | tier 3 structured | tier 4 transcript |
|---|---|---|---|---|
| en | 1.000 | 0.889 | 1.000 | 1.000 |
| de | 1.000 | 1.000 | 1.000 | 1.000 |
| **el** | **0.222** | **0.111** | **0.167** | **0.000** |

Language detection against the corpus's known language: 99/102 agreement, **zero**
confident misclassifications, 3 abstentions to `und`.

Every number above was re-measured in session 4 and reproduced exactly. They are now
also enforced: `configs/benchmark_gates.yaml` holds them as gates, so this table and
that file must agree.

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
2. **Greek PERSON recall is 0.606 here against 0.111–0.222 on the synthetic corpus**,
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

**Deliberately not done:** the `incident_notes` pack. ADR-0010 named three families and
this delivers two; incident metadata combined with generated work notes needs no public
source and is better placed with Increment E's mask/redact variants than bolted on here.

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

**What it opens** (ranked by what the measurement supports, none started): Greek span
absorption as an ADR-0016-family remedy — repair the output, and the rule must be
structural rather than a list of Greek words; evidence-gated promotion of `LOC`, `ORG` **and**
`MISC` — which one appears varies by carrier, so a one-label remedy would miss the
rest — which trades leakage for over-redaction and needs a measurement before an
implementation; and a better-licensed Greek model at Phase 7, now with a benchmark that
can say which of the three it fixed.

**Narrowed rather than ruled out:** treating Greek as a *pure* detection problem. Only
4 of the 40 Greek probes returned no span at all, and tier 4 is 100% boundary error — detection
work cannot touch it. But 2 of 8 do go silent in the tier-3 `Από:` form, so better
detection would move tier 3; it is simply the smallest of the three effects.

### After the queue

`docs/11_ROADMAP.md` order still holds: Increment E (benchmark hardening, split
discipline, mask-vs-redact leakage variants per ADR-0013 §5), then F (Databricks
Connect). Two parked ideas with their rationale are in the session-3 handoff:
MLflow trace redaction, and GLiNER for the Greek gap — the latter subject to
**ADR-0015 (CPU-only)**.

Also open from Increment D: the `incident_notes` pack (ADR-0010's third family), and a
permissively-licensed public transcript corpus free of real PII, to replace the one
MultiWOZ's rejection removed (ADR-0018).

### Known deferrals carried forward

- Greek PERSON is licence-bound to `xx_ent_wiki_sm` until Phase 7 (ADR-0007), **and
  the gap is now diagnosed** (Q4, ADR-0019): span absorption, `LOC`/`MISC` label
  confusion, and the άνω τελεία. Two of the three are not licensing problems. The
  corpus is deliberately not made easier to improve the number.
- **Licence obligations are recorded but not emitted.** MASSIVE is CC BY 4.0 and Bitext
  is share-alike; both facts reach a pack's `meta.json` (`license`, `share_alike`,
  `attribution_required`, `source_url`, `transformation`), but no NOTICE file is
  written. Nothing is published today, so nothing is owed yet — this becomes real the
  moment a pack is distributed.
- ADDRESS stays in the taxonomy, undetected, until a capable provider exists (ADR-0002).
- Pseudonymization collision detection is per process, not global (ADR-0013 §4).
- Language detection is per field, not per segment; code-switching would need the
  per-segment form.
- The pipeline is row-at-a-time; `detect_batch` exists but nothing calls it until F.

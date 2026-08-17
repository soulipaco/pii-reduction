# Session handoff

A running record of what each working session established, so a later session can
build on evidence instead of re-deriving it. Append a new section per session.
Keep it factual: what was verified, how, and what is still unknown.

---

## Session 1 — 2026-08-17 — Environment and development harness

**Repository root:** `C:\Users\onurh\Desktop\porfolios\pii_reduction`. The project
originally sat one level deeper, in a `databricks-pii-reduction-starter/` subfolder;
its contents were moved up so the repository root and the usual working directory are
the same path.

**Scope:** preparation only. No project source code was written. `docs/`, `README.md`,
`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and `SECURITY.md` were read but **not
modified** — they remain the source of truth.

### Repository state

- `git init` on branch `main`; initial commit `2d798ae` contains the pre-existing
  documentation plus the harness listed below. Nothing has been pushed to a remote.
- No `src/`, `tests/`, `configs/`, `pyproject.toml`, `notebooks/`, `demo/` or
  `resources/` exists yet. Every roadmap phase from Phase 0 onward is open.
- `.gitignore` excludes credentials, `.databrickscfg`, `.venv/`, data, models, outputs.
- `.gitattributes` normalizes to LF **except** `tests/fixtures/**` and `demo/**`, which
  are marked binary. Reason: parser round-trip tests assert byte-exact reconstruction,
  and git's CRLF rewriting on Windows would otherwise cause false failures.

### Environment: deliberately empty

**There is no virtualenv and no dependency file, and that is on purpose.** Which
detection provider, language detector, and NLP stack this project depends on is an
open design decision — one of the first things to be decided and justified, per
`AGENTS.md`'s dependency-discipline rule and `docs/04_PII_ENGINE.md`'s provider
abstraction. Installing a stack up front would have quietly pre-answered it.

`pyproject.toml` should be written when the decision is actually made, with core
versus optional extras, and a documented reason for every major NLP/model dependency.

What the machine has available, as raw capability rather than as a choice already made:

| Tool | Version | Note |
|---|---|---|
| Python | 3.11.9 | `py` launcher present |
| uv | 0.9.18 | fast resolver/installer, cache is warm for the probes below |
| git | 2.47.1 | repo initialized |
| gh | authenticated as `soulipaco` | scopes: repo, workflow, gist, read:org |
| databricks CLI | 0.280.0 | four valid workspace profiles |
| Java | **22 only** | see finding 3 |
| — | — | no Node.js, no Docker, no conda |

### Findings from throwaway probes

To sanity-check the documented design, a temporary environment was built with one
plausible stack (Presidio + spaCy `en/de/el_core_*_lg` + lingua), the observations
below were recorded, and **the environment was then deleted**.

Read these as evidence about *that* stack, not as an endorsement of it. They are
included because they are cheap to act on and expensive to rediscover — each one
contradicts an assumption the documentation currently rests on. If a different stack
is chosen, the first two findings need re-checking against it; the third is about the
machine and holds regardless.

**1. None of the spaCy models probed exposes an ADDRESS-style label.**

| Model | NER labels |
|---|---|
| `en_core_web_lg` | CARDINAL, DATE, EVENT, FAC, GPE, LANGUAGE, LAW, LOC, MONEY, NORP, ORDINAL, ORG, PERCENT, PERSON, PRODUCT, QUANTITY, TIME, WORK_OF_ART |
| `de_core_news_lg` | LOC, MISC, ORG, **PER** |
| `el_core_news_lg` | EVENT, GPE, LOC, ORG, PERSON, PRODUCT |

`ADDRESS` is in the documented baseline entity scope (`README.md`,
`docs/04_PII_ENGINE.md`). Presidio over spaCy will not deliver it directly — it has to
be composed from `LOC`/`GPE`/`FAC` plus context rules, or come from a different
provider. Note also that German returns `PER`, not `PERSON`: normalized label mapping
is required per model, not per provider. **This is unresolved and needs a decision.**

**2. Presidio's default email recognizer rejects RFC-reserved TLDs.**

Smoke test on `"Contact Maria Rossi at maria.rossi@example.test or +30 210 000 0000"`
returned `PERSON [8,19] 0.85`, `URL [23,31] 0.5`, `PHONE_NUMBER [51,67] 0.40` — and
**no EMAIL**. The `.test` TLD fails its validation, and a partial URL match appeared
instead. This matters directly: `AGENTS.md` requires obviously-synthetic fixtures, the
natural choice for those is reserved domains, and the default recognizer scores them
as non-emails. Decide the synthetic-fixture domain policy and the email recognizer
configuration **together**, or the benchmark will measure the fixture format rather
than detection quality. Note too that the phone score was 0.40 — default thresholds
need to be set deliberately.

`lingua` did identify Greek text correctly, so a working language detector exists for
this problem. Its accuracy on the short strings this domain is full of (`Thanks`,
`Resolved`, `OK`) was not tested and must not be assumed — `docs/05_MULTILINGUAL_STRATEGY.md`
is explicit that short text should not produce a confident language claim.

**3. Local Spark is blocked on this machine.** Only Java 22 is installed; PySpark 3.5
supports Java 8/11/17. `winget install --id EclipseAdoptium.Temurin.17.JDK --scope user`
fails with "no applicable installer" (the package is a machine-scope MSI), so it needs
an elevated shell. Not required before roadmap Phase 6. Worth evaluating instead:
Databricks Connect against the already-authenticated workspace, rather than local Spark
on Windows, which additionally needs `winutils.exe` / `HADOOP_HOME`.

A related constraint that will surface at dependency-declaration time: PySpark 3.5's
pandas API is not compatible with pandas 3.x, and Databricks runtimes ship pandas
1.5/2.x. Whatever pandas version the project declares, that pin is a Spark-parity
decision and should be made knowingly rather than by taking whatever resolves latest.

### Databricks access

The `databricks` CLI has four valid authenticated profiles (`dev`, `marvelous`,
`ecfr-demo-v1`, `contact-center-portfolio`) against a single workspace. The host is
deliberately not recorded here — `AGENTS.md` forbids hard-coded workspace values, and
the privacy hook blocks writing it. Read it from the CLI profile at runtime.

A malformed profile literally named `databricks workspace ls /` exists in
`.databrickscfg` and should be cleaned up.

### Claude Code harness (all under `.claude/`, committed)

| Path | Purpose |
|---|---|
| `settings.json` | UTF-8 + `PYTHONHASHSEED=0` env for multilingual/deterministic work; allowlist for read and test commands; **deny** rules over `.env`, `.databrickscfg`, `*.pem`, `*.key`, `.ssh/` |
| `hooks/privacy_guard.py` | PreToolUse. Blocks writes containing tokens, private keys, hard-coded workspace hosts, or consumer-domain emails. Allows RFC-reserved domains. Never echoes the matched value. Verified against 8 cases. |
| `hooks/ruff_autofix.py` | PostToolUse. `ruff format` + `ruff check --fix` on edited `.py`; exits 2 with the remaining errors so they get repaired in the same turn. Resolves ruff from `.venv` first, then PATH, and no-ops silently if neither exists — so it stays dormant until the project declares its own toolchain, then starts working on its own. |
| `agents/privacy-auditor.md` | Read-only reviewer: PII in logs/exceptions, non-synthetic fixtures, hard-coded env values, dataset provenance, non-destructiveness. |
| `agents/architecture-guardian.md` | Read-only reviewer: layer responsibilities, import direction, provider-label leakage, Databricks code in core, notebook drift, premature abstraction. |
| `commands/qa.md` | `/qa` — ruff, mypy, pytest with honest reporting of skips and deselects. |
| `commands/gate.md` | `/gate` — tests plus both auditors in parallel; consolidated blocking/non-blocking verdict. |
| `commands/phase-report.md` | `/phase-report` — the completion report `AGENTS.md` requires. |

The harness only loads when the working directory is the repository root. That is now
`…/porfolios/pii_reduction` itself, which is where sessions start by default — the
nesting that would have made this a trap was removed.

### Open decisions carried forward

Nothing below has been decided. The probes above inform some of them; none settles one.

1. **The dependency set itself** — which detection provider, language detector, and NLP
   stack the project commits to, and what goes in `pyproject.toml` as core versus
   optional extras. Everything else on this list depends on it.
2. How `ADDRESS` is produced, given that no model probed emits it directly.
3. Synthetic-fixture domain policy versus email-recognizer configuration — these two
   have to be decided together, per finding 2.
4. Per-model label normalization (`PER` versus `PERSON`).
5. Confidence thresholds per entity and per provider.
6. Local Spark (Java 17) versus Databricks Connect for Phase 6, and the pandas pin
   that follows from it.
7. Repository licence — `README.md` intentionally leaves it open pending a review of
   the licences of whatever dependencies are chosen in decision 1.

---

## Session 2 — 2026-08-17 — Assessment, probes, decisions, implementation plan

**Scope:** assessment and planning only. No pipeline code, no `pyproject.toml`, no
directories created beyond `docs/adr/`. Artifacts produced:
`docs/14_IMPLEMENTATION_PLAN.md`, twelve ADRs under `docs/adr/`, this section.

### What was verified, and how

A throwaway probe environment was built in the session scratchpad with `uv`
(Python 3.11.9; presidio-analyzer 2.2.364, spaCy 3.8.15, models 3.8.0,
lingua 2.1.1, phonenumbers 9.0.37, langdetect for comparison) and discarded.
Probe scripts lived under the scratchpad only; nothing was committed. All probe
text was synthetic.

**Session 1 findings re-verified, all three hold:**

1. No probed spaCy model emits an ADDRESS label (en/de lg+md, el lg+md, xx re-run).
2. Presidio's default `EmailRecognizer` rejects `.test` and `.invalid`; accepts
   `example.com/org/net/co.uk` at score 1.0. Also: `jane.doe@demo.example` was
   tagged PERSON 0.85 — reserved-style domains can produce false PERSON hits.
3. Java 22 only → local PySpark still blocked.

**New findings, in decreasing order of consequence:**

1. **`el_core_news_lg` and `el_core_news_md` are CC BY-NC-SA 3.0 (non-commercial)**
   per their own `meta.json`. They cannot be dependencies of an MIT project.
   en/de models and `xx_ent_wiki_sm` are MIT. This forced the Greek routing
   decision (ADR-0007): Greek NER via `xx_ent_wiki_sm` until Phase 7.
2. **Presidio scores are recognizer constants, not probabilities:** every
   spaCy-backed hit scores exactly 0.85 (correct or not), EmailRecognizer 1.0,
   PhoneRecognizer 0.40 across all matched formats. A global threshold of 0.5
   would silently drop all phones (ADR-0005).
3. Presidio maps German `PER`→`PERSON` itself; adapter-level normalization still
   required for its own labels (`EMAIL_ADDRESS`, `PHONE_NUMBER`; `URL` emits
   partial-match noise like `maria.ro` and is dropped) (ADR-0004).
4. Greek NER via `xx_ent_wiki_sm` works but with boundary errors: PERSON span
   absorbed the preceding verb `Ονομάζομαι`; a bare surname was tagged ORG; a
   street name was tagged LOCATION-ish or ORG. Motivates strict+relaxed dual
   metrics (ADR-0011).
5. German address probe: only `Musterstrasse` and `Berlin` tagged LOC; house
   number and postal code uncovered → LOC-composition ADDRESS is not credible
   (ADR-0002).
6. Offsets are Python codepoint indices and slice-true on NFC, NFD (combining
   characters change span lengths: same Greek name 18 vs 20 codepoints), and
   astral emoji, for spaCy and Presidio alike. Ground-truth spans are therefore
   valid only against the exact string form; no normalization anywhere (ADR-0011).
7. lingua on short strings (restricted to en/de/el): `Thanks` en 0.89,
   `Resolved` en 0.96, `OK` en 0.52, `Ευχαριστώ` el 1.00; `maria@example.com`
   alone → en 0.95 (spurious). Confidence alone cannot gate short text — hard
   char-count gate required (ADR-0012). langdetect mislabeled `Danke`→da,
   `Call me`→it, `Resolved`→no; rejected.
8. Timing: 3-model Presidio engine init ~7.7 s; first analyze ~1.8 s (lazy
   warmup); warm 7–30 ms per short text. md models load ~1 s vs lg 2.2–3.4 s with
   identical label sets → md for CI, lg for benchmarks (ADR-0009).
9. Negative-example probe (`INC0004182`, `DEMO-PC-6915`, `KB000002715`, `v4.8.3`)
   produced zero detections on defaults — good over-redaction baseline. But the
   word "Email" was tagged PERSON 0.85 in another sentence; PERSON false
   positives at the flat score are real.

**Dataset licences verified via the web (2026-08-17):** Bitext customer-support
(CDLA-Sharing-1.0, synthetic, placeholder-templated), MultiWOZ 2.2 (MIT),
MASSIVE (CC BY 4.0, includes de-DE and el-GR). Kaggle "Customer Support on
Twitter" rejected (CC BY-NC-SA + real PII).

### Decisions taken (full reasoning in docs/adr/)

All seven carried-forward decisions are now closed: 1→ADR-0001/0008,
2→ADR-0002, 3→ADR-0003, 4→ADR-0004, 5→ADR-0005, 6→ADR-0006, 7→ADR-0007.
Additional: CI (ADR-0009), datasets (ADR-0010), evaluation (ADR-0011),
language detection (ADR-0012).

Documentation inconsistencies found: `LanguageResult.supported` vs `is_supported`
(docs/03 form wins; the one-word example in `docs/01` was corrected in place);
`fasttext` in config examples (ADR-0012 records the divergence; examples left
as-is since the docs label them suggestions); roadmap Phase 2 demanding metrics
before Phase 5 builds the evaluator (plan §6 pulls a minimal evaluator into the
first slice); ADDRESS in the initial baseline (ADR-0002). Per the
architecture-guardian's review, one-line "amended by ADR-0002 / plan §6" pointers
were added at the affected spots in `docs/11_ROADMAP.md` (Phase 2 exit criteria),
`README.md` (entity baseline), and `docs/00_PROJECT_CHARTER.md` (initial scope)
so the read-order docs no longer contradict the ADRs silently. No other doc text
was changed.

Both auditors reviewed the artifacts before this session ended. privacy-auditor:
no blocking issues (two suggestions folded into the plan: privacy-safe manifest
rejection errors; postal-code annotation if the German address template becomes a
fixture — the latter deferred to Increment A6). architecture-guardian: plan sound;
one blocking wording bug fixed (plan §E now names the 20/20/60 dev/calibration/test
split and calibration-split-only tuning), plus: adapter-owned label mapping tables
(ADR-0004 amended — provider-native strings never leave `providers/`),
`entities/` and entry-point placement added to the plan §3 dependency rules,
deterministic provider score semantics specified in ADR-0005, shared
pattern-module note added to ADR-0012.

### Deliberately left open

- Exact CI benchmark gate values — locked from measured baselines at Increments
  A6/E, not invented (ADR-0009).
- Bitext share-alike implications for redistributing injected derivatives —
  decision point at Increment D with MultiWOZ fallback wired (ADR-0010).
- Databricks Connect version selection — resolved at Increment F against the
  workspace runtime (ADR-0006).
- Threshold calibration — Increment E, calibration split only (ADR-0005).

### Nothing from the probes is worth keeping as code

Probe scripts were measurement one-offs; the implementation session should write
providers fresh against the contracts. No probe output was committed.

### What the next session should do first

1. Increment A1 from `docs/14_IMPLEMENTATION_PLAN.md` §5: `pyproject.toml`,
   `LICENSE` (MIT), `contracts/`, `config/`, `entities/` with their tests.
2. Run `/qa` once the package exists; the ruff hook activates automatically once
   `.venv` + dev extra exist.
3. Proceed A2 → A6 in order; do not start Increment B until A6's exit criteria
   (deterministic corpus benchmark running, EMAIL/PHONE recall ≥0.95) hold.

---

## Session 3 — 2026-08-17/18 — Increments A1–A6, B and C

### Start here (session 4)

Everything below this block is evidence — read it when you need the reasoning behind
something, not as a prerequisite. To pick up work:

1. Read `docs/14_IMPLEMENTATION_PLAN.md` **§8**. It holds the status table, the
   measured baseline, and the three-item queue with exit criteria.
2. Work the queue **in order**: CI workflows → English tier-3 PERSON recall →
   Increment D (public datasets). All three are required; none is optional.
3. Before each commit: `/qa`, then `/gate`. Report which test tier you ran — the
   default `pytest` excludes `integration`, `slow` and `databricks` (ADR-0009).
4. When you finish an increment, update §8 of the plan and append a session section
   here. Numbers in documentation must come from a run you actually did.

State at the end of session 3: ten commits on `main`, working tree clean, nothing
pushed (no remote configured). `ruff`, `mypy src tests` clean. 480 default-tier tests
and 71 integration tests pass. `.venv` has core + `dev` + `presidio` + `language`
installed, with `en_core_web_md`, `de_core_news_md` and `xx_ent_wiki_sm`.

Two constraints that are easy to violate without noticing:

- **CPU-only (ADR-0015).** This repository is real parallel work, not only a
  portfolio piece, and the deployment target has no GPU. No component may *require*
  one; published baselines are CPU numbers.
- **Synthetic data comes from published unassigned ranges (ADR-0014).** A phone
  number in a fixture must be both valid to `phonenumbers` and impossible to reach.
  Session 3 shipped 17 real Berlin numbers before the privacy audit caught it.

---

**Scope:** Increments A1–A6 of `docs/14_IMPLEMENTATION_PLAN.md` §5 — the whole first
slice. First code in the repository. A1: `pyproject.toml`, `LICENSE` (MIT, ADR-0007),
`contracts/`, `entities/`, `config/`. A2: `parsers/`. A3: `providers/` +
`patterns.py`. A4: `entities/reconcile.py` + `reducers/` — with masking and
pseudonymization included by explicit decision (ADR-0013). A5: `sources/`,
`language/`, `outputs/`, `observability/`, `processing/`. A6: `synthetic/`,
`evaluation/`, `benchmark.py`, `cli.py`, `configs/`, `demo/`, and the committed
corpus. Tests with each.

### Environment

`.venv` created with `uv` (CPython 3.11.9), `uv pip install -e ".[dev]"`. Resolved:
pydantic 2.13.4, PyYAML 6.0.3, pandas 2.3.3, phonenumbers 9.0.37, pytest 9.1.1,
ruff 0.16.3, mypy 2.3.1, Faker 40.36.0. No provider extra, no spaCy model — and the
suite passes without them, which is the A1 exit criterion. The `ruff_autofix` hook
went live as soon as `.venv` existed, exactly as session 1 designed it.

### Decisions taken while implementing (nothing here contradicts an ADR)

1. **Label validation is split by layer.** `contracts` validates only the *shape* of
   an entity label (`^[A-Z][A-Z0-9_]*$`); membership in the taxonomy belongs to
   `entities`. Reason: plan §3 requires `contracts` to import nothing else in the
   package, so it cannot ask `entities` whether `EMAIL_ADDRESS` is real. The split
   keeps the dependency hub clean and is covered by a test that walks the AST of
   every `contracts/*.py` looking for project-internal imports.
2. **`entities/mapping.py` ships the machinery, not the tables** (`LabelMapping`,
   `DropCounter`), per ADR-0004; plan §3's wording was amended in place. Tests use
   `PER→PERSON` / `EMAIL_ADDRESS→EMAIL` doubles that stand in for the tables
   Increment B will ship inside `providers/`.
3. **`config/registries.py` holds the names configuration may reference**
   (parsers, reducers, provider types, source/destination types, overlap policies,
   detectors). A name is added there in the increment that implements it, so
   unimplemented components fail config validation instead of failing mid-run —
   and `config` stays free of imports from `parsers`/`providers`/`sources`.
4. **Entity scope is never defaulted.** A column with no `entities` list is a
   configuration error rather than an implicit "all four" (AGENTS.md rule 7).
5. **`observability.log_raw_text: true` is refused unless `project.environment`
   is `local`.**
6. **ruff excludes `docs/` and `.claude/`** (documentation is the source of truth;
   the harness is tooling) and ignores RUF001–003, whose ambiguous-Unicode warnings
   fire on every legitimate Greek fixture.

### Increment A2 — parsers

`PlainTextParser` and `TranscriptParser` behind a `Parser` protocol, with
`BaseParser` implementing reconstruction **once** so a new parser cannot get the
round-trip subtly wrong; a `registry.build_parser(name, options)` whose contents a
test pins to `config.registries.KNOWN_PARSERS`.

Decisions:

1. **Line breaks are their own non-processable segments** (`line_break`), and lines
   are split on CR/LF/CRLF by regex rather than `str.splitlines`, which also breaks
   on U+2028 and friends and would silently change what counts as a line. CRLF
   therefore survives byte-exact without any special casing downstream.
2. **A colon only starts a body when the text before it looks like a speaker:**
   non-empty, ≤40 chars, ≤5 words, contains a letter, does not end in a digit, and
   is not a URI scheme (or followed by `//`). This is what keeps `call me at 09:15`,
   `the ratio is 3:1` and `https://example.com` out of the prefix. Timestamped lines
   are matched first so the timestamp's own colons are consumed by the prefix
   pattern before the speaker search begins. Known limitation: a body line starting
   `Note: ...` is still read as a speaker turn — harmless (the prefix is preserved
   either way, and `Note` is not PII) but worth revisiting if note-history parsing
   lands.
3. **Malformed/undelimited lines become one processable body** and append
   `no_speaker_prefix` to `ParseResult.fallbacks` (`docs/06` `fallback:
   preserve_line`). Fallbacks are reason codes only — never text.
4. **Parser fixtures are Python constants with explicit escapes, not files** under
   `tests/fixtures/`. The plan assumed files; constants are strictly safer for a
   byte-exact invariant on Windows, since no git/editor/checkout setting can rewrite
   a literal `\r\n` in source. `tests/fixtures/` is still the right home for the A6
   corpus, which is generated data rather than hand-written cases.
5. `parse()` rejects non-`str` input with an actionable `ParserError`: null handling
   is the field processor's job (`docs/03` §18), not every parser's.

### Increment A3 — deterministic provider

`BaseProvider.detect` is a template method: subclasses implement `_detect`, the base
enforces the provider contract on the way out (normalized labels, spans within the
text, requested scope only, stable ordering, correct attribution). `DeterministicProvider`
covers EMAIL and PHONE. `tests/provider_contract.py` holds the shared suite that
Increment B's Presidio adapter subclasses instead of restating.

Two findings came from the tests, both of which changed the implementation:

1. **`phonenumbers` at `possible` leniency matches ordinary identifiers.** It
   reported `6915` from `DEMO-PC-6915`, `12345` from `Order 12345 shipped`, and
   fragments of `2026-04-03 09:15:04` as phone numbers — the exact negative fixtures
   of `docs/10_TESTING_QA.md` §6. Default leniency is therefore **`valid`**;
   `possible` stays available per dataset and is where ADR-0005's 0.85 score tier
   applies. A boundary guard additionally rejects matches whose neighbouring
   character is alphanumeric, so a digit run inside a ticket id cannot surface.
2. **The first email pattern rejected a sentence-final period** —
   `Write to maria@example.com.` found nothing, because the trailing-context
   exclusion included `.`. Fixed; `example.co.uk` still matches in full.

Email/URL/digit patterns live in a neutral `pii_reduction/patterns.py` so the
Increment C short-text gate strips exactly what the recognizer matches (ADR-0012).
Region handling runs one `PhoneNumberMatcher` pass per configured region plus a
region-less pass for `+`-prefixed numbers, deduping identical spans at the strongest
score.

### Increment A4 — reconciliation and reduction (scope extended)

The reconciler implements the seven documented steps of `docs/04_PII_ENGINE.md` with
a configurable `ReconciliationPolicy` (priorities, provider order, per-provider
per-entity thresholds, entity scope) and records every rejection with a reason —
`overlap`, `below_threshold`, `out_of_scope` — carrying offsets only. Two providers
returning an *identical* span corroborate each other (both land in
`supporting_matches`) rather than one being recorded as rejected.

**Reduction scope was extended beyond the plan by explicit decision.** The plan and
roadmap Phase 8 deferred masking and pseudonymization; session 3 assessed the
trade-off, the repository owner chose to build all three strategies now, and
**ADR-0013** records the decision and its consequences. `docs/11_ROADMAP.md`
Phase 8 and plan §5 carry "amended by ADR-0013" pointers.

What that forced to be right the first time:

- `reduce(text, entities) -> ReductionResult`, not `replacement_for(entity)`. Only a
  reducer that sees the text can produce `ma***@example.com` or a stable token. The
  surface reaches `_replacement` and nothing else; `ReductionOperation` still records
  offsets, label, replacement and strategy only.
- Right-to-left replacement, span validation and operation recording live once in
  `BaseReducer`; overlapping input is refused with "reconcile candidates before
  reducing" rather than silently corrupting offsets.
- Pseudonymization: HMAC-SHA256, key read only from the environment variable named
  by `key_env` (missing key is a hard failure naming the variable), scope mixed into
  the message, no normalization before hashing, no reverse mapping, and in-process
  collision detection over digests — never plaintext. The limits (truncated digest,
  no cross-worker collision check) are documented in the module and in ADR-0013.
- Leakage must be reported per strategy from Increment E onward: masking retains part
  of the value by design, so its leakage number is not comparable with redaction's
  (ADR-0013 §5).

### Increment A5 — the slice runs end to end

`sources/` (pandas, CSV, parquet), `outputs/` (pandas, CSV, parquet, run-metrics
JSON), `language/` (static and column resolvers — lingua is Increment C),
`observability/` (metrics accumulator, privacy-safe logging), `processing/`
(field processor + pipeline). `build_pipeline(config)` then `pipeline.process(dataset)`
is the whole public surface, as `docs/01_ARCHITECTURE.md` specifies for
local/Databricks parity.

Decisions and their reasons:

1. **Every package except `processing/` is built from primitives, not config
   objects.** `build_source("csv", path=..., options=...)` rather than
   `build_source(SourceConfig)`. `processing/pipeline.py` is the single module that
   imports both `config` and the registries; sources, outputs, language, parsers,
   providers and reducers stay config-free and independently testable.
2. **A `parquet` extra (pyarrow) was added** — configuration already allows parquet
   sources and destinations, pandas cannot read or write parquet unaided, and putting
   pyarrow in core would contradict ADR-0008's "nothing else". The adapters raise an
   actionable error naming the extra when it is missing; `pyarrow` is in `dev` so the
   default test run covers them. ADR-0008 carries the amendment.
3. **Failure modes are all three, and they differ.** `preserve_original_and_record_error`
   passes the source text through; `quarantine_row` writes no reduced value (the row
   stays, so row count is preserved, but nothing unreviewed can be mistaken for
   reduced output); `fail_fast` raises `ProcessingError` naming dataset, row and
   column.
4. **Third-party exception messages are dropped.** Only this package's own exceptions
   (written to be privacy-safe) keep their message in `ProcessedFieldResult.error`;
   anything else retains its type name only, because a pandas or stdlib exception can
   quote a cell value. Covered by a test that raises `ValueError(f"...{text}")` and
   asserts the text never survives.
5. **Logging cannot carry text by construction.** `observability.logging.safe_fields`
   renders only an allow-list of field names and silently drops everything else, so a
   future caller cannot start logging `text=` by accident.
6. **The run status distinguishes "worked" from "worked, but".** A field that
   succeeded only via a parser or language fallback now increments
   `fields_with_fallback` and lifts the run status to `success_with_fallback` — found
   because a test expected that and the first implementation reported plain success.

Structural validation runs before processing (missing/duplicate/null row ids, missing
configured column, pre-existing output column) and after (row count, originals
unchanged, output columns present), driven by the `validation:` config block.

### Increment A6 — corpus, evaluation, and the first measured baseline

`synthetic/` (curated value pools, templates per language and tier, injector,
corpus writer/loader), `evaluation/` (strict and IoU-relaxed matching, detection
metrics with mandatory support counts, leakage, over-redaction, document clean rate,
report rendering), `benchmark.py` (the entry point that imports both `processing` and
`evaluation`), `cli.py` with a `pii-reduction` console script, shipped `configs/`, a
`demo/build_corpus.py` front door, and the committed corpus under
`tests/fixtures/corpus/`.

Decisions:

1. **No Faker.** The plan said "template + Faker generation"; curated pools are used
   instead. They are deterministic without seeding a third-party RNG, keep the
   generator out of the dev-only dependency set, and — the deciding reason — let
   Greek names actually be Greek with a matching Latin transliteration for the email
   local part, which locale-based generation does not guarantee. A `ValueProvider`
   protocol is the seam Faker plugs into at Increment D, where volume matters more
   than control.
2. **Audit offsets became field-relative** (`start = segment_start + entity.start`,
   with `segment_start` retained for traceability). Segment-relative offsets cannot be
   compared with ground truth, which is measured against the whole document — the
   benchmark simply could not have scored transcripts otherwise.
3. **Two dataset configs, one per document type** (`benchmark_plain`,
   `benchmark_transcript`). A column has one parser, and that is the real-world shape;
   the benchmark filters by `document_type` and runs each subset through its own
   config, so both parsers are exercised.
4. **The manifest carries `surface`** because this corpus is wholly synthetic and
   committed — it is what the loader validates against and what the leakage metric
   searches for. A manifest over real data would carry only `synthetic_value_id`. The
   loader's rejection message reports document id, entity id and offsets and never the
   expected value, so it stays privacy-safe against non-synthetic data.
5. **Document-level slice attributes are first-wins.** Language and tier belong to a
   document, not to an entity inside it; a test caught the original last-wins
   behaviour silently moving a document between slices.

### Increment B — the Presidio provider

`providers/presidio_provider.py`, `docs/15_PROVIDERS.md`, the `deterministic_presidio`
chain in `configs/providers.yaml`, a `--chain` benchmark override, and two
integration-marked test modules (45 tests).

Environment: `presidio-analyzer 2.2.364`, `spaCy 3.8.15`, models `en_core_web_md`,
`de_core_news_md`, `xx_ent_wiki_sm` (all 3.8.0, all MIT).

Decisions:

1. **The adapter does not filter by threshold.** Thresholds are configuration policy
   applied once, by the reconciler, which already records what each threshold
   rejected. Two enforcement points would mean two places to look when a phone number
   goes missing. `RECOMMENDED_THRESHOLDS` documents the ADR-0005 values;
   `configs/providers.yaml` sets them.
2. **The adapter requests only the three native labels it maps.** `URL` (partial-match
   noise like `maria.ro`) and `LOCATION` (not an address, ADR-0002) never arrive
   rather than being filtered after the fact. The drop table remains as a safety net
   for future Presidio versions, and every drop is counted.
3. **Lazy dependency, not lazy module.** ADR-0008 said importing the module without the
   extra should raise. It does not: the module imports fine, the provider constructs
   fine, and only building the engine reaches for Presidio. That keeps config
   validation, registry listing and `--help` working on a machine with no models, and
   the error still names the exact install commands.
4. **Configuring `el_core_news_*` is refused in code**, not only in documentation
   (ADR-0007) — it is the obvious pick for Greek and the licence problem is invisible
   at the call site.
5. **Engine caching by model configuration**, module-level, so constructing the
   provider twice loads nothing. Tested by timing (cold vs warm) and by identity.
6. **The default `pytest` run is now the fast tier** (`-m "not integration and not slow
   and not databricks"` in `addopts`, per ADR-0009). Integration is explicit:
   `pytest -m integration`. `/qa` therefore reports the model-free tier, which is what
   a contributor without models can actually run.

Two tests failed when B landed, both correctly:

- the import guard had been passing by luck — collecting the Presidio test module
  imports spaCy, so an in-process `sys.modules` check depended on test ordering. It
  now runs a subprocess and asserts the stronger property that
  `pii_reduction.providers` itself imports without the extra.
- the "pending provider type" test described a world where presidio was
  unimplemented. It is now a registry-parity test
  (`available_provider_types() == KNOWN_PROVIDER_TYPES`) plus a small test that the
  pending mechanism still works.

### Increment B results — the measured comparison

`pii-reduction benchmark` versus `pii-reduction benchmark --chain deterministic_presidio`,
same 102-document corpus, same `redact` strategy:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | **0.886** |
| relaxed F1 | 0.723 | **0.921** |
| leakage rate | 0.433 | **0.117** |
| document clean rate | 0.161 | **0.774** |
| over-redaction rate | 0.000 | **0.000** |
| PERSON strict precision / recall | 0.000 / 0.000 | **0.820 / 0.641** |

EMAIL and PHONE stay at 1.000 with zero false positives — adding a provider did not
disturb what already worked, because the reconciler prefers the deterministic span on
identical matches.

PERSON strict recall by language and tier — the number that matters:

| language | tier 1 clean | tier 2 noisy | tier 3 structured | tier 4 transcript |
|---|---|---|---|---|
| en | 1.000 | 0.889 | 0.333 | 1.000 |
| de | 1.000 | 1.000 | 1.000 | 1.000 |
| **el** | **0.222** | **0.111** | **0.000** | **0.000** |

Three findings to carry forward:

1. **Greek is effectively uncovered for PERSON.** A licensing consequence, not an
   oversight: `el_core_news_*` is CC BY-NC-SA (ADR-0007), so Greek runs through
   `xx_ent_wiki_sm`. The honest position until roadmap Phase 7 is that Greek is
   deterministic-entities-only, and `docs/15_PROVIDERS.md` says so in the table rather
   than in a footnote.
2. **English tier 3 (structured key/value) is the second weakest slice at 0.333** —
   `Customer: Maria Rossi` on its own line gives the model little sentence context.
   Cheaper to address than Greek and worth looking at before Phase 7.
3. **The strict–relaxed gap opened for the first time** (0.886 vs 0.921). It was
   exactly zero while only deterministic spans existed. That gap is boundary quality,
   and it is why ADR-0011 insists on reporting both.

### Increment C — language detection and routing

`language/gate.py` (the short-text policy, dependency-free), `language/lingua_detector.py`,
`language/registry.py`, per-language provider routing in the field processor, and
`configs/` switched to detection as the product default.

Decisions:

1. **The gate is separated from the detector and has no optional dependency.** It is
   the part with the interesting edge cases and must be testable in the default
   model-free tier. Detection-accuracy tests are integration-marked; the policy tests
   are not.
2. **The gate is structural, not probabilistic** (ADR-0012, re-confirmed by probe):
   `Thanks` scores `en` 0.89, `Resolved` 0.96, and a bare `maria@example.com` scores
   `en` 0.95. No confidence threshold separates those from genuine short German or
   Greek, so the gate strips emails, URLs and digits — using the same `patterns.py`
   the EMAIL recognizer uses, so the two cannot disagree about where an address ends
   — counts what is left, and refuses when there is too little.
3. **Language is resolved from eligible text only**, not the raw field. Transcript
   timestamps and speaker names are structure, and feeding them to a detector biases
   it toward whatever the metadata looks like. Closes an architecture-audit
   observation.
4. **Provider routing is real.** `languages:` maps a language to a chain; an unknown
   or unsupported language takes `language.fallback_chain` (deterministic-only by
   default) rather than a guess, because running an English NER model over text of
   unknown language is how false positives are manufactured. Providers are built once
   and shared across chains, so two chains naming the same provider do not each load
   its models.
5. **Provider-scoped `entities` and `languages` now bind.** They were inert
   configuration — the architecture audit flagged it, and the first routing test
   failed because of it, which is the best possible way to find out. A provider
   declared `entities: [EMAIL]` that returns PHONE is the scope drift `AGENTS.md`
   rule 7 forbids; the chain now enforces both scopes.
6. **`configs/project.yaml` defaults to `mode: detect`** — real datasets do not arrive
   with a language column. The two benchmark dataset configs override back to
   `mode: column` deliberately: a detected language there would fold detection error
   into the PII numbers, and the two failure modes must stay separately attributable.

### Increment C results — detection measured against the corpus

The corpus carries its true language, so agreement is measured rather than assumed.
Over all 102 documents:

| | |
|---|---|
| agreement with the known language | **99/102 = 0.971** |
| confident misclassifications | **0** |
| abstentions (`und`) | 3 |

The shape matters more than the rate. Every disagreement is an *abstention*, not a
wrong answer: three tier-2 (noisy) English documents fell below the confidence floor,
routed to `und`, and from there to the deterministic-only fallback chain. Tiers 1, 3
and 4 agree on every document in all three languages. A wrong language claim would
route text to the wrong provider chain; the gate turns uncertainty into a safe
fallback instead, which is exactly what it exists for.

### Verified

At the end of C: `ruff format --check .` clean (108 files), `ruff check .` clean,
`mypy src tests` clean (102 files, strict + pydantic plugin).

- Default tier: `pytest -q` → **480 passed / 0 failed / 0 skipped / 71 deselected**,
  7.5 s.
- Integration tier: `pytest -q -m integration` → **71 passed / 0 failed**, 11.2 s,
  with the three spaCy models and lingua installed.

The published benchmark is unchanged by C (strict F1 0.723 deterministic-only, 0.886
hybrid), because the benchmark configs deliberately keep the corpus's known language.

(Test counts by increment: A1 90; A2 183; A3 244; A4 316; A5 378; A6 447; B adds 45
integration; C 480 default and 71 integration.)

**A6's exit criterion holds, and the first measured baseline exists.**
`pii-reduction benchmark` runs the slice end to end over the committed 102-document
corpus (180 injected entities, 102 protected tokens, en/de/el, tiers 1–4, plain and
transcript) and prints the table. Measured with the `deterministic_only` chain and
`redact`:

| metric | value | support |
|---|---|---|
| EMAIL strict precision / recall / F1 | 1.000 / 1.000 / 1.000 | 51 |
| PHONE strict precision / recall / F1 | 1.000 / 1.000 / 1.000 | 51 |
| PERSON strict recall | **0.000** | 78 |
| overall strict F1 | 0.723 | 180 |
| relaxed F1 | 0.723 | 180 |
| leakage rate | 0.433 | 180 |
| document clean rate | 0.161 | 93 |
| over-redaction rate | **0.000** | 102 |

EMAIL/PHONE recall is 1.000 in every language and every tier, clearing the ≥0.95
gate. Every number in the leakage column is a PERSON entity: 78 of 180 entities leak
because nothing detects names yet, and the document clean rate is 0.161 for the same
reason. That is the honest v0.1 picture, and the gap is exactly what Increment B is
for. Over-redaction is 0.000: no ticket, KB, machine, version or order identifier was
touched. Strict and relaxed agree because deterministic spans are exact; the gap
becomes informative when an NER provider joins.

A5's exit criterion holds: `build_pipeline(config).run()` processes the committed
20-row synthetic fixture (`tests/pipeline_fixtures.py`, en/de/el/fr, plain and
transcript, nulls, empty strings, negative identifiers) from CSV to CSV, writes a
run-metrics JSON whose keys match `docs/03_DATA_CONTRACTS.md` §11, and a privacy-safe
audit file. All eight synthetic emails and five phone numbers are gone from the
output; `INC00128492`, `KB000002715`, `DEMO-PC-6915`, `v4.12.3` and `Order 12345`
all survive. Captured logs, the metrics file, the audit file and the row results were
each asserted free of every fixture PII value.

A2's exit criterion holds: `reconstruct(parse(text)) == text` for all 19 transcript
fixtures under both parsers, including CRLF, mixed CR/LF/CRLF, NFD Greek, blank
lines, empty turns, empty string, and text with no delimiter at all. Segment
`source_start`/`source_end` are asserted slice-true against the source for every
fixture.

A4's exit criterion holds: `tests/test_reduction_slice.py` composes parser →
provider → reconciler → reducer by hand over Demo 2 of `docs/12_DEMO_SCENARIOS.md`.
All four metadata prefixes come back byte-identical under all three strategies, and
the documented demo output is reproduced exactly once a PERSON span is supplied by
hand. The provider-driven case deliberately shows `Maria Rossi` surviving — PERSON
detection does not exist until Increment B, and the test says so rather than hiding
it.

### Known gaps

- The transcript parser's speaker heuristic and the phone boundary guard are tuned on
  synthetic fixtures only; Increment D's real corpora are the first honest test.
- **Greek PERSON detection is weak (0.000–0.222 recall)** and bounded by licensing
  until a permissively-licensed multilingual model arrives in roadmap Phase 7. Any
  Greek demo should be presented as deterministic-entities-only.
- English tier-3 (structured key/value) PERSON recall is 0.333 — the second weakest
  slice, and not licence-bound.
- The `presidio` chain is **not** the default in `configs/datasets/*.yaml`: the
  default benchmark must stay runnable without models. Use `--chain
  deterministic_presidio` (or set it per dataset) to exercise NER.
- Pseudonymization collision detection is per process. On Spark it is per worker and
  therefore not a global guarantee (ADR-0013 §4).
- Mask leakage semantics are decided (ADR-0013 §5) but not implemented — Increment E
  owes two leakage variants and a strategy dimension in the benchmark schema.
- The benchmark reports every split together. Increment E owes the discipline of
  calibrating on the calibration split and reporting test once (ADR-0011); the
  `--split` plumbing exists and is tested, but nothing enforces the protocol yet.
- Language detection is per field, not per segment. `docs/14` §5 Increment C mentions
  "confidence recorded per segment"; the aggregate-per-field form is what shipped,
  which is the right default for a transcript where every turn is the same language.
  A code-switching document would need the per-segment form.
- The pipeline is row-at-a-time. `detect_batch` exists on the provider contract but
  nothing calls it yet; batching matters at Increment F, not before.
- The corpus is 102 documents from 12 templates per language. It is a regression set,
  not a quality benchmark: template variety, not size, is its limiting factor.
  Increment D's public datasets are where breadth comes from.
- The privacy-auditor and architecture-guardian have **not** been run against any of
  these increments.
- A1–A6, B and C are committed (ten commits). Nothing is pushed; no remote is
  configured.
- No CI workflow exists yet. ADR-0009 designs three tiers and the markers now work
  locally, but `.github/workflows/` is empty. This is the largest remaining gap in the
  engineering story.
- **CPU-only is now a hard constraint (ADR-0015)** — the repository is real parallel
  work, not only a portfolio piece, and the deployment target has no GPU. Every Phase 7
  provider evaluation gates on CPU latency and throughput alongside quality.

### Next

Increment D (public datasets) is the plan's next step, but three things now compete
with it and the ordering is a judgement call:

1. **CI workflows** (ADR-0009). Both tiers work locally; nothing runs them on push.
   The cheapest durable protection for everything built so far.
2. **English tier-3 PERSON recall (0.333)** — the weakest slice that is *not* licence
   bound. Names in key/value blocks (`Customer: Maria Rossi`) give the model no
   sentence context. Likely a recognizer-configuration or context-window fix rather
   than a model limit, and directly improves the published number.
3. **Increment D** — Bitext, MultiWOZ 2.2, MASSIVE with the licence registry and
   injection at scale. Real breadth, and the first honest test of the transcript
   parser's speaker heuristic on text nobody wrote for it.

Two integration ideas were reviewed and deliberately parked (session 3):

- **MLflow trace redaction** (`mlflow.tracing.configure(span_processors=[...])`).
  Databricks ships no detector there — the docs tell you to bring a regex or
  instantiate Presidio yourself — so a thin `pii_reduction.integrations.mlflow` span
  processor is a natural fit over the existing field-level path, behind an `mlflow`
  extra. The owner's call was "optional, later". Note the caveat: it redacts only what
  is *recorded in the trace*, not what the model receives, so it is an observability
  control rather than data minimization.
- **GLiNER** (Apache-2.0, so licence-compatible unlike the Greek spaCy models) as a
  Phase 7 candidate for the Greek gap — but subject to ADR-0015: it must be CPU-viable
  to qualify.

---

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

### Start here (session 6) — superseded, see session 6's own block at the end

Everything below this block is evidence — read it when you need the reasoning behind
something, not as a prerequisite.

**State:** working tree clean, all work pushed to `soulipaco/pii-reduction` (private),
CI green, nightly integration workflow green on its own schedule. `ruff` and
`mypy src tests` clean. **730 default-tier tests, 73 integration.** `.venv` has core +
`dev` + `presidio` + `language`, with `en_core_web_md`, `de_core_news_md` and
`xx_ent_wiki_sm` (all 3.8.0).

**Q1 and Q2 are complete.** The queue is down to **Increment D — public datasets**,
which is half built. Pick up there.

#### What Increment D still needs

Landed already (`pii_reduction.synthetic`):

- `injection.py` — inserts synthetic PII into text this project did not write, and
  records exact spans. This is the piece A6 could not do: the template generator knows
  where entities are because it placed them, while a public corpus already exists.
- `registry.py` + `demo/registry.yaml` — the licence gate. `require_publishable()`
  refuses an unregistered dataset, a non-permissive licence, or any source whose
  `contains_real_pii` is not `False` (including `possible`).

**Open items the session-5 audits raised and did not close** — read before writing the
pack builder, because two of them are its job:

- **The licence gate is not on the path.** `require_publishable()` refuses correctly,
  but nothing forces a build to call it: `inject()` takes raw `text` and has no dataset
  parameter, so at the moment public text enters an artifact nothing knows where it
  came from. Thread a `dataset_key` through the builder into the gate, or make the gate
  the only way to obtain text.
- **ADR-0010 needs superseding twice.** MultiWOZ was its MIT fallback and is now
  rejected (below); and it decided Bitext injection would substitute at the corpus's
  `{{placeholder}}` markers, while `injection.py` inserts at sentence and line
  boundaries instead. Marker substitution would also sidestep the structure problem
  entirely for Bitext — worth reconsidering, and either way it needs an ADR.
- **Provenance fields are incomplete.** `AGENTS.md` and ADR-0010 both require a
  recorded *transformation* and a *checksum*; `_REQUIRED_FIELDS` has neither. Bitext
  ships ~443 `{{...}}` placeholders per sample that must be transformed before use, and
  that transformation is unrecorded. Without a checksum, "reproducible from documented
  commands" is not yet true.
- **Licence obligations are recorded but never travel.** A Bitext-derived pack must
  itself carry CDLA-Sharing-1.0, and MASSIVE (CC BY 4.0) requires attribution *and* an
  indication that the material was modified — injection is a modification. Add
  `attribution_required` / `derived_license` and have the pack writer emit a NOTICE.
- **Shape, if it still bites:** `inject()` carries pack-level arguments (language,
  document_type, difficulty_tier, seed) that will repeat at every call site. A frozen
  `InjectionSpec` was recommended. Also `tier` is caller-asserted rather than derived,
  so the pack's tier column is decorative unless the builder sets it honestly.

Not built yet, in order:

1. **Download scripts.** All three sources are HuggingFace datasets. The open decision
   is the retrieval mechanism: the `datasets` library as a new `demo` extra, versus
   direct file fetches. Whichever wins, **no raw data may be committed** — the pack is
   rebuilt from source, which is what `version` and `retrieval_method` in the registry
   are for. Record the choice as an ADR; ADR-0008's extras list needs the amendment.
2. **The pack builder** — the first real caller of `inject()`. Its shape is an open
   design question flagged in review: `inject()` currently takes document_id, language,
   document_type, difficulty_tier, split, seed and provider, several of which are
   per-pack rather than per-document.
3. **Benchmark the packs and publish the numbers beside the synthetic ones**, not
   instead of them. Increment D's exit criterion is in plan §8 Q3.

Two things the injector already knows that the builder must respect:

- **Share one `ValueProvider` across the whole pack.** Constructing one per document
  restarts the value sequence, and Bitext and MASSIVE both repeat their templates
  heavily, so every row would receive the same name.
- **Injection inserts, never edits.** A pack whose base text was altered is no longer a
  test against the public corpus.

#### Working rules that cost time to relearn

1. Read `docs/14_IMPLEMENTATION_PLAN.md` **§8** first. It holds the status table, the
   measured baseline and the queue with exit criteria.
2. **A green local run does not prove CI is green.** `mypy` resolves optional imports
   differently when the extras are installed, and this machine has them. When touching
   anything `presidio` or `lingua` reach, check a clean `uv venv` with `.[dev]` only —
   that is what the push tier installs. This has already broken one push.
3. **Do not enable a change on dev/calibration evidence alone.** Develop against
   `--split dev` / `--split calibration` so you are not iterating on the test split
   (ADR-0011), but run the whole-corpus gates before claiming anything works: a
   remedy that looked clean on 45 documents took over-redaction from 0.000 to 0.020 on
   the full corpus.
4. **Benchmark numbers are enforced, not merely published.** `configs/benchmark_gates.yaml`
   gates them. Raise a floor from your own run after a real improvement; lowering one
   needs the reason in the commit message (`CONTRIBUTING.md`), and there is a worked
   example of a justified lowering in that file's `relaxed_f1` comment.
5. Before each commit: `/qa`, then `/gate`. Say which test tier you ran — the default
   `pytest` excludes `integration`, `slow` and `databricks` (ADR-0009).
6. **Run the auditors and take them seriously.** In session 5 they found a defect in
   every single change, including two that would have leaked names into output — both
   in code that passed my own tests and the benchmark gates. Neither was reachable
   from the committed corpus.
7. When you finish an increment, update §8 of the plan and append a session section
   here. Numbers in documentation must come from a run you actually did.


State at the end of session 4: thirteen commits on `main`, working tree clean, pushed
to `soulipaco/pii-reduction` (private), both workflows green. `ruff`, `mypy src tests`
clean. **525 default-tier tests and 72 integration tests pass.** `.venv` has core +
`dev` + `presidio` + `language` installed, with `en_core_web_md`, `de_core_news_md`
and `xx_ent_wiki_sm` (all 3.8.0).

**A green local run does not prove CI is green.** The first push failed `mypy` because
strict mode cannot resolve `lingua` or `presidio_analyzer` in a core-only install, and
this machine has both. When touching anything the extras reach, verify in a clean
`uv venv` with `.[dev]` only — that is what the push tier installs.

A third constraint joins the two below: **benchmark numbers are now enforced, not
just published.** `configs/benchmark_gates.yaml` holds them as gates. If you improve
a metric, raise its floor in that file from your own run; if you must lower one, say
in the commit message why the metric or the gate was wrong (`CONTRIBUTING.md`).

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

## Session 4 — 2026-08-18 — Queue item Q1: CI and benchmark regression gates

**Scope:** queue item Q1 of `docs/14_IMPLEMENTATION_PLAN.md` §8 only. No change to
any provider, parser, reducer or metric definition — the pipeline behaves exactly as
it did at commit `4fc9cfd`, and the benchmark numbers below are that commit's numbers
re-measured, not new ones.

### The baseline was re-measured before anything was locked

Gate values must come from a run someone actually did (ADR-0009), so both chains were
re-run before the gate file was written. Every published number reproduced **exactly**:
deterministic strict F1 0.723 / leakage 0.433 / clean rate 0.161; hybrid strict F1
0.886 / relaxed 0.921 / leakage 0.117 / clean rate 0.774 / PERSON 0.820 precision,
0.641 recall; over-redaction 0.000 in both. The PERSON-by-language-and-tier table
reproduced cell for cell, including en tier 3 at 0.333 and the Greek row.

Environment for those runs, recorded in the gate file because the Presidio numbers
depend on it: presidio-analyzer 2.2.364, spaCy 3.8.15, `en_core_web_md`,
`de_core_news_md`, `xx_ent_wiki_sm` all 3.8.0.

### What landed

`src/pii_reduction/evaluation/gates.py`, `configs/benchmark_gates.yaml`,
`--gates` on `pii-reduction benchmark`, `tests/test_benchmark_gates.py` (40 tests),
five benchmark-output privacy tests in `tests/test_privacy_logging.py`, one gate test
in `tests/test_benchmark_presidio.py`, `.github/workflows/{ci,integration}.yml`, and
`.github/spacy-models.sha256`.

### Decisions

1. **A gate that measures nothing fails.** This is the whole design, and it is worth
   stating as a rule rather than as a feature: a gate whose selector matches no row
   (metric renamed, slice gone, chain never ran) or matches several rows (ambiguous
   about which number it checked) is a **failure**. The obvious implementation —
   "look the metric up, compare it if you find it" — turns green the moment the
   thing it guards disappears, which is precisely when you need it.
2. **Support is part of the claim.** Each gate records the ground-truth count it was
   measured over and fails if the slice shrank below it. A floor of 1.000 is trivially
   satisfiable on three entities; it means something on 51.
3. **Selectors are literal, not wildcards.** `entity_type: "*"` selects the aggregate
   row the benchmark emits, not "any entity". A wildcard would let one gate silently
   cover a changing number of rows, which is decision 1 again by another route.
4. **The gate set is chosen by the chain that ran**, never by a flag. Scoring a hybrid
   run against deterministic floors would pass trivially and prove nothing.
5. **Values are stored at three decimals, compared with a tolerance of 5e-4.** That is
   half the last published digit, so the file can be checked against the documentation
   by eye — and the tolerance is two orders of magnitude below one missed entity in
   the smallest gated slice (6 entities → 0.167), so it cannot absorb a real
   regression. A test asserts that relationship rather than trusting the comment.
6. **PERSON is deliberately ungated on the deterministic chain.** Its recall there is
   0.000 by design, and gating it would encode "names are never detected" as a
   requirement.
7. **The two weakest PERSON slices are gated individually** (en tier 3 at 0.333, el
   tier 1 at 0.222) so that an overall improvement cannot hide a regression in them.
   Q2's exit criterion is now partly mechanical: improve the slice, raise the floor.
8. **spaCy models are pinned to 3.8.0 in the integration workflow**, not resolved by
   `spacy download`. An unpinned model bump would move the hybrid gates on a night
   nobody changed anything, and a gate that moves on its own gets ignored. The pin is
   in the workflow, not in package metadata — ADR-0008 forbids the latter, and
   `docs/15_PROVIDERS.md` keeps `spacy download` as the human install path.
9. **The deterministic gates run on every push, not nightly.** That chain needs no
   model and its numbers are exactly reproducible, so there is no reason to defer the
   protection to a nightly job.
10. **Two checks were added to `ci.yml` that the plan did not ask for**, both cheap
    and both guarding an existing claim rather than adding a new one: the committed
    corpus must still regenerate byte-for-byte from its seed (it is the ground truth
    every metric is scored against — verified locally, `diff -r` clean), and no
    provider extra may be importable in the push tier (the A1 exit criterion, which
    until now was only ever true by accident).
11. **`--gates` refuses `--split`.** The shipped floors are whole-corpus numbers;
    scoring one split against them compares numbers that were never comparable. Found
    by the architecture audit, and it is the reason `measured.splits` exists.

Two bugs were found in my own workflows while testing them, both worth recording
because they are the kind that pass review and fail in production:

- `-m "integration or slow"` would have *selected* a future test marked both
  `databricks` and `integration` — the natural way to mark a workspace parity test at
  Increment F — and failed it in CI for want of credentials. Now
  `(integration or slow) and not databricks`.
- `ci.yml` had no explicit `shell:`, so the Windows leg would have run PowerShell
  while Linux ran bash. A matrix whose legs run different shells is not testing
  cross-platform behaviour. Now `defaults.run.shell: bash` on the job.

### Both auditors ran, and both changed the result

This is the first increment either auditor has reviewed. Neither found a blocking
issue, and between them they produced eight changes worth keeping.

**privacy-auditor** — no high-severity findings. It confirmed mechanically that gate
output can only emit metric names, selectors, floats and ints; that the step-summary
path is structurally text-free (`MetricRow` has no text field, `TruthSpan` carries no
surface); and that neither workflow touches secrets or a workspace value. Acted on:

1. **The text-free property had no test.** It held by convention only — adding a
   `surface` field to `TruthSpan` for error analysis and listing it in
   `SLICE_DIMENSIONS` would have published entity values to a world-readable step
   summary with nothing failing. `tests/test_privacy_logging.py` now asserts the
   corpus's own injected values appear in neither renderer, the gate report, nor the
   gate *failure* path.
2. **Model wheels had no integrity check.** A version pin says "3.8.0"; a digest says
   "this exact artifact", and `actions/cache` is mutable state. `.github/spacy-models.sha256`
   now pins all three, verified before install and on the cached copy too.
3. **Gate provenance omitted the seed**, so `measured.corpus` said where a copy lives
   without saying what defines it. Added `seed` and `documents_per_language`, both
   asserted equal to the CLI defaults.
4. **A malformed gate file and a failed gate both exited 1.** Now 2 versus 1, with a
   message rather than a traceback.

Left undone deliberately: pinning `actions/*` to commit SHAs (real posture
improvement, but needs Dependabot to stay maintainable — an owner decision).

**architecture-guardian** — the invariant holds. It verified the import graph by AST
rather than by folder names: `evaluation`'s only outward edge is `contracts`, no
cycles, and `processing` imports `evaluation` neither directly nor transitively.
It also settled the placement question I had flagged as genuinely open:

- **`config/` was not merely a worse home for `gates.py` — it was forbidden.** A gate
  is defined over `MetricRow`, which lives in `evaluation/`, so the loader in `config/`
  would create `config -> evaluation`; since `processing -> config`, that would put
  `evaluation` inside `processing`'s import closure and break plan §3 outright.
- `benchmark.py` was wrong for a different reason: anything there is untestable
  without the pipeline. The current split buys 40 tests that need no corpus and no
  model.
- Plan §3 had already assigned I/O to `evaluation/` ("manifest-driven ground truth
  loading"), so the "evaluation was pure" concern was mine, not the plan's.

Acted on: the split provenance (below), the two documentation gaps, top-level and
gate-set key validation to match the per-gate check, `version: 1` now actually
validated rather than decorative, `GATE_FILE` moved to `tests/test_benchmark.py`
beside the other path constants, and `DEFAULT_SEED` / `DEFAULT_DOCUMENTS_PER_LANGUAGE`
made public so a test stops importing a private CLI symbol.

The finding worth carrying forward is **O4, and it changed Q2's instructions**: gates
are whole-corpus numbers and CI re-reads them, so "change it, read the gate, change
again" is iterating against a set that is 60% test split. Plan §8's Q2 now says to
develop against dev/calibration and read the whole-corpus number once, and `--gates`
**refuses** to run with `--split` so the two cannot be mixed by accident. The gate
file records `splits: all (dev + calibration + test)`, which `AGENTS.md` requires and
the first draft omitted.

Two observations left as noted rather than fixed, both with reasons in the code:
`load_gate_file` deliberately duplicates `config.loader.load_yaml_mapping` (reusing it
would cost `evaluation` its single edge), and the gate-set name is passed to both
`load_gate_file` and `evaluate_gates` (fixing it costs a fourth dataclass for a
low-likelihood mislabel).

### Verified

Locally, running the same commands the workflows run:

| | |
|---|---|
| `ruff format --check .` | clean, 110 files |
| `ruff check .` | clean |
| `mypy src tests` | clean, 104 files (strict + pydantic plugin) |
| `pytest -q` (default tier) | **525 passed**, 72 deselected, 8.2 s |
| `pytest -q -m "(integration or slow) and not databricks"` | **72 passed**, 525 deselected, 11.1 s |
| `pii-reduction benchmark --gates …` | 9/9 gates passed, exit 0 |
| `… --chain deterministic_presidio --gates …` | 12/12 gates passed, exit 0 |
| corpus reproducibility | `build-corpus` output `diff -r`-identical to the committed corpus |
| wheel digests | `sha256sum -c` OK for all three models |

Gate failure is tested two ways rather than assumed: a gate tightened past the
measured value fails with the reason, and the CLI exits 1 — the contract CI actually
reads is the exit code, so that is what the test asserts.

### The push, and what it caught

The owner approved a private remote at the end of the session. `soulipaco/pii-reduction`
was created and `main` pushed.

**The first CI run failed, on both platforms, and the failure was invisible locally.**
`mypy src tests` cannot resolve `lingua` or `presidio_analyzer` in the push tier,
which installs core + `dev` only; every local run passed because this machine has the
extras. Fixed by declaring both optional in the mypy overrides — modelling what
ADR-0008 already said about the packaging — and verified in a throwaway core-only
`uv venv`: mypy clean, 525 passed / 3 skipped (the two extras-gated modules skip, as
designed), 9/9 gates.

This is the single most useful thing the push produced, and it is worth remembering
as a rule rather than an incident: **an environment with the extras installed cannot
tell you whether a core install works.**

Second run green on both platforms (32080834089). `Integration` dispatched manually
and green in 1m6s including the model download (32081004870): 72 tests, then 9/9
deterministic and 12/12 hybrid gates.

Every hybrid gate value reproduced **exactly** on GitHub's runner — strict F1 0.886,
relaxed 0.921, precision 0.933, PERSON 0.820/0.641, leakage 0.117, clean rate 0.774,
en tier 3 0.333, el tier 1 0.222. The baseline is machine-independent, which is a
stronger claim than anything a local run could support.

Unactioned by choice: `actions/*` are pinned to `@v4` rather than commit SHAs. Real
supply-chain improvement, but it needs Dependabot to stay maintainable — an owner
decision, not a session's. GitHub also warns that Node 20 actions now run on Node 24;
harmless today, and it resolves itself when those actions publish a v5/v6.

### Q2 continued — the identifier guard (session 5, later)

`patterns.is_identifier_shaped` + `_is_name_like`, applied by the reconciler as
rejection reason `identifier_shaped`, default scope **PERSON only**. Ships enabled and
is a **verified no-op on the shipped configuration**: all twelve hybrid gates returned
identical values before and after.

Measured whole-corpus, hybrid chain, with the guard active:

| | shipped | `split_lines` | `key_value` |
|---|---|---|---|
| strict F1 | 0.886 | 0.902 | **0.915** |
| relaxed F1 | 0.921 | 0.913 | **0.927** |
| en tier-3 PERSON recall | 0.333 | 1.000 | **1.000** |
| over-redaction | 0.000 | 0.000 | 0.000 |
| leakage | **0.117** | 0.122 | 0.122 |
| document clean rate | **0.774** | 0.763 | 0.763 |

`key_value` is the better remedy and the over-redaction regression is gone. **Neither
parser ships**, by the owner's decision: both leak one more entity — the Greek
`Ελένη Παππά` in `Από: Ελένη Παππά`, found with block context and missed on its own
line. Its slice recall is 0.000 before *and* after, because the old detection produced
an over-long span that failed strict matching **while still redacting the name**. A
span can be wrong for scoring and right for privacy at once; only the leakage metric
saw it.

Three things worth carrying forward:

1. **The first version of the guard leaked names**, and the privacy audit caught it.
   Counting a token as name-like only when it carried no digit rejected `Mueller2024`,
   `jmueller01`, `grace.okafor2` and `Παππά2026` — a rejected PERSON span means the
   name is *not* redacted, and usernames with numeric suffixes are routine in real
   support data. Letter-versus-digit counts do not separate the cases that matter
   (`DEMO-PC-6963` is 6/4, `Mueller2024` is 7/4); a lowercase run of three or more
   does. A lone all-caps token with digits (`MUELLER2024`) is a known remaining gap,
   pinned by a test.
2. **ADDRESS was removed from the default guard scope.** It had shipped guarded on no
   evidence — no provider emits it, the corpus has no ADDRESS truth — and it is the
   one guarded-looking type whose surface is legitimately all digits. A postcode would
   have been dropped silently the moment an ADDRESS provider landed.
3. **`key_value` costs roughly an order of magnitude in runtime**: provider calls go
   from one per document to one per line. Under ADR-0015 (CPU-only) that is a
   selection criterion, not a footnote.

The guard scope is a `ReconciliationPolicy` field, adjustable from Python but **not
reachable from YAML** — `ChainSettings` exposes only `providers` and `overlap_policy`.

### Known gaps carried forward

Everything in session 3's "Known gaps" still holds except the last two, which change:

- ~~No CI workflow exists~~ — both exist and both are green on GitHub.
- ~~Nothing is pushed; no remote is configured~~ — `soulipaco/pii-reduction`, private.
- ~~The privacy-auditor and architecture-guardian have not been run against any of
  these increments~~ — both ran against Q1. **A1–A6, B and C remain unaudited**; the
  audits above cover this change only.

New, from this session:

- The gate file protects the *committed synthetic* corpus. It says nothing about
  behaviour on real text; Increment D is where that gets measured, and it needs its
  own gate set rather than a relaxation of these.
- `docs/08` lists `transcript prefix preservation == 1.00` as an example gate and no
  such metric exists in the report grain. The invariant is covered by round-trip
  tests; it is the obvious next gate once a metric backs it.

---

---

## Session 5 — 2026-08-18 — Q1 closed, Q2 solved, Increment D started

Six commits: `913118d` (Q1 closed on GitHub), `0590f0f` (mypy in a core install),
`14ec056` (Q2 diagnosis + split-scoring bug), `55335fe` (key_value parser),
`ed09e83` (identifier guard), `d9b01d6` + `f351c74` (span repair, gate floors).

### The headline: Q2 was a span-boundary bug, not a detection failure

English tier-3 PERSON recall sat at 0.333. The plan assumed a detection problem and
listed remedies accordingly. Presidio was in fact finding **every** name; handed a
multi-line key/value block it ran the entity boundary through the line break and
returned the name plus the next line's first word. Strict matching scored that as a
miss *and* a false positive — the whole of the 0.333 — and reduction destroyed the
next line's label, a structure-preservation failure the over-redaction metric cannot
see because field labels are not protected tokens.

Confirming evidence was already in the baseline: tier-4 transcripts scored 1.000 with
the same model and the same names, because the transcript parser is line-oriented and
no span can cross a break.

**The general lesson, now in ADR-0016:** a remedy that changes the model's *input*
trades one error for another; one that changes its *output* cannot. Three remedies
re-cut the input — `split_lines`, the `key_value` parser, and label-stripping — and
each lost context and leaked a Greek name. Span repair leaves detection untouched.

Final published numbers (whole corpus, hybrid chain):

| | before Q2 | after |
|---|---|---|
| en tier-3 PERSON | 0.333 | **1.000** |
| el tier-3 PERSON | 0.000 | **0.167** |
| strict F1 | 0.886 | **0.902** |
| PERSON precision / recall | 0.820 / 0.641 | **0.833 / 0.705** |
| leakage / over-redaction / clean rate | 0.117 / 0.000 / 0.774 | **unchanged** |
| relaxed F1 | 0.921 | 0.914 *(gate deliberately lowered)* |

### What shipped, and what deliberately did not

**Shipped:** span repair (`providers/base.py::_bound_to_line`), the identifier guard
(`patterns.is_identifier_shaped`, PERSON-scoped, rejected by the reconciler as
`identifier_shaped`), and `surface_may_span_lines` on `EntityDefinition` so the fact
is declared once rather than per layer.

**Built but enabled nowhere:** `split_lines` on `PlainTextParser`, and the `key_value`
parser. Both are correct and tested; both fix the span by re-cutting the input and
both leak a Greek name doing it. They remain available per column for data that is
genuinely key/value shaped. `key_value` also turns one provider call per document into
one per line — roughly an order of magnitude slower on the whole corpus, which matters
under ADR-0015.

### Three bugs worth remembering

1. **`run_benchmark(splits=…)` scored a subset against the whole corpus's ground
   truth.** A dev+calibration run reported over-redaction 0.627 against a true 0.000.
   Fixed on both axes — `splits` and a narrowed `datasets` mapping — and results now
   record which splits they cover.
2. **The identifier guard's first rule leaked names.** Counting a token as name-like
   only when it carried no digit rejected `Mueller2024`, `jmueller01`,
   `grace.okafor2` — and a rejected PERSON span means the name is not redacted.
   Letter/digit counts do not separate the cases that matter (`DEMO-PC-6963` is 6/4,
   `Mueller2024` is 7/4); a lowercase run of three or more does. Known remaining gap,
   pinned by a test: a lone token whose lowercase run is under three (`MUELLER2024`,
   `Wei2`), and the rule assumes a cased script.
3. **Span repair leaked names twice before it was right.** Version one kept the head
   fragment, version two kept the longest — both leak when the name falls on the other
   side of the break, or when a hard-wrapped name is *split by* it (`Jürgen` + break +
   `Müller`). The shipped rule keeps **every** fragment, which sometimes over-redacts a
   neighbouring label. That was a deliberate choice of the visible error over the
   invisible one, and it cost relaxed F1.

**`leakage_rate` cannot see a partial-name leak.** It matches only the exact *full*
surface, so a half-redacted name scores as clean. The gate holding at 0.117 was never
evidence that bugs 2 and 3 were absent. Any future rule that drops or narrows a span
needs a test built from a constructed input, not from the corpus.

### On the auditors

They found a real defect in **every** change this session, including both leaks above,
and each time in code that passed the full test suite and all benchmark gates. Both
leaks were unreachable from the committed corpus — one needed a username with a digit,
the other a hard-wrapped name. Neither shape exists in 102 template-generated
documents.

The architecture reviews were equally productive: repair running before validation
(turning a `ProviderError` into a bare `IndexError`), separator arithmetic that assumed
one character and misaligned every span after a CRLF, silent drops where this repo had
already legislated for counted ones, the same entity fact declared in two layers, and
an ADR header that contradicted its own Consequences section — which would have led a
later session to re-arm the bug the privacy audit had just removed.

### Increment D, started

`synthetic/injection.py` and `synthetic/registry.py` + `demo/registry.yaml`. See the
"Start here" block for what remains and the two constraints the pack builder must
respect. Nothing yet calls either module outside tests — the download scripts and pack
builder are the next work, and the retrieval mechanism is an open decision needing an
ADR.

---

## Session 6 — 2026-08-18 — Increment D closed: public-dataset packs

### Start here (session 7)

**State:** Increment D complete **and Q4 answered**. **809 default-tier tests, 87
integration**, `ruff` and `mypy src tests` clean in the dev environment and in a
throwaway core-only one. The committed corpus still rebuilds byte-identically. Three
demo packs build from two public sources and all 49 of their gates pass on both chains.

Everything is pushed and **CI is green on all three pushes** (runs 32155683694 and
32162154845). Q4's fifteen diagnosis tests are `integration`-marked and never run on a
push; they were verified cross-runner by a dispatched Integration run (32162320370):
87 integration tests passed and both gate sets held, 9/9 and 13/13. **The Greek
mechanisms therefore reproduce on GitHub's runner** — the diagnosis is
machine-independent, not an artifact of this laptop.

**The queue is empty.** Next is `docs/11_ROADMAP.md` order: **Increment E** — benchmark
hardening, split discipline (ADR-0011's calibrate-then-read-test protocol, which the
gates deliberately do *not* implement), and mask-vs-redact leakage variants per
ADR-0013 §5.

**Read ADR-0019 before touching anything Greek.** The one-line "Greek is weak because
the good models are non-commercial" explanation is superseded. The model almost always
*finds* the Greek names and then gets the label or the boundary wrong, and the three
mechanisms have three different remedies. Plan §8 Q4 has the table; the mechanisms are
pinned by `tests/test_greek_person_diagnosis.py`, which fails on purpose if a model bump
changes them. It pins the **model**, below the adapter — two of the three mechanisms are
invisible above it — so a Presidio-side change could move Greek without failing it.

**Do not "fix" the Greek templates.** Removing the άνω τελεία or rephrasing
`Ονομάζομαι` would raise the published Greek number by making the corpus easier. A test
asserts both are still there and says why.

**Read the pack numbers with their limitations** (plan §8). The one that matters most:
the two English packs are the same source rows under two parsers, so they are **one**
measurement, not two agreeing.

### What Increment D actually shipped

Retrieval (**ADR-0017**): files fetched at a pinned commit revision, verified against a
SHA-256 recorded in `demo/registry.yaml`, cached under `data/downloads/`. Stdlib
`urllib` — **no `datasets` extra, no new dependency at all**. The alternative would have
added roughly ten transitive packages to fetch three files, and for MASSIVE it would
have resolved the identical parquet URL anyway, since `datasets>=3` no longer runs
loading scripts.

**MultiWOZ is gone (ADR-0018).** The session-5 privacy audit's finding — real Cambridge
landlines and postcodes in its published utterance text — moved it to `rejected:`, which
removed the transcript pack's source. Bitext now renders both English packs: its columns
are literally `instruction` and `response`, so `Customer:`/`Agent:` turns restate the
source rather than inventing structure. That turned out *better* than MultiWOZ would
have been: 7,104 of its 26,872 responses contain newlines, so continuation lines with no
speaker prefix exercise the parser's fallback rather than only its happy path.

New modules: `synthetic/fetch.py`, `synthetic/public.py` (readers), `synthetic/packs.py`
(specs + `build_pack`). New commands: `pii-reduction fetch-dataset` and `build-pack`,
with `demo/download_datasets.py` and `demo/build_pack.py` as front doors.

### Three changes to code that already existed, each with a reason

1. **`inject()` gained `protected=`.** Spans the caller recorded against the base text
   are shifted by the same arithmetic as the injected entities and verified the same
   way. Without it the pack's substituted order numbers could not stay aligned, and
   over-redaction — the metric guarding AGENTS.md rule 5 — would be unmeasurable on
   public text. A second implementation of offset arithmetic is a second chance to
   drift.
2. **`eligible_offsets` now offers each processable region's start.** Restricted to
   sentence breaks alone, a transcript's entities all landed in whichever turn was
   longest, and nine of 200 documents received nothing at all. One existing test
   asserted the parser could only ever *narrow* the offset set; that is no longer true
   by design, and the test now asserts the property that matters — every offset lies
   inside a processable region.
3. **`write_corpus` writes headers for an empty table.** MASSIVE carries no identifiers,
   so that pack has zero protected tokens, and a headerless empty CSV cannot be read
   back — `load_corpus` would have failed on a perfectly valid pack.

Also moved: `document_seed` now lives in `corpus.py` beside `split_for`, because the
readers need the same derivation. The first version of the reader used `hash()`, which
Python randomises per process — a pack that differed between two runs on the same
machine. Caught before it shipped; worth remembering as a shape of bug.

### The session-5 constraint that is now wrong

That handoff said to **share one `ValueProvider` across a pack** or a repetitive corpus
would give every row the same name. The injector solved it the other way instead: values
derive from `(seed, document_id)`. Sharing a provider would now *break* reproducibility,
because a document's values would depend on where its row sat in the run. A test pins
the property that mattered.

### What the packs measured

Full tables are in plan §8. The four findings worth carrying:

1. **The deterministic recognizers did not merely fit the corpus they were built
   against** — EMAIL and PHONE at 1.000 precision and recall over 1,600 entities in
   public prose, three languages, two scripts, including lower-case Greek.
2. **Greek PERSON 0.606** against 0.111-0.222 synthetic — Q4.
3. **Precision, not recall, is where public text is hard.** Recall is 1.000 on both
   English packs; the only detection errors are names in prose nobody wrote for us
   (PERSON precision 0.985 and 0.995). A template corpus cannot show this, because its
   non-PII text was written by the same hand as its entities.
4. **The transcript parser holds.** Same sentences under two parsers: 0.999 against
   0.998, every speaker prefix reconstructed, and PERSON precision *higher* under
   line-scoped segments — the mirror image of ADR-0016.

### Working rules, unchanged and still expensive to relearn

1. Read plan §8 first; it is the status, the baseline and the queue.
2. **A green local run does not prove CI is green.** Verified this session in a
   throwaway `uv venv` with `.[dev]` only, which is what the push tier installs.
3. Develop against `--split dev`/`--split calibration`, but run whole-corpus gates
   before claiming anything works.
4. Gates are enforced. Raise a floor from your own run; lowering one needs the reason in
   the commit message.
5. `/qa` then `/gate` before committing. Say which tier you ran.
6. **Take the auditors seriously.** Session 5 found a defect in every change.
7. Update plan §8 and append here when an increment closes.

### Two things a later session must not undo

- **Pack gates are separate from the synthetic gates and must stay that way.** A pack is
  a new gate set on its own corpus (`configs/pack_gates/`), never a reason to loosen
  `configs/benchmark_gates.yaml`. A test asserts no workflow gates on a pack — which
  also keeps CI offline, since building a pack needs a download.
- **No pack and no raw data is committed.** `.gitignore` covers `demo/packs/` and
  `data/downloads/`. The registry's `retrieval:` pin is what makes a pack reproducible
  instead of stored.

### Q4 — the Greek diagnosis, and why no number moved

The pack asked the question and a direct probe answered it (ADR-0019). Counts are out
of the eight committed Greek names, against `xx_ent_wiki_sm`:

| carrier | exact PER | wrong label | wrong span | nothing |
|---|---|---|---|---|
| the name alone | 3 | 1 | 2 | 2 |
| `Ο πελάτης είναι {name}.` | **6** | 2 | 0 | 0 |
| synthetic tier-4 (`Ονομάζομαι {name}`) | **0** | 0 | 8 | 0 |
| German equivalent | **8** | 0 | 0 | 0 |

**It is not a detection failure.** Three mechanisms:

1. **Span absorption** — `Ονομάζομαι {name}` comes back as
   `PER 'Ονομάζομαι Ελένη Παππά'`, 7 of 8 times. A capitalised token before the name is
   swallowed. That is ADR-0016's English bug *within* a line, where line-boundary span
   repair cannot reach it. Greek tier-4 0.000 is a boundary failure.
2. **Label confusion** — an exact span with the wrong label: `ORG` and `LOC` in the
   neutral carrier, `MISC` in others. ADR-0004 correctly refuses to map any of them, so
   the name is found and then dropped. **Do not look for a morphological rule** — three
   of the pool's five genitive surnames are labelled correctly; the first draft of
   ADR-0019 claimed otherwise and the audit caught it.
3. **The άνω τελεία** — `Παππά· δεν` scores 3/8 where `Παππά, δεν` scores 6/8. Only the
   middle dot; comma, semicolon and full stop are all fine.

The public pack scores 0.606 because MASSIVE utterances are single short clauses that
trigger none of the three. **The synthetic Greek is legitimately harder, not
miscalibrated**, so nothing was changed and no published number moved. That was the
whole decision: every mechanism has an obvious corpus-side fix that would raise the
number by making the text easier, which is tuning the benchmark to the model.

Method worth reusing: change **one** thing at a time against a fixed carrier sentence,
and record *what the model returned instead* — exact / wrong label / wrong span /
nothing — rather than only whether it was right. The "wrong span" column is what turned
a five-year-old-sounding "Greek is weak" into three separate, actionable bugs, and it is
the same column that solved Q2.

---

## Session 6 (overnight continuation) — 2026-08-19 — Increment E complete

Worked autonomously by request; the user reviews this in the morning. Commits
`5175a56` (E1), `4fb13eb` (E2), and the E3 commit that follows this file. Every
commit was audited (privacy + architecture) before landing, and both auditors
reproduced the published numbers independently.

### Start here (session 7) — supersedes the block above

**State:** Increments D and E complete, Q4 answered. The queue in plan §8 is empty;
next is **Increment F (Databricks Connect)** per the roadmap — deliberately not
started unattended, since it runs against the authenticated workspace. The other
open thread is ADR-0019's **mechanism-2 measurement** (what would requesting Greek
`LOC`/`ORG`/`MISC` and reconciling them do to leakage and over-redaction?), scoped
in plan §8 Q4's follow-ups.

**Leakage is two numbers now (ADR-0013 §5, E1).** `fragment_leakage_rate` counts any
surviving whitespace-free 4-char window of a value, minus windows occurring in the
source text outside entity spans — ambient prose is not evidence (`chne` in
`Rechnername` was the false positive that forced that exclusion, now a test).
Mask: 0.922 det / 0.606 hybrid — the deliberate retention made visible. Redact:
fragment == full on the committed corpus, pinned by test AND gate floors. The
strategy is in the metric-row grain, and gates compare the run's strategy to the
file's recorded `measured.strategy` at the data level — a config-level
`reducer: mask` cannot slip past a flag check.

**Calibration was a null operation with reasons (E2).** Every score is a recognizer
constant (det 1.0, spaCy NER flat 0.85 for TP and FP alike — 19/19 on the
calibration split). Thresholds reviewed and locked, not moved; provenance travels as
`provider=note` in `RunMetadata.threshold_calibration`, and the note feeds the
config fingerprint — rewording it changes `config_hash`, documented in docs/06.
**The test split was read once**: dev 0.875 / calibration 0.882 / test 0.921, test
above the working splits — the direction that says nothing was tuned onto it.

**The 10k comparison is `docs/16_BENCHMARK_REPORT_10K.md` (E3)**, with its own gate
set (`configs/pack_gates/support_tickets_10k.yaml`, on-demand like all pack gates).
Two findings only scale could show: precision is structurally capped by the source
corpus itself (21 of Bitext's own example addresses correctly detected, charged as
FPs — the benign form of ADR-0018's contaminant), and the fragment metric sees
cross-entity recovery (det fragment 0.373 > full 0.333: email windows surviving
inside leaked names, because the pool derives locals from names — as reality does).
Throughput: ~2,147 det vs ~29 hybrid rows/s on ~600-char documents (~74×); context,
never gates.

**The mechanism-2 measurement is DONE — read plan §8 Q4's follow-ups before any
Greek work.** Promoting `LOC`/`ORG`/`MISC` to PERSON for Greek cuts leakage 0.350 →
0.133 and lifts recall 0.154 → 0.423, but the best stack measured (promote →
line-bound → colon-trim → identifier guard) still destroys 5 of 34 protected
identifiers (over-redaction 0.147 vs the 0.000 gate). The remaining failure shape is
an identifier inside a wider promoted span with no separator to trim at. The open
design question for session 7 — ideally with the user, since it touches the gate
philosophy — is token-level coverage surgery inside promoted spans. Numbers came
from an offline simulation of the real provider-boundary stack with the real metric
functions; nothing shipped.

**Greek span-absorption remedy: scoped, unshippable, recorded (plan §8 Q4
follow-ups).** Colon-trim fires zero times (absorbed-label spans arrive `MISC`/`LOC`
and are dropped before PERSON repair sees them); leading-token-trim can always be
cutting a real name's first token — the invisible error. Tier-4 absorption costs
metrics and a swallowed verb, not privacy: the name IS redacted. Next Greek step is
the mechanism-2 measurement, not more span repair.

### Traps encountered, for whoever works nights here

- **Wall-clock is contamination-prone.** The first hybrid 10k measured 5 rows/s
  because the box was simultaneously running test suites and audits; the quiet
  re-run measured 29. Runtime numbers say so in the report and may never be gated
  (ADR-0009).
- **The harness collapses `
` inside bash heredocs.** A `"...
..."` in a patch
  script arrives as a real newline and breaks the written file (twice this session:
  a test string, a ` ` literal). Write files with the editor tools, not
  heredoc-driven patch scripts, when a string literal contains escapes.
- **Auditors stall sometimes** (infrastructure watchdog, 600s). Resume them with a
  message — their context survives and they finish in minutes.
- **Sequence audits against a frozen diff.** Both E1 auditors reviewed the tree
  while I kept editing adjacent files for E2; their line references survived, but
  the clean way is: freeze slice, audit, fix, commit, then start the next slice.

---

## Session 7 — 2026-08-19 — Increment F: Databricks execution — **complete, committed `4464065`, CI green**

User authorized both open decisions in plain terms; the Greek call went to
"hold until zero damage" (recorded, nothing shipped) and Databricks went ahead.

**Increment F's exit criterion is met on the real workspace.** The corpus went up as
a Delta table, came back through `SparkTableSource`, was processed by the
byte-identical local `Pipeline.process`, landed via `DeltaTableOutput`, and the
reduced column hashes equal the local run's. Audit and run-metrics Delta tables
verified metadata-only. The parity tests build one throwaway schema and drop it.

**Two workspace facts that shape everything:**

1. **Serverless-only.** Classic cluster creation is refused ("no associated worker
   environments"). ADR-0006's Connect decision was the only path; amended with the
   findings.
2. **Serverless Python-UDF sandboxes are broken on this workspace's channel**
   (`ISOLATION_STARTUP_FAILURE`: the aarch64 image cannot exec its own Python).
   Reproduced across client 15.4/py3.11 and 16.4/py3.12 — Databricks infra, not
   client skew. The `mapInPandas` path is shipped, its init-once and parity
   semantics are unit-tested WITHOUT Spark in the default tier, and a
   databricks-marked test skips today naming the incident and asserts distributed
   parity automatically when the sandbox is fixed. Re-check occasionally.

**Environment:** `.venv-dbx17` (Python 3.12, databricks-connect 16.4) — the
dedicated venv ADR-0006 anticipated; the extra pins `databricks-connect>=15.4` with
the Python-minor coupling documented in pyproject. Profile via
`DATABRICKS_CONFIG_PROFILE` (contact-center-portfolio used for parity); never a
host in code — `get_session` deliberately has no host/token parameters.

**Run the workspace tests with:**
```
DATABRICKS_CONFIG_PROFILE=<profile> .venv-dbx17/Scripts/python.exe -m pytest tests/test_databricks_parity.py -m databricks -o addopts=""
```

**Post-audit additions (both auditors ran before the commit):** run identity is
driver-generated and in the worker cache key (a warm worker was stamping a previous
job's run id — two tests pin it); `distributed_frame`'s declared schema is asserted
name-and-order equal to what `process` appends (the first declaration had the two
appended columns swapped, caught by the new test); the audit-table assertion is an
exact column-set match against `AUDIT_COLUMNS`, not a denylist; the parity fixture
refuses to adopt a pre-existing schema; the Spark-free guard in `test_package.py`
now imports `pii_reduction.databricks`; the distributed path's reduced-frame-only
scope is disclosed in the docstring and plan §8 F.

**854 default-tier tests, 90 deselected (3 databricks). The roadmap is complete
through Phase 6.** Remaining, unsequenced: the Greek promotion design call (plan §8
Q4 follow-ups), the sandbox-incident recheck, docs/01+plan §3 naming `databricks/`
as an execution surface (architecture review Q3 — docs lag, code is right), and the
parked ideas.

## Session 8 — 2026-08-19 — Docs reconciled with Increment F; sandbox re-checked; **the Greek call taken and shipped (ADR-0020, ADR-0021)**

**Start here:** the queue is empty. The Greek promotion decision was brought to you,
taken, and shipped as **ADR-0020** — the second half of this session. Published
numbers moved for the first time since Increment E, deliberately and in both
directions; the trade is in ADR-0020 and plan §8.

**The finding worth carrying forward, above all the numbers:** the open question was
"how do we get token-level surgery to reach over-redaction 0.000?" — and the premise
was wrong. Measured against the real pipeline instead of the offline simulation plan
§8 recorded, promotion through the shipped adapter destroys **nothing**, because
Presidio discards spaCy's `MISC` label before this project's adapter ever sees it, and
21 of the 22 model spans overlapping a protected token are `MISC`. Surgery was built,
measured, shown to work on the one arm that has destroyers, and **deliberately not
shipped**. Two sessions of design pressure had been aimed at a defect that the real
stack did not have. The harness that established this reproduces the published
baseline exactly, twice, through independent code paths — that validation is what
made it safe to contradict a recorded finding.

**What landed:** the documentation half of Increment F. `databricks/` is now named as
an *execution surface* in `docs/01_ARCHITECTURE.md` and plan §3 — outermost edge,
beside `cli.py`/`benchmark.py`, not beside `sources/`/`outputs/`. It may import
`processing/`; nothing on the runtime path imports it. Layer 1 and Layer 10 both point
at the real modules, and the "Suggested adapters" tree no longer lists a
`sources/spark_source.py` or `sources/databricks_table_source.py` — neither ever
existed, and neither can without dragging Spark onto the runtime path.

**Two pre-existing contradictions went with it**, both found by the architecture
review rather than by the brief: `docs/06_CONFIGURATION_CONTRACT.md` advertised
`source: type: databricks_table` and `destination: type: delta_table` as if they were
config-buildable — neither is registered, `run_driver` constructs both directly, and
the shipped `source_type` is `spark_table`. The block is kept and labelled intended-
not-shipped, with the structural reason (`build_source` takes a path;
`SparkTableSource` needs a session). And `docs/11_ROADMAP.md`'s Phase 6 now records
which deliverables shipped and that the third exit criterion — "at least one
meaningful distributed benchmark executed" — is **not met, infra-blocked**, rather
than leaving a roadmap that reads as fully green.

**The auditors earned their keep again, on a docs-only diff.** Both independently
caught the same defect: the new prose credited
`test_core_layers_import_without_any_provider_extra` with asserting that `databricks/`
is the *only* package allowed to import `pyspark`. It does not. It is a
no-eager-import guard over eight named packages; a module-level Spark import in
`evaluation/`, `synthetic/`, `cli.py` or `benchmark.py` would never be loaded by it,
and a function-local import anywhere would pass. The privacy auditor named the cost
exactly: that paragraph is what a reviewer would cite when waving through a Spark
import somewhere new.

**Fixed by making the claim true rather than by weakening it** — two AST scans in
`tests/test_package.py`:

- `test_only_the_databricks_surface_names_spark` — walks every module under `src/`,
  fails on a `pyspark`/`databricks.connect` import outside `databricks/` at any
  nesting depth.
- `test_nothing_outside_the_databricks_surface_imports_it` — pins the direction.

Both were verified to **fail** on injected violations (a function-local
`from pyspark.sql import ...` in `evaluation/`, and an `outputs/` module importing the
surface) before being trusted — the function-local case is precisely the hole the
subprocess check cannot see.

**That verification was not enough, and the second audit pass proved it.** Both
auditors independently found the direction guard still passed on
`from pii_reduction import databricks` — the *shape* `cli.py:15` already uses, with a
different name after `import` — because an `ast.ImportFrom` node was read for its
module and never its aliases. `from . import databricks` was dropped entirely.

A third pass then found the first fix had its own defect: emitting the bare prefix
`X` alongside `X.y` forced the contracts guard to exempt a bare `pii_reduction`,
which silently masked `import pii_reduction` from inside the hub — a
partially-initialized cycle, and precisely what that guard advertises it catches.
Emitting **only** `X.y` removes the exemption and the hole together, because it is
what lets a caller reject `import X` while allowing `from X import y`.

The final helper is checked by a 27-case matrix across all three guards at two package
depths, covering every form the auditors named plus the ones they did not: `import X
as p`, `from X import *`, `from .. import y`, and four legitimate imports that must
stay clean. **The lesson is the general one, and it cost three passes: a guard verified
against the violation you imagined is only tested for imagination.** Also added `TestProtocolConformance`: `SparkTableSource`
and `DeltaTableOutput` satisfy their protocols without declaring conformance, so
nothing type-checked them; two `isinstance` assertions now hold it. (The first draft
of that docstring justified the non-declaration as "an import would put Databricks on
the runtime path" — **wrong**, and both auditors said so: `databricks/ -> sources/` is
the permitted inward direction and `source.py` already imports from the very module
that defines `SourceAdapter`. What keeps Spark off the runtime path is where these
adapters live, not what they import. A false architectural justification is worse than
none, because it is what gets cited later to refuse a legitimate import.)

Two further prose defects, both caught by both auditors: "nothing depends on them" was
false for `cli.py`/`benchmark.py` (the `demo/` front doors import `cli`), and plan §3's
compressed "Nothing imports it" was false of the tests. One factual slip of mine: the
worker cache is keyed on **run id + config hash**, not the config hash alone, and the
run-id half is the part that stops a warm worker restamping a previous job's id.

**Sandbox re-check (item 3): still broken.** Same command, unchanged code —
driver-path parity 2 passed against the real workspace, distributed test still skipped
on `ISOLATION_STARTUP_FAILURE`. Logged as a dated row in plan §8 F so the re-checks
accumulate instead of being re-derived. Re-run occasionally:

```
DATABRICKS_CONFIG_PROFILE=<profile> .venv-dbx17/Scripts/python.exe -m pytest tests/test_databricks_parity.py -m databricks -o addopts=""
```

**916 default-tier tests**, 95
deselected; **92 integration**; all six gate-set runs green — both benchmark sets on
both chains, plus `multilingual_utterances` and `support_tickets` on both. The two touched test
modules also pass with every optional extra hard-blocked, and `mypy src tests` caught
an untyped fixture that a `mypy src` run would have shipped to CI.

**The corpus is untouched** — ADR-0019's rule holds. What moved is a provider option,
a chain, and the gate floors that record the trade.

### The Greek work (ADR-0020)

**What shipped.** `PresidioProvider` gains a `promote` option: listed native labels
join the analyzer *request* and normalize to PERSON. Q4 had already established the
request is the only place this can work — an unrequested label never reaches the
mapping table — so a table-only change would have been a silent no-op.
`configs/providers.yaml` splits Presidio into `presidio` (en, de) and `presidio_el`
(el, promoting `LOCATION`/`ORGANIZATION`), both in the hybrid chain, routed by
`language_scopes`.

**Why the split lives in the chain and not in a `languages:` route** — this is a trap
worth remembering: `benchmark.with_chain` overrides a column's chain but **not** a
project-level language route, so a route would have applied Presidio to Greek during
the `deterministic_only` benchmark and quietly corrupted that baseline. Verified
unchanged afterwards: 0.723 / 0.433 / 0.000 / 0.161. A default-tier test now asserts
no `languages:` block exists in `configs/project.yaml`, with the reason attached.

**Scoping was not optional.** Promotion applied globally was measured and rejected: en
PERSON precision 0.833 → 0.694, de 0.963 → 0.839, over-redaction off its 0.000 gate,
strict F1 0.902 → 0.875. Scoped to Greek, en and de are numerically identical.

**The trade, both directions.** Lowered: strict F1 0.902 → 0.899, overall strict
precision 0.935 → 0.886, PERSON precision 0.833 → 0.747. Raised or tightened: leakage
0.117 → 0.067, fragment 0.117 → 0.078, document clean 0.774 → 0.871, PERSON recall
0.705 → 0.795, relaxed F1 0.914 → 0.921, Greek tier 1 0.222 → 0.444, tier 2
0.111 → 0.667, plus a new Greek tier-2 floor. Every floor that improved was tightened,
not left slack — a later change that gives the precision back must give the leakage
back too. 15/15 hybrid gates and 10/10 deterministic gates pass.

**The fragment-leakage equality broke, and the plan told me not to accept that.**
Hybrid fragment 0.078 against full 0.067. Investigated by comparing the leaked-entity
*sets* before and after: **no entity leaks that did not leak before** — seven fixed
outright, two Greek values downgraded from fully leaked to partially redacted (surname
removed, given name left). Incomplete progress, not new damage. That reasoning is
written into the gate file beside the number, so the next person to see the gap does
not have to re-derive it.

**Not addressed, and now bounded:** ADR-0019's mechanisms 1 (span absorption — Greek
tier 4 stays 0.000) and 3 (the άνω τελεία). The `MISC` finding is a hard ceiling on
any further label-level remedy through Presidio; reaching it needs a spaCy recognizer
registered into Presidio or a separate provider adapter, neither built.

**The auditors found three things the measurement did not, and one was serious.**

1. **A second gate file measures Greek on the same chain.**
   `configs/pack_gates/multilingual_utterances.yaml` is de+el, half Greek, with two
   precision floors sitting at exactly their measured value. Promotion broke both. The
   MASSIVE source was still cached, so the pack was rebuilt and **re-measured** rather
   than flagged: precision 0.926 → 0.893 and strict F1 0.930 → 0.923 against leakage
   0.065 → 0.030, clean rate 0.870 → 0.940, PERSON recall 0.805 → 0.865, Greek PERSON
   0.606 → 0.727. **Independent corroboration on public text, in the same shape.** The
   English packs were re-run too and are unchanged. Lesson: "which gate files measure
   this chain?" is a question to ask *before* changing a chain, not after.
2. **Drop counts were misattributed across the two instances.** `LabelMapping` captured
   the provider name at construction, but `build_provider` assigns the configured name
   *after* the constructor returns — so `presidio_el` filed its drops under `presidio`,
   and `pipeline` merges the counters, so they summed silently. Latent with one
   instance; a real loss of ADR-0004's signal with two. Fixed by re-stamping the mapping
   on access; two tests pin it.
3. **`document_clean_rate` calls two partially-redacted documents clean.** It derives
   from full-surface leakage, so 0.774 → 0.871 is seven genuinely clean plus two that
   still carry a Greek given name. The fragment/full divergence was disclosed in five
   places and this consequence of it in none. Now stated wherever 0.871 appears —
   README, docs/15, plan §8 and the gate file. **A metric that is honest and a framing
   that is honest are two different things.**

Also from the audits: the ADR claimed an audit row could distinguish a promoted span,
which is false (`AUDIT_COLUMNS` is a closed set that no metadata reaches) — reworded
rather than delivered, since adding the column changes the Delta schema the parity test
asserts exactly. `docs/15_PROVIDERS.md` still documented the pre-change adapter and
shipped a yaml snippet reproducing the rejected configuration. And the stated reason
`NRP` never fires was wrong: it comes from spaCy's `NORP`, which `xx_ent_wiki_sm` does
not emit — not from `MISC`, which is a separate ceiling.

**One dead branch removed by its own test.** The `promote` validator had an
"already mapped" rule no input could reach, because `PROMOTABLE_LABELS` and
`NATIVE_LABELS` are disjoint. The test written to exercise it failed with the wrong
message, which is how it surfaced; the branch is gone and the disjointness that makes
it unnecessary is asserted instead.

### The span extension (ADR-0021), and why the plan's next target was wrong

**The recommended next step was mechanism 1 (span absorption). Measuring it first
showed it is worth one entity.** Classifying all 26 Greek PERSON entities on the
shipped chain gave 11 matched and 15 misses: **8 SILENT** (the model returns no span at
all), **4 DROPPED** under a refused label (3 of them `MISC`), **2 PARTIAL**,
**1 ABSORBED**. After ADR-0021: 13 matched, 13 misses, PARTIAL empty. Absorption was the
dominant mechanism when ADR-0019 measured it — *before* promotion; promotion has since
converted most absorbed spans into approved ones. Classify before building: the
recommendation was three hours old and already stale.

**What shipped instead** was the `PARTIAL` remedy — worth twice as much and it closes
the fragment-leakage gap ADR-0020 opened. `extend_person_span_left` widens a PERSON
span over **one** preceding token when four structural refusals allow it: not across a
line break, not over an identifier-shaped token, not over a token ending in `:` or the
άνω τελεία, not over an uncased token. It lives in `providers/base.py` beside
`_bound_to_line` (same repair family, not Presidio-specific) and is opt-in per provider
instance, enabled for Greek only.

**It is the mirror of the trim session 7 rejected, and that is the whole argument.**
Trimming a leading token can cut the first token of a genuine three-token name — an
invisible leak. Extending can only swallow a neighbouring word — a visible
over-redaction. ADR-0016 chose the visible error; this follows it rather than reversing
it.

**Result:** strict F1 0.899 → **0.910** (above the 0.902 that preceded promotion),
PERSON precision 0.747 → 0.771 and recall 0.795 → 0.821, Greek PERSON 0.423 → 0.500 on
both, Greek tier 1 0.444 → 0.556 and tier 3 0.167 → 0.333, **fragment leakage
0.078 → 0.067 — equal to the full-value rate again**. Over-redaction still 0.000,
leakage and clean rate unchanged, en and de numerically unchanged. Nothing measured got
worse. It fires exactly twice on the corpus and both times lands exactly on the truth
span; on the `multilingual_utterances` pack (66 Greek PERSON in public text) it is
inert, which is the evidence it does not over-fire.

**The audits caught a defect that invalidated the ADR's central argument.** ADR-0021
was written claiming extension "can only over-redact — the visible error". Both
reviewers independently reproduced the opposite: widening a PERSON span into overlap
with a higher-priority EMAIL makes the reconciler reject the PERSON outright, so the
**name survives in cleartext**; and widening over a neighbouring PERSON's last token
wins the length tie-break and evicts that neighbour. Both are under-redaction — the
invisible error the whole design was justified by avoiding. The reconciler resolves
overlaps by priority and is greedy without backtracking, and a provider-layer repair
cannot see what it will collide with.

Two defences, because the conflicts are visible in different places: `_extend_left` now
receives its **sibling candidates** and refuses to claim a token another already covers
(same provider call), and it returns the **widened span plus the original** so the
reconciler can fall back (cross-provider, where EMAIL/PHONE come from a different call).
A third refusal stops a span whose own surface is identifier-shaped from being widened
past the reconciler's identifier guard. Five regression tests pin all of it. Measured
numbers did not change — the corpus never contained the shapes — which is exactly why
the argument, not the number, was the thing that needed to be right.

**Two bugs the measurement caught, both worth remembering.**

1. **`EntityMatch` is a pydantic model, not a dataclass.** The first implementation used
   `dataclasses.replace`, which raised `TypeError` on every extended span. The failure
   policy did exactly its job — the field failed, the original was preserved — so the
   suite stayed green and the *benchmark* reported leakage 0.089 instead of 0.067. **A
   silently worse number was the only symptom.** The probe had not caught it because it
   constructed `EntityMatch` directly. Use `model_copy(update=...)`.
2. **A debug harness that does not apply `--chain` runs the dataset's default chain.**
   That briefly looked like "a raising provider is reported as `success`", which would
   have been a serious defect. It was not: the provider was never called. Verified
   properly through `run_benchmark`, a raising provider gives `run status=failed` on
   every affected run. **Do not report a defect found through a harness you have not
   checked runs the code you think it does.**

**The README was refreshed** (its tree, status blurb, licence section and capability
lists), and the `incident_notes` family was delivered — as something other than a pack.

### The incident-notes stress corpus (ADR-0022)

**The design question was the work.** `demo/registry.yaml` is the licence record for
*public* corpora; a generated corpus has no source, licence or retrieval block, so an
entry there would corrupt what the registry means. And a generated corpus inherits
Increment D's own criticism — it can say nothing honest about detection realism. What
it *can* say is whether identifiers survive, because identifier formats are conventions
and `is_identifier_shaped` judges token structure rather than meaning. So it shipped as
an **over-redaction stress corpus**, committed at `tests/fixtures/incidents/`, gated by
`configs/incident_gates.yaml`, explicitly not a pack.

Built because the over-redaction gate was thin: 102 tokens at 1.00/document on the
benchmark corpus, 56 of one kind on `support_tickets`, **zero** on
`multilingual_utterances`. It adds 585 tokens across seven kinds at 6.5/document.

**It found two things immediately, which is the whole argument for it:**

1. **Over-redaction is 0.024, not 0.000.** 14 Greek tier-4 ticket ids swallowed by a
   PERSON span covering `Περιστατικό INC…`. The identifier guard passes it by design: it
   refuses only when no token is name-like, and the Greek word is.

   **I got the attribution wrong and an audit caught it.** I probed one document, saw
   the unpromoted adapter return no span, and wrote that this was a cost of ADR-0020.
   Re-running the *whole corpus* with `promote: []` still destroys 13 of the 14 — those
   are native `PERSON` labels from the base model, owing nothing to either ADR. Exactly
   one is promotion-attributable. Had that stood, a future session would have gone
   tuning promotion to recover 1 token in 14. **Generalizing from a single document is
   the error to watch for; re-run the corpus.**
2. **A work-note author is never offered to a provider.** PERSON recall is 0.000 at
   tier 4 in *all three* languages while tier 3 is 0.933-1.000. The transcript parser
   classifies `2026-04-03 09:12:04 - Peter Novak:` as structure — correct for a role
   label, wrong for a person. Those names cannot be redacted by any provider or repair
   rule. Pinned by a structural test, not by the metric.

**Neither is fixed here, deliberately.** A corpus that motivates a fix and validates it
in the same commit cannot show the fix was not fitted to it. Finding 2 in particular
collides with the reconstruction guarantee (`README.md` asks whether transcript
reconstruction preserves speaker metadata *exactly*) and needs its own ADR.

**A metric caveat fell out too:** `fragment_leakage_rate` exceeds `leakage_rate` on both
chains here, and unlike ADR-0020's gap it is an attribution artefact — emails are
name-derived, so a leaked PERSON carries an unrelated EMAIL's four-character windows,
and the ambient exclusion does not remove windows sitting inside a *different*
unredacted entity. The metric was not changed to suit a corpus introduced alongside it.

**One process note.** The provenance guard added earlier this session (commit must be a
hash, never `pending`) immediately caught the new gate file — working as designed, but
it means the old two-commit dance would leave a red commit. Resolved by committing the
corpus and code first, then the gate file recording *that* commit's hash. Cleaner than
the old pattern, and worth reusing.

**One near-miss worth keeping.** Adding `profile` to `meta` made
`tests/fixtures/corpus/meta.json` stale, so the CI step that diffs a regenerated corpus
would have gone red on push — on the *benchmark* corpus, reading as a corpus-integrity
failure rather than a new key. No default-tier test caught it, because the
reproducibility tests compare texts and spans and never `meta`. Found by an audit that
actually ran the CI command. `GENERATOR_VERSION` is now `2`, which is the field that
exists to signal exactly this.

**Still open, none started:** the distributed-path re-verification whenever Databricks
fixes the channel; **the transcript speaker-prefix leak** (finding 2 above — it needs an
ADR reconciling redaction with the reconstruction guarantee, and it is the most
serious thing left open); and
the parked ideas (`incident_notes` pack, a public transcript corpus to replace
MultiWOZ, NOTICE emission if a pack is ever published, MLflow trace redaction, GLiNER
under ADR-0015).

**On Greek specifically, stop reaching for repair rules.** After ADR-0020 and ADR-0021
the remaining gap is 13 misses of 26, and **12 of them never reach the reconciler as a
usable span** — 8 the model does not see at all, 4 reported under a refused label. Both are properties of the model and the library, not of span
boundaries. ADR-0019's mechanisms 1 and 3 are still open but are worth 1 entity and 0
respectively on this corpus. **A better-licensed Greek model at Phase 7 is the next
real move**, and the benchmark can now say which of the three mechanisms it fixes.

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

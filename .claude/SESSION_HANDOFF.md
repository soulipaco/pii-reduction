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

# Session handoff

A running record of what each working session established, so a later session can
build on evidence instead of re-deriving it. Append a new section per session.
Keep it factual: what was verified, how, and what is still unknown.

---

## Session 1 — 2026-08-17 — Environment and development harness

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

### Pre-warmed environment

A virtualenv exists at `.venv` (Python 3.11.9, Windows, ~2.2 GB). It is **not** the
project's dependency declaration — `pyproject.toml` still has to be written, and it
should pin what it actually needs rather than mirroring this list uncritically.

| Package | Version |
|---|---|
| presidio-analyzer / presidio-anonymizer | 2.2.364 |
| spacy | 3.8.15 |
| `en_core_web_lg`, `de_core_news_lg`, `el_core_news_lg` | 3.8.0 |
| lingua-language-detector | 2.1.1 |
| phonenumbers | 9.0.37 |
| pandas | 2.3.3 (deliberately pinned `<3`) |
| numpy | 2.4.6 |
| pydantic / pydantic-settings | 2.13.4 / 2.x |
| pyarrow, openpyxl, rich | current |
| ruff / mypy / pytest / pytest-cov / faker / pre-commit | 0.16.3 / 2.3.1 / 9.1.1 / … |

`pandas` is pinned below 3.0 on purpose: PySpark 3.5's pandas API is not compatible
with pandas 3.x, and Databricks runtimes ship 1.5/2.x. Raising this pin later is a
decision that has to be made against the Spark parity requirement, not by accident.

Other tooling on the machine: `git` 2.47.1, `gh` (authenticated), `uv` 0.9.18,
`databricks` CLI 0.280.0, VS Code, Java 22. No Node.js, no Docker.

### Empirical findings — verified by running the stack, not by reading docs

These three shape early design decisions and are not visible from the repository.

**1. No installed model exposes an ADDRESS-style label.**

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

**3. Local Spark is blocked.** Only Java 22 is installed; PySpark 3.5 supports Java
8/11/17. `winget install --id EclipseAdoptium.Temurin.17.JDK --scope user` fails with
"no applicable installer" (the package is machine-scope MSI), so it needs an elevated
shell. Not required before roadmap Phase 6. The alternative worth evaluating is
Databricks Connect against a real workspace instead of local Spark on Windows, which
additionally needs `winutils.exe`/`HADOOP_HOME`.

`lingua` correctly identified Greek text, so language detection has a working
dependency. Its accuracy on short text is untested and should not be assumed.

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
| `hooks/ruff_autofix.py` | PostToolUse. `ruff format` + `ruff check --fix` on edited `.py`; exits 2 with the remaining errors so they get repaired in the same turn. |
| `agents/privacy-auditor.md` | Read-only reviewer: PII in logs/exceptions, non-synthetic fixtures, hard-coded env values, dataset provenance, non-destructiveness. |
| `agents/architecture-guardian.md` | Read-only reviewer: layer responsibilities, import direction, provider-label leakage, Databricks code in core, notebook drift, premature abstraction. |
| `commands/qa.md` | `/qa` — ruff, mypy, pytest with honest reporting of skips and deselects. |
| `commands/gate.md` | `/gate` — tests plus both auditors in parallel; consolidated blocking/non-blocking verdict. |
| `commands/phase-report.md` | `/phase-report` — the completion report `AGENTS.md` requires. |

**The harness only loads when the working directory is the repository root**
(`…/pii_reduction/databricks-pii-reduction-starter`). Started from the parent folder,
every item above is silently inert.

### Open decisions carried forward

1. How `ADDRESS` is produced, given no model emits it directly.
2. Synthetic-fixture domain policy vs. Presidio email recognizer configuration.
3. Per-model label normalization (`PER` vs `PERSON`).
4. Confidence thresholds per entity and per provider.
5. Local Spark (Java 17) vs. Databricks Connect for Phase 6.
6. Repository licence — `README.md` intentionally leaves it open.
7. Whether `pyproject.toml` should carry the `.venv` package set or a narrower one.

---

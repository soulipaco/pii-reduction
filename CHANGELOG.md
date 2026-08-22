# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every non-obvious choice below has a decision record under
[`docs/adr/`](docs/adr/README.md); the ADR number is the shortest route to *why*.

---

## [Unreleased]

Work on top of `0.1.0`, all of it about making the shipped engine **usable**. No
detection capability changed, no published number moved, no shipped default changed;
all 56 gates hold at the same floors.

### Added

- **The accuracy knobs are reachable through the API** (ADR-0034). `split_lines`
  (ADR-0016) and `preserve_prefix` (ADR-0032) — the two settings most likely to change
  a result on a real column — are settable per column, from a template menu the
  operator opts into per option. The rule: *a caller may choose anything whose worst
  outcome is a measurable quality result, and never anything whose worst outcome is
  data in a place, or raw text in a column, the operator did not sanction.* Thresholds
  stay closed; they were calibrated on a held-out split and locked.
- **A control panel** (ADR-0035), served by the same process at `/` and `/ui`, on by
  default and off with `--no-ui`. Pick a template, configure the columns, preview the
  generated YAML, save it, run it, watch it finish. One static file inside the wheel —
  no build step, no CDN — so it is the same page locally and on a Databricks App.
- **A template may offer a directory** (ADR-0036). `select_file: true` makes
  `source.path` a directory and the caller names one file inside it, so a file dropped
  into a Unity Catalog volume becomes a run **without the service ever receiving the
  file**. The caller still cannot name a source: the operator chose the directory.

### Fixed

- **A `parser_options` typo in a hand-written dataset YAML** used to survive
  configuration validation and fail when the pipeline built the parser — after the
  source was resolved and, on Databricks, after a Spark session existed. Now refused at
  configuration time, on all four entry points (ADR-0034).
- **The 422 handler echoed caller-supplied mapping keys.** Pydantic puts a rejected
  dict key into the error location *before* the pattern that rejects it, so an
  unbounded string came back verbatim in a response body. Both routes closed, including
  the pre-existing `extra="forbid"` one.

### Security

- The control panel is served with a Content-Security-Policy, `X-Frame-Options: DENY`
  and `nosniff`. Without them a hostile page could frame it and turn one tricked click
  from an authenticated operator into a run under the service's own credentials.

### Known limitations added in this line of work

- **Whether a Databricks App can see `/Volumes` is unverified.** The proven route for
  volume ingestion is a serverless job (`docs/18` §6); the App's runtime is `local`.
- **An inbox listing is a shared surface.** Filenames are visible to everyone who may
  use that template, and a filename can itself be personal data. It is the first
  data-derived entry on `docs/09`'s display-surface allowlist; the operator who opts a
  directory in owns that.

---

## [0.1.0] — 2026-08-22

The first release. Built over thirteen working sessions, and complete against the nine
items of the charter's *Definition of done for a credible portfolio release*
(`docs/00_PROJECT_CHARTER.md`).

**What it is:** a multilingual, provider-agnostic engine that detects and reduces PII in
named free-text columns while preserving the structure around them — locally and on
Azure Databricks — with every published quality number locked as a regression gate.

**What it is not:** an estate scanner. It reduces PII in columns an operator names; it
has no column or table discovery, and no claim to regulatory compliance.

### At a glance

| | |
|---|---|
| default-tier tests | **1240** (model-free, Spark-free, every push) |
| integration tests | **97** (real models, nightly and on demand) |
| regression gates | **56**, across three corpora and both provider chains |
| decision records | **33** |
| CI | green on `ubuntu-latest` and `windows-latest` |
| entity taxonomy | `PERSON`, `EMAIL`, `PHONE` detected; `ADDRESS` declared and **not** detected (ADR-0002) |
| languages | English, German, Greek |

Headline quality on the committed synthetic corpus, hybrid chain
(`deterministic_presidio`): strict F1 **0.910**, leakage **0.067**, document clean rate
**0.871**, over-redaction **0.000**. The model-free chain is strict F1 0.723 with the
same 0.000 over-redaction. Full tables, per language and per difficulty tier, in
`docs/14_IMPLEMENTATION_PLAN.md` §8.

### Added

**Engine**

- **Source adapters** for pandas, CSV, Parquet and Spark/Delta tables behind one
  protocol, plus `SourceAdapter.schema()` — column names **without reading a row**
  (ADR-0031), with `pii-reduction describe` as its front door.
- **Parsers** that separate content from structure and reconstruct byte-exactly: plain
  text (with an opt-in `split_lines` mode, ADR-0016) and transcripts, whose timestamp
  and speaker prefix are preserved as non-processable structure (ADR-0032).
- **Providers** behind one contract: deterministic EMAIL/PHONE recognizers and a
  Presidio/spaCy NER adapter whose result objects, label vocabulary and engine
  configuration stop at the adapter boundary (ADR-0004). Per-provider, per-entity
  confidence thresholds; a global threshold is forbidden (ADR-0005).
- **Language detection and routing** — lingua with a hard short-text gate (ADR-0012),
  resolved from eligible text only, with per-language provider chains.
- **Reconciliation** of overlapping candidates across providers, with an identifier
  guard that refuses to redact an operational identifier, and every rejection counted
  by reason.
- **Reducers** — redact, mask and deterministic pseudonymization (ADR-0013), the last
  with measured referential consistency (1.000) and scope isolation.
- **Span repair at the provider boundary**: line-bounding for spans that cross a line
  break (ADR-0016), a Greek-only PERSON left-extension (ADR-0021), and clipping spans
  out of HTML/BBCode/URL markup with an independently written output check (ADR-0027).
- **Greek label promotion**, scoped to the Greek provider instance (ADR-0020) — traded
  strict precision for 43% less leakage after ADR-0019 diagnosed the gap to three
  mechanisms.
- **Fail-closed by default**: `failure_mode` defaults to `quarantine_row`; raw-text
  pass-through is an explicit opt-in (ADR-0023).
- **Batched detection within a row** (ADR-0033) — 1.56–1.77× on multi-segment columns,
  output-identical over 576 corpus segments. Across-row batching is refused, because it
  would break the per-row quarantine.

**Evaluation**

- A **seeded synthetic corpus** with an injection manifest, so ground truth is derived
  deterministically rather than reverse-engineered (ADR-0011), reproducible byte-for-byte
  and checked as such by CI.
- **Two more corpora**, each built to measure something the first could not: an
  incident-notes over-redaction stress corpus with 585 protected tokens across eight
  kinds (ADR-0022), and a markup corpus for the ADR-0027 guard (ADR-0029).
- **Three public-dataset packs** — Bitext tickets and conversations, MASSIVE de/el —
  fetched from pinned revisions with recorded checksums rather than redistributed
  (ADR-0017, ADR-0018), each with its own gate set.
- **Metrics that separate distinct failures**: strict and relaxed matching, leakage
  beside fragment leakage, over-redaction of protected tokens, document clean rate, and
  `unreachable_entity_rate` — how much ground truth the parser ever offered a provider,
  because a miss nothing could have caught is not a detection result (ADR-0028).
- **A gate runner** where a gate that matches no row, matches several, or whose slice
  support shrank is a **failure**, not a pass (ADR-0009).
- Threshold calibration reviewed on a calibration split and locked; the test split read
  exactly once, and that read recorded.
- A **10k-document two-chain comparison** (`docs/16_BENCHMARK_REPORT_10K.md`).

**Databricks**

- A `databricks/` surface: `SparkTableSource`, `DeltaTableOutput`, metadata-only audit
  and metrics tables, and `pii-reduction-databricks run` as the front door. Local and
  remote call the same core APIs (ADR-0006).
- **Local/remote parity asserted against a real workspace** — byte-identical processing
  on the driver path.
- An **opt-in reduced-only projection** (ADR-0024), which makes `docs/09`'s grant model
  realisable with shipped code.
- Run provenance carrying real library **and model** versions, a language-detector
  version, a Delta source version, and a non-secret pseudonymization key digest — so key
  rotation is a visible provenance change.
- An Asset Bundle (`databricks.yml`, `resources/`) with zero hard-coded workspace
  values, pinned by a guard.

**Service (rung 4)**

- A **thin HTTP API** over server-side templates (ADR-0026), hosted as a Databricks App
  rather than built as one. **No endpoint accepts or returns text of any kind** —
  enforced by a reflection test over every model, not by a filter — and four static
  guards make the layering code rather than prose.
- A **durable run journal** (ADR-0030): every state transition appended to JSON lines
  and reloaded at startup, so a run that happened does not 404 after a restart. A record
  recovered non-terminal is rewritten to `failed`/`interrupted`, because `running` for a
  dead process is the one state a caller waits on.

**Documentation**

- 22 design documents, 33 ADRs, a Databricks runbook executed end to end
  (`docs/18`), and two adversarial reconciliations: two external reviews
  (`docs/17`) and a second independent implementation of the same problem
  (`docs/20`), each classified item by item **including the rejections**.

### Decided

- **ADR-0032 — the speaker prefix stays preserved by default.** Open since session 8 and
  named "the most serious open design item" in three documents. A transcript prefix is
  structure, so a work-note author is never offered to a provider; the ruling keeps that
  default and names `preserve_prefix: false` — which had shipped since Increment A2 and
  which nobody had measured — as the per-column opt-in. Measured both ways: it takes the
  incident corpus's strict F1 0.761 → 0.844 and its 90 unreachable entities to 0, and
  costs the benchmark corpus's PERSON precision 0.771 → 0.744 for no recall gain.
- **ADR-0025 — Azure Databricks is the primary deployment target**, not one execution
  surface among several. Local stays the development surface and a hard constraint.
- **ADR-0015 — CPU-only is a hard constraint.** No component may require a GPU.
- **ADR-0007 — MIT**, which excludes the better Greek spaCy models (CC BY-NC-SA) and is
  why Greek routes through the multilingual `xx_ent_wiki_sm`.

### Known limitations

Stated here because a release that hides them is worth less than one that does not. Each
is parked with the condition that would reopen it, in `docs/14` §8.

- **Greek PERSON recall is 0.500 overall and 0.000 at difficulty tier 4** — licence-bound
  to a weaker multilingual model, diagnosed to the mechanism (ADR-0019), and two of the
  three mechanisms already addressed.
- **Markup destroys PERSON recall** — 0.322 against 0.821 — because the model returns no
  span at all on markup-dense clauses (ADR-0029). The remedy changes the model's input,
  which has twice been measured as trading one error for another.
- **`ADDRESS` is in the taxonomy and is not detected** (ADR-0002).
- **Over-redaction is 0.024 on identifier-dense Greek text**, not 0.000 everywhere. It is
  gated so it cannot grow.
- **The distributed `mapInPandas` path is shipped and has never executed** — the
  workspace's serverless sandbox returns `ISOLATION_STARTUP_FAILURE`, which is
  infrastructure. A `databricks`-marked test flips from skip to assertion the day it is
  fixed, with no code change.
- **`bundle deploy` is blocked** by the Databricks CLI's expired Terraform signing key.
  It never affected Apps, which deploy without a bundle.
- **The service is single-replica** — two writers would interleave in the run journal.
- **No `note_history` parser**, so the charter's UC-03 (ServiceNow-style note blocks,
  each header preserved) is **unmet**. The charter says so in place. A note column
  parsed as `transcript` gets most of the way, and ADR-0032 puts the note author in
  scope for it.
- **A Databricks App authenticates the end user and authorizes as its own service
  principal.** Measured, not assumed: the default on-behalf-of-user scopes are
  identity-only. So the server-side-template design is load-bearing, and whoever grants
  the App data access grants it to the service principal.

### Notes

- **Nothing is published, so no attribution is owed.** Dataset licences (MASSIVE
  CC BY 4.0, Bitext share-alike) reach each built pack's `meta.json`, but no dataset is
  redistributed and no `NOTICE` is written. Distributing a pack, or making this
  repository public, makes that obligation real and it must land in the same change.
- **No published number has ever moved without being re-measured.** Three corpora exist
  so the numbers stay honest, not so they can be improved; `AGENTS.md` forbids tuning a
  benchmark to the model.
- **All committed PII examples are synthetic**, generated from seeds, using phone
  numbers from published permanently-unassigned ranges (ADR-0014) and reserved example
  domains (ADR-0003).

[Unreleased]: https://github.com/soulipaco/pii-reduction/compare/v0.1.0...main
[0.1.0]: https://github.com/soulipaco/pii-reduction/releases/tag/v0.1.0

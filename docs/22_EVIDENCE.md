# Evidence: what has actually been run, and where the proof is

One page for the question a reader asks first — **does this work?** — answered by things
that were executed rather than described. Every figure below was re-run on 2026-08-22
against the committed tree; nothing here is quoted from an earlier session.

The rule this document exists to serve is `AGENTS.md`'s: *do not claim Databricks
execution succeeded unless it was actually executed in a Databricks environment.* So
each claim carries **where it was proven** and, where it matters, **what was not
proven**.

---

## 1. It runs, and the tests say what they cover

| tier | result | what it needs |
|---|---|---|
| default (`pytest -q`) | **1380 passed**, 2 skipped | nothing — no models, no Spark, no extras |
| integration (`-m integration`) | **97 passed** | the `presidio` + `language` extras and spaCy models |
| packaging (`-m packaging`) | **1 passed** | builds a wheel and reads an asset back out of it |
| `ruff format --check` / `ruff check` / `mypy src tests` | clean | — |

The 2 skips are the symlink traversal tests, which need a privilege Windows does not
grant by default; they run in CI on Linux. **The whole default tier was also re-run in a
genuine core-only environment** (`uv pip install -e ".[dev]"`, `lingua` and
`presidio_analyzer` verifiably absent) — because a green run on a developer machine that
has the extras proves nothing about the tier CI actually installs.

CI runs both platforms on every push: `ubuntu-latest` and `windows-latest`.

## 2. The published numbers are enforced, not reported

**56 regression gates**, re-run in full:

| corpus | model-free chain | hybrid chain |
|---|---|---|
| committed synthetic (`tests/fixtures/corpus`) | 10/10 | 15/15 |
| incident notes (`tests/fixtures/incidents`) | 6/6 | 10/10 |
| markup (`tests/fixtures/markup`) | 7/7 | 8/8 |

A gate that matches no row, matches several, or whose slice support shrank is a
**failure**, not a pass — a gate that measures nothing is the failure mode the design
exists to stop (ADR-0009).

**All three corpora regenerate byte-for-byte from their seeds**, checked by `diff -r`
here and by CI on every push. That is what makes the gates meaningful: they are scored
against the same corpus the repository holds.

## 3. What reduction actually looks like

From the committed synthetic corpus — Class A throughout, generated from a seed, with
phone numbers from published permanently-unassigned ranges (ADR-0014) and reserved
example domains (ADR-0003). Hybrid chain, `redact` strategy.

**English, plain text**

```text
- Please email James Whitfield at maria.rossi@example.net about ticket INC00100000.
+ Please email <PERSON> at <EMAIL> about ticket INC00100000.
```

The ticket id survives. That is the point of the over-redaction metric: an operational
identifier is not PII, and destroying it makes the data useless for the analysis it was
reduced *for*.

**English, transcript — structure preserved**

```text
- 2026-04-03 09:15:13 - Guest: Hi, I'm Aisha Bello. Please call me on +1 202 555 0142.
+ 2026-04-03 09:15:13 - Guest: Hi, I'm <PERSON>. Please call me on <PHONE>.
```

The timestamp and the speaker label are untouched, because the parser marks them as
structure and no provider is ever offered them (ADR-0032).

**German**

```text
- Bitte schreiben Sie Jürgen Müller an jan.becker@example.org zum Vorgang INC00100518.
+ Bitte schreiben Sie <PERSON> an <EMAIL> zum Vorgang INC00100518.
```

**Greek — and this one is a failure, shown deliberately**

```text
- Παρακαλώ στείλτε email στον/στην Μαρία Παπαδοπούλου στο maria.papadopoulou@example.net …
+ <PERSON> στείλτε email στον/στην Μαρία Παπαδοπούλου στο <EMAIL> …
```

`Παρακαλώ` ("please") was taken for a name, and the actual name **survived**. This is
the Greek gap the project documents rather than hides: the good Greek spaCy models are
CC BY-NC-SA and cannot enter an MIT project (ADR-0007), so Greek routes through a weaker
multilingual model. The gap is diagnosed to three mechanisms (ADR-0019), two of them
addressed (ADR-0020, ADR-0021), and Greek PERSON recall is published as **0.500** rather
than rounded up.

## 4. The service, driven over the wire

Against the shipped configuration, live:

```text
GET  /health     200      GET  /ui      200
GET  /entities   200      GET  /docs    200
GET  /templates  200
GET  /datasets   200
```

**The confused-deputy guard answers for itself.** A run request that tries to name its
own source:

```text
POST /runs  {"dataset": "...", "source": {"type":"csv","path":"/etc/passwd"}}
-> 422
```

Refused because no request model has anywhere to put it — absence, not a filter
(ADR-0026). The reason is measured rather than cautious: a Databricks App authenticates
the end user and authorizes as its **own service principal**, so a caller who could name
a table would make that principal read it (`docs/19`).

**The control panel carries its clickjacking and egress headers:**

```text
x-frame-options: DENY
content-security-policy: … connect-src 'self'; frame-ancestors 'none'; form-action 'none'
```

## 5. Build a configuration and run it, without touching a file by hand

```text
POST /configs   -> saved as datasets/evidence_demo.yaml
POST /runs      -> 202 accepted
GET  /runs/{id} -> succeeded

  rows_read          102        fields_failed       0
  rows_written       102        entities_detected   295
  fields_processed   102        entities_reduced    188
```

`entities_detected` exceeds `entities_reduced` because the reconciler rejects candidates
— overlaps resolved by priority, and identifier-shaped spans refused outright. Every
rejection is counted by reason and reaches the run metrics.

## 6. Databricks — what was executed, and what was not

**Executed on a real Azure Databricks workspace:**

| | when | what it proved |
|---|---|---|
| driver-path parity | sessions 7, 8, 10 — **5 runs** across two auth routes (`docs/14` §8) | byte-identical local/remote processing, `SparkTableSource` and `DeltaTableOutput` against real Delta |
| runbook end to end | first run session 10 (2026-08-20, 20 rows); session 11 added the PERSON repeat (30 rows) and a **volume-file source read as a serverless job** (25 rows, three Delta tables, audit table with its exact column set) | `docs/18` executed as written |
| the service, hosted | session 12 | `apps create` → `apps deploy`; `SUCCEEDED — App started successfully`. **The five endpoints that existed then** — `/health`, `/entities`, `/templates`, `/datasets`, `/runs` — answered over HTTPS through the App proxy, and the 422 guard answered in the hosted process |
| the identity question | session 12 | read off the deployment: the App carries its own service principal, and its default on-behalf-of-user scopes are `iam.access-control:read` and `iam.current-user:read` — **identity only, no data scope** |

**Not executed, and stated as such:**

- **The distributed `mapInPandas` path.** Shipped, never run — the workspace's serverless
  sandbox returns `ISOLATION_STARTUP_FAILURE`, which is Databricks infrastructure. A
  `databricks`-marked test flips from skip to assertion the day it is fixed, with no
  code change here.
- **`bundle deploy`.** Blocked by Databricks CLI v0.280.0's expired Terraform signing
  key. `bundle validate` passes. This never affected Apps, which deploy without a bundle.
- **Whether a Databricks App can see `/Volumes`.** The proven volume route is a
  serverless job. The App's runtime is `local`. One `ls /Volumes/...` from the App
  settles it; until then the ADR-0036 inbox is proven locally and on a job, not on an App.
- **The Spark path against a real Unity Catalog table for `SourceAdapter.schema()`**
  (ADR-0031) — fake-session tested only.
- **The control panel, the caller-settable knobs and the file-picker template
  (ADR-0034 / 0035 / 0036) have never run on the App.** The hosted deployment *predates
  all three* — it was created and stopped before they existed — so its snapshot is a
  wheel without them. They are proven locally and, for the volume source underneath
  ADR-0036, on a serverless job. `apps deploy` with the current wheel is what would
  prove them hosted, and nobody has run it.
- **The ADR-0024 grant boundary, at the level that matters.** The workspace run wrote
  the reduced-only projection into the *same* throwaway schema, so what it proved is
  that the table exists and drops the raw column. The **separate-prefix** grant boundary
  `docs/09`'s model rests on is covered by unit tests only (`docs/18`).
- **The hosted run journal survives a restart but not a redeploy** — it is on
  container-local disk (`docs/19`). A Volume path is the next step and is not taken.

The App itself is **stopped, not deleted** (2026-08-22): it proved what it was created
to prove and compute is not free. `apps start` plus `apps deploy` brings it back.

## 7. What the numbers are

Measured baseline on the committed corpus, both chains — reproduce with
`pii-reduction benchmark [--chain deterministic_presidio]`:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | **0.910** |
| leakage rate | 0.433 | **0.067** |
| document clean rate | 0.161 | **0.871** |
| over-redaction rate | **0.000** | **0.000** |
| PERSON precision / recall | 0.000 / 0.000 | 0.771 / 0.821 |

Deterministic recognizers find no names at all — that row is why the NER provider
exists, and publishing it is why the comparison means anything.

Per-language, per-tier tables, the public-dataset packs, the 10k-document comparison and
the strategy comparison are all in `docs/14_IMPLEMENTATION_PLAN.md` §8 and
`docs/16_BENCHMARK_REPORT_10K.md`.

## 8. The claim this project makes about its own numbers

**No published benchmark number has ever moved without being re-measured.** Three
corpora exist so the numbers stay honest, not so they can be improved; `AGENTS.md`
forbids tuning a benchmark to the model, and `docs/08` records the one deliberate
test-split read and its protocol.

Where a change *did* move a number, it says so and shows both sides — ADR-0020 traded
PERSON precision 0.833 → 0.771 for 43% less leakage, and ADR-0032 publishes what its
opt-in costs as well as what it buys.

---

## Reproducing this page

```bash
pip install -e ".[dev]"                                    # core + dev, no models
pytest -q                                                  # 1380 passed
pii-reduction benchmark --gates configs/benchmark_gates.yaml
pii-reduction-service --configs configs                    # then open http://127.0.0.1:8000/
```

The hybrid numbers need the provider extras and the documented spaCy models — see
`docs/15_PROVIDERS.md`. Nothing in this page requires a Databricks workspace except
§6, which is labelled accordingly.

# Databricks PII Reduction Accelerator

> An open-source, multilingual, provider-agnostic accelerator for detecting, redacting, pseudonymizing, and benchmarking personally identifiable information (PII) in known free-text columns, locally and on Databricks.

<!-- "discovering" was deliberately removed from this line (session 9): the system
     detects entities inside columns the operator names — it has no estate or
     column discovery, and both external reviews independently flagged the word
     as the one misleading claim in this README (docs/17 §1.8). -->

## Why this project exists

Organizations increasingly store operational text alongside structured business data: support tickets, chat transcripts, call summaries, case notes, incident descriptions, resolution notes, emails, CRM comments, survey responses, and knowledge-work artifacts. These fields often contain PII even when the surrounding table is otherwise well governed.

PII reduction in those environments is not just a named-entity-recognition problem. A production-grade solution must also understand document structure, preserve non-sensitive metadata, support multiple languages, work at data-platform scale, expose measurable quality, and integrate cleanly with governance and downstream analytics.

This repository is intended to demonstrate that full problem, end to end.

The accelerator is designed around five principles:

1. **Source-agnostic:** the PII engine should not care whether input comes from Excel, CSV, Parquet, Delta, or an existing Databricks table.
2. **Structure-aware:** transcript speaker labels, timestamps, ticket headers, and other operational metadata should be preserved when only the conversational or note body is in scope.
3. **Multilingual:** language detection and language-aware recognizers are first-class parts of the pipeline rather than afterthoughts.
4. **Provider-agnostic:** Presidio, transformer-based NER, deterministic recognizers, and Databricks-native or model-serving approaches should be interchangeable behind a common interface.
5. **Measurable:** every provider and pipeline version should be evaluated against reproducible ground truth using entity-level and document-level metrics.

## Repository status

**The `docs/11_ROADMAP.md` build order is complete through Phase 6.** Shipped and
measured: CSV/pandas sources, plain-text and transcript parsers, deterministic
EMAIL/PHONE and Presidio NER providers, language detection with per-language provider
routing, entity reconciliation, redact/mask/pseudonymize reducers, local outputs with
run metrics and run provenance, a seeded synthetic corpus with an injection manifest,
three public-dataset packs built from pinned checksummed sources, the evaluation
framework with its gate runner, and a Databricks execution surface whose local/remote
parity is asserted against a real workspace.

The architecture, data contracts, security model and contribution rules that framed
all of it are in `docs/`, and every non-obvious choice has a decision record under
`docs/adr/`.

Every number published below is enforced rather than only reported: they are locked as regression gates in `configs/benchmark_gates.yaml` and checked by CI on the committed corpus. The public-dataset packs carry their own gate sets under `configs/pack_gates/`, measured on their own corpora — never a reason to loosen the synthetic floors.

`docs/14_IMPLEMENTATION_PLAN.md` §8 carries the live status, the measured baseline, and what is queued next.

### Quickstart

```bash
pip install -e ".[dev]"
```

That is the whole install: no NLP model, no provider extra. Then run the benchmark over the committed synthetic corpus:

```bash
pii-reduction benchmark
```

Measured baseline (`deterministic_only` chain, `redact` strategy, 102 documents, 180 injected entities): EMAIL and PHONE strict precision/recall/F1 of 1.000 in every language and tier, over-redaction 0.000, and **PERSON strict recall 0.000 over a support of 78** — deterministic recognizers cannot find names.

Adding the NER provider (requires the `presidio` extra and the models documented in `docs/15_PROVIDERS.md`):

```bash
pii-reduction benchmark --chain deterministic_presidio
```

Either chain can be checked against its locked floors, which is what CI does — it exits non-zero if a gate fails:

```bash
pii-reduction benchmark --gates configs/benchmark_gates.yaml
```

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | 0.910 |
| leakage rate | 0.433 | 0.067 |
| fragment leakage rate | 0.433 | 0.067 |
| document clean rate | 0.161 | 0.871 |
| over-redaction rate | 0.000 | 0.000 |

Both leakage metrics are published because agreement between them is a *result*, not a
tautology. `leakage rate` counts an entity leaked only when its exact full surface
survives; `fragment leakage rate` counts any surviving 4-character window, so a
boundary error that redacts half a name shows up in the second and not the first.
They agree here, which is the claim being made. They briefly did not: ADR-0020 opened a
0.011 gap by detecting two Greek surnames without their given names, and ADR-0021's
span extension closed it.

PERSON recall reaches 1.000 for German and 0.889–1.000 for English across every difficulty tier, but **0.000–0.667 for Greek**. The good Greek spaCy models are non-commercial and excluded on licensing grounds (ADR-0007), so Greek routes through a multilingual model — but that is only part of the story. Measured directly (ADR-0019), the model usually *finds* the Greek names and then gets the boundary or the label wrong, so two of the three mechanisms behind that number are not licensing problems at all. Acting on two of them cut whole-corpus leakage 0.117 → 0.067 and took Greek tier-2 recall 0.111 → 0.667: ADR-0020 promotes `LOCATION`/`ORGANIZATION` spans to PERSON for Greek, and ADR-0021 extends a PERSON span over a preceding token when that is structurally safe. Both are Greek-scoped — English and German are numerically unchanged — and the net cost is PERSON precision 0.833 → 0.771. The third mechanism is untouched: the model simply not finding the name is now the majority of what remains, and no boundary or label rule can reach it. `docs/15_PROVIDERS.md` publishes the gap per language and tier rather than reporting an average that hides it.

To regenerate the corpus (same seed gives a byte-identical corpus and manifest):

```bash
python demo/build_corpus.py --out tests/fixtures/corpus --seed 42
```

### Public-dataset demo packs

The corpus above is templates this project wrote, so a provider that does well on it has
only been asked an easy question. Three packs measure the same pipeline on text written
by other people, with synthetic PII injected into it so the ground truth is still exact:

```bash
python demo/build_pack.py support_tickets
pii-reduction benchmark --corpus demo/packs/support_tickets --chain deterministic_presidio
```

| pack | source | shape |
|---|---|---|
| `support_tickets` | Bitext customer support (CDLA-Sharing-1.0) | English support notes |
| `support_conversations` | the same exchanges, as Customer/Agent turns | English transcripts |
| `multilingual_utterances` | MASSIVE (CC BY 4.0) | short lower-case German and Greek |

**No raw data and no pack is committed.** Each source file is fetched from a pinned
commit revision and verified against a SHA-256 recorded in `demo/registry.yaml`
(ADR-0017), so a pack is rebuilt rather than stored. The registry is a gate, not a
document: an unregistered dataset, a non-permissive licence, or a source carrying real
personal data is refused before anything downloads — which is how MultiWOZ 2.2 left the
demo set once its published text turned out to contain real Cambridge phone numbers
(ADR-0018).

On the packs, EMAIL and PHONE hold at 1.000 precision and recall across 1,600 entities
in three languages, and the hybrid chain reaches strict F1 0.998–0.999 on English with
leakage 0.000. The interesting numbers are elsewhere: PERSON *precision* is 0.985–0.995
because public prose contains names no manifest knows about, and Greek PERSON recall is
0.727 against 0.556–0.667 on the synthetic corpus with the same model (both sides moved with ADR-0020 and ADR-0021, from 0.606 and 0.111–0.222) — which is
**easier Greek, not better detection**: single short clauses avoid all three of the
failure modes the synthetic templates trigger (ADR-0019). `docs/14_IMPLEMENTATION_PLAN.md`
§8 publishes all of it beside the synthetic numbers, with the limitations that keep it
honest.

The recommended first implementation is a public-data demo with three families of text:

- customer-support tickets,
- multi-turn customer/agent conversations,
- ServiceNow-style incident notes generated from public or synthetic content.

Synthetic PII is injected into public-safe text so the project can measure precision, recall, F1, and leakage without publishing real personal information.

## What the final accelerator should support

The lists below are the intended scope. Each is annotated with what is **shipped
today**, so the ambition and the state of the code cannot be confused for one another.
`docs/14_IMPLEMENTATION_PLAN.md` §8 is the authoritative status.

### Sources

- Excel workbooks with multiple sheets
- CSV files and folders of CSV files
- Parquet
- local pandas DataFrames for development
- Spark DataFrames
- Delta tables
- fully-qualified Unity Catalog tables

*Shipped: CSV, Parquet, local pandas, and Unity Catalog tables through a Spark session
(`SparkTableSource`). Excel is not implemented.*

### Text structures

- plain free text
- transcript / diarized conversation text
- ServiceNow-style work-note histories
- key/value case summaries
- email-like text
- configurable custom parsers

*Shipped: plain free text and transcript/diarized text, both with byte-exact
reconstruction, plus a `key_value` parser and a `split_lines` option on the plain
parser. The last two are registered and configurable but enabled nowhere: both were
measured against the English key/value problem and lost to a span repair that fixes
the model's output instead of re-cutting its input (ADR-0016). Work-note histories and
email-like text are not implemented.*

### PII entity families

Initial baseline:

- person names
- email addresses
- phone numbers
- physical addresses (in taxonomy and benchmarks from the start; detection deferred
  to a later provider — see `docs/adr/0002-address-entity-deferred.md`)

Designed for future extension to:

- dates of birth
- government identifiers
- account numbers
- financial identifiers
- IP addresses
- device identifiers
- user IDs
- health identifiers
- geolocation
- custom organization-specific entity types

### Reduction strategies

- redaction: `<PERSON>`, `<EMAIL>`, `<PHONE>`, `<ADDRESS>`
- masking: `jo***@example.com`
- deterministic pseudonymization
- reversible pseudonymization when explicitly configured and appropriately secured
- drop / suppress for selected entity types

*Shipped: redaction, masking and deterministic pseudonymization, all three measured
side by side (`--strategy`). Reversible pseudonymization and drop/suppress are not
implemented; reversibility in particular needs a key-management design this project
has not taken.*

### Providers

The pipeline should support a common `PIIProvider` abstraction, allowing implementations such as:

- Microsoft Presidio
- spaCy-backed Presidio engines
- transformer / Hugging Face NER
- GLiNER-style zero-shot entity detection
- deterministic recognizers for high-precision patterns
- Databricks-native AI or model-serving implementations where appropriate
- hybrid ensembles

*Shipped: a deterministic recognizer (EMAIL, PHONE) and a Presidio/spaCy adapter
(PERSON), composed as a hybrid chain and routed per language. Two Presidio instances
serve different languages with different options (ADR-0020, ADR-0021). Transformer NER,
GLiNER and Databricks-native providers are roadmap Phase 7 — GLiNER subject to the
CPU-only constraint of ADR-0015.*

No single provider is assumed to be best for every language or entity type. The
measured numbers in `docs/15_PROVIDERS.md` are the evidence for that claim rather than
an assertion of it: the deterministic recognizers beat the NER on their own entities,
and the NER is the only thing that finds names.

## Conceptual pipeline

```text
Data Source
   |
   v
Source Adapter
   |
   v
Dataset Contract + Column Policy
   |
   v
Text Parser / Segmenter
   |
   +---- plain text
   +---- transcript turns
   +---- note blocks
   +---- key/value sections
   |
   v
Language Detection
   |
   v
PII Provider(s)
   |
   v
Entity Reconciliation
   |
   v
Reduction Strategy
   |
   v
Reconstruction
   |
   +---- preserve timestamps
   +---- preserve speaker labels
   +---- preserve note headers
   +---- preserve row grain
   |
   v
Validation + Metrics + Audit Events
   |
   v
Output Adapter
   |
   +---- local file
   +---- pandas
   +---- Spark
   +---- Delta / Unity Catalog
```

## Repository layout

As built. Every path below exists; nothing here is aspirational.

```text
.
├── README.md · AGENTS.md · CLAUDE.md · CONTRIBUTING.md · SECURITY.md · LICENSE
├── pyproject.toml            # src layout, optional extras (ADR-0008)
├── .github/workflows/        # ci.yml (every push, model-free) + integration.yml (nightly)
├── docs/
│   ├── 00_PROJECT_CHARTER.md … 13_PORTFOLIO_STORY.md
│   ├── 14_IMPLEMENTATION_PLAN.md   # §8 is the live status and work queue
│   ├── 15_PROVIDERS.md             # shipped providers, licences, measured results
│   ├── 16_BENCHMARK_REPORT_10K.md  # the 10k-document two-chain comparison
│   └── adr/                        # decision records, indexed in adr/README.md
├── configs/
│   ├── project.yaml · entities.yaml · providers.yaml
│   ├── datasets/             # one dataset contract per file
│   ├── benchmark_gates.yaml  # the committed corpus's regression floors
│   └── pack_gates/           # one gate set per public-dataset pack
├── src/pii_reduction/
│   ├── contracts/            # typed core objects; imports nothing else in the project
│   ├── config/ entities/ language/ patterns.py
│   ├── sources/ parsers/ providers/ reducers/ outputs/
│   ├── processing/           # the pipeline: parse → language → detect → reconcile → reduce
│   ├── evaluation/ observability/
│   ├── synthetic/            # build-time corpus, injection and pack builders
│   ├── databricks/           # execution surface: Spark source, Delta output, runners
│   └── cli.py · benchmark.py # entry points
├── tests/                    # fast tier by default; integration/slow/databricks marked
├── demo/                     # runnable front doors; the logic lives in synthetic/
└── data/downloads/           # fetched public datasets, gitignored and checksummed
```

Two directories the original plan named are deliberately absent. There is no
`notebooks/`: the Databricks entry points are importable modules under
`src/pii_reduction/databricks/`, because a notebook is not testable and `AGENTS.md`
forbids logic living in one. There is no `resources/`: no job, bundle or app resource
has been needed yet, and an empty directory is a promise rather than a fact.

## Implementation philosophy

The repository should avoid becoming a notebook collection. Business logic belongs in importable Python modules. Notebooks should only orchestrate or demonstrate those modules.

The local development path should be able to run without Databricks. The Databricks path should reuse the same pipeline components rather than maintaining a separate implementation.

The core library should be testable with synthetic data in seconds. Larger public datasets are demo and benchmark assets, not a dependency for running the unit-test suite.

## Public-data policy

The repository must not contain:

- proprietary corporate exports,
- copied production transcripts,
- real customer names or contact information,
- secrets or tokens,
- raw datasets whose redistribution license does not permit inclusion.

Preferred approach:

1. download or reference a public-safe dataset,
2. normalize it into the accelerator's canonical text contracts,
3. inject synthetic PII with deterministic seeds,
4. store ground-truth entity spans separately,
5. run detection and reduction,
6. evaluate the output against the injected ground truth.

See `docs/02_PUBLIC_DATA_STRATEGY.md`.

## Success criteria

A mature version of this repository should make it possible to answer all of the following with evidence:

- How accurately does each PII provider detect each entity type?
- How does performance differ by language?
- How does performance differ by document structure?
- What percentage of fields still contain known PII after reduction?
- How often does the system over-redact non-PII operational identifiers?
- Does transcript reconstruction preserve speaker metadata exactly?
- Does the same configuration behave consistently locally and on Databricks?
- How does throughput scale as text volume increases?
- What are the quality/cost tradeoffs of deterministic, NER, and AI-based approaches?

## Non-goals

This project is not intended to claim that automated PII reduction guarantees regulatory compliance. It is an engineering and evaluation accelerator. Production adoption requires organization-specific legal, security, privacy, retention, and model-risk review.

The project should also avoid pretending that every identifier is PII. Entity scope must be explicit and configurable.

## Documentation map

- **Project purpose and boundaries:** `docs/00_PROJECT_CHARTER.md`
- **Technical design:** `docs/01_ARCHITECTURE.md`
- **Public datasets and synthetic PII:** `docs/02_PUBLIC_DATA_STRATEGY.md`
- **Canonical schemas and contracts:** `docs/03_DATA_CONTRACTS.md`
- **PII provider and reduction engine:** `docs/04_PII_ENGINE.md`
- **Language-aware processing:** `docs/05_MULTILINGUAL_STRATEGY.md`
- **Configuration model:** `docs/06_CONFIGURATION_CONTRACT.md`
- **Databricks execution model:** `docs/07_DATABRICKS_RUNTIME.md`
- **Metrics and benchmarking:** `docs/08_EVALUATION_BENCHMARKING.md`; the 10k-document two-chain comparison is `docs/16_BENCHMARK_REPORT_10K.md`
- **Security and privacy:** `docs/09_SECURITY_PRIVACY_GOVERNANCE.md`
- **Test strategy:** `docs/10_TESTING_QA.md`
- **Implementation roadmap:** `docs/11_ROADMAP.md`
- **Portfolio demo scenarios:** `docs/12_DEMO_SCENARIOS.md`
- **How to present the project:** `docs/13_PORTFOLIO_STORY.md`
- **Build sequence and increments:** `docs/14_IMPLEMENTATION_PLAN.md`
- **Shipped providers, licences and measured results:** `docs/15_PROVIDERS.md`
- **Decision records:** `docs/adr/`

## License

**MIT** (`LICENSE`). The choice is recorded in ADR-0007 and it constrains what may be
depended on: the good Greek spaCy models are CC BY-NC-SA (non-commercial) and are
therefore excluded, which is why Greek routes through the multilingual `xx_ent_wiki_sm`
and why the provider refuses to be configured with them. A test asserts the licence
file and that exclusion together.

Dataset licences are tracked separately from the code licence, as they must be. No
public dataset is redistributed here — packs are rebuilt on demand from a pinned
revision with a recorded checksum (ADR-0017), and each pack's `meta.json` carries its
source licence, attribution requirement and share-alike flag. Nothing is published
today, so no attribution is owed yet; that becomes real the moment a built pack is
distributed.

# Public Data Strategy

## Objective

The repository needs realistic text without publishing or redistributing private PII. The public-data strategy therefore separates **text realism** from **PII ground truth**.

The preferred pattern is:

```text
public-safe text
    +
synthetic PII generator
    +
deterministic injection manifest
    =
portfolio-safe labeled benchmark
```

This gives the project realistic language and business structure while preserving exact ground truth.

## Dataset families to support

The accelerator should not depend on a single benchmark. It should support multiple domain packs.

### 1. Customer-support tickets

Useful fields:

- subject,
- description,
- customer message,
- agent reply,
- resolution,
- ticket category,
- priority,
- language,
- timestamps.

Why useful:

- resembles real operational lakehouse data,
- contains both short and long text,
- easy to map into incident-style schemas,
- useful for names, emails, phones, and addresses.

### 2. Customer-service dialogues

Useful representation:

```text
Agent: ...
Customer: ...
```

or timestamped variants.

Why useful:

- validates transcript-aware parsing,
- allows PII to appear only in dialogue bodies,
- creates turn-level language scenarios,
- exposes reconstruction mistakes.

### 3. ITSM / incident-management event data

Even when public incident datasets do not contain rich text, they provide realistic structural metadata:

- incident number,
- opened/closed times,
- assignment groups,
- priority,
- category,
- state transitions.

These can be combined with public-safe or generated text to create a ServiceNow-like demo table without pretending the source is an exact ServiceNow export.

### 4. Email-like corpora

Useful for:

- signatures,
- greetings,
- phone numbers,
- addresses,
- names,
- quoted text,
- headers versus body segmentation.

Licensing and privacy must be inspected carefully before using any historical email corpus.

### 5. Legal anonymization benchmarks

Useful because they contain complex names, locations, organizations, dates, and narrative context. They are especially valuable for evaluating false positives and long-context behavior.

### 6. Dedicated PII / de-identification benchmarks

These should be used to validate raw detection quality independently of the business-demo corpus.

A provider that works well on synthetic support tickets may perform differently on a standardized PII benchmark. Both views matter.

## Dataset selection criteria

Every candidate dataset should be scored on:

| Criterion | Question |
|---|---|
| License | Can we download, transform, and redistribute it? |
| Privacy | Does it contain real personal information? |
| Domain fit | Does it resemble operational text? |
| Language | Does it contribute useful multilingual coverage? |
| Structure | Does it contain turns, notes, or useful metadata? |
| Size | Is there enough data for benchmarking? |
| Accessibility | Can a user reproduce the download? |
| Stability | Is the dataset likely to remain available? |
| Labels | Does it already contain entity annotations? |
| Transformation burden | How much normalization is required? |

## Licensing rules

For every dataset, create a registry entry containing:

```yaml
name: example_dataset
source_url: ...
license: ...
redistribution_allowed: true|false|unknown
contains_real_pii: false|possible|yes
retrieval_method: manual|script|huggingface|kaggle|other
version: ...
notes: ...
```

If redistribution is not clearly permitted:

- do not commit the raw dataset,
- provide a download/preparation script if permitted,
- document the source and expected checksum/version,
- store only small synthetic fixtures in Git.

## Synthetic PII injection

### Why inject PII

Real PII cannot safely serve as an open benchmark. Injection solves three problems:

1. exact ground-truth spans are known,
2. entity frequency can be controlled,
3. multilingual and edge-case scenarios can be generated intentionally.

### Injection pipeline

```text
base text
  ↓
choose eligible location
  ↓
choose entity template
  ↓
generate synthetic entity
  ↓
render grammatical/contextual phrase
  ↓
record exact start/end span
  ↓
store injection manifest
```

### Ground-truth manifest

Each injection should produce data similar to:

```json
{
  "document_id": "chat_000184",
  "segment_id": "turn_03",
  "entity_type": "PHONE",
  "start": 41,
  "end": 58,
  "synthetic_value_id": "phone_0081",
  "language": "en",
  "injection_rule": "callback_request_v2",
  "seed": 42
}
```

Raw synthetic values do not need to be repeated across every audit layer if the exact source benchmark text already contains them.

## Entity generation

### Person names

Generate culturally plausible names by language/locale. Avoid using real-user lists scraped from private sources.

Consider:

- single given name,
- given + surname,
- multiple surnames,
- apostrophes,
- hyphens,
- diacritics,
- transliteration variants,
- all-uppercase forms,
- lowercase/noisy chat forms.

### Email

Use reserved/synthetic-safe domains wherever possible, for example `example.com`, `example.org`, or clearly fictional domains.

Patterns:

- firstname.lastname,
- initials,
- numeric suffix,
- mixed case,
- surrounding punctuation.

### Phone

Generate fictional numbers or non-routable ranges where feasible. Tests should cover:

- `+country` format,
- spaces,
- dashes,
- parentheses,
- local format,
- extensions.

### Address

Use synthetic addresses. Include:

- street number + street,
- apartment/unit,
- postal code,
- city,
- country,
- abbreviated and multiline forms.

Address generation should be locale-aware because ordering differs across countries.

## Negative examples

The benchmark must include strings that look sensitive but should remain.

Examples:

- ticket numbers,
- order IDs,
- incident IDs,
- machine names,
- KB article identifiers,
- timestamps,
- model numbers,
- version numbers,
- department names,
- generic role labels.

This is essential for measuring over-redaction.

## Difficulty tiers

Create benchmark tiers.

### Tier 1: clean

```text
Please email Maria Rossi at maria.rossi@example.com.
```

### Tier 2: noisy

```text
pls call maria r. on +30-210-000-0000 thx
```

### Tier 3: structured

```text
Mobile number: +30 210 000 0000
Machine name: DEMO-PC-43
```

### Tier 4: transcript

```text
10:41:08 - Guest: My name is Maria Rossi.
```

### Tier 5: multilingual / code-switching

One message may contain a Greek greeting, English support terminology, and a Latin-script email address.

### Tier 6: ambiguous

Words that may be names in one context and common nouns or product names in another.

## Benchmark splits

Suggested deterministic splits:

- development: 20%
- validation/calibration: 20%
- final test: 60%

For a pure rules/provider comparison without model training, a simpler dev/test split may be sufficient.

Never tune thresholds repeatedly on the final test split.

## Public demo packs

A strong portfolio release could contain three preparation pipelines:

### `support_tickets`

Plain and semi-structured support text.

### `support_conversations`

Agent/customer turns rendered into multiple transcript formats.

### `incident_notes` — delivered as something else (ADR-0022)

Incident metadata combined with generated work-note histories. **This family has no
public source**, which is why it is not a pack: `demo/registry.yaml` is the licence
record for public corpora, and a source-less entry there would say nothing true. It
ships instead as a *generated over-redaction stress corpus* at
`tests/fixtures/incidents/`, carrying no realism claim and never quoted beside the
packs. See ADR-0022, including the two findings it produced immediately.

The first two create structurally different challenges while using the same PII
engine; the third tests whether operational identifiers survive it.

## Data volume targets

Initial development fixture:

- 100-500 rows

Portfolio demo:

- 10,000-50,000 rows

Performance benchmark:

- 100,000+ text fields or a configurable multiplier

Large volume should be generated from source data rather than committed to Git.

## Dataset provenance table

The project should eventually produce a Delta table or local manifest like:

```text
dataset_name
source_name
source_version
license
retrieval_date
transformation_version
contains_real_pii
synthetic_injection_version
row_count
language_distribution
```

## As built (session 6, Increment D)

This document is the policy; what implements it:

| requirement above | where it lives |
|---|---|
| registry entry per dataset | `demo/registry.yaml`, loaded and validated by `pii_reduction.synthetic.registry` |
| "do not commit the raw dataset" | `data/downloads/` and `demo/packs/` are gitignored; packs are rebuilt |
| "document the source and expected checksum/version" | the `retrieval:` block — repository, full commit revision, per-file SHA-256 and byte count (ADR-0017) |
| injection pipeline and manifest | `pii_reduction.synthetic.injection`, spans recorded as the text is assembled |
| transformation performed before use | recorded per pack in its `meta.json`, and in the registry notes |

Three packs are built (`pii_reduction.synthetic.packs`): `support_tickets` and
`support_conversations` from Bitext, `multilingual_utterances` from MASSIVE de/el.
`incident_notes` is **not** among them and never will be — it has no public source,
so ADR-0022 delivers it as a generated stress corpus outside the pack machinery.

Two decisions worth reading before extending this:

- **ADR-0017** — files are fetched directly at a pinned revision and checked against a
  recorded digest, rather than through the `datasets` library. A checksum is what makes
  "reproducible from documented commands" something the code asserts on every run.
- **ADR-0018** — MultiWOZ 2.2 was rejected after its published utterance text turned out
  to carry real Cambridge landlines and postcodes. `contains_real_pii: false` had been
  recorded for it and was wrong, which is the case this whole document exists for: a
  provenance record is a claim someone made, and a green test suite checks only that the
  registry agrees with itself.

The registry keeps rejected datasets with their reasons, so a later session finds a
decision rather than a gap.

## Privacy rule

The fact that a dataset is publicly downloadable does not automatically make it appropriate to republish. The repository should prefer public-safe, licensed, synthetic, or explicitly de-identified sources and document the decision.

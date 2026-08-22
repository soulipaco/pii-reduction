# Alternative-implementation reconciliation

A second implementation of this problem exists. It was built and run between
2026-08-17 and 2026-08-18 against a real 45,366-row ServiceNow/chat workbook, on
Databricks serverless, by a different author to a different design, and it shipped a
transfer pack — `..\pii_alternative\project_reference_handsoff\` — explicitly written
for "a different repo with a different design". Session 12 (2026-08-21/22) compared
this repository against it and implemented what the comparison justified.

**This is not session 9 again.** `docs/17_EXTERNAL_REVIEW_RECONCILIATION.md` reconciled
two *assessments of this repository* by readers who had executed nothing. This is a
comparison against a *working system with its own corpus and its own measured
history*, and the failure mode is different: the risk there was absorbing a critique,
the risk here is absorbing an architecture. The pack itself says so — its
`ADOPTION_CHECKLIST.md` has a Part 3 headed "Do NOT copy", and its README states "no
claim that this design is right".

## How this comparison was conducted

- **Everything under `project_reference_handsoff/` was read**, in the order its README
  prescribes: the brief, the checklist, all nine knowledge files, all eleven portable
  modules, the five reference-data files and the four source documents.
- **Every transferable claim was checked against this repository's code**, not against
  its documentation. Where a probe was needed it was run
  (`entities/reconcile.py` overlap behaviour, `config/models.py` YAML-boolean handling,
  `outputs/local.py` dependency timing, taxonomy priorities).
- **The private workbook was never opened.** `openpyxl` is not installed and is not a
  dependency, no Excel source adapter exists, and none was added. Every figure quoted
  from the alternative below comes from its own sanitized, counts-only reports.
  Nothing from that workbook — no value, no fragment, no offset — is in this
  repository.
- **Nothing was copied.** No portable module was imported, vendored or pasted. Where an
  idea was adopted it was rebuilt against this repository's typed contracts, and the
  places where the rebuild deliberately behaves *differently* are named below.
- **Example names were checked.** The alternative's prose uses person names from its
  own corpus, and its `knowledge/01` §4.2 states those are real agent names. None of
  them appears anywhere in this repository; every fixture added here uses this
  project's own synthetic pool (`synthetic/values.py`).

The alternative's portable smoke test was **not** run. Its dependencies are unknown,
`.venv` is not the place to discover them, and a passing smoke test would in any case
prove only that the alternative's code works in the alternative's shape — which is not
the question this comparison asks.

---

## 1. What landed

Four changes, in the order they were built. Every one of them was measured against all
41 benchmark gates before and after: **41/41 pass and no published number moved.**

### A1 — Markup is machine syntax (ADR-0027) · **the highest-value item in the pack**

**The evidence.** The alternative's single most damaging detection failure, and the one
its own README ranks first: spaCy has no notion of markup, reads `[code]<div` as running
prose and returns it as a **PERSON at 0.85** — the same recognizer constant a real name
carries, so no threshold separates them. Redaction then destroyed the tag. Measured on
its first full run, before the guard existed: 384 note cells lost a `[code]` tag, 1,263
transcript cells lost a bracket to a location span covering a URL, **blast radius 2,687
of 105,279 processed cells**. Its sanitized corpus profile records **html/code markup in
72% of non-empty `Comments and Work notes` cells** on its largest sheet.

**Does the same failure mode exist here? Yes, and nothing here could see it.**

- The parser/reconstructor contract makes everything *outside* a processable segment
  structurally unreachable — and this damage is *inside* one. A note body containing
  quoted HTML is correctly offered for scanning.
- `over_redaction_rate` counts configured **protected tokens** (ticket ids, machine
  names, asset codes). A `<div>` is not one, so the metric is blind to it.
- **No corpus in this repository contains markup** — not the committed corpus, not the
  three demo packs, not the incident stress corpus. The failure class had zero support
  in every number this project publishes.

And it is not hypothetical here: ADR-0025 makes Azure Databricks the primary target and
names ServiceNow/case descriptions as the data, while `docs/18`'s runbook tells an
operator to point a dataset config at exactly such a column.

**What was built.** Two halves, deliberately by different means — the guard at the
provider boundary (`BaseProvider._clip_out_of_markup`, `patterns.markup_regions`) and an
independently written output assertion (`processing/fidelity.py`, wired to
`validation.require_markup_preserved`, on by default). Full reasoning in ADR-0027.

**Three ways the rebuild differs from the alternative, each deliberate:**

| | alternative | here | why |
|---|---|---|---|
| fragments kept | the longest one | **every** one | `_bound_to_line` already settled this (ADR-0016): a name split by a tag is a name on both sides, and keeping the longer half leaks the other — invisible to `leakage_rate`, which matches only the exact full surface |
| exempt types | a hard-coded pair | a taxonomy fact (`EntityDefinition.format_defined`) | the same shape as `surface_may_span_lines`; a per-layer list is how two definitions drift |
| plausibility drops | applied to every span in a markup-bearing cell | only to a surface the markup **produced** | the vocabulary holds attribute names as well as tags and several are real surnames (`Small`, `Link`, `Name`), and an ADDRESS surface is legitimately digit-only; judging an untouched span by either test deletes a real entity |
| what counts as a tag | any bracketed word run | a **known** element name | `<Grace Okafor>` is a chat display name, not a tag, and reading it as one discarded the span and leaked the name. The cost — an unknown dialect loses its protection from over-redaction — is the trade this project makes everywhere else |
| a span wholly inside a region | discarded | judged, and kept unless its own surface is syntax | a name in a URL path clips to nothing; dropping it leaks it, redacting it damages a URL, and this project takes the visible error |
| chat-client bracketed links | included | **not transferred** | corpus-specific (`@Name[/vd.php?id=..|123]`), and the alternation most likely to swallow a bracketed email address |

**Both required reviewers found this guard leaking, in three variants of one mistake**,
and the fixes are part of what shipped. A guard against over-redaction that causes
under-redaction has made the trade backwards, and none of the three was visible to a
corpus, a gate or a metric — they were found by reading the diff against the doctrine
it claimed to follow. In short: a bracketed display name (`<Grace Okafor>`) was read as
a tag and the span discarded; a name inside a URL path was discarded for the same "no
fragments left" reason; and an untouched quoted surname or digit-only ADDRESS was
deleted because the "did the clip shorten this?" flag was computed *after* the
punctuation trim. ADR-0027's decisions 4 and 5 and its *What the two reviews changed*
section carry the detail. On a real ServiceNow column — where a URL somewhere in the
cell is near-universal — the third would have removed candidates silently on most rows.

**Now measured.** The guard was exercised by 50 synthetic unit tests and nothing else
when it shipped; ADR-0029 gave it a corpus in the same session
(`configs/markup_gates.yaml`, both chains). Their PERSON/ADDRESS/EMAIL trade is still
*their* number on *their* data and is not adopted as one here. The alternative's own
numbers for what its guard cost and bought —
PERSON −3.3%, ADDRESS −1.6%, EMAIL +42, PHONE +41 — are *its* measurement on *its*
data and are **not adopted as a number here**; Reproducing them would need a corpus
shaped like theirs; `tests/fixtures/markup/` measures the same guard on ours, and found
something their catalogue does not contain (§9, item 1).

### A2 — Delta refuses the column names ServiceNow produces

**The evidence.** `DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES`, item 17 in the
alternative's failure catalog. Delta rejects `` ,;{}()\n\t= `` in a column name unless
column mapping is enabled, and every ServiceNow export column has a space in it.

**Does it exist here? Yes, and it would have hit on the first real run.** Every fixture,
corpus, config example and test column in this repository is a plain identifier, so
nothing had ever written such a name. `docs/18` §2 invites an operator to name their own
column; `loader.py:348` derives the output column as `<column><output_suffix>`, so the
sibling carries the space too; `DeltaTableOutput.write` then called `saveAsTable` with no
column-mapping option. The runbook's day-one path failed.

**What was built.** `needs_column_mapping()` plus the three Delta options, set **only
when a column in the frame actually needs them** — column mapping raises the table's
reader/writer protocol version, which older readers cannot open, and that is a price for
making a write possible rather than a default. This is the same kind of translation the
adapter already performs for `errorifexists` → `error`, and it sits in the same file for
the same reason (ADR-0004's shape: client-specific spellings stop at the adapter).

Renaming was the alternative's rejected alternative and is rejected here too, for the
reason it gives: configuration addresses columns by their real names and the reduced
sibling is derived from that name, so a rename ripples into the dataset config and into
the output contract.

**Not verified on a workspace.** The option plumbing is unit-tested against a recording
session. No Databricks run has written such a column, and none is claimed.

### A3 — Recall is decomposed into what the detector was offered (ADR-0028)

**The evidence, and it is the pack's most quotable number.** A whole-cell "did an email
survive?" check reported **8,346 of 8,442 cells** as recall failures on a ServiceNow
journal column. Decomposed against the regions the parser is *required* to preserve:
**17,669 occurrences sat in a preserved note header**, and genuine body-level misses
numbered **24**. A ~500× reading error, in the direction that invites someone to "fix" a
system working as specified.

**Does it exist here? Yes, on a corpus this repository already ships.** The
incident-notes stress corpus (ADR-0022) puts the work-note author in the speaker prefix,
which `TranscriptParser` marks as structure. ADR-0022 already *said* those names "cannot
be redacted by any provider or repair rule" — and that fact appeared nowhere in the
metric grain. A reader saw tier-4 PERSON recall 0.000 and had no way to tell a scope
decision from a detection failure.

**What was built.** `is_reachable` / `reachability_metrics` in `evaluation/`, and two
additive rows on every benchmark run: `unreachable_entity_rate` and
`reachable_strict_recall`. Measured:

| corpus | chain | unreachable | strict recall | reachable strict recall |
|---|---|---|---|---|
| committed benchmark corpus | either | **0 / 180** | as published | identical |
| `tests/fixtures/incidents` | `deterministic_only` | 90 / 315 (0.286) | 0.571 | **0.800** |
| `tests/fixtures/incidents` | `deterministic_presidio` | 90 / 315 (0.286) | 0.711 | **0.996** |

**On the hybrid chain the engine finds 224 of the 225 entities it was ever offered.**
PERSON recall 0.326 over 135 is 44 of the 45 PERSON entities that reach a provider at
all. The gap between 0.711 and 0.996 is the speaker-prefix question, which now has a
number attached instead of a footnote — and **that number is what made the question
answerable in session 13** (ADR-0032): flipping `preserve_prefix` takes the 90
unreachable to 0, which is this metric confirming its own attribution.

**The alternative's own first option was rejected**: it suggests *scoping* the recall
metric to eligible regions. That would silently change what every published number
means, and `AGENTS.md` forbids moving a number without re-running it. Reporting both
leaves the existing numbers exactly as measured — 41/41 gates unchanged.

The benchmark corpus reporting 0 unreachable is not luck: the injector places entities
at `eligible_offsets`, which is restricted to a parser's processable regions. That
property is now asserted, so a future drift between corpus and parser configuration
fails a test instead of quietly turning every recall number into a blend.

### A4 — The parquet engine is checked before the run, not after it

**The evidence.** A one-line aside in the alternative's failure catalog §18: `pyarrow`
missing at write time killed a run after **18 minutes** of compute.

**Does it exist here? It did.** `ParquetOutput.write` raised a perfectly good error
message — at write time, after every document had been detected and reduced. The
pipeline builds its output adapter before it reads a row, so moving the check into the
constructor turns an 18-minute failure into a first-second one. Five lines and a test.

---

## 2. Already covered, verified against the code

Each of these is something the pack recommends and this repository already does. Listed
because "we already do that" is a claim that has to be checked, and three of them were
checked by probe rather than by reading.

| # | pack item | state here |
|---|---|---|
| B1 | **Offsets, never rewritten text** — "the single highest-leverage decision in the whole project" | Identical and load-bearing. `EntityMatch`/`ResolvedEntity` carry `(start, end, type, score, provider, recognizer, language)`; reducers splice into the original string; parsers return segments with `source_start`/`source_end`. Byte-exact round-trip is a test invariant. |
| B2 | **Shared entity vocabulary, provider-native labels mapped at the boundary** | ADR-0004, and stricter: a native label may travel only as `metadata["native_label"]` provenance, and `docs/04` names that carve-out explicitly. |
| B3 | **One overlap-resolution rule for every source; no "gazetteer wins"** | Same principle, different rule — see §3.1. Both of the failures that made it non-negotiable for them are impossible here, verified by probe. |
| B4 | **Clip every span to its first line** | ADR-0016, shipped since session 5, and stronger: *every* fragment is kept rather than the first, because a hard-wrapped name is split rather than merely overrun. |
| B5 | **A digit floor so a postcode is not a phone number** | Different mechanism, same outcome. `phonenumbers` at `Leniency.VALID` plus `_has_clean_boundaries`; measured at **over-redaction 0.000 over 585 protected tokens across seven identifier kinds** on the incident corpus. Their floor of 8 is a constant tuned to their corpus; this is a validator plus a boundary rule. |
| B6 | **Reject unknown configuration keys** | `ConfigModel.model_config = ConfigDict(frozen=True, extra="forbid")` — every config model, not just the parser block. |
| B7 | **Reject YAML-boolean language codes (`no` → `False`)** | Already impossible. Probed: pydantic v2 refuses `False` where `str` is required, so `supported: [en, no, de]` fails at load with `supported.1 · Input should be a valid string`. Loud, not silent. The message does not say "quote it", which is the only thing lost. |
| B8 | **`SystemExit: 0` marks a successful serverless run as FAILED** | Found independently by session 10's P3 hardening, from real job runs, and fixed in **both** directions — the wrapper raises only on a non-zero code, and both directions were re-confirmed against real jobs. |
| B9 | **Verify a model install landed; never trust `spacy download`'s exit code** | `docs/18` §1 already carries a stronger version, found independently: the uv/pip target trap, direct wheel URLs, **SHA-256 pins in `.github/spacy-models.sha256`**, and a `spacy.load` confirmation step. |
| B10 | **Models loaded once per worker, never per row** | `_ENGINE_CACHE` per model configuration, plus a `mapInPandas` worker cache keyed on run id + config hash, asserted by default-tier tests that drive the partition function with plain iterators. `docs/07` names per-row construction as the anti-pattern. |
| B11 | **The audit trail records offsets and types, never surfaces; `include_surface` stays off** | Stronger: `AUDIT_COLUMNS` is a **closed set with no surface field at all**, asserted as an exact set, and since session 11 span offsets and per-entity confidence are governed like reduced output rather than as safe metadata (`docs/09`). |
| B12 | **A `combined` output table is as sensitive as the source** | ADR-0024's reduced-only projection plus `docs/09`'s grant model, and the confused combination with in-place replacement is refused at config validation. |
| B13 | **Scope boundary: four types in; ids, tickets, machines, dates out** | Identical, and enforced three ways — the closed taxonomy, `AGENTS.md` rule 7, and a gated over-redaction metric with a purpose-built stress corpus behind it (ADR-0022). |
| B14 | **`de/fr/it/es/pt` models emit only `PER/LOC/ORG/MISC`; Presidio discards `MISC`** | Both already measured here and recorded in ADR-0019 and ADR-0020, with the additional finding that `MISC` is dropped *inside Presidio*, before this project's adapter. |
| B15 | **Land sources as Delta, not Excel — the driver-side parse caps throughput** | Their open item #1 is this repository's shipped design: Excel is deferred (`docs/06`), and `SparkTableSource` reads a UC table directly. |
| B16 | **Phone regions: fewer is faster** | Coincidental agreement — this repository ships exactly four regions plus a region-less pass. Their 23→4 finding is about Presidio's `PhoneRecognizer` re-scanning per region; this provider calls `phonenumbers` directly. |
| B17 | **`monotonically_increasing_id()` moves between passes and attaches entities to the wrong row** | Cannot occur: row identity is a configured `row_id` column validated for uniqueness and nullity, and run identity is driver-generated and part of the worker cache key. |
| B18 | **A reference-run oracle to diff against** | Covered by three things rather than a kept parquet: 41 regression gates whose values must equal the published tables, a CI check that `build-corpus` reproduces the committed corpus byte for byte, and the Databricks parity test comparing reduced-column hashes between workspace and local. |
| B19 | **Parser fallbacks are the most useful counter you have** | `RunMetrics.parser_fallbacks` is a per-reason counter already in run metrics and in the written metrics table. |

---

## 3. Where the two disagree on a fact

Settled against the code, as the brief requires.

### 3.1 "Longest span wins" is *not* the only correct overlap rule

The pack states this twice and calls it non-negotiable: "There is exactly one correct
way to combine detections from several sources, and it is not 'gazetteer wins' or
'model wins'. Longest span wins; ties break by type specificity."

This repository ranks by **entity priority, then chain order, then score, then length,
then position** (ADR-0005, `entities/reconcile.py`). Score never crosses providers,
because provider scores are recognizer constants rather than calibrated probabilities.

**Both of the failures that made their rule non-negotiable are impossible here**,
verified by probe rather than argued:

| their failure | here |
|---|---|
| a gazetteer surname inside that person's email produced `<PERSON>.5@…` — "a redaction that leaks the address it was meant to remove" | EMAIL priority 100 beats PERSON 50, so the EMAIL span wins and the whole address is replaced. Probed: the PERSON candidate is rejected with reason `overlap`. |
| spaCy tags a phone number as PERSON at 0.85, so the span is labelled wrongly | PHONE priority 90 beats PERSON 50; the span is labelled `PHONE`. Same outcome, from priority rather than from type specificity. |

**One asymmetry does remain, and it is recorded rather than dismissed.** Where a
*longer* low-priority span contains a *shorter* high-priority one — a PERSON span
covering `Maria maria@example.com` — their rule redacts everything, while this
reconciler accepts the EMAIL and rejects the containing PERSON, leaving the leading name
in the output. Probed and confirmed. Three things bound it: no such case appears in any
measured corpus (leakage and PERSON precision/recall are gated on both chains), the
repository is already aware of the mechanism (`BaseProvider._extend_left`'s docstring
reasons about exactly this and returns both spans to defend against it), and the fix —
splitting an outer span around an inner winner — changes reconciliation semantics and
would need its own measurement. **Deferred, with the condition in §4.**

### 3.2 "The offset invariant protects you"

The pack's `knowledge/02` says the invariant "was assumed to and it does not" protect
against damage inside an eligible region. **The alternative is right, and this
repository was making the same assumption.** That is item A1, and it is the single
most valuable thing this comparison produced.

### 3.3 `ADDRESS` composed from `LOCATION`/`GPE`/`LOC`/`FAC`

The alternative maps all four onto `ADDRESS` and accepts that "a bare city or country
mention is redacted too", then needs a per-row protected-terms list to stop
`department <Company>` becoming `department <ADDRESS>`.

ADR-0002 refused exactly this composition here, on probe evidence, and left ADDRESS in
the taxonomy undetected until a capable provider exists. **Their experience corroborates
the decision rather than challenging it**: the compensating machinery they had to build
is the cost ADR-0002 declined to pay. Nothing changes.

---

## 4. Deferred, with the condition that reopens each

Every one of these is a real capability this repository lacks. None was adopted, and
each says what would have to be true.

| # | item | why not now | reopens when |
|---|---|---|---|
| D1 | **Case augmentation** — a second NER pass over `text.title()`, trusted only where the original span was ≥60% uppercase, gated on two adjacent uppercase-dominant words | The strongest *detection* idea in the pack, and unmeasurable here: **no corpus in this repository contains an ALL-CAPS name**, so adopting it would ship an unmeasured recall change with corpus-tuned constants (0.6, run length 2) copied wholesale — which the brief and `patterns.py`'s own doctrine forbid. It also doubles detection cost, which ADR-0015 (CPU-only) makes a real price. | A corpus slice with ALL-CAPS names exists and the whole-corpus effect on precision, recall and over-redaction is measured on both chains. **This is §5's recommended next increment.** |
| D2 | **Row-scoped gazetteer** — each row's identity columns (`Opened for`, `Caller`, `Assigned to`) become a per-row dictionary of known people | "Free recall from data the row already carries", and the only thing that catches a bare name on a continuation line. The architecture already supports it — `FieldProcessor.process` receives the whole `row` — so this is a provider plus configuration, not a redesign. Not adopted because it is a **new detection capability** and this repository does not ship detection changes it cannot measure: no corpus here has identity columns. It also needs an ADR (a per-row provider is a new provider shape) and careful scoping so real column names never reach core logic. | A corpus with identity columns exists, or a real-data run can be measured. Pairs with D3. |
| D3 | **Protected terms** — columns naming organisations are never redacted | The mirror of D2 and cheaper, but it presupposes D2's configuration surface. Partially covered already by the identifier guard and the gated over-redaction metric, which is why it is second rather than first. | With D2. |
| D4 | **Per-segment language detection** | The evidence is strong and specific: **43–46% of their transcript cells contain more than one language**, so per-cell detection routes half the corpus through the wrong model. This repository detects per *field* and has carried that as a known deferral since Increment C. Not adopted because **no corpus here can measure it** — every synthetic document is single-language by construction, so the change would be unmeasurable in either direction while touching language routing, the metric grain and the run-metrics contract. | A code-switching corpus exists. The alternative's percentage is now the evidence that this deferral matters, which it did not have before. |
| D5 | **Join a cell's segments per (cell, language) before inference** — measured at 4.7× on transcripts | This is P5 (batching) with a specific design attached, and P5 is already queued. Worth taking *with* its three Spark rules (D6). | P5 is picked up. |
| D6 | **`repartition(n, row_id)`, an explicit `sort_values([row_id, segment_index])`, and Delta-landed intermediates** | **Not applicable today and dangerous tomorrow.** This repository's distributed path is row-at-a-time `mapInPandas`; no segment is ever joined across rows, so partitioning cannot change the answer. All three become live the moment D5 exists — and all three produced *successful, clean-looking runs with wrong output* for them, in ~50% of cells. | D5. Recorded here so P5 does not rediscover them. |
| D7 | **Language-partitioned execution** — three passes split where the memory is spent | The memory budget behind it is now in `docs/07` (§ below). The execution shape is not adopted: the distributed path here is blocked by `ISOLATION_STARTUP_FAILURE`, the driver path loads models on one node with ordinary driver memory, and a three-pass design would be a second implementation of the pipeline — `AGENTS.md` rule 10 and ADR-0025's parity contract. | The serverless sandbox incident closes **and** a multilingual workload actually OOMs. |
| D8 | **A shape-only source profiler** (`% of characters eligible`, parser fallback rate, language mix per segment, `% of cells with >1 language`, folded structural signatures) | "Those four numbers determine most of the design", and it is metadata-only by construction so it is privacy-safe by design. A real gap: `docs/18` §2 asks an operator to describe their table with no tool to inspect it. Not adopted this session because it is a new CLI surface with its own output contract, and three other items had stronger evidence. | Recommended in §5 as the second increment — it is the one that would make a real-data run *safe to plan*. |
| D9 | **Split an outer span around a contained higher-priority winner** (§3.1's residual asymmetry) | Changes reconciliation semantics; unmeasured; no corpus exhibits it. | A measured case appears, on any corpus. |
| D10 | **An international-phone pattern** (`+`/`00` + 8–15 digits) beside the validating library | Their motivation is malformed source values a validator legitimately rejects. Here, `phonenumbers` at VALID leniency scores **1.000 precision and recall on 1,600 entities** across three languages and two scripts in public prose. Adding a looser pattern would trade measured precision for unmeasured recall. | A real-data run shows `+`-prefixed numbers surviving. |
| D11 | **A bounded LRU on language detection (50,000 entries)** | Solves a problem this repository does not have: there is no detection cache to bound. Their unbounded one cost ~230 MB and crossed a serverless cap. | A cache is introduced — at which point the bound arrives with it, not after. |
| D12 | **Disable unused spaCy pipes** | Part of a measured 4.8× win for them, but they configure spaCy directly; here the pipeline is assembled by Presidio's `NlpEngineProvider`, and reaching past it to prune pipes would put spaCy internals inside a provider adapter that exists to keep them out. | A profiled runtime problem, with `docs/07`'s "profile before optimising" rule applied. |

---

## 5. Rejected, with the contract behind each

| # | item | why |
|---|---|---|
| R1 | **The multilingual PERSON denylist** (~150 support-vocabulary terms across eight languages) | A word list tuned to one corpus, in five languages this project does not ship. `patterns.py`'s own doctrine forbids exactly this: "a pattern list tuned to the shapes in the committed corpus would fit the fixture rather than the problem". The *mechanism* is not rejected — an evidence-gated denylist could return with a measurement — but copying the list is corpus tuning under `AGENTS.md`'s benchmark-integrity rule. |
| R2 | **The labelled-address recognizer** (claim the whole value after `Address -`, `Anschrift:`, `διεύθυνση:`) | ADR-0002 refused a regex-composed ADDRESS on probe evidence, and `AGENTS.md` rule 6 forbids treating regex as a complete solution for addresses. Shipping this would put an ADDRESS detector in the taxonomy's undetected slot, poisoning a benchmark column that is deliberately empty. Reopens at roadmap Phase 7 with a capable provider, not before. |
| R3 | **A `PII` type for untyped spans** | It exists so a provider that emits typeless spans (`ai_mask`) is not filtered away. No provider here emits one, and the taxonomy is closed by design — `AGENTS.md` rule 7 forbids widening it. Reopens only with an LLM provider, and then as its own ADR. |
| R4 | **The `surname.5` employee-id recognizer, off by default** | Their owner's ruling on their corpus. This project's taxonomy has no employee-id concept and its scope is configuration-driven. |
| R5 | **Their two ruled policy decisions as policy** (bare usernames stay unredacted; speaker labels and note authors stay preserved) | Not this project's rulings to inherit — a different owner, a different brief, a different corpus. **But the second was real evidence for an open question here**: this repository's speaker-prefix ADR was undecided, and a production deployment choosing "preserve", with the consequence measured (17,669 preserved-header occurrences against 24 body misses), is input that ADR should weigh. Recorded as input, explicitly not as a decision. **ADR-0032 (session 13) weighed it and reached the same default from its own measurement**, for a reason that is this repository's rather than theirs: the error the opt-in introduces — destroyed structure — is the one our instrumentation cannot see. |
| R6 | **`ai_mask` as a provider** | Not a rejection of their finding — an endorsement of it. They measured it against real data: no types, no offsets, **not reproducible** (the same 7-digit id masked in one row and kept in another), masked out-of-scope ids unprompted, missed a guest's first name in six consecutive German turns, and produced `[MASKED].5@…` — a redaction that leaks the address it was meant to remove. This repository never considered it; the measurement is recorded here so nobody proposes it without reading this row. Note their honest caveat: **asking a model for JSON spans with offsets was never tried**, and is a materially different design. |
| R7 | **cp38 wheel pins and `--only-binary=:all:`** | Environment-specific to a Python 3.8.8 Anaconda box with no C++ toolchain. This project requires 3.11+ and CI provisions its own environment. |
| R8 | **The module layout, the ABC + registry pattern, the YAML schema, the parsers, `mode: combined`/`split`, sheet-name normalisation** | The pack's own Part 3 says not to copy these, and it is right. |

---

## 6. Recorded as knowledge, not as code

Two things transferred as documentation because they are expensive to rediscover and
cheap to write down.

**The serverless memory budget** → `docs/07`, *Serverless worker memory, as measured
elsewhere*. 216 MB gone before user code runs, ~1.15 GB usable ceiling, +242 MB for the
first spaCy pipeline, **+294 MB for each additional language**, +511 MB for lingua at 20
languages. Probed by allocating in 64 MB steps and logging to a volume, because a cgroup
OOM kill leaves no exception behind and surfaces only as a bare `UDF_PYSPARK_ERROR.OOM`.
Recorded with its provenance and with the warning that these are **their numbers on
their runtime, not a platform guarantee** — and with the observation that matters here:
this project's distributed path builds one pipeline per worker for the whole configured
chain, which on the shipped three-language configuration is exactly the shape that
budget forbids. It has never been reached, because the sandbox incident blocks it first.

**Column names, and what to do when a run goes wrong** → `docs/18` §2 and §8, two new
rows in the troubleshooting table.

Two further environment facts are noted without action: their corporate policy blocks
both git and the Databricks CLI, so they deploy over the Workspace Import REST API. This
repository's `bundle deploy` is blocked by a CLI bug and the owner's organisation is
known to restrict the CLI, so a REST route is a **third** option beside the workspace UI
for the hosting increment — recorded in the plan's pickup list rather than built. And
their **"re-push before every job run"** warning (a stale workspace copy silently ran a
build from before the markup fix) applies to any non-bundle deployment route.

---

## 7. The decision table

| ref | item | classification |
|---|---|---|
| A1 | Markup guard + independent output check | **ADOPTED** (ADR-0027) |
| A2 | Delta column mapping for refused column names | **ADOPTED** |
| A3 | Reachability decomposition of recall | **ADOPTED** (ADR-0028) |
| A4 | Parquet engine preflight | **ADOPTED** |
| B1–B19 | Offsets contract · label mapping · one overlap rule · line clipping · phone digit floor · reject unknown config keys · YAML-boolean codes · `SystemExit(0)` · verify model installs · per-worker model caching · audit carries no surface · combined-table sensitivity · scope boundary · coarse label sets · Delta over Excel · phone regions · id stability · reference oracle · parser-fallback counter | **ALREADY IMPLEMENTED EQUIVALENTLY** (19 items, each verified) |
| 3.1 | "Longest span wins is the only correct rule" | **DISPUTED** — both motivating failures impossible here; one residual asymmetry recorded as D9 |
| 3.2 | "The offset invariant does not protect the inside of an eligible region" | **CONFIRMED — they are right**; became A1 |
| 3.3 | ADDRESS composed from `LOC`/`GPE`/`FAC` | **INCOMPATIBLE** (ADR-0002); their experience corroborates the refusal |
| D1 | Case augmentation | **DEFERRED** — no ALL-CAPS corpus to measure on |
| D2 | Row-scoped gazetteer | **DEFERRED** — new detection capability, no corpus |
| D3 | Protected terms | **DEFERRED** — with D2 |
| D4 | Per-segment language detection | **DEFERRED** — unmeasurable on a single-language corpus |
| D5 | Segment joining per (cell, language) | **DEFERRED** — this is P5 |
| D6 | Spark partitioning/ordering/landing rules | **NOT APPLICABLE**, becomes live with D5 |
| D7 | Language-partitioned execution | **DEFERRED** — sandbox blocked; would be a second implementation |
| D8 | Shape-only source profiler | **DEFERRED** — recommended next-but-one |
| D9 | Split an outer span around a contained winner | **DEFERRED** — unmeasured |
| D10 | International-phone pattern | **INSUFFICIENTLY EVIDENCED here** — 1.000/1.000 measured without it |
| D11 | Bounded LRU on the language cache | **NOT APPLICABLE** — no cache exists |
| D12 | Disable unused spaCy pipes | **DEFERRED** — would put spaCy internals past the adapter |
| R1 | PERSON denylist | **REJECTED** — corpus-tuned word list |
| R2 | Labelled-address recognizer | **REJECTED** — ADR-0002, `AGENTS.md` rule 6 |
| R3 | `PII` untyped-span type | **REJECTED** — closed taxonomy, rule 7 |
| R4 | `surname.5` recognizer | **REJECTED** — no such concept here |
| R5 | Their two ruled policy decisions | **NOT INHERITED** — recorded as input to the speaker-prefix ADR, which ADR-0032 then decided the same way from its own evidence |
| R6 | `ai_mask` as a provider | **REJECTED**, on their measurement |
| R7 | cp38 pins, wheels-only pip | **ENVIRONMENT-SPECIFIC** |
| R8 | Module layout, registries, YAML schema, parsers, output modes | **NOT TRANSFERABLE** — the pack says so itself |
| §6 | Serverless memory budget; column-name and install traps; REST deployment route; re-push warning | **RECORDED AS DOCUMENTATION** |

**Totals: 4 adopted · 19 already covered · 9 deferred with conditions · 8 rejected ·
1 disputed · 1 confirmed against us · 4 recorded as documentation.**

---

## 8. What this comparison did not do

- **It did not open the workbook.** No structural claim required it; the sanitized
  reference-data reports answered every question that mattered, and the two figures
  quoted from them (72% markup share, the recall decomposition) are percentages and
  counts.
- **It did not run the alternative's code.** See the method note above.
- **It did not move a benchmark number.** All 41 gates were re-run after every
  increment and after the last one: 10/10, 15/15, 6/6, 10/10.
- **It did not touch Databricks.** A2's option plumbing is unit-tested and unverified on
  a workspace, and this document says so wherever the claim appears.
- **It did not settle the speaker-prefix question**, which A3 measured rather than
  answered. *(Settled in session 13 by ADR-0032, on that measurement.)*

## 9. What to do next, ranked by the evidence this comparison produced

1. ~~**A markup-bearing synthetic corpus slice**~~ — **done in this session**
   (ADR-0029, `tests/fixtures/markup/`), and it repaid the cost immediately by finding
   something the alternative's own catalogue does not contain: **markup destroys PERSON
   recall**, 0.322 against 0.821 on the committed corpus, because the model returns no
   span at all on markup-dense clauses. Their twenty failures record only the
   false-positive direction — a tag returned as a name. This is the leak direction, and
   it is upstream of every remedy either project built. **The replacement for this item
   is the remedy**: strip markup before detection and map the offsets back. That is a
   change to the model's *input*, which plan §8 Q2 measured as trading one error for
   another twice, so it needs its own increment and its own before/after on this
   corpus — which now exists to measure it.
2. **The shape-only source profiler (D8)**, so an operator pointing `docs/18` at a real
   table can see eligible share, parser fallback rate and language mix *before*
   configuring — the four numbers the alternative says determine most of the design,
   and the ones this repository currently asks an operator to guess.
3. **Case augmentation (D1)**, measured on the corpus from step 1 or on its own.
4. **The row-scoped gazetteer and protected terms (D2/D3)**, together, with an ADR.

None of these displaces the session-11 pickup list (plan §8), which resumes with
hosting the service.

# ADR-0032: The speaker prefix stays preserved by default, and naming its people is a per-dataset opt-in that already ships

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 13

## Context

Three documents call this the most serious open design item, and it has been open since
session 8.

`TranscriptParser` classifies `2026-04-03 09:12:04 - Peter Novak:` as **structure**. The
prefix is a non-processable segment, so the name inside it is never handed to a
provider. No provider, threshold, promotion rule, span repair or reduction strategy can
redact it, because nothing was ever offered it.

That is **correct** when a speaker label is a role — `Customer`, `Agent`, `Πελάτης`,
`Automation` — which is the only shape the committed benchmark corpus contains. It is
**wrong** when the author is a person, which is exactly what a ServiceNow work-note
author is (`docs/00` UC-03).

The cost has been measured twice already, from two directions:

- **ADR-0022** built the incident-notes corpus and recorded PERSON strict recall
  **0.000 at tier 4 in all three languages**, against 0.933–1.000 at tier 3 in the same
  documents. It deliberately did not fix it, because fixing a leak in the same change
  that introduces the corpus motivating it is how a benchmark-fitted fix gets built.
- **ADR-0028** decomposed recall and put the exact number on it: **90 of 315 entities
  (0.286) unreachable**, and the entire gap between overall strict recall 0.711 and
  0.996 over the 225 the parser ever offered.

`docs/20` R5 adds one more input, explicitly recorded as input and not as a ruling: the
reference implementation at `..\pii_alternative` — a different owner, a different brief,
a production deployment — faced the same choice and **ruled preserve**, with 17,669
preserved-header occurrences against 24 body misses.

What has been missing is a decision, and one document made the choice look harder than
it is. `docs/06_CONFIGURATION_CONTRACT.md` stated *"there is no configuration that
currently fixes it."* **That was wrong.** `preserve_prefix: false` has shipped on
`TranscriptParser` since Increment A2, is per column, and does exactly this. Nobody had
measured it, so nobody knew what it cost.

## Decision

**Three rulings, none of which changes any shipped default or any published number.**

### 1. The default stays `preserve_prefix: true`

It is the only setting under which `AGENTS.md` rule 5 ("transcript metadata before the
speaker delimiter may be out of scope", "timestamps must not be damaged") and
`README.md`'s success criterion *"transcript reconstruction preserves speaker metadata
exactly"* hold **unconditionally**, for every transcript, without the operator having
to know what shape their speakers are.

Preserving is also the safe direction of the two errors. Preserving a person's name
leaks one span that the corpus, the gates and `unreachable_entity_rate` all report out
loud. Reducing a role label destroys structure that **no metric in this repository can
see** — role labels are not protected tokens, so `over_redaction_rate` stays 0.000
through it (measured below; it does).

### 2. `preserve_prefix: false` is the ruled answer for transcripts whose speakers are people

Not a new mode, not a new parser — the option that already exists, now measured, named
in the configuration contract as the answer to this exact question, and pinned by a
test rather than by prose.

It moves the boundary rather than punching a hole in it: the whole line becomes one
processable body, so the name is offered to a provider through the ordinary path. The
timestamp and separator survive because they are not entities under any shipped policy
— which is a **consequence of the entity policy, not a guarantee of the parser**, and
is stated as such in `docs/06`.

### 3. No third mode is built

"Redact inside the preserved prefix" is rejected. See *Alternatives rejected*.

## What was measured

Hybrid chain (`deterministic_presidio`), full corpora, both configurations differing in
one boolean. Every published number in `docs/14` §8 was reproduced first, so the
baseline column is the shipped one rather than a re-derivation.

### Incident-notes corpus (ADR-0022) — the shape where preserving is wrong

| | `preserve_prefix: true` (shipped) | `preserve_prefix: false` |
|---|---|---|
| strict F1 | 0.761 | **0.844** |
| relaxed F1 | 0.761 | **0.862** |
| leakage rate | 0.289 | **0.114** |
| fragment leakage rate | 0.314 | **0.127** |
| document clean rate | 0.489 | **0.689** |
| over-redaction rate | **0.024** | 0.026 |
| unreachable entities | **90 / 315 (0.286)** | **0 / 315** |
| transcript-slice strict F1 | 0.634 | **0.813** |
| tier-4 PERSON recall — en / de / el | 0.000 / 0.000 / 0.000 | **0.333 / 0.900 / 0.400** |

The unreachable row going to zero is the mechanism confirming itself: ADR-0028's metric
says the 90 were exactly the tier-4 PERSON entities in the prefixes, and flipping the
boolean makes all 90 reachable. Roughly half are then found.

On the **deterministic chain** the same flip moves **nothing** — strict F1 0.727,
leakage 0.429, over-redaction 0.000, identical to three decimals — because that chain
detects no PERSON at all. Only `unreachable_entity_rate` changes, from 0.286 to 0. **The
option buys nothing without a model.**

### Committed benchmark corpus — the shape where preserving is right

| | `preserve_prefix: true` (shipped) | `preserve_prefix: false` |
|---|---|---|
| strict F1 | **0.910** | 0.902 |
| relaxed F1 | **0.921** | 0.918 |
| transcript-slice strict F1 | **0.914** | 0.842 |
| PERSON strict precision | **0.771** | 0.744 |
| PERSON strict recall | 0.821 | 0.821 |
| leakage rate | 0.067 | 0.061 |
| over-redaction rate | 0.000 | 0.000 |

**Recall does not move**, because this corpus's speakers are roles and none of them is
ground truth. The whole delta is false positives.

**And they are not the ones anyone predicted.** The expectation was that role labels
would be redacted. They are not: `Support Agent`, `Guest`, `Automation`, `Πράκτορας`
and `Πελάτης` all survive. Two Greek documents change, and both changes are in the
**body**, upstream of the prefix.

*Synthetic committed fixture, `tests/fixtures/corpus` — generated from a seed
(`synthetic/templates.py`), quoted under the Class A carve-out in `docs/09`:*

```text
- 2026-04-03 11:20:00 - Πράκτορας: Καλημέρα, πώς μπορώ να βοηθήσω;
+ 2026-04-03 11:20:00 - Πράκτορας: <PERSON>, πώς μπορώ να βοηθήσω;

- 2026-04-03 11:20:24 - Πελάτης: Ονομάζομαι Νίκος Αντωνίου, τηλέφωνο <PHONE>.
+ 2026-04-03 11:20:24 - Πελάτης: <PERSON>, τηλέφωνο <PHONE>.
```

Joining the prefix to the body **changes the model's input**, so the Greek chain
returns different spans: `Καλημέρα`
("good morning") becomes a false-positive PERSON, and the span over `Νίκος Αντωνίου`
extends left across `Ονομάζομαι` ("my name is"). Relaxed F1 falls only 0.003 against
strict's 0.008, which is the signature of span-boundary error rather than newly
invented regions.

This is the **same failure class plan §8 Q2 measured twice**: `split_lines` and the
`key_value` parser both traded one error for another by changing what the model saw,
which is why ADR-0016 repairs spans at the provider boundary instead of re-cutting the
input. `preserve_prefix: false` re-cuts the input, so it inherits that risk. It is
offered per column for exactly that reason.

**`over_redaction_rate` is 0.000 on both columns of that table** while two Greek words
are destroyed. The metric counts protected *identifier* tokens; `Καλημέρα` is not one.
That is a real limitation of the metric, recorded here rather than fixed, and it is the
second reason the default is *preserve*: the error the opt-in introduces is the kind
this repository's instrumentation is worst at seeing.

## Consequences

- **Nothing ships differently.** No default changes, no config file changes, all 56
  gates hold at the same floors, and no published number moves. This ADR converts an
  open question into a documented ruling and a measured option.
- **`docs/06` is corrected.** Its "there is no configuration that currently fixes it"
  was false when written. It now names `preserve_prefix: false`, states what it costs
  in both directions, and warns that the timestamp survives because of the entity
  policy rather than because the parser protects it.
- **The README criterion is refined, not weakened.** Byte-exact reconstruction of every
  region the pipeline did not reduce is unconditional and stays so. *"Preserves speaker
  metadata exactly"* holds under the shipped default; an operator who sets
  `preserve_prefix: false` is deliberately trading it for the author's name, and this
  ADR is where that trade is recorded.
- **ADR-0022's tier-4 0.000 rows and ADR-0028's 90 unreachable stop being open items.**
  They are the measured price of a ruled default, and the remedy with its own measured
  price sits beside them.
- **`docs/17` D13's reopening condition is met.** The note-history parser was deferred
  until this decision landed, so that the second would not prejudge the first. It no
  longer blocks; it remains deferred on its own merits.
- **UC-03 becomes reachable by configuration.** `docs/00`'s ServiceNow work-note case
  needed the author redactable; a dataset YAML can now ask for that, at a cost this ADR
  publishes.
- **The reference implementation and this one now agree, from evidence rather than by
  inheritance.** `docs/20` R5 recorded their ruling as input. The measurement here
  reaches the same default for a reason that is ours: the error we would introduce is
  the one our metrics cannot see.

## What would reopen this

- **A metric that sees a destroyed role label.** The default rests partly on the claim
  that reducing structure is invisible here. Make it visible — protected tokens for
  transcript labels, or a structure-preservation check on the prefix region — and the
  asymmetry that justifies *preserve* weakens.
- **A measured remedy for the input-change effect.** ADR-0027's markup guard clips
  spans out of a region at the provider boundary without re-cutting the input. The same
  shape — offer the prefix, then constrain what may be returned from it — would give the
  author's name without the body-context regression. `tests/fixtures/incidents` and
  `tests/fixtures/corpus` measure both directions of it already.
- **A corpus of transcripts whose speakers are people and whose labels are roles in the
  same document.** Everything here separates the two shapes by corpus. A mixed corpus is
  what a per-document decision — as opposed to a per-column one — would need before it
  could be argued for.

## Alternatives rejected

- **Redact inside the preserved prefix (a third parser mode).** It requires running
  detection over a region the parser has declared non-processable, which inverts the
  parser contract that `AGENTS.md` rule 5 and `docs/01` state, and every consumer that
  trusts "the prefix is structure" — reconstruction, the audit table's span
  accounting, `unreachable_entity_rate` — would have to be re-checked against a region
  that is now both. `preserve_prefix: false` reaches the same output by moving the
  boundary instead, and its cost is measured above rather than assumed.
- **Making `preserve_prefix: false` the default.** Rejected with the numbers: transcript
  strict F1 0.914 → 0.842 and PERSON precision 0.771 → 0.744 on the corpus whose
  speakers are roles, for zero recall gain there and zero gain of any kind on the
  model-free chain.
- **A role-vs-person classifier on the speaker label** (gazetteer, heuristic, or the
  provider itself deciding). It is a classifier with no corpus to justify it, and both
  of its errors are bad in ways this ADR has just finished arguing are asymmetric:
  calling a person a role leaks silently, calling a role a person destroys metadata no
  metric here reports. The operator already knows which shape their transcripts have,
  and a per-column boolean asks them once.
- **Leaving it open for another session.** Six sessions of "the most serious open design
  item" produced two measurements and no ruling. The measurements were the hard part and
  they are done.

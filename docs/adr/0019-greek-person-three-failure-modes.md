# ADR-0019: Greek PERSON is three failure modes, not one — and the corpus is not changed to hide them

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 6

## Context

Since ADR-0007 the weak Greek PERSON numbers (strict recall 0.222 / 0.111 / 0.167 /
0.000 by tier) have been recorded as a **licensing** consequence: the good Greek spaCy
models are CC BY-NC-SA and excluded from this MIT project, so Greek routes through
`xx_ent_wiki_sm`. Everything downstream — `docs/15_PROVIDERS.md`, the plan's deferral
list, the README's honesty note — repeats that one-line explanation.

Increment D produced a fact the one-liner cannot absorb. On the
`multilingual_utterances` pack — real Greek written by native speakers for another
purpose — **the same model and the same eight-name pool reach 0.606 strict recall**,
while German reaches 1.000 on the same text. Plan §8 opened Q4 to explain the
difference before spending anything further on Greek, and listed the confounds to
eliminate: tier mix, phrasing, and the shared name pool.

## What was measured

Probes against `xx_ent_wiki_sm` directly, each carrying the same eight committed Greek
names at a known span, recording whether the model returned an exact `PER` span, an
overlapping span, a different label, or nothing. Counts are out of 8.

| carrier | exact PER | wrong label | wrong span | nothing |
|---|---|---|---|---|
| the name alone | 3 | 1 | 2 | **2** |
| `Ο πελάτης είναι {name}.` | **6** | 2 | 0 | 0 |
| synthetic tier-1 #1 (name + email + ticket) | 2 | 1 | 5 | 0 |
| synthetic tier-3 `Από: {name}` | 1 | 1 | 4 | 2 |
| synthetic tier-4 turn (`Ονομάζομαι {name}`) | **0** | 0 | 8 | 0 |
| German `Der Kontoinhaber ist {name}.` | **8** | 0 | 0 | 0 |

**Silence is the minority case: 4 of the 40 Greek probes returned no span at all**, and
all four are in the two carriers where the name stands with least context. Everywhere else
the model produces a span covering the name and then assigns the wrong label or the
wrong boundary. Three distinct mechanisms, with three different remedies:

### 1. Span absorption — the largest single effect, and the whole of tier 4

```text
expected  'Ελένη Παππά'
returned  PER 'Ονομάζομαι Ελένη Παππά'     ← 7 of 8 names, every time
```

Measured both on the reduced carrier above and on the full template line with its
`2026-04-03 11:20:24 - Πελάτης: ` prefix: 0 exact spans either way, 8 wrong spans either
way. The prefix adds another capitalised token but changes nothing.

A **capitalised token immediately before the name is absorbed into the span**. Strict
matching scores that as a miss *and* a false positive — the exact shape of ADR-0016's
English tier-3 bug, but *within* a line, so line-boundary span repair cannot see it.
Confirmed by isolation: the same sentence with the verb lower-cased recovers 5/8, and a
different phrasing (`Το όνομά μου είναι {name}`) gives 6/8. Greek tier-4 recall of
0.000 is therefore a **boundary** failure, not a detection failure, and most of it is
recoverable in principle.

### 2. Label confusion — the span is right, the label is not

Two of the eight pool names come back with an exact span and a non-`PER` label even in
a neutral sentence with nothing else nearby: one `ORG`, one `LOC`. In other carriers
`MISC` appears as well. None of the three reaches the normalized taxonomy — and the
mechanism matters for the remedy: the adapter **asks Presidio for its three native
labels only** (`NATIVE_LABELS` in `providers/presidio_provider.py`), so these are
never requested rather than requested and unmapped. `ADR-0004`'s table is the last
line of defence, not the first. Anything that promotes them has to change the
*request*.

**There is no morphological rule here, and looking for one is the trap.** An earlier
draft of this ADR said Greek genitive surnames read as place names. They do not: of the
five `-ου`/`-ών` genitive surnames in the pool, three are labelled `PER` correctly and
two are not, and the two that fail do so under *different* labels. Which names fail is
a property of what the model saw in training, not of Greek grammar — which is exactly
why the remedy in "what this opens" has to be structural rather than a word list.

### 3. The άνω τελεία flips the label

```text
'... είναι Ελένη Παππά, δεν ...'   → PER    6/8
'... είναι Ελένη Παππά· δεν ...'   → MISC   3/8
```

Comma, semicolon and full stop all give 6/8; only the middle dot halves it. The corpus
uses U+00B7, which tokenizes correctly and is then mislabelled; with U+0387, the proper
Greek code point, the tokenizer glues the mark to the surname and the span is wrong as
well. Both are legitimate ways to write Greek.

**Why the public pack scores higher.** MASSIVE utterances are single short clauses:
no adjacent entity strings, no field label before the name, no άνω τελεία, no
capitalised verb ahead of it. They avoid all three mechanisms. The synthetic templates
hit all three *by being more realistic Greek*.

## Decision

**Record the mechanisms. Do not change the synthetic Greek templates.**

Every one of the three has an obvious "fix" in the corpus — drop the άνω τελεία,
rephrase `Ονομάζομαι`, stop putting a ticket id next to a name — and every one of them
would raise the published Greek number by making the corpus easier. That is tuning the
benchmark to the model, which `AGENTS.md`'s benchmark-integrity rule forbids, and it
would leave the tool no better at the Greek it will actually meet. The corpus stays as
it is, and the numbers stay as they are.

**The one-line licensing explanation is superseded, not deleted.** ADR-0007's
constraint is real and still binding. But two of the three mechanisms are not about the
licence at all: a better-licensed Greek model would help only insofar as it made
different span and label errors, and the tier-4 absorption is a boundary bug of the
kind this project has already fixed once in English without changing models.

## Consequences

- **Greek is no longer "weak, because licensing".** `docs/15_PROVIDERS.md` and plan §8
  now name the three mechanisms and their measured cost, so a later session picks a
  remedy rather than re-deriving the diagnosis.
- **The published Greek numbers are unchanged**, and so is the committed corpus. The
  synthetic Greek corpus is *legitimately harder* than the public one; the pack's 0.606
  and the corpus's 0.111–0.222 are both correct measurements of different text.
- **The pack numbers must not be quoted as the Greek result.** A single-clause utterance
  with no punctuation near the name is the easy end of Greek, not a representative one.
- **The failure modes are pinned by an integration test**, not only by this document. If
  a model bump fixes one, the test fails and Greek gets re-measured deliberately — the
  same discipline the gate file applies to the numbers. It pins the **model**, below
  the adapter, which is where two of the three mechanisms are visible at all: a
  Presidio-side change could move Greek without failing it, and
  `configs/benchmark_gates.yaml` is what covers the pipeline number.
- **`over_redaction` is untouched by any of this.** Nothing here promotes a `LOC`,
  `ORG` or `MISC` span, which is the change that would put it at risk.

## What this opens, and what it rules out

Ranked by what the measurement supports:

1. **Greek span absorption, in the ADR-0016 family** — repair the output, never re-cut
   the input. It is the largest effect and the only one with a precedent in this
   repository. The rule must be **structural**, not a list of Greek words: a stopword
   list tuned to `Ονομάζομαι` would fit this corpus and fail on the next one, which is
   exactly the trap the identifier guard was built to avoid.
2. **Evidence-gated promotion of non-`PER` labels for Greek** — `LOC`, `ORG` and
   `MISC`, all three, since which one appears varies by carrier. Plausible and
   dangerous: it
   trades the leakage the label confusion causes for over-redaction, which is gated at
   0.000. It needs a measurement before it needs an implementation.
3. **A better-licensed Greek model** (roadmap Phase 7, subject to ADR-0015's CPU-only
   constraint). Still worth having, and now with a benchmark that can say *which* of
   the three mechanisms it fixed.

**Narrowed by this measurement, rather than ruled out:** treating Greek as a *pure*
detection problem. Tier 4 is 100% boundary error and detection work cannot touch it;
the neutral sentence never goes silent either. But 2 of 8 do go silent in the tier-3
`Από: {name}` form, so better detection would move tier 3 — it is simply the smallest of
the three effects, and the one with no evidence behind it yet.

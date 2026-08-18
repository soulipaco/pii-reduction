# ADR-0016: repair the span, do not re-cut the input

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 5

> **Amended three times in one session. This block is the decision; the sections
> below are the road that led to it.**
>
> The English tier-3 failure is a *span boundary* error, not a detection failure.
> Three remedies were built and measured:
>
> | whole corpus, hybrid | shipped | `split_lines` | `key_value` | **span repair** |
> |---|---|---|---|---|
> | strict F1 | 0.886 | 0.902 | 0.915 | **0.902** |
> | relaxed F1 | 0.921 | 0.913 | 0.927 | **0.914** |
> | en tier-3 PERSON | 0.333 | 1.000 | 1.000 | **1.000** |
> | el tier-3 PERSON | 0.000 | 0.000 | 0.000 | **0.167** |
> | over-redaction | 0.000 | 0.000 | 0.000 | **0.000** |
> | leakage | 0.117 | 0.122 | 0.122 | **0.117** |
> | document clean rate | 0.774 | 0.763 | 0.763 | **0.774** |
>
> **Span repair ships.** A PERSON span that crosses a line break is split into one
> span per line, at the provider boundary (`providers/base.py::_bound_to_line`).
> No detection slice regressed and two improved (en tier 3 0.333 → 1.000, el tier 3
> 0.000 → 0.167); leakage, over-redaction and document clean rate all hold exactly at
> baseline.
>
> **Every fragment is kept, not the best one, and that choice costs relaxed F1**
> (0.921 → 0.914, a gate deliberately lowered). `Peter Novak` + break + `Mobile` and a
> hard-wrapped `Jürgen` + break + `Müller` are structurally identical, so no rule can
> tell a trailing label from the second half of a name. Dropping a fragment risks
> leaving half a name in the output — and `leakage_rate` cannot see that, because it
> matches only the exact *full* surface. Keeping every fragment sometimes redacts a
> neighbouring label instead, which is the direction this project measures and gates
> at 0.000. The safe error was chosen over the flattering one.
>
> `split_lines` and the `key_value` parser remain available per column but are
> **enabled nowhere**. Both fixed the span by re-cutting the *input*, and every such
> remedy pays for it in lost context: both leaked a Greek name, and `key_value` also
> multiplied provider calls by the number of lines. Span repair changes the *output*
> instead, so detection is untouched and the context cannot be lost by construction.
>
> The identifier guard (PERSON-scoped) also ships. It was built to unblock
> `key_value`; it turned out not to be needed for the remedy that won, but it is a
> correct rule in its own right and a verified no-op on the shipped configuration.

## Context

`docs/14_IMPLEMENTATION_PLAN.md` §8 Q2 named the remedy for English tier-3 PERSON
recall (0.333) before the cause was known, listing candidates "in increasing cost: a
key/value parser that marks labels non-processable and passes the value with context,
per-tier provider options, or a custom recognizer". `config/registries.py` records
`key_value` as a deferred parser name.

The diagnosis found a different cause than any of those assumed. Presidio detects
**every** name in the failing documents. The span is wrong:

```text
truth:      (10,21) 'Peter Novak'
prediction: (10,28) 'Peter Novak\nMobile'
```

Handed a multi-line key/value block as one segment, spaCy runs the entity boundary
through the line break and absorbs the next line's first word. Strict matching scores
that as a miss *and* a false positive, which is the whole of the 0.333. The same model
and the same names score 1.000 on tier-4 transcripts, because the transcript parser is
line-oriented and no span can cross a break.

It is not only a metric artifact. The reduced output today is:

```text
'Customer: <PERSON> number: +1 202 555 0140'     ← the label "Mobile" is destroyed
```

against the correct:

```text
'Customer: <PERSON>\nMobile number: <PHONE>'
```

Destroying a field label is a structure-preservation failure (`AGENTS.md` rule 5) that
the over-redaction metric cannot see, because labels are not in the protected-token
list.

## Decision

Add `split_lines` as a **parser option on `PlainTextParser`**, default `false`. Do not
add a `key_value` parser for this.

Reasoning:

1. **The cause is segmentation granularity, not document structure.** A key/value block
   and a wrapped paragraph are the same contract — free text in one column. What
   differs is whether a line is a record or a sentence. That is a switch on the
   existing parser, not a new document contract, and `key_value` as a registered parser
   would be `plain_text` plus a boolean.
2. **Marking labels non-processable is a separate, later decision.** A probe showed
   the value alone is enough for detection (`'Grace Okafor'` → exact span, without its
   `Customer:` label), so the planned key/value parser would also work — and would
   additionally suppress a false positive that line-splitting introduces (see below).
   That parser remains deferred and is now better motivated; this ADR does not
   pre-empt it.
3. **Off by default**, because splitting is wrong for prose that wraps mid-sentence: a
   name broken across the wrap would become undetectable. The failure mode of the
   default must be the conservative one.

## Consequences

- Measured on the dev+calibration splits, `deterministic_presidio`: English tier-3
  PERSON strict recall 0.000 → 1.000 (support 3); PERSON overall 0.595 → 0.676;
  strict F1 0.857 → 0.890; over-redaction unchanged at 0.000.
- **It introduces one false positive.** Splitting removes context, and on its own line
  the German `Rechnername:` ("computer name") is tagged PERSON where the whole-block
  context suppressed it. Net strict F1 still rises, but this is a precision regression
  in a German slice, so plan §8 Q2's "no drop in any other slice" is **not** satisfied
  by line-splitting alone. The option therefore ships enabled in **no** shipped
  configuration; Q2 is not complete.
- **`key_value` was built, and it closes that gap — while opening a worse one.**
  Holding the label out of processing does remove the `Rechnername` false positive.
  On the dev+calibration splits it looked unambiguously better than `split_lines`:
  strict F1 0.857 → 0.896, precision 0.904 → 0.945, relaxed F1 back to baseline, en
  tier-3 PERSON 0.000 → 1.000, over-redaction 0.000, and **no slice regressed**.

  The whole-corpus run said otherwise. Strict F1 0.886 → 0.910 and en tier-3 PERSON
  0.333 → 1.000, but **over-redaction 0.000 → 0.020** and leakage 0.117 → 0.122:

  ```text
  'KB Article: KB000002739'    → value ' KB000002739'  tagged PERSON → redacted
  'Rechnername: DEMO-PC-6963'  → value ' DEMO-PC-6963' tagged PERSON → redacted
  ```

  The label was not only noise — it was *context that suppressed false positives on
  bare identifiers*. Removing it cuts both ways. Q2's exit criterion requires
  over-redaction to stay 0.000, so at this point `key_value` could not ship either —
  which is what motivated the identifier guard below.

- **The development splits did not reveal this.** Both destroyed identifiers are in
  the test split, and dev+calibration (45 documents) reported over-redaction 0.000.
  Developing against dev/calibration remains right — it is what stops iterating on the
  test split — but it is not sufficient evidence to enable a change. The whole-corpus
  gate run is, and it is the reason the gates exist.

- **The identifier guard was built and it works.** `patterns.is_identifier_shaped`,
  applied by the reconciler as rejection reason `identifier_shaped`. It is a
  *structural* rule — no token in the surface is name-like — not a list of known
  identifier formats: a list tuned to the committed corpus would fit the fixture and
  stop working on Increment D's public data. The verdict is "no token is name-like"
  rather than "some token looks like an identifier", so `Maria Rossi 2026` stays a
  name — rejecting it would leave the name unredacted, and leaking a name is worse
  than over-redacting a year.

  Two corrections came out of the privacy audit, both of which would have leaked:

  - The first rule counted a token as name-like only if it carried **no** digit, which
    rejected `Mueller2024`, `jmueller01`, `grace.okafor2` and `Παππά2026` — usernames
    and handles are routine in real support data, and a rejected PERSON span means the
    name is not redacted. Letter-versus-digit counts do not separate the cases that
    matter (`DEMO-PC-6963` is 6/4, `Mueller2024` is 7/4); a lowercase run of three or
    more does, because machine identifiers are conventionally upper case. A lone
    all-caps token with digits (`MUELLER2024` by itself) remains a known gap, pinned
    by a test rather than left latent.
  - **Default scope is PERSON only, not PERSON + ADDRESS.** ADDRESS is the one
    guarded-looking type whose surface is legitimately all digits — a postcode or
    house number alone — and no shipped provider emits it (ADR-0002), so there was no
    measurement behind guarding it. Add it when a provider emits it and the benchmark
    can show what the guard does to it.

  The scope is a `ReconciliationPolicy` field, so it is adjustable from the Python API
  but **not yet reachable from YAML**: `ChainSettings` exposes only `providers` and
  `overlap_policy`. A config key is the natural next step if the guard ever needs
  turning off per dataset.

- **Measured whole-corpus, hybrid chain, with the guard active:**

  | | shipped | `split_lines` | `key_value` |
  |---|---|---|---|
  | strict F1 | 0.886 | 0.902 | **0.915** |
  | relaxed F1 | 0.921 | 0.913 | **0.927** |
  | en tier-3 PERSON recall | 0.333 | 1.000 | **1.000** |
  | over-redaction | 0.000 | 0.000 | **0.000** |
  | leakage | **0.117** | 0.122 | 0.122 |
  | document clean rate | **0.774** | 0.763 | 0.763 |

  `key_value` is the better remedy on every axis where they differ, and the
  over-redaction regression that blocked it is gone.

- **One privacy regression survives, and the detection metrics cannot see it.**
  Both remedies leak one more entity: the Greek `Ελένη Παππά` in `Από: Ελένη Παππά`.
  With block context `xx_ent_wiki_sm` finds it; on the isolated line it does not. Its
  slice recall was 0.000 before and is 0.000 after — the old detection produced an
  over-long span that failed strict matching *while still redacting the name*. So the
  detection table records no change while a value starts surviving. This is exactly
  why ADR-0011 reports leakage beside detection, and a reminder that a span can be
  wrong for scoring and right for privacy at once.

- **Line-scoped segmentation helps English and hurts Greek**, and the pipeline cannot
  express that: segmentation is chosen per column, detection is routed per language.
  Recovering the Greek detection needs either provider-level context words or a
  two-granularity detection pass whose overlap ordering is a design question in its
  own right. Both are larger than Q2.

## Alternatives rejected

- **Shipping either remedy on the strength of the dev/calibration numbers.** Both
  looked good there. The whole-corpus run is what caught the over-redaction, and a
  metric the exit criterion pins at 0.000 is not a rounding concern.
- **Weakening the over-redaction gate to 0.020 so `key_value` could ship.** The gate is
  the only automated defence of AGENTS.md rule 5, the regression is real rather than a
  metric artifact (two identifiers genuinely destroyed), and `CONTRIBUTING.md` forbids
  weakening a gate to make a change pass.
- **Per-tier provider options / a custom recognizer** (plan §8's other candidates).
  Both were aimed at a detection failure. There is no detection failure.
- **Making line-splitting the default.** Would silently change behaviour for every
  existing plain-text column, including wrapped prose, to fix a structured-text
  problem.


## Where this leaves Q2

The identifier guard ships. Neither segmentation remedy does, by the repository
owner's decision: `key_value` buys strict F1 0.886 → 0.915 and English tier-3 PERSON
0.333 → 1.000, and costs one leaked Greek name. In a tool whose purpose is reducing
PII, a leakage regression is not a fair trade for a detection gain, and the gates say
so — `leakage_rate` is pinned at 0.117.

Q2 therefore stays open on a narrower and better-understood problem than it started
with: **recover Greek detection under line-scoped segmentation.** Two candidates, both
larger than a config change:

1. Pass the label to the provider as *context* without making it processable. Presidio
   supports context words; the label would inform detection while staying immutable.
2. Detect at two granularities — whole field and per line — and let the reconciler
   choose. The overlap ordering is the open question: both candidates are PERSON from
   the same provider at the same constant score, so today's "longer span wins" rule
   would re-select the over-long span and undo the English fix.

A third possibility is architectural: segmentation is chosen per column while
detection is routed per language, so "line-scope English, block-scope Greek" cannot
currently be expressed. That is a pipeline design change, not a parser one.

Also worth carrying forward: `key_value` turns one provider call per document into one
per line, and the whole-corpus benchmark run slowed by roughly an order of magnitude on
the development machine. Under ADR-0015 (CPU-only deployment) that cost is a selection
criterion, not a footnote.


## The remedy that won, and why the others did not

Every earlier attempt re-cut the input: split the field into lines, or split each line
into label and value. Each fixed the boundary and each cost context, because the
model's accuracy depends on the text it is shown. That is not a tuning problem to be
solved with a better split — it is inherent to changing the input.

Span repair changes the output. Detection runs exactly as before, on the whole block;
a PERSON span that crosses a line break is trimmed back to the line. It cannot lose
context, because it does not touch what the model sees.

It is **repair rather than rejection** deliberately: the model was right about the
entity and wrong only about where it stops. Dropping the span would leave the name in
the output; keeping it destroys the next line's label. Trimming is the only option
that is right on both counts.

It lives at the provider boundary rather than in the reconciler because the text and
the match are already in hand there — no optional `text=` parameter, and no downstream
layer ever sees a malformed span.

`ADDRESS` is excluded from `LINE_BOUNDED_ENTITIES`: a postal address written across
several lines is one address, and trimming it at the first break would cut a real
entity in half.

### What this cost, and what it did not

Nothing operationally: one provider call per document, as before. No configuration
change, so every existing user gets the fix rather than only those who opt a column
in. No corpus change.

### Candidate eliminated

Presidio's `context=` parameter cannot recover a missed name. It feeds the
context-aware *enhancer*, which boosts the score of candidates a recognizer already
produced; PERSON comes from the spaCy NER reading the text it was given. Probed
directly on the Greek line with and without context words: no PERSON either way.
Recorded so the next session does not spend the same afternoon on it.

### Still open

Greek PERSON remains weak (0.222 / 0.111 / 0.167 / 0.000 by tier) and licence-bound to
`xx_ent_wiki_sm` until roadmap Phase 7 (ADR-0007). Span repair improved tier 3 by one
entity; it did not change the licensing reality.

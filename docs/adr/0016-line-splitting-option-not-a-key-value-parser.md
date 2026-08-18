# ADR-0016: line-scoped segmentation for key/value text, and why neither form ships enabled

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 5

> **Amended the same session.** This ADR was written when `split_lines` was the only
> remedy and the `key_value` parser was still deferred. Both now exist, `key_value` is
> registered, and a whole-corpus measurement changed the conclusion: **neither is
> enabled in any shipped configuration**, for a reason worth reading — see
> *Consequences*. The original decision (a segmentation option rather than a new
> document contract) stands for `split_lines`; the reasoning about `key_value` being
> "the next step" has been overtaken by measurement.

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
  over-redaction to stay 0.000, so `key_value` does not ship enabled either.

- **The development splits did not reveal this.** Both destroyed identifiers are in
  the test split, and dev+calibration (45 documents) reported over-redaction 0.000.
  Developing against dev/calibration remains right — it is what stops iterating on the
  test split — but it is not sufficient evidence to enable a change. The whole-corpus
  gate run is, and it is the reason the gates exist.

- **What both remedies actually need is identifier-false-positive suppression**, not a
  third parser: a way for the pipeline to refuse a PERSON span whose surface is
  ticket-, KB-, machine-, version- or order-shaped. That belongs with the reconciler or
  a provider-level guard, applies to both segmentation forms, and is independently
  useful — the same false positives can occur in prose. Recorded as Q2's remaining
  work in plan §8.
- Two parsers now split lines with duplicated logic. They are deliberately **not**
  refactored onto a shared line splitter: they do not agree on line *semantics* (the
  transcript parser splits a line into speaker prefix and body; this one does not), so
  a shared module would advertise an agreement that does not exist. Revisit when a
  third line-oriented parser lands, or when `key_value` needs the transcript parser's
  prefix heuristic.
- `parser_options` are validated at pipeline construction rather than at config load,
  so a typo (`split_line: true`) surfaces as a `ParserError` mid-build rather than a
  `ConfigurationError` during validation. This is pre-existing behavior shared with the
  transcript parser, and it is the acknowledged cost of choosing an option over a
  registry name.

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

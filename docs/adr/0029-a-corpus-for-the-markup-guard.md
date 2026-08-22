# ADR-0029: A markup corpus, and what it found in its first run

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 12

## Context

ADR-0027 shipped a **detection change** — a span clipped out of machine syntax at the
provider boundary, plus an output check that blocks a run when a tag disappears — with
**no corpus support at all**. Every corpus in this repository is markup-free: the
committed benchmark corpus, all three demo packs, and the incident stress corpus. The
guard's evidence was 50 synthetic unit tests and a measurement somebody else made on
data this project cannot see.

That is a state this repository does not accept elsewhere, and it is not academic. The
guard's own first draft leaked three different ways, and every one of them was found by
reading the diff rather than by running anything, because there was nothing to run it
against. A behaviour with no corpus is a behaviour whose regressions are invisible.

ADR-0022 faced the same problem for over-redaction and answered it the same way: a
generated corpus, committed, not a pack, carrying no realism claim.

## Decision

**A third corpus profile — `tests/fixtures/markup/`, 90 documents, 270 entities, 330
protected tokens, en/de/el, tiers 3 and 4** — built by
`pii_reduction.synthetic.markup_notes` through the same `build_corpus` generator as the
other two, with its own gate set in `configs/markup_gates.yaml`.

Four things follow ADR-0022 deliberately, because the argument is the same:

1. **Generated, and it says so.** The prose is ours, so it makes no claim about how the
   pipeline performs on text nobody wrote for us. What a generated corpus *can* say
   honestly is whether machine syntax survives reduction, because markup dialects are
   conventions: who wrote the sentence around a `<div>` does not change whether the tag
   comes through.
2. **Committed, not fetched**, because there is no source to rebuild it from — only the
   generator and its seed. CI checks it byte for byte.
3. **Not a pack, and never publishable as one.** It carries no licence, no provenance
   and no realism.
4. **Its own gate set, never a reason to loosen another.** The synthetic floors in
   `configs/benchmark_gates.yaml` are untouched. **Both sets are run by CI** — the
   model-free one on every push, the hybrid one nightly — because the consequence
   claimed below (a regression is a gate failure, not a code review) is only true if
   something evaluates them. The architecture review of this increment caught that
   claim outrunning its automation; a test now pins each set to the workflow that can
   run it.

**Every markup shape in it is one the reference implementation measured being
destroyed** (`docs/20_ALTERNATIVE_RECONCILIATION.md`), not one invented to be easy: the
`[code]<div` adjacency spaCy returns as a PERSON at 0.85, a URL beside a name, a name
inside an anchor's `title` attribute, BBCode blocks, `&nbsp;` runs, and a zero-width
space.

The CLI dispatch became a three-row profile table rather than a third branch, so a
fourth profile is a row and not a builder.

**On reserved names:** the URL hosts here use `.test` (RFC 6761), which is the right
reservation for a hostname. Email addresses stay on RFC 2606's `example.com` family, so
ADR-0003's concern — Presidio's `EmailRecognizer` rejecting `.test` domains, which is
what makes the deterministic provider load-bearing — is untouched by this corpus.

## What the first run found, and none of it was the expected result

### 1. Markup destroys PERSON recall. That is the finding.

**PERSON strict recall is 0.322 on the hybrid chain, against 0.821 on the committed
benchmark corpus.** The reference implementation's failure catalogue records only the
*false-positive* direction — NER reading markup as prose and returning a tag as a name.
This is the other half, and it is the worse one: **a missed name is a leak.**

Isolated by changing one thing at a time against `en_core_web_md`, which is the method
ADR-0019 established for this kind of question:

| text | PERSON |
|---|---|
| `From: Grace Okafor` | found |
| `From: Grace Okafor <grace.okafor@example.com>` | found |
| `<b>From:</b> Grace Okafor &lt;…&gt;<br>` | **nothing at all** |
| `Owner: Grace Okafor profile` | found |
| `Owner: <a href='…' title='Grace Okafor'>profile</a>` | **nothing at all** |

The model returns **no span**, so no guard, repair, reconciler rule or threshold can
reach it. This is upstream of everything ADR-0027 does — the guard cannot help, because
there is nothing to clip.

Where the markup sits matters for English and German, and **does not explain Greek**: en
tier 4 and de tier 4 are both 1.000 while en tier 3 is 0.050 and de tier 3 is 0.000 —
those bodies carry markup around the sentence rather than inside the clause. **Greek
runs the other way: tier 3 is 0.400 and tier 4 is 0.000.** The placement explanation
therefore covers two languages of three, and Greek is open. Its tier-4 zero is
consistent with the span absorption ADR-0019 diagnosed and ADR-0022 saw at the same
tier, so markup may not be the operative cause there at all — which is exactly why the
sentence must name it rather than average it away.

### 2. Over-redaction reproduces a known mechanism on new text

`over_redaction_rate` is 0.033 on the hybrid chain — 11 of 330 tokens. **10 of the 11
are the mechanism ADR-0022 already named**: Greek tier-3 ticket ids inside a PERSON span
covering `Περιστατικό INC…`, which the reconciler's identifier guard passes by design
because `Περιστατικό` is name-like. The eleventh is one English tier-4 ticket id.

Reproducing a known mechanism on new text is the useful result: the asymmetry in
`patterns.py` — prefer over-redacting a year to leaking a name — has a price on
markup-dense text too, and now two corpora say so.

### 3. The deterministic chain destroys nothing

Over-redaction 0.000, and EMAIL and PHONE hold at 1.000 precision *and* recall against
text where an address sits between `&lt;` and `&gt;`. That is also the measurement that
ADR-0027's format-defined exemption costs nothing here.

## Consequences

- **ADR-0027 now has a number**, and a regression in the guard shows up as a gate
  failure rather than as a code review.
- **A new open problem is on the record with evidence**: detection collapses on
  markup-dense text. The obvious remedy — strip markup before detection and map offsets
  back — is a change to the model's **input**, which plan §8 Q2 measured as trading one
  error for another twice (`split_lines` and `key_value` each leaked a Greek name). It
  needs its own increment and its own measurement.
- **No published number moved.** This corpus is new, its gates are new, and the
  benchmark and incident floors were re-run unchanged: 10/10, 15/15, 6/6, 10/10.
- **The floors here are low on purpose and must not be raised by editing the corpus.**
  Greek and English tier-3 PERSON are low because markup-dense text is genuinely hard.
  `AGENTS.md` forbids tuning a benchmark to the model, and ADR-0019 already refused the
  corpus-side "fix" for the Greek gap for the same reason.

## Alternatives considered

**Add markup to the incident corpus instead.** Rejected: it would move published
numbers on a committed corpus in order to measure something else, and ADR-0022's
corpus answers a different question. Two corpora measuring one thing each is cheaper to
read than one corpus measuring two.

**Make the markup tags protected tokens**, so tag survival lands in
`over_redaction_rate`. Rejected: a protected token is an *identifier that must survive*,
and folding structural damage into the same metric would make one number mean two
things — the mistake `fragment_leakage_rate` exists to avoid (ADR-0013 §5). Markup
damage is a **fidelity** failure and blocks the run; over-redaction is measured. The
severity split is ADR-0027's, and this corpus keeps it.

**Leave the guard unmeasured until a real dataset arrives.** Rejected: that is the
state that produced the three leaks, and a real dataset cannot be committed.

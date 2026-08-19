# ADR-0021: Extend a PERSON span left, rather than trim it — the visible error again

**Status:** accepted · **Date:** 2026-08-19 · **Session:** 8

## Context

ADR-0020 shipped Greek label promotion and left two things behind.

First, a **measurable defect it introduced**: `fragment_leakage_rate` (0.078) stopped
equalling `leakage_rate` (0.067). Two Greek PERSON values went from fully leaked to
*partially* redacted — the model returned only the surname of `Γιώργος Δημητρίου`, so
`Δημητρίου` was removed and `Γιώργος` survived. ADR-0013 §5 built the fragment metric
precisely to make that visible, and ADR-0020 verified it was incomplete progress rather
than new damage. It was still a gap that wanted closing.

Second, a **question about what to do next**. Plan §8 named ADR-0019's mechanism 1
(span absorption) as the next Greek target. Classifying every remaining Greek PERSON
miss against the chain says otherwise — 26 entities, before and after this ADR:

| bucket | before | after | what it is |
|---|---|---|---|
| MATCHED | 11 | **13** | — |
| **SILENT** | 8 | 8 | the model returns no span overlapping the name at all |
| DROPPED | 4 | 4 | a span arrives under a label the adapter refuses (3 of them `MISC`) |
| PARTIAL | 2 | **0** | a span covers part of the name |
| ABSORBED | 1 | 1 | a span swallows a preceding token |

**Absorption is one miss in twenty-six.** It was the dominant mechanism when ADR-0019
measured it, before promotion; promotion has since converted most absorbed spans into
approved PERSON spans. Building a remedy for mechanism 1 today would buy one entity.
The `PARTIAL` bucket is worth twice that *and* closes the fragment gap — and
this ADR empties it.

**What that leaves is the useful part.** Of the 13 remaining misses, 12 are cases
where no span reaches the reconciler at all: 8 the model never produces, 4 it
produces under a refused label (3 of them `MISC`, which Presidio discards before
this adapter — see ADR-0020). Only 1 is a boundary error. **The remaining Greek
gap is almost entirely beyond span and label engineering.**

## What was measured

Whole corpus, hybrid chain, against ADR-0020 as shipped:

| metric | ADR-0020 | + extension, **Greek only** | + extension, global |
|---|---|---|---|
| strict F1 | 0.899 | **0.910** | 0.882 |
| relaxed F1 | 0.921 | 0.921 | 0.921 |
| leakage | 0.067 | 0.067 | 0.067 |
| **fragment leakage** | 0.078 | **0.067** | 0.067 |
| document clean rate | 0.871 | 0.871 | 0.871 |
| over-redaction | 0.000 | **0.000** | 0.000 |
| PERSON precision / recall | 0.747 / 0.795 | **0.771 / 0.821** | 0.711 / 0.756 |
| en PERSON | r 0.962 / p 0.833 | r 0.962 / p 0.833 | r **0.885** / p **0.767** |
| de PERSON | r 1.000 / p 0.963 | r 1.000 / p 0.963 | r **0.885** / p **0.852** |
| el PERSON | 0.423 / 0.423 | **0.500 / 0.500** | 0.500 / 0.500 |

**Nothing measured gets worse in the Greek-scoped column.** Strict F1 lands at 0.910 —
above the 0.902 that preceded promotion — and the fragment rate returns to equality.

Two further checks, because a rule this small is easy to fool yourself about:

- **It fires exactly twice on the corpus, and both times lands exactly on the truth
  span.** Every changed prediction was enumerated; there are no false extensions.
- **On the `multilingual_utterances` pack it is inert** — 66 Greek PERSON entities of
  text nobody wrote for us, every gated metric identical, one fragment entity
  improving. **This is weaker evidence than it looks and is recorded as such**: that
  pack is lower-case and unpunctuated by construction, so the capitalisation refusal
  guarantees inertness there whether or not the rule is sound. It shows the rule does
  not misfire on uncased text; it says nothing about cased public Greek, for which no
  permissively-licensed source is currently in the registry.

## Decision

**Extend a PERSON span left over one preceding token when that is structurally safe**,
as an opt-in per provider instance, enabled for Greek only.

`extend_person_span_left` lives in `providers/base.py` beside `_bound_to_line`, because
it is the same family of repair — change the model's *output*, never its input — and
is not Presidio-specific. `BaseProvider.extend_person_left` is `False` by default;
`PresidioProvider` reads it from configuration and `configs/providers.yaml` sets it on
`presidio_el` alone.

Four refusals, all structural. ADR-0019 requires the rule not be a list of Greek words:

1. **across a line break** — ADR-0016 established a name does not span lines;
2. **an identifier-shaped token** — reusing `is_identifier_shaped`, so the ticket and
   machine ids behind the 0.000 over-redaction gate can never be swallowed;
3. **a token ending in a boundary mark** — `:` (a field label), the άνω τελεία in both
   codepoints (U+00B7 and U+0387, ADR-0019's mechanism 3), or sentence-final
   punctuation (`.`, `!`, `?`, and both semicolons, U+003B and U+037E). The last group
   is why a name opening a sentence does not absorb the previous sentence's last word;
4. **an uncased token** — in a cased script, a name part is capitalised.

Exactly one token, never two: "how many tokens can a name have" is a question about
names, and this rule is deliberately about text shape instead.

### Why extension and not the trim that was rejected

Session 7 examined the mirror-image rule — drop a capitalised token *ahead* of a
PERSON span, to fix absorption — and rejected it: it can always be cutting the first
token of a genuine three-token name, which leaks a name part and is invisible to
`leakage_rate`. This ADR does not reverse that judgement; it inherits it. Trimming
removes coverage by construction; extension adds it.

**But "extension can only over-redact" was wrong as first written, and two independent
reviews reproduced why.** Widening is not leak-safe by itself, because the *reconciler*
resolves overlaps by entity priority and is greedy without backtracking. A PERSON span
widened into overlap with a higher-priority EMAIL is rejected outright and the name it
was covering survives in cleartext. A PERSON span widened over a neighbouring PERSON's
last token wins the length tie-break and evicts that neighbour, leaking whatever only
the neighbour covered. Both are under-redaction — the invisible error this repair was
justified by avoiding.

The repair is therefore built so that neither can happen, and the two defences are
different because the conflicts are visible at different places:

* **Within one provider call**, `_extend_left` receives every sibling candidate and
  refuses to claim a token another candidate already covers. That closes peer eviction
  at source.
* **Across providers** — the deterministic EMAIL/PHONE recognizers run in a separate
  call and are invisible here — the repair returns the **widened span *and* the
  original**. The reconciler takes the wide one where it fits and falls back to the
  narrow one where it does not, so a lost overlap costs precision, never coverage.

With both in place the claim holds: an extension can cost a swallowed neighbouring
word, which `over_redaction_rate` sees when it touches a protected token and strict
precision sees when it does not. ADR-0016 chose the visible error deliberately, and
this is the same choice pointed the other way — but it took two reviews to make it
true rather than merely stated.

A third defence guards the identifier boundary: a span whose own surface is
identifier-shaped is never widened. The reconciler's guard rejects such a span because
nothing in it looks like a name; widening it over a capitalised word would make the
joined surface name-like and silently unblock a candidate the guard was holding back,
redacting the identifier underneath it.

## Consequences

**The fragment/full equality is a live property again**, on both chains rather than
only the deterministic one. That matters beyond the number: while the two disagreed,
the deterministic set's "if these diverge, investigate" note had a standing exception,
and a standing exception is how a real partial leak would have been waved through. The
gate comment now says the equality is expected on both chains.

**`document_clean_rate` recovers its plain meaning.** ADR-0020 had to disclose that two
of its "clean" documents still carried a Greek given name; those two are now genuinely
clean, and the caveat is retired rather than carried.

**Greek tier 3 moved as well** — 0.167 → 0.333, which was not the target. Both partial
spans happened to sit in tier-1 and tier-3 documents.

**What it does not touch.** The eight `SILENT` misses, which are now the majority of the
remaining Greek gap and are a property of what the model was trained on rather than
anything a span rule can repair — the same names go missing repeatedly. Nor the three
`MISC` misses, which ADR-0020 established are unreachable through Presidio. **The
remaining Greek gap is now mostly not addressable by boundary or label engineering at
all**, which makes a better-licensed Greek model at roadmap Phase 7 the next real move
rather than a further repair rule.

**Residual risk, stated rather than discovered later.** A capitalised non-name word
immediately before a name, mid-line, ending in no boundary mark, will be swallowed — a
Greek title such as `Κύριος` is the obvious shape. That over-redacts one word. It is
the visible failure this design accepts, it is bounded to a single token, and the
identifier refusal keeps it away from protected tokens.

**Firings are counted.** `_extend_left` records `person_extended_left` through the same
drop counter `_bound_to_line` uses, and for the same reason ADR-0004 gives: a provider
or model upgrade that changes how often a repair fires would otherwise change coverage
with no signal. The "fires exactly twice" claim above is a one-off probe; the counter
is what keeps it observable.

**Class-attribute default.** `extend_person_left` is a mutable-looking class attribute
on `BaseProvider` set to `False`; `PresidioProvider` shadows it per instance. A provider
that neither declares nor configures it inherits the safe default, which is the
behaviour every provider had before this ADR.

## Alternatives rejected

- **A remedy for span absorption (ADR-0019 mechanism 1)** — worth one entity of
  twenty-six after promotion, against two plus the fragment gap for this. Deferred, not
  refused; the classification above is the evidence.
- **Leading-token trim** — rejected in session 7 and again here, for the same reason:
  it fails invisibly.
- **Extending by more than one token** — unmeasured, and it turns a shape rule into an
  assumption about name length.
- **Applying it to every language** — measured: en recall 0.962 → 0.885 and de
  1.000 → 0.885.
- **Making the corpus easier** — forbidden by ADR-0019, and not done: no corpus file is
  touched.

# ADR-0020: Greek label promotion, scoped to Greek — precision traded for leakage

**Status:** accepted · **Date:** 2026-08-19 · **Session:** 8

## Context

ADR-0019 diagnosed Greek PERSON as three mechanisms rather than one, and named the
second — **label confusion** — as the one worth acting on next: the model returns an
*exact span* covering the name and labels it `LOC`, `ORG` or `MISC`, so ADR-0004's
mapping table correctly refuses it and the name is found and then dropped. ADR-0019
also fixed where a remedy must live: the adapter asks Presidio for three native labels
only, so an unmapped label never *arrives*. **A promotion remedy has to change the
request, not the mapping table.**

Plan §8 recorded an offline probe of that remedy and left it unshipped behind an open
design question: the best measured stack still destroyed 5 of 34 protected identifiers
against a 0.000 over-redaction gate, and closing that was thought to need "token-level
coverage surgery inside promoted spans" — a decision about whether that is still
"repair the output" (ADR-0016) or something new.

This ADR records what happened when that question was measured against the real stack
instead of an offline simulation. **The premise did not survive.**

## What was measured

Six arms on the committed corpus's Greek slice (34 documents, 26 PERSON, 34 protected
tokens), using the real pipeline, the real reconciler and the real metric functions.
The harness was validated twice: it reproduces the published baseline exactly
(0.154 / 0.350 / 0.000), and a spaCy-direct PER-only control arm reproduces it a
second time through an independent code path.

| arm | PERSON recall | precision | leakage | over-redaction |
|---|---|---|---|---|
| baseline (shipped, PER only) | 0.154 | 0.444 | 0.350 | **0.000** |
| promotion `LOCATION`/`ORGANIZATION` | **0.423** | 0.423 | **0.200** | **0.000** |
| promotion + token surgery | 0.346 | 0.346 | 0.200 | 0.000 |
| spaCy-direct PER only *(control)* | 0.154 | 0.444 | 0.350 | 0.000 |
| spaCy-direct promotion incl. `MISC` | 0.423 | 0.239 | 0.167 | 0.059 |
| spaCy-direct promotion + surgery | 0.346 | 0.196 | 0.167 | **0.000** |

### Why the 5 destroyers did not reproduce

Two causes, both verified rather than inferred:

1. **Presidio silently drops every `MISC` entity.** On the Greek slice
   `xx_ent_wiki_sm` emits `PER 8, MISC 41, LOC 20, ORG 1`; Presidio surfaces
   `PERSON 8, LOCATION 20, ORGANIZATION 1`. `MISC` has no Presidio entity name and is
   discarded *inside Presidio*, before this project's adapter — it cannot be requested
   under any label, `NRP` included. And **21 of the 22 model spans that overlap a
   protected token are `MISC`** (the 22nd is `ORG`). The destroyers are unreachable
   through the shipped provider.
2. The real reconciler — the identifier guard, ADR-0016 line-bounding and the overlap
   policy — removes the remainder. No approved span, promoted or not, overlaps a
   protected token.

**Token-level surgery is therefore not built.** It works where destroyers exist (0.059
→ 0.000 on the spaCy-direct arm, holding leakage at 0.167), but reaching that arm means
bypassing Presidio's `MISC` drop with a new provider path, and it halves precision
(0.239 → 0.196). Against the alternative — promotion through the existing adapter,
already at 0.000 — it buys 0.033 of leakage for a large precision loss and a new
architecture. It is also the reason the surgery question was worth asking and is now
answered: surgery would have inverted the safety asymmetry `patterns.py` states
explicitly ("leaking a name is worse than over-redacting a year"), and nothing in the
measurement justifies paying that.

### Promotion must be scoped to Greek

Promotion is a provider-level change, so an unscoped version lands on English and
German too. Measured whole-corpus:

| metric | baseline | promotion **global** | promotion **Greek-only** |
|---|---|---|---|
| strict F1 | 0.902 | 0.875 | **0.899** |
| relaxed F1 | 0.914 | 0.896 | **0.921** |
| leakage | 0.117 | 0.067 | **0.067** |
| over-redaction | **0.000** | **0.010** | **0.000** |
| en PERSON | r 0.962 / p 0.833 | r 0.962 / p **0.694** | r 0.962 / p 0.833 |
| de PERSON | r 1.000 / p 0.963 | r 1.000 / p **0.839** | r 1.000 / p 0.963 |
| el PERSON | r 0.154 / p 0.444 | r 0.423 / p 0.423 | r 0.423 / p 0.423 |

Global promotion breaks two gates and damages two languages that were already correct.
Greek-only promotion leaves en and de **numerically identical**.

## Decision

1. **`PresidioProvider` gains a `promote` option**: native labels listed there are
   added to the analyzer request *and* normalized to PERSON. Restricted to
   `PROMOTABLE_LABELS` = {`LOCATION`, `ORGANIZATION`, `NRP`} — promoting `URL` or
   `DATE_TIME` would be a category error, not a coverage choice. A promoted label also
   leaves the drop set, or `drop_counter` would report a configured behaviour as an
   unbidden arrival. Every match records `promoted` in its metadata. That is
   in-process provenance only: `AUDIT_COLUMNS` is a deliberately closed set and no
   audit row carries it today, so the precision cost below cannot yet be attributed
   from an audit table. Adding the column is a separate decision — it changes the
   Delta schema the Databricks parity test asserts exactly.

2. **The shipped configuration promotes for Greek only**, through a second provider
   instance `presidio_el` (`languages: [el]`, `promote: [LOCATION, ORGANIZATION]`).
   `presidio` narrows to `[en, de]`. `NRP` is promotable but deliberately not enabled:
   Presidio derives it from spaCy's `NORP`, which `xx_ent_wiki_sm` does not emit, so it
   never fires and enabling it would ship a path nothing measures. (It is kept
   *promotable* for a future Greek model that does emit `NORP`.)

3. **The split lives inside the chain, not in a project-level `languages:` route.**
   `benchmark.with_chain` overrides a column's chain but *not* a language route, so a
   route would silently apply Presidio to Greek during the `deterministic_only`
   benchmark and corrupt that baseline. Provider-level `language_scopes` routes each
   document to exactly one Presidio instance, so this is not a second opinion on the
   same text. Verified: the deterministic chain's numbers are unchanged
   (0.723 / 0.433 / 0.000 / 0.161).

4. **Floors move in two gate files** — `configs/benchmark_gates.yaml` and
   `configs/pack_gates/multilingual_utterances.yaml`, the only other gate set whose
   corpus contains Greek. On the committed corpus, three precision floors are
   lowered and six tightened or added. Lowered:
   overall strict F1 0.902 → 0.899, overall strict precision 0.935 → 0.886, PERSON
   strict precision 0.833 → 0.747. Tightened or raised: leakage 0.117 → 0.067,
   fragment leakage 0.117 → 0.078, document clean rate 0.774 → 0.871, PERSON strict
   recall 0.705 → 0.795, relaxed F1 0.914 → 0.921, Greek tier-1 PERSON recall
   0.222 → 0.444, plus a new Greek tier-2 floor at 0.667. Over-redaction stays 0.000
   and EMAIL/PHONE stay 1.000.

   Lowering a floor to admit a measured improvement is a different act from making the
   corpus easier, which ADR-0019 forbids and which is not done here: **no corpus file
   is touched.** But it moves published numbers, which is why it is an ADR and not a
   config edit.

## Consequences

**What this buys.** Greek PERSON strict recall 0.154 → 0.423 overall, by tier
0.222 → 0.444 (t1), 0.111 → 0.667 (t2), 0.167 (t3, unchanged) and 0.000 (t4,
unchanged — tier 4 is span absorption, ADR-0019 mechanism 1, which promotion does not
address). Whole-corpus leakage falls 43%, document clean rate rises 0.774 → 0.871.

**What it costs.** PERSON strict precision 0.833 → 0.747, all of it Greek: promotion
accepts `LOCATION`/`ORGANIZATION` spans that are not names. Overall strict F1 loses
0.003 while relaxed F1 gains 0.007 — the signature of a boundary trade rather than a
detection loss, since promoted spans redact the right name with imprecise edges.

**The fragment-leakage rate no longer equals the full-value rate** (0.078 vs 0.067),
and ADR-0013 §5 requires that divergence be investigated rather than absorbed. It was,
by comparing the leaked-entity *sets* before and after: **no entity leaks that did not
leak before**, in either metric. Seven are fixed outright; two Greek PERSON values move
from fully leaked to partially redacted — the surname removed, the given name left.
The gap is incomplete progress on two pre-existing leaks, not new damage. If the
fragment gate ever fails while `leakage_rate` holds, that reasoning has stopped
applying and the leak must be investigated before the metric is touched.

**Two engines now load instead of one** (en+de, and el), so the same three models are
built across two cached analyzer instances. Total models loaded is unchanged — and for
an English-only dataset it now *falls*, because the chain short-circuits on language
before the Greek instance's engine is built, where the single instance used to load all
three models eagerly on first use.

**Drop counts had to be fixed to make this safe.** `LabelMapping` captured the provider
name at construction, but `build_provider` assigns the configured name afterwards, so
both instances filed their dropped labels under `presidio` — and `pipeline` merges the
per-provider counters into one, so the Greek instance's drops would have summed
silently into the English one's key. Latent with one instance; a real loss of the
signal ADR-0004 keeps drop counts for, with two. The mapping is now re-stamped with the
instance name on access, and a test pins it.

**The `multilingual_utterances` pack is affected too and was re-measured**, not left to
fail later. It is half Greek against the committed corpus's third, so the same
per-language cost lands harder: strict precision 0.926 → 0.893 and strict F1
0.930 → 0.923, against leakage 0.065 → 0.030, document clean rate 0.870 → 0.940, PERSON
recall 0.805 → 0.865 and Greek PERSON 0.606 → 0.727. **This is independent
corroboration on text nobody wrote for us**, in the same shape as the synthetic result.
The English packs are unchanged (`support_tickets` re-run, 10/10). Note that the
session-6 reading of the pack — that synthetic Greek templates, not the model alone,
explain part of the gap — survives: 0.727 against 0.444/0.667 is a narrower gap than
0.606 against 0.111/0.222, but still a gap.

**Still not addressed:** ADR-0019's mechanisms 1 (span absorption — Greek tier 4 stays
0.000) and 3 (the άνω τελεία). Promotion targets mechanism 2 only, and the `MISC`
finding above bounds how much of even that is reachable through Presidio. A
better-licensed Greek model at roadmap Phase 7 remains the structural fix, and the
benchmark can now say which of the three it addresses.

## Alternatives rejected

- **Token-level coverage surgery** — measured, works, unnecessary through the shipped
  adapter, and expensive where it is not (see above).
- **Global promotion** — breaks the over-redaction and strict-F1 gates and damages en
  and de precision for no Greek benefit that the scoped version does not already give.
- **A project-level `languages:` route** — corrupts the `deterministic_only` benchmark,
  because `with_chain` does not override language routes.
- **Promoting `NRP` as well** — never fires; would ship an unmeasured path.
- **Changing the mapping table without changing the request** — a silent no-op, per
  ADR-0019's Q4 finding.
- **Making the Greek corpus easier** — forbidden by ADR-0019 and not done.

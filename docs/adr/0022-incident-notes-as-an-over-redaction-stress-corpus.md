# ADR-0022: `incident_notes` is a generated over-redaction stress corpus, not a public pack

**Status:** accepted · **Date:** 2026-08-19 · **Session:** 8

> Supersedes the `incident_notes` pack family named in
> `docs/02_PUBLIC_DATA_STRATEGY.md`. ADR-0010, which names the *datasets* (Bitext,
> MultiWOZ, MASSIVE) rather than the pack families, is untouched by this.

## Context

`docs/02_PUBLIC_DATA_STRATEGY.md` names three demo pack families. Increment D
delivered two and parked the third with a reason (plan §8 Q3): *"incident metadata combined with generated work notes
needs no public source."* That is exactly the problem. Every other pack is built from
a pinned, checksummed public corpus, and `demo/registry.yaml` is explicitly the licence
record for those — *"nothing may be downloaded, injected into or published as a pack
unless it has an entry here."* A generated corpus has no source URL, no licence and no
retrieval block, so an entry there would corrupt what the registry means.

And the parking reason still half-applies. Increment D's own argument against the
synthetic corpus was that *"a template corpus cannot show this, because its non-PII
text was written by the same hand as its entities."* A generated incident corpus
inherits that limitation for anything it might claim about detection.

What changed is that a **measurement identified something a generated corpus can say
honestly.** Before this corpus:

| corpus | protected tokens | per document | kinds | documents with any |
|---|---|---|---|---|
| committed benchmark corpus | 102 | 1.00 | 5 | 66 of 102 |
| `support_tickets` | 56 | 0.28 | 1 | 26 of 200 |
| `support_conversations` | 56 | 0.28 | 1 | 26 of 200 |
| `multilingual_utterances` | **0** | 0.00 | 0 | 0 of 200 |

The 0.000 over-redaction gate rested almost entirely on one corpus carrying one
identifier per document — and ADR-0021 had just leaned on the reconciler's identifier
guard to keep it there.

## Decision

**Build it as an over-redaction stress corpus.** It is generated, committed at
`tests/fixtures/incidents/`, gated by `configs/incident_gates.yaml`, and is **not** a
pack: it has no registry entry, does not live under `demo/packs/`, and must never be
published or quoted beside the public packs.

> **Sequencing.** The gate file and its CI steps land in the commit *after* the corpus.
> The provenance guard added earlier this session requires a gate file's `commit:` to be
> a real hash, and a commit cannot name its own — so the corpus commit carries the code
> the floors were measured against, and the next commit adds the floors naming it.
> Between the two, the numbers below are recorded but **not enforced**.

The claim it makes is narrow and deliberately so. Operational identifier formats are
*conventions* — `INC00100037`, `CHG0030017`, `AST-B90029` — and `is_identifier_shaped`
judges a surface by token structure rather than meaning. Whether we or a real service
desk wrote the sentence around an asset tag does not change whether the tag survives
reduction. **It says nothing about detection realism**, and the gate file repeats that
at the top rather than leaving a reader who opens it first to infer it.

90 documents, 315 entities, **585 protected tokens across seven kinds at 6.5 per
document**, in en/de/el, at two tiers: a structured incident header (tier 3) and a
timestamped work-note history (tier 4). Three identifier kinds are new — `change`,
`request` and `asset` — chosen for shape variety rather than realism. `ORDER` exists as
a placeholder but no incident template uses it, which is why the count is seven kinds
and not eight.

It reuses `build_corpus` through a `templates`/`id_prefix`/`profile` parameter rather
than growing a parallel generator, so it inherits span validation, split assignment and
deterministic value sequencing. Ids are `inc_NNNN`, so a document from one corpus can
never be mistaken for one from the other in a manifest or a metric row.

## Consequences — two findings, both invisible before

### 1. Over-redaction is 0.024 on the hybrid chain, not 0.000

14 of 585 tokens destroyed, **all Greek tier-4 ticket ids**, each swallowed by a PERSON
span covering `Περιστατικό INC…` — the Greek for "Incident" plus the id.

**Attribution, corrected during review.** The first draft of this ADR blamed ADR-0020's
label promotion, on the strength of probing *one* document where the unpromoted adapter
returns no span. Running the whole corpus with `promote: []` says otherwise:

| configuration | over-redaction | destroyed |
|---|---|---|
| shipped | 0.024 | 14 |
| `promote: []` | 0.022 | **13** |
| `extend_person_left: false` | 0.024 | 14 |
| both off | 0.022 | 13 |

**13 of the 14 are native `PERSON` labels from `xx_ent_wiki_sm` and have nothing to do
with either ADR.** Exactly one (`inc_0062`) is promotion-attributable. ADR-0021's
extension accounts for none — `extended` is unset on all 14.

That correction matters more than the number: a future session reading the first draft
would have gone tuning promotion to recover a cost that is 1 token of 14. The real
cause is the base Greek model reading *"[the Greek word for Incident] INC…"* as a
person's name, which no promotion setting touches. **Generalizing from one document was
the error**, and it survived until an audit re-ran the corpus.

The reconciler's identifier guard does not stop it, *by design*. `is_identifier_shaped`
refuses a span only when **no** token is name-like, and `Περιστατικό` is name-like, so
the joined surface passes. `patterns.py` states that asymmetry and its reason: it
prefers over-redacting a year to leaking a name. **This is the first corpus to put a
price on that preference**, and the price is 14 ticket ids.

ADR-0020's claim that promotion held over-redaction at 0.000 was true of the corpora
that existed when it was written, and survives this almost intact: promotion costs one
destroyed token here. What does *not* survive is the broader reading that the hybrid
chain holds 0.000 everywhere — **it does not on identifier-dense Greek text, with or
without promotion.**

0.024 becomes a ceiling when the gate file lands, so it cannot grow. It is a recorded
position, not a budget.

### 2. A work-note author is never offered to a provider

PERSON strict recall is **0.000 at tier 4 in all three languages**, against 0.933–1.000
at tier 3. Not a detection failure and not repairable by any span rule: the transcript
parser classifies `2026-04-03 09:12:04 - Peter Novak:` as **structure**, so the name is
never presented for detection. It is verified structurally by a test, not inferred from
the metric.

That behaviour is *correct* when a speaker label is a role — `Customer`, `Agent`,
`Πελάτης` — which is the only shape the benchmark corpus contains. It is wrong when the
author is a person, which is precisely what a work-note author is. **Those names cannot
be redacted today**, and they are the bulk of this corpus's leakage.

This is deliberately **not fixed here**. Redacting inside a speaker prefix changes the
prefix, and `README.md`'s own success criteria ask whether *"transcript reconstruction
preserves speaker metadata exactly"*. Reconciling those two is a design decision that
deserves its own ADR, and making it in the same change that introduces the corpus
motivating it is how a benchmark-fitted fix gets built.

> **Decided in session 13: [ADR-0032](0032-the-speaker-prefix-stays-preserved-by-default.md).**
> The default stays *preserve*, and `preserve_prefix: false` — which has shipped since
> Increment A2 and which nobody had measured — is the ruled opt-in for transcripts
> whose speakers are people. On this corpus it takes strict F1 0.761 → 0.844, leakage
> 0.289 → 0.114 and the tier-4 PERSON rows below off 0.000 in all three languages; on
> the benchmark corpus, whose speakers are roles, it costs PERSON precision
> 0.771 → 0.744 for no recall gain. **The 0.000 rows below are therefore the measured
> price of a ruled default, not an open defect.** Nothing in this corpus, its gate file
> or its numbers changes.

### A metric caveat this corpus exposed

`fragment_leakage_rate` runs above `leakage_rate` on **both** chains here (0.463 vs
0.429; 0.314 vs 0.289), and unlike ADR-0020's gap it is not a partial redaction. The
emails are name-derived, so when a PERSON leaks, four-character windows of an unrelated
EMAIL survive *inside the leaked name*. The ambient exclusion removes windows found
outside every entity span, but not windows sitting inside a **different unredacted
entity**, so the leak is counted twice and attributed to the wrong entity. The metric
is not changed to suit a corpus introduced in the same commit; the caveat is recorded
beside both gates.

### Cost

A second committed corpus and a second gate file. CI checks it regenerates byte-for-byte from
its seed, exactly as it already does for the benchmark corpus. With the follow-up
commit it also runs the deterministic gates on every push — they are model-free and
this is the corpus with 585 protected tokens — and the hybrid gates nightly.

`GENERATOR_VERSION` moved to `2` because `meta` gained `profile`. Both committed
corpora were regenerated: the benchmark corpus's three CSVs are byte-identical and only
its `meta.json` changed, which is what that field exists to signal.

## Alternatives rejected

- **A full third pack with a registry entry** — would put a source-less, licence-less
  entry in the file that exists to record public-data licences, and would invite its
  detection numbers to be read as comparable to the public packs'.
- **Not building it** — leaves the over-redaction gate resting on 102 tokens at one per
  document, and would have left both findings above undiscovered.
- **Waiting for a public incident corpus** — none is in the registry and none was
  found; this would have deferred the item a third time.
- **Fixing either finding in this change** — see above. A corpus that motivates a fix
  and validates it in the same commit cannot show the fix was not fitted to it.

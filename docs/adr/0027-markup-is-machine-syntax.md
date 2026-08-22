# ADR-0027: Markup is machine syntax — clip detected spans out of it, and check the output independently

**Status:** accepted · **Date:** 2026-08-21 · **Session:** 12

## Context

This project has treated "structure must survive" as a *structural* guarantee since
Increment A2, and it is one: a parser divides a field into processable segments and
preserved structure, the reconstructor rebuilds the field from the original string,
and nothing in the code path can address a region no parser marked eligible
(`AGENTS.md` rule 5, `docs/01_ARCHITECTURE.md`). Round-trip tests pin it byte for byte.

**That guarantee stops at the edge of an eligible region, and this repository had
nothing inside one.**

The reference implementation at `..\pii_alternative` measured what lives there, on
45,366 rows of real ServiceNow and chat data
(`docs/20_ALTERNATIVE_RECONCILIATION.md` is the full comparison):

- spaCy read `[code]<div` as prose and returned it as a **PERSON at 0.85** — the same
  constant a real name gets, so no threshold separates them (ADR-0005 says why that is
  structural rather than bad luck);
- URLs came back as location spans that ate the leading `[` of a chat-client link;
- **384 note cells lost a `[code]` tag, 1,263 transcript cells lost a bracket, blast
  radius 2,687 of 105,279 processed cells** — all inside regions the parser had
  *correctly* offered for scanning;
- and their own sanitized corpus profile records **html/code markup in 72% of
  non-empty `Comments and Work notes` cells** on the largest sheet.

The same shape reaches this project directly. ADR-0025 makes Azure Databricks the
primary target and names ServiceNow/case descriptions as the data; `docs/18`'s runbook
tells an operator to point a dataset config at exactly such a column. Nothing in this
repository would have caught the damage:

- **the round-trip invariant cannot** — the damage is inside an eligible segment;
- **`over_redaction_rate` cannot** — it counts configured *protected tokens*
  (ticket ids, machine names, asset codes), and a `<div>` is not one;
- **no corpus contains markup** — the committed corpus, the three demo packs and the
  incident stress corpus are all markup-free, so the failure class has zero support in
  every number this project publishes.

## Decision

Two halves, deliberately built by different means.

### 1. The guard: clip a model-inferred span out of markup, at the provider boundary

`BaseProvider._clip_out_of_markup`, applied in `detect()` **after** the ADR-0016
line-bounding split and the ADR-0021 left-extension. It is the same family of repair
as both: **change the model's output, never its input** — the lesson plan §8 Q2
recorded when `split_lines` and `key_value` each traded one error for another.

**The ordering is load-bearing and the first draft had it wrong.** Clipping between the
two repairs is undone by the second: the extension widens a span leftward over one
capitalised token, and a token can end in a tag — `Γιώργος</b>` is capitalised, is not
identifier-shaped, and passes every one of ADR-0021's four structural refusals, so it
would be swallowed whole and the tag destroyed. Clipping **last** cannot be undone by
anything, and it costs nothing: ADR-0021 offers the widened span *and* the original, so
a widening clipped back to the original leaves the reconciler two identical candidates,
which `_find_identical` already treats as corroboration. Where a widening crosses a tag
the clip yields two fragments instead — over-redaction of a neighbouring token, which
is ADR-0021's accepted *visible* error, rather than structural damage, which is not.
A test drives exactly that case.

`patterns.markup_regions` supplies the regions (HTML and BBCode tags, URLs — composed
from the existing `URL_PATTERN` rather than restated — HTML entities, and zero-width
or bidi control runs), behind a cheap hint so prose costs one `search` and nothing
else.

Five decisions, each load-bearing:

1. **Clip, never drop.** `Grace Okafor</div>` must still lose the name; only the tag
   is handed back. Dropping the span would leak the name — the invisible error.
2. **Format-defined entities are exempt.** A string matching the email or phone
   grammar *is* that thing whatever sits beside it, so clipping one is a leak, which
   is strictly worse than the over-redaction the guard prevents. Expressed as a new
   `EntityDefinition.format_defined` flag and read through
   `taxonomy.markup_guarded_labels()`, in the same shape as `surface_may_span_lines`
   and for the same reason: it is a static fact about the entity, and restating it in
   the provider layer is how two definitions drift.
3. **Every surviving fragment is kept**, not the longest. **This diverges from the
   reference implementation**, which keeps one. It follows `_bound_to_line`'s
   reasoning instead: a name split by a tag is a name on both sides of it, and keeping
   the longer half alone leaves the other half in the output — a leak `leakage_rate`
   cannot see, because it matches only the exact full surface.
4. **Both plausibility drops apply only to a surface the markup produced** — a
   fragment the clip actually shortened, or a span lying wholly inside a region. A
   surface with fewer than two letters is not a name; once the angle brackets are
   gone, a model reads `div` and `href` as proper nouns. **Neither test may touch a
   span markup never touched**: the vocabulary holds real surnames (`Small`, `Link`,
   `Name`) and an ADDRESS surface is legitimately digit-only, so judging an untouched
   span by either would delete a real entity. The reference implementation applies
   both to every span in a markup-bearing cell; this narrowing is a deliberate
   divergence. On markup-free text the guard returns every span untouched either way.

5. **A span lying wholly inside a region is judged, not discarded.** Clipping leaves
   it with no fragments, and dropping it there is a **leak** — the whole point of
   decision 1, undone in the one case that produces no evidence. It is discarded only
   when its surface carries a bracket character (`code]<div` — the measured failure),
   is a tag or attribute name, or holds fewer than two letters. A plain surface
   sitting inside a URL path is a name; redacting it damages the URL, which is the
   visible error this project chooses every time it has the choice.

Firings are counted (`markup_clipped`, `markup_dropped`) through the same drop counter
ADR-0004 introduced, for the reason it gives: a repair nobody can see is a coverage
change nobody can notice.

### 2. The check: `validation.require_markup_preserved`, on by default

`processing/fidelity.py` compares the source column with the reduced column per row
and counts **known** markup tag names that disappeared. A loss stops the run
(`Pipeline._validate_output` raises, and ADR-0023's fail-closed posture carries it to
a non-zero exit).

This is a **fidelity** failure, and the severity split is the point: structural damage
blocks, a detector miss does not. Gating on recall means nothing ever ships, because
recall is never 1.0; not gating on fidelity means shipping damage that stays invisible
until someone downstream tries to parse the output.

**The check imports nothing from `patterns.py`** — its own expression, its own
vocabulary, pinned by a test. A validator that shares the detector's idea of markup
rubber-stamps a shared mistake, and the failure both halves exist for was precisely a
fixed pattern set meeting a dialect nobody had listed. Three details inside it each
cost the reference implementation a bug:

- it compares tag **names**, so a name legitimately redacted inside an attribute
  (`<a title='Peter Novak'>`) does not read as a lost tag;
- it strips angle-bracketed replacement labels from **both** sides, so `<PERSON>`
  landing inside an attribute cannot manufacture a failure — and stripping both sides
  keeps the comparison symmetric, so it cannot invent one either;
- it counts only **known** tags, so `<Grace Okafor>` written in prose is content
  that may be redacted rather than a tag to be defended.

Results carry counts only — rows affected and tags lost. No text, no fragment, no
offset, no tag name reaches a message (`AGENTS.md` rule 8).

### What the two reviews changed, recorded because it is the substance of the decision

Both required reviewers found this guard **leaking**, in three variants of one
mistake: a guard against over-redaction that causes under-redaction has made the trade
backwards, and every variant was in the direction the ADR's own decision 1 forbids.

1. **`<Grace Okafor>` was a tag.** The tag pattern matched any bracketed word run, so
   a chat-style display name read as markup, the span fell "wholly inside a region",
   and the name was discarded — written out unredacted. Fixed by requiring a known
   element name (`patterns._HTML_TAG_NAMES`, `_BBCODE_TAG_NAMES`). The cost is
   stated rather than hidden: an unknown markup dialect is no longer protected from
   over-redaction. That is the trade this project makes everywhere else.
2. **A name inside a URL path was discarded**, for the same "no fragments" reason.
   Fixed by decision 5 above.
3. **A quoted surname and a digit-only ADDRESS were deleted although markup never
   touched them.** The "did the clip shorten this?" flag was computed *after* the edge
   trim, so trimming a quote character counted as clipping and re-opened both
   plausibility drops to untouched spans. In a real ServiceNow column — where a URL
   somewhere in the cell is near-universal — that would have removed candidates
   silently on most rows. Fixed by decision 4 above.

Recorded here at length because the pattern is the lesson: **every one of the three
was the guard doing the invisible harm in order to prevent the visible one**, and none
was visible to a corpus, a gate or a metric. They were found by reading the diff
against the doctrine it claimed to follow.

A fourth, smaller finding: clipping last can produce a widened span clipped back to
the span it was widened from, so `detect()` now drops exact duplicates — otherwise one
provider appears in `supporting_matches` as its own corroboration, which is the one
thing that field is not.

## What was measured

**Nothing moved, and that is the claim being made.** All 41 gates re-run before and
after, on this machine, with `md` models:

| gate set | chain | result |
|---|---|---|
| `configs/benchmark_gates.yaml` | `deterministic_only` | 10/10, every value identical |
| `configs/benchmark_gates.yaml` | `deterministic_presidio` | 15/15, every value identical |
| `configs/incident_gates.yaml` | `deterministic_only` | 6/6, identical |
| `configs/incident_gates.yaml` | `deterministic_presidio` | 10/10, identical |

That is the expected result and the reason the guard can ship on by default: **no
committed corpus contains markup**, so `markup_regions` returns empty and the guard
returns every span untouched. The property is asserted directly rather than inferred
from the gates (`tests/test_markup_guard.py::TestTheGuardRefuses`).

**What has *not* been measured is what the guard does to text that does contain
markup.** The reference implementation's own figures for its corpus — PERSON −3.3%,
ADDRESS −1.6%, EMAIL +42, PHONE +41, the last two because a bogus PERSON span that
used to swallow an email now gets clipped and the email wins overlap resolution — are
recorded in `docs/20` as *their* measurement, on *their* data, and are not adopted as
a number here. This repository has no markup corpus to reproduce them on.

## Consequences

- **A capability with no corpus support.** The guard is exercised by 50 synthetic unit
  tests and by nothing else; the first real evidence will come from a markup-bearing
  corpus or from a real run. That is the honest state and it is recorded here rather
  than discovered later. Building such a corpus is the natural follow-on (`docs/20`
  §5).
- **The exemption has a visible price, and the two halves cover each other.** An
  EMAIL or PHONE span that swallows a tag still damages it — the guard will not touch
  it, by decision 2 — and the output check is what notices. A test drives exactly that
  case end to end.
- **A false fidelity failure would stop a legitimate run.** Three mitigations above
  bound it (names only, labels stripped both sides, known tags only), and the setting
  can be turned off per project. Turning it off is a decision, not a workaround: it
  says this dataset accepts structural damage inside eligible regions.
- **Throughput.** The reference implementation measured 30–65% on its transcripts, of
  which per-entity Python overhead was the irreducible part. This implementation scans
  once per `detect()` call behind a hint rather than once per entity, and the default
  test tier's wall clock is unchanged (16.7s → 16.5s). No large-corpus measurement of
  the markup path exists here, because no such corpus exists here.
- **The heuristic is bounded by its pattern set.** A markup dialect it does not know
  can still be damaged. That is exactly why the check is written independently: it is
  the thing that would say so.

## Alternatives rejected

- **Making the guard opt-in per provider instance**, like ADR-0021's extension. That
  ships a capability nobody enables, and unlike the extension's capitalisation rule
  this one has no language dependence to scope it by. It is a no-op where it is not
  needed, which is a better default than off.
- **Dropping spans that touch markup instead of clipping them.** Leaks the name beside
  the tag — the invisible error, again.
- **Adopting the reference implementation's chat-client bracketed-link pattern**
  (`@Name[/vd.php?id=..|123]`). Corpus-specific, and it is the alternation most likely
  to swallow a bracketed email. Recorded in `docs/20` as not transferred.
- **Excluding markup at the parser instead.** That re-cuts the input, which plan §8 Q2
  measured as trading one error for another: a model's accuracy depends on the text it
  is shown, and a remedy that changes the input loses context, while one that changes
  the output cannot.
- **Sharing one vocabulary between the guard and the check.** Cheaper, and it defeats
  the only reason the check exists.

# ADR-0018: MultiWOZ is out; Bitext supplies both the ticket pack and the conversation pack

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 6
**Supersedes in part:** ADR-0010

## Context

ADR-0010 chose three demo sources: Bitext for `support_tickets`, MultiWOZ 2.2 for
`support_conversations`, MASSIVE for the multilingual slice. It scored MultiWOZ's PII
risk as "fictional booking details; treat names as real-shaped".

That assessment was wrong about the *numbers*, and `demo/registry.yaml` now records
the correction under `rejected:`, from the session-5 privacy audit against
`budzianowski/multiwoz@master`: MultiWOZ's dialogues are fictional but they are
grounded in a scrape of real Cambridge (UK) venue listings, and the wizard reads those
database values aloud, so they reach the published utterance text. The recorded count
is 192 utterances carrying real Cambridge landlines (112 distinct numbers) and 191
carrying real UK postcodes in a single dev file, plus a real police station with
address and landline in `db/police_db.json`. That finding is taken as given here; this
ADR records what follows from it, and this session deliberately did **not** download
MultiWOZ to re-verify it, because re-verifying would mean retrieving the very data the
finding says not to retrieve.

Two independent consequences, either one disqualifying:

1. **Publishing a pack would redistribute real dialable numbers as demo text.** That
   is the harm ADR-0014 was written after — session 3 shipped 17 real Berlin numbers
   in fixtures — at an order of magnitude more numbers.
2. **The benchmark would measure a contaminant.** Those values are not in the
   injection manifest, so every one a provider correctly finds scores as a false
   positive. The pack's precision would be a function of how much real PII the base
   text carries, which is not a property of this project's engine.

`contains_real_pii` is a registry gate that `require_publishable()` enforces, so with
the entry moved to `rejected:` the pack simply cannot be built. What was left open is
the hole it leaves: `support_conversations` existed to test the transcript parser's
speaker heuristic on text nobody wrote for it, and no permissively-licensed public
support-dialogue corpus was found to replace it.

## Decision

**Bitext supplies both English packs.** One source, two renderings:

- `support_tickets` — the customer message and the agent response as two paragraphs of
  a free-text note. `document_type: plain`, tier 1.
- `support_conversations` — the same two fields as two transcript turns,
  `Customer: …` / `Agent: …`. `document_type: transcript`, tier 4.

The turn structure is a *rendering*, not an invention: Bitext's own columns are named
`instruction` and `response`, so labelling them customer and agent restates what the
source already says. It is recorded as the transformation `docs/02` requires, and the
pack meta names it.

**MASSIVE keeps the de/el slice** unchanged (`multilingual_utterances`, tier 2, one
utterance per document).

## Consequences

- **The transcript parser still gets tested on text this project did not write**,
  which was the whole point of the conversation pack. It gets a harder version than
  MultiWOZ would have given: 7,104 of the 26,872 Bitext responses contain newlines, so
  continuation lines with no speaker prefix exercise the parser's
  `no_speaker_prefix` fallback rather than only its happy path.
- **The two English packs are not independent.** They are the same sentences under two
  parsers, and a difference between their numbers is attributable to *parsing*, which
  is a useful comparison in its own right — but it must never be read as two
  independent corpora agreeing. Documented wherever the numbers are published.
- **Both English packs inherit CDLA-Sharing-1.0.** Bitext is share-alike, so a derived
  pack carries the obligation. ADR-0010 named MultiWOZ (MIT) as the fallback if that
  proved awkward. **That fallback no longer exists.** Since no pack is committed —
  every pack is rebuilt locally from source — the obligation currently travels no
  further than the machine that built it, but there is now no MIT-licensed escape route
  if a published pack is ever wanted.
- **A replacement transcript source stays on the wish list**, permissively licensed and
  free of real PII. Failing that, a documented scrubbing transformation over MultiWOZ,
  validated before use, is the only route back — and it would have to remove the
  contamination from the *measurement*, not merely from the published text.
- **ADR-0010's dataset table is superseded for MultiWOZ only.** Bitext and MASSIVE, and
  the rejection of the Kaggle Twitter corpus, stand as written.

## Alternatives rejected

- **Scrubbing MultiWOZ now.** A scrubber is a PII detector, and using this project's
  own detector to clean its own benchmark corpus makes the benchmark circular: every
  entity the scrubber misses is a false positive the pack then charges to the engine.
- **Dropping the conversation pack.** The transcript parser is the component with the
  most project-specific behaviour and the least public-text evidence behind it. Leaving
  it measured only on templates this project wrote is exactly the gap Increment D
  exists to close.
- **Synthesising dialogues from the MASSIVE utterances.** They are single-turn
  assistant commands with no addressee; stacking them into turns would produce text
  nobody wrote *and* nobody would write.

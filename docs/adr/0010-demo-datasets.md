# ADR-0010: Demo datasets — Bitext (tickets), MultiWOZ 2.2 (conversations), MASSIVE (multilingual)

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

> **Superseded in part by ADR-0018 (session 6): MultiWOZ 2.2 is rejected.** The PII
> risk scored below as "fictional booking details" was wrong about the numbers — the
> dialogues are grounded in a scrape of real Cambridge venue listings and the wizard
> reads those values aloud, so real landlines and postcodes reach the published
> utterance text (`demo/registry.yaml`, `rejected:`). `support_conversations` is now
> rendered from Bitext's own `instruction`/`response` columns as transcript turns.
> Bitext, MASSIVE and the rejection of the Kaggle Twitter corpus stand as written —
> and so does the retrieval mechanism question, answered in ADR-0017.

## Context

`docs/02_PUBLIC_DATA_STRATEGY.md` sets the policy (public-safe text + deterministic
synthetic PII injection); it names no datasets. Candidates verified in session 2
against licence and redistribution status:

| Dataset | Licence | Redistribution | Content | PII risk |
|---|---|---|---|---|
| Bitext customer-support (HF) | CDLA-Sharing-1.0 | permitted (share-alike, data-only) | 26,872 EN support Q/A pairs, 27 intents, **synthetic with `{{Order Number}}`-style placeholders** | none — templated |
| MultiWOZ 2.2 (GitHub) | MIT | permitted | 10k EN human-written task dialogues, multi-turn | fictional booking details; treat names as real-shaped |
| MASSIVE (Amazon, HF) | CC BY 4.0 | permitted with attribution | 54 languages incl. **de-DE and el-GR**, ~16.5k short utterances each | none observed; short assistant commands |
| Customer Support on Twitter (Kaggle) | CC BY-NC-SA | **rejected** | real tweets | real handles/PII + non-commercial |

## Decision

- **First demo (Increment D `support_tickets` pack): Bitext.** Its placeholders are
  natural injection points — the injection engine substitutes synthetic entities at
  template markers and records exact spans, which is precisely the
  `docs/02` pattern. English-only is acceptable for the first pack.
- **`support_conversations` pack: MultiWOZ 2.2**, rendered into the transcript
  format to exercise the transcript parser at scale.
- **Multilingual pack: MASSIVE de/el** utterances as short-text realism, combined
  with the committed template-generated multilingual corpus (Increment A6) for
  transcript-form de/el text, which no permissively-licensed public support corpus
  provides — recorded as a known limitation.
- Raw datasets are never committed; download scripts + registry entries
  (source, licence, version, checksum, `contains_real_pii`, transformations) per
  `docs/02`. Only small generated fixtures live in Git.

## Consequences

- Every demo pack is reproducible without credentials and is licence-clean.
- Decision point at Increment D: if CDLA-Sharing share-alike terms complicate
  redistributing *injected derivatives*, the ticket pack falls back to
  MultiWOZ-derived text (MIT); the registry keeps both wired.
- Attribution entries for MASSIVE (CC BY) and Bitext ship with the demo docs.

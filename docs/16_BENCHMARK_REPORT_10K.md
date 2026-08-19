# Benchmark report: two chains on 10,000 public documents

Increment E's exit artifact: both provider chains compared end-to-end on a
10,000-document pack built from public text, with the committed report this file is.

## What was run

| | |
|---|---|
| **Corpus** | `support_tickets` pack at 10,000 documents (`pii-reduction build-pack support_tickets --documents 10000 --out demo/packs/support_tickets_10k`) |
| **Source** | Bitext customer-support corpus, pinned revision `430d1a89bd93` (ADR-0017); 30,000 injected entities, 2,079 protected order numbers |
| **Strategy** | `redact` |
| **Splits** | all — this is a chain comparison, not a protocol read (see plan §8 for the one-time test-split read) |
| **Machine** | Windows 11, CPU only (ADR-0015); wall-clock numbers are context, never gates (ADR-0009) |
| **Date / session** | 2026-08-19, session 6 |
| **Code** | the commit that adds this file; the gate file records it (a commit cannot name its own hash) |
| **Models** | presidio-analyzer 2.2.364, spaCy 3.8.15, `en_core_web_md` 3.8.0 |

The pack is rebuilt from source, never committed (ADR-0017): `demo/packs/` is
gitignored, and the numbers below are reproducible from the commands above — the
pack build is deterministic per document id, and both runs print the config
fingerprints they ran under.

## Headline comparison

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict precision | 0.999 | 0.996 |
| strict recall | 0.667 | 1.000 |
| strict F1 | 0.800 | 0.998 |
| relaxed F1 | 0.800 | 0.998 |
| leakage rate | 0.333 | 0.000 |
| fragment leakage rate | 0.373 | 0.000 |
| document clean rate | 0.000 | 1.000 |
| over-redaction rate (2,079 tokens) | 0.000 | 0.000 |
| throughput (rows/s, lightly loaded machine) | 2,147 | 29 |

Per entity, strict:

| entity | det. precision | det. recall | hybrid precision | hybrid recall |
|---|---|---|---|---|
| EMAIL | 0.998 | 1.000 | 0.998 | 1.000 |
| PERSON | — | 0.000 | 0.989 | 1.000 |
| PHONE | 1.000 | 1.000 | 1.000 | 1.000 |

## What 10,000 rows shows that 200 could not

1. **Precision is structurally capped by the source corpus itself.** The
   deterministic chain's 21 EMAIL "false positives" are Bitext's own example
   addresses — `…@company.com`, `…@example.com` in the support-agent replies. The
   recognizer is right; the manifest simply does not own those strings. This is the
   contaminant phenomenon ADR-0018 predicted for MultiWOZ, in benign synthetic form,
   and it surfaces at a rate (21 in 10,000 documents) that a 200-document pack
   samples about zero of. Any precision number measured on injected-ground-truth
   public text carries this cap, and it is a property of the *measurement*, not of
   the engine.

2. **The fragment metric sees cross-entity recovery.** Deterministic fragment
   leakage (0.373) exceeds full-value leakage (0.333, the undetected PERSON third).
   The excess is emails recoverable *through* leaked names: the pool derives email
   local parts from person names, so when `Grace Okafor` survives (no NER in this
   chain), windows of her redacted `grace.okafor@…` survive inside the name. That is
   a real recoverability fact — real-world addresses derive from names too — and
   exactly what ADR-0013 §5's second variant exists to count. The hybrid chain
   redacts the names and both rates fall to 0.000 together.

3. **The throughput ratio, not the absolute numbers, is the decision.**
   ~2,147 rows/s deterministic against ~29 rows/s hybrid on this pack's ~600-character
   documents — roughly **74×** — with model loading amortised to nothing over 10,000
   rows. Document length matters as much as the chain: the same hybrid pipeline runs
   at ~140 rows/s on the committed corpus's ~100-character documents. Under ADR-0015
   (CPU-only) the ratio is what a deployment sizes against: the hybrid chain buys
   leakage 0.333 → 0.000 at ~74× the compute here. Wall-clock was measured on a
   lightly loaded machine; a run taken while the box was saturated measured 5 rows/s
   for the same work — which is exactly why these numbers are context and never
   gates (ADR-0009).

4. **Over-redaction held at 0.000 across 2,079 protected tokens** — ten times the
   support the 200-document pack could offer the preservation gate.

## Limitations

- One document type (plain notes), one language, one strategy. The multilingual and
  transcript findings live with their packs (plan §8); the strategy comparison lives
  in `docs/08` and plan §8.
- Injected values still come from the eight-name committed pools (ADR-0014), so
  PERSON recall partly reflects names the model has seen in this project's corpora.
  See the pack limitations in plan §8.
- The gates for this pack (`configs/pack_gates/support_tickets_10k.yaml`) run on
  demand like every pack gate set: building the pack needs a download, and CI is
  deliberately offline (ADR-0017).

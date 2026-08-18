# Provider Registry

One record per shipped provider, covering what `AGENTS.md` requires before a provider
is merged: supported languages, entity mapping, confidence semantics, dependencies,
known limitations, expected runtime mode, and measured benchmark results.

Numbers here come from the committed corpus (`tests/fixtures/corpus/`, 102 documents,
180 injected entities, en/de/el, tiers 1–4) via `pii-reduction benchmark`. They are
reproducible with the commands shown.

---

## `deterministic` — pattern and library recognizers

| | |
|---|---|
| **Type** | `deterministic` |
| **Entities** | EMAIL, PHONE |
| **Languages** | any (language-independent) |
| **Dependencies** | `phonenumbers` (core install; no model, no extra) |
| **Runtime** | pure CPU, microseconds per document |
| **Increment** | A3 |

### Entity mapping

No mapping table: the recognizers emit normalized labels by construction.

### Confidence semantics

Fixed by construction, not learned (ADR-0005):

- EMAIL → `1.0`. An anchored structural match either holds or it does not.
- PHONE → `1.0` when `phonenumbers` validates the number for a configured region,
  `0.85` when the text is only a *possible* number for that region.

### Configuration

```yaml
providers:
  deterministic:
    type: deterministic
    entities: [EMAIL, PHONE]
    options:
      regions: [GR, DE, GB, US]   # one matcher pass per region, plus a region-less pass
      leniency: valid             # 'possible' also reports unvalidated numbers at 0.85
```

### Known limitations

- `leniency: possible` measurably matches ordinary identifiers — the probe reported
  `6915` from `DEMO-PC-6915`, `12345` from `Order 12345`, and fragments of
  `2026-04-03 09:15:04`. `valid` is the default for that reason; opt in per dataset
  only when recall matters more than precision.
- The email pattern accepts any dot-TLD of two or more ASCII letters, including
  `.test` and `.invalid` — deliberately broader than Presidio (ADR-0003). It does not
  handle internationalized (non-ASCII) addresses.
- National-format phone numbers are only found for configured regions.

### Measured results

`pii-reduction benchmark`

| entity | strict precision | strict recall | strict F1 | support |
|---|---|---|---|---|
| EMAIL | 1.000 | 1.000 | 1.000 | 51 |
| PHONE | 1.000 | 1.000 | 1.000 | 51 |
| PERSON | 0.000 | 0.000 | 0.000 | 78 |

Overall strict F1 0.723, leakage 0.433, document clean rate 0.161, over-redaction
0.000. Every leaked entity is a PERSON.

---

## `presidio` — Microsoft Presidio over spaCy

| | |
|---|---|
| **Type** | `presidio` |
| **Entities** | PERSON, EMAIL, PHONE |
| **Languages** | en, de, el |
| **Dependencies** | `presidio-analyzer`, `spacy` (extra), plus models installed by command |
| **Runtime** | engine cached per process/worker; ~8 s to build, 7–30 ms per short text |
| **Increment** | B |

### Installation

```bash
pip install -e ".[presidio]"
python -m spacy download en_core_web_md
python -m spacy download de_core_news_md
python -m spacy download xx_ent_wiki_sm
```

`md` models are the CI tier; `lg` (`en_core_web_lg`, `de_core_news_lg`) are used for
benchmark runs and expose identical label sets (ADR-0009). Nothing downloads a model
automatically; a missing model raises `ProviderNotAvailableError` with the commands
above.

### Models and licensing

| Language | Model | Licence |
|---|---|---|
| en | `en_core_web_md` / `en_core_web_lg` | MIT |
| de | `de_core_news_md` / `de_core_news_lg` | MIT |
| el | `xx_ent_wiki_sm` | MIT |

`el_core_news_md`/`lg` are **CC BY-NC-SA 3.0 (non-commercial)** and are incompatible
with this project's MIT licence (ADR-0007). The provider refuses to be configured
with them, with a message saying why. Greek therefore runs through the multilingual
model, at the quality cost measured below.

### Entity mapping (ADR-0004)

| Presidio label | Normalized |
|---|---|
| `PERSON` | PERSON |
| `EMAIL_ADDRESS` | EMAIL |
| `PHONE_NUMBER` | PHONE |
| `URL`, `LOCATION`, `NRP`, `DATE_TIME`, `IP_ADDRESS` | dropped, and counted |

The adapter requests only the three native labels it maps, so `URL` — which produced
partial-match noise such as `maria.ro` from an email address — never arrives. The drop
table is a safety net for future Presidio versions, and every drop is counted through
a shared drop counter rather than silently discarded.

### Confidence semantics

Presidio scores are **recognizer constants, not calibrated probabilities**
(ADR-0005), confirmed again by the Increment B tests:

| Recognizer | Score |
|---|---|
| spaCy-backed NER (PERSON) | exactly `0.85`, correct or not |
| `EmailRecognizer` | `1.0` |
| `PhoneRecognizer` | `0.40` |

A single global threshold of 0.5 would therefore drop every phone number. Thresholds
are per provider and per entity, and are applied **once, by the reconciler**, which
records what each threshold rejected. The adapter itself does no filtering.

```yaml
providers:
  presidio:
    type: presidio
    languages: [en, de, el]
    entities: [PERSON, EMAIL, PHONE]
    thresholds:      # uncalibrated until Increment E
      PERSON: 0.5
      EMAIL: 0.6
      PHONE: 0.3
    options:
      models:
        en: en_core_web_md
        de: de_core_news_md
        el: xx_ent_wiki_sm
```

### Known limitations

- **Greek PERSON detection is weak** — see the numbers below. The multilingual model
  finds few Greek names and its boundaries wander; a probe saw the preceding verb
  (`Ονομάζομαι`) absorbed into the span.
- The flat 0.85 NER score means false positives cannot be filtered by confidence. The
  probe found the word "Email" tagged PERSON at 0.85 in one sentence.
- The default email recognizer rejects `.test` and `.invalid` domains, which is why
  the deterministic provider stays first in the chain (ADR-0003).
- An unsupported language returns nothing rather than raising; the chain's other
  providers still run and the run metrics record the language distribution.

### Measured results

`pii-reduction benchmark --chain deterministic_presidio`

| entity | strict precision | strict recall | strict F1 | support |
|---|---|---|---|---|
| EMAIL | 1.000 | 1.000 | 1.000 | 51 |
| PHONE | 1.000 | 1.000 | 1.000 | 51 |
| PERSON | 0.833 | 0.705 | 0.764 | 78 |

PERSON strict recall by language and tier:

| language | tier 1 (clean) | tier 2 (noisy) | tier 3 (structured) | tier 4 (transcript) |
|---|---|---|---|---|
| en | 1.000 | 0.889 | 1.000 | 1.000 |
| de | 1.000 | 1.000 | 1.000 | 1.000 |
| **el** | **0.222** | **0.111** | **0.167** | **0.000** |

Chain comparison, whole corpus:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | **0.902** |
| relaxed F1 | 0.723 | **0.914** |
| leakage rate | 0.433 | **0.117** |
| document clean rate | 0.161 | **0.774** |
| over-redaction rate | 0.000 | **0.000** |

Three things this table says plainly:

1. Adding an NER provider is what moved leakage from 43.3% to 11.7%; deterministic
   recognizers alone cannot cover names.
2. **The strict–relaxed gap is boundary quality** — spans covering the right name with
   the wrong edges. It was zero while only deterministic spans existed (ADR-0011),
   opened to 0.886 vs 0.921 the moment a model joined, and is 0.902 vs 0.914 after
   ADR-0016's span repair. Repair narrowed the *strict* side by fixing boundaries and
   widened the relaxed side slightly, because keeping every line fragment of a
   crossing span redacts the occasional neighbouring label. That is the deliberate
   safe-direction trade; the rest is Greek boundary fuzziness.
3. **Greek is the outstanding gap**, and it has been read as a licensing consequence
   rather than a modelling oversight. Until a permissively-licensed multilingual model
   arrives (roadmap Phase 7), Greek PERSON coverage should be described as weak and the
   Greek demo positioned as deterministic-entities-only.

   **The public-dataset packs complicate that reading and it is now an open question**
   (plan §8 Q4). On MASSIVE utterances — real Greek written by native speakers for
   another purpose — the *same* `xx_ent_wiki_sm` model reaches **0.606** Greek PERSON
   strict recall over a support of 66, with German at 1.000 on the same text. The two
   corpora are not comparable slice for slice, so this is not a claim that Greek
   detection improved; it is a reason to find out how much of the 0.111-0.222 belongs to
   the model and how much to the synthetic Greek templates.

   English tier 3 (key/value blocks) was the second weakest slice at 0.333 and is now
   1.000: the model had been finding every name and running the span through the line
   break, so the fix was to trim the span rather than to detect harder (ADR-0016).

### Measured on public text

The table above is the committed synthetic corpus — templates this project wrote. The
demo packs (plan §8, ADR-0018) run the same chain over text written by other people,
with synthetic PII injected so ground truth stays exact. Rebuild and measure:

```bash
python demo/build_pack.py support_tickets
pii-reduction benchmark --corpus demo/packs/support_tickets --chain deterministic_presidio
```

| pack | strict F1 | PERSON precision | PERSON recall | leakage | over-redaction |
|---|---|---|---|---|---|
| `support_tickets` (en, plain) | 0.998 | 0.985 | 1.000 | 0.000 | 0.000 (56 tokens) |
| `support_conversations` (en, transcript) | 0.999 | 0.995 | 1.000 | 0.000 | 0.000 (56 tokens) |
| `multilingual_utterances` (de/el, plain) | 0.930 | 0.781 | 0.805 | 0.065 | no support |

What changes when the text is not ours: **recall stops being the hard part and precision
starts.** Every injected English name is found; the errors are spans in the public prose
that no manifest knows about. The synthetic corpus cannot show this failure mode at all,
because its non-PII text was written by the same hand as its entities.

These packs carry their own gate sets under `configs/pack_gates/`, run on demand — they
need a download, and CI is offline (ADR-0017). The limitations that keep these numbers
honest are listed in `docs/14_IMPLEMENTATION_PLAN.md` §8; the most important is that
injected values come from the same eight-name pools as the synthetic corpus, so a pack
measures the realism of the surrounding text and not the diversity of the values.

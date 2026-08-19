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
| **Languages** | en, de (Greek is served by a second instance, `presidio_el` — see below) |
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

The adapter requests only the native labels it maps, so `URL` — which produced
partial-match noise such as `maria.ro` from an email address — never arrives. The drop
table is a safety net for future Presidio versions, and every drop is counted through
a shared drop counter rather than silently discarded. Drops are attributed to the
*configured instance name*, not the provider type, so two instances of this adapter
cannot pool their counts.

#### Label promotion (`promote`, ADR-0020)

The table above describes an instance with promotion off, which is the default and is
what the `presidio` instance ships. A `promote` list moves native labels from the drop
row into the mapping:

| Presidio label | Normalized, with `promote: [LOCATION, ORGANIZATION]` |
|---|---|
| `LOCATION` | PERSON |
| `ORGANIZATION` | PERSON |

Promotion widens the analyzer **request**, not just the table — an unrequested label
never arrives, so a table-only change would be a silent no-op (ADR-0019 Q4). Promotable
labels are `LOCATION`, `ORGANIZATION` and `NRP`; anything else is refused, because
promoting `URL` or `DATE_TIME` is a category error rather than a coverage choice.
A promoted span carries `promoted: True` in its `EntityMatch.metadata`.

**It is enabled for Greek only.** Applied to every language it was measured to cost
English PERSON precision 0.833 → 0.694 and German 0.963 → 0.839, and to take
over-redaction off its 0.000 gate. Scoped to Greek, English and German are numerically
unchanged. `NRP` is promotable but not enabled: Presidio derives it from spaCy's
`NORP`, which `xx_ent_wiki_sm` does not emit, so it never fires.

**What promotion cannot reach:** spaCy's `MISC`. On the Greek slice the model emits
`PER 8, MISC 41, LOC 20, ORG 1` and Presidio surfaces only the first, third and
fourth — `MISC` has no Presidio entity name and is discarded inside Presidio, before
this adapter. That is a ceiling on every label-level remedy here.

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

As shipped, two instances of this adapter split the languages between them (ADR-0020).
`language_scopes` routes each document to exactly one, so this is not a second opinion
on the same text:

```yaml
providers:
  presidio:
    type: presidio
    languages: [en, de]
    entities: [PERSON, EMAIL, PHONE]
    thresholds:
      PERSON: 0.5
      EMAIL: 0.6
      PHONE: 0.3
    options:
      models:
        en: en_core_web_md
        de: de_core_news_md

  presidio_el:
    type: presidio
    languages: [el]
    entities: [PERSON, EMAIL, PHONE]
    thresholds:      # must match the instance above; a test asserts it
      PERSON: 0.5
      EMAIL: 0.6
      PHONE: 0.3
    options:
      models:
        el: xx_ent_wiki_sm
      promote: [LOCATION, ORGANIZATION]

chains:
  deterministic_presidio:
    providers: [deterministic, presidio, presidio_el]
```

One consequence worth knowing: an English-only dataset now never loads
`xx_ent_wiki_sm` at all, because the chain short-circuits on language before the Greek
instance's engine is ever built.

### Known limitations

- **Greek PERSON detection is weak — but not because the model fails to find the
  names** (ADR-0019). It usually returns a span covering the name and then gets the
  boundary or the label wrong: the preceding verb `Ονομάζομαι` is absorbed into the
  span, and two of the eight pool names come back exactly placed but labelled `ORG`
  or `LOC`. See the diagnosis below; a remedy aimed at detection will move little.
  **The label half of this shipped** (ADR-0020): promoting `LOCATION`/`ORGANIZATION`
  took Greek tier 1 from 0.222 to 0.444 and tier 2 from 0.111 to 0.667. The boundary
  half did not — tiers 3 and 4 are unchanged, and tier 4 remains 0.000, because no
  label change can repair a span that swallowed the preceding verb.
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
| PERSON | 0.747 | 0.795 | 0.770 | 78 |

PERSON strict recall by language and tier:

| language | tier 1 (clean) | tier 2 (noisy) | tier 3 (structured) | tier 4 (transcript) |
|---|---|---|---|---|
| en | 1.000 | 0.889 | 1.000 | 1.000 |
| de | 1.000 | 1.000 | 1.000 | 1.000 |
| **el** | **0.444** | **0.667** | **0.167** | **0.000** |

Greek tiers 1 and 2 moved with ADR-0020's label promotion (from 0.222 and 0.111).
Tier 3 and tier 4 did not, and that is the expected shape rather than a shortfall:
promotion addresses ADR-0019's *label confusion* only. Tier 4 is span absorption — the
model swallows the capitalised verb before the name — which no label change can reach.

Chain comparison, whole corpus:

| metric | `deterministic_only` | `deterministic_presidio` |
|---|---|---|
| strict F1 | 0.723 | **0.899** |
| relaxed F1 | 0.723 | **0.921** |
| leakage rate | 0.433 | **0.067** |
| fragment leakage rate | 0.433 | **0.078** |
| document clean rate | 0.161 | **0.871** |
| over-redaction rate | 0.000 | **0.000** |

`document clean rate` is derived from the full-surface leakage metric, so it means "no
complete PII value survives", not "nothing identifying survives". Two of the nine
documents that became clean with ADR-0020 still contain a Greek given name whose
surname was redacted — the same two behind the fragment/full gap above. Stated here
because this is the metric most likely to be quoted on its own.

Three things this table says plainly:

1. Adding an NER provider is what moved leakage from 43.3% to 6.7%; deterministic
   recognizers alone cannot cover names. (It was 11.7% before ADR-0020 promoted
   Greek `LOCATION`/`ORGANIZATION` labels to PERSON.)
2. **The strict–relaxed gap is boundary quality** — spans covering the right name with
   the wrong edges. It was zero while only deterministic spans existed (ADR-0011),
   opened to 0.886 vs 0.921 the moment a model joined, became 0.902 vs 0.914 after
   ADR-0016's span repair, and is 0.899 vs 0.921 after ADR-0020's promotion. Repair
   narrowed the *strict* side by fixing boundaries and widened the relaxed side
   slightly, because keeping every line fragment of a crossing span redacts the
   occasional neighbouring label. Promotion then moved both the other way — strict
   down 0.003, relaxed up 0.007 — which is the signature of spans that cover the right
   name with imprecise edges. Both are deliberate safe-direction trades; the rest is
   Greek boundary fuzziness.

   **The fragment-leakage rate no longer equals the full-value rate** (0.078 vs 0.067).
   That gap was investigated rather than absorbed, as ADR-0013 §5 requires: no entity
   leaks that did not leak before promotion. Seven are fixed outright and two Greek
   values go from fully leaked to partially redacted, the surname removed and the
   given name left.
3. **Greek is the outstanding gap, and it is three bugs rather than one weakness**
   (ADR-0019, plan §8 Q4). It had been read as a pure licensing consequence; the
   diagnosis says otherwise. Probed directly, `xx_ent_wiki_sm` almost always returns a
   span covering the Greek name and then gets the label or the boundary wrong —
   "nothing found" is the rare case, and German on the same model and sentence shape is
   8/8.

   | mechanism | measured | remedy family |
   |---|---|---|
   | **span absorption** — `Ονομάζομαι {name}` returns `PER 'Ονομάζομαι Ελένη Παππά'` | 7/8, and all of tier 4 | ADR-0016: repair the output |
   | **label confusion** — an exact span with a non-`PER` label (`ORG`, `LOC`, and `MISC` in other carriers), which never reaches the normalized taxonomy | 2/8 in a neutral sentence | evidence-gated promotion, untested |
   | **άνω τελεία** — `Παππά· δεν` scores 3/8 where `Παππά, δεν` scores 6/8 | halves detection *in the one tier-1 template that uses it* | none; it is correct Greek |

   So Greek PERSON coverage should still be described as weak and the Greek demo
   positioned as deterministic-entities-only — but a remedy should target boundaries and
   labels first. Detection is the smallest of the three: only 4 of 48 probes returned no
   span at all, and tier 4 is 100% boundary error, so better *finding* cannot touch it.

   On the `multilingual_utterances` pack the same model reaches **0.727** over a support
   of 66 (0.606 before ADR-0020). That is not a better Greek result; it is easier Greek
   — single short clauses with none of the three triggers. It must not be quoted as the Greek number, and the
   synthetic corpus is deliberately **not** made easier to close the difference, because
   that would tune the benchmark to the model.

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

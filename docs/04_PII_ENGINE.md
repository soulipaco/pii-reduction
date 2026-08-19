# PII Engine

## Goal

The PII engine converts eligible text segments into normalized entity spans, resolves conflicts, and applies a configured reduction strategy. It must support multiple recognition providers without coupling downstream processing to provider-specific APIs.

## Entity taxonomy

Initial normalized taxonomy:

```text
PERSON
EMAIL
PHONE
ADDRESS
```

The taxonomy should be implemented centrally.

Future entity types may include:

```text
DATE_OF_BIRTH
GOVERNMENT_ID
BANK_ACCOUNT
CREDIT_CARD
IP_ADDRESS
DEVICE_ID
USER_ID
LOCATION
HEALTH_ID
```

Provider-native labels should never leak throughout the codebase: no span carrying one may cross out of a provider adapter, and nothing under `src/` outside `providers/` may name one. Tests that deliberately characterise a provider or a model *below* that boundary are the one exception, and say so.

One narrow carve-out, stated because the code has always relied on it: `EntityMatch.metadata` may carry a provider's native label under `native_label`, with a `promoted` boolean beside it (ADR-0020) and an `extended` one (ADR-0021). This is **provenance, not vocabulary** — no code under `src/` outside `providers/` reads either field, and nothing branches on a native label's value. The rule that matters is unchanged: a span's `entity_type` is always normalized, so no consumer can act on a provider's label set. If a native label is ever promoted into an audit column or a routing decision, that carve-out has been exceeded and needs its own decision.

## Provider abstraction

### Provider output normalization

Three things happen before a candidate leaves the provider layer, so no downstream
layer ever sees a malformed span:

- **Labels**, in each adapter's own mapping table — provider-native strings never
  cross the boundary (ADR-0004).
- **Offsets**, in the shared base: spans are validated against the text, and for
  entity types whose surface cannot contain a line break, a span that crosses one is
  split into one span per line and *every* fragment is kept (ADR-0016). Which entity
  types those are is a static fact on `EntityDefinition.surface_may_span_lines`, not a
  per-layer list; `ADDRESS` is excluded because a postal address written across
  several lines is one address.
- **Coverage**, optionally and per provider instance: a PERSON span may be widened
  over one preceding token when that is structurally safe (ADR-0021). This is the one
  repair that does not narrow, and it is off unless an instance opts in — the shipped
  configuration enables it for Greek only. It offers the reconciler the widened span
  *and* the original, because widening a span into a conflict it would lose is how a
  repair meant to add coverage could remove it.

Splitting is repair, not rejection: an NER model that runs a PERSON span through a line
break was right about the entity and wrong about where it stops. Dropping the span
would leave the name in the output; keeping it whole destroys the next line's text.
*Every* fragment is kept rather than the best one, because the name may fall on either
side of the break and may be split across it — a hard-wrapped `Jürgen` + break +
`Müller` is one name in two pieces, and choosing either piece leaks the other. Keeping
them all can over-redact a neighbouring line instead, which is the direction this
project measures and gates at 0.000.

Spans trimmed or emptied by this rule are counted into provider drop metrics rather
than discarded silently.


Suggested provider interface:

```python
class PIIProvider(Protocol):
    @property
    def name(self) -> str: ...

    def supported_languages(self) -> set[str] | None: ...

    def supported_entities(self) -> set[str]: ...

    def detect(
        self,
        text: str,
        *,
        language: str | None,
        entities: set[str],
    ) -> list[EntityMatch]: ...

    def detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None],
        entities: set[str],
    ) -> list[list[EntityMatch]]: ...
```

`detect_batch` may have a default implementation but providers should override it when native batching exists.

## Provider families

### Deterministic recognizers

Best suited for highly structured entities.

Initial candidates:

- email,
- telephone,
- optionally URLs or IPs in later phases.

Advantages:

- fast,
- explainable,
- deterministic,
- usually high precision.

Limitations:

- context-insensitive,
- poor fit for names and addresses,
- locale complexity can be underestimated.

Deterministic rules are part of the solution, not the whole solution.

### Microsoft Presidio

Presidio is a strong baseline because it provides a recognizer framework, analyzer, and anonymization concepts. The project should wrap it rather than make Presidio types the repository's internal contract.

Provider implementation should document:

- installed Presidio version,
- NLP engine,
- recognizers enabled,
- per-language configuration,
- thresholds,
- custom recognizers,
- mapping to normalized entities.

### Transformer-based NER

Transformer models can improve person/address recognition or multilingual coverage.

The provider wrapper should handle:

- tokenizer offset mapping,
- subword aggregation,
- batch inference,
- device selection,
- maximum sequence length,
- long-text chunking,
- model label mapping.

### GLiNER-style provider

A zero-shot or label-conditioned NER model is useful for experimentation because it can detect configured entity labels without task-specific fine-tuning.

It should still be evaluated carefully for:

- false positives,
- language variation,
- address extraction,
- throughput.

### Databricks-hosted model provider

The accelerator may support a provider that calls a model hosted or served within Databricks. This should remain an adapter behind the same normalized interface.

Avoid designing the entire project around a specific proprietary endpoint.

### LLM provider

An LLM-based detector may be added later for benchmarking or difficult cases.

If implemented, require:

- strict structured output,
- character-span alignment back to source text,
- retry policy,
- token/cost accounting,
- explicit data-boundary documentation,
- deterministic settings where possible,
- leakage-risk evaluation.

LLM detection should not be the first baseline because exact span recovery is more complex than classification.

## Hybrid provider

A practical strategy may combine:

```text
EMAIL, PHONE -> deterministic recognizers
PERSON       -> NLP provider
ADDRESS      -> NLP provider + deterministic/context rules
```

The hybrid provider should produce all candidates and let the reconciler decide final spans.

## Confidence

Provider scores are not automatically comparable.

A score of `0.8` from one model may not mean the same thing as `0.8` from another.

Therefore:

- retain provider identity,
- allow provider-specific thresholds,
- avoid naïve averaging across providers,
- calibrate only when benchmark evidence exists.

## Entity overlap resolution

Overlaps are inevitable.

Example:

```text
John Smith <john.smith@example.com>
```

A provider may detect:

```text
PERSON: John Smith
EMAIL: john.smith@example.com
PERSON: john
PERSON: smith
```

Resolution rules should prioritize exact/high-specificity entities such as email over nested person fragments.

Recommended initial hierarchy:

```text
EMAIL / PHONE
    >
ADDRESS
    >
PERSON
```

but this should be configurable and validated.

### Deterministic resolution algorithm

> Amended by ADR-0005: step 4 orders by priority, **provider priority, confidence**,
> span length. Provider order comes before confidence because provider scores are
> recognizer constants rather than calibrated probabilities, so comparing them across
> providers is false precision. Confidence still decides between candidates from the
> same provider. See `src/pii_reduction/entities/reconcile.py::_sort_key`.

> Amended by ADR-0016: step 3b rejects a candidate whose *surface* is a machine
> identifier rather than a name — `KB000002739`, `DEMO-PC-6963`, `v4.12.3`. It applies
> to `PERSON` by default (`ReconciliationPolicy.identifier_guard`; set it to an empty
> set to disable) and deliberately **not** to `EMAIL` or `PHONE`, whose surfaces are
> supposed to be digits, nor to `ADDRESS`, whose surface may legitimately be a bare
> postcode. It runs before ordering on purpose: a candidate that won an overlap first
> and was dropped afterwards would take a legitimate overlapping span down with it.
> See `src/pii_reduction/entities/reconcile.py::_is_identifier` and
> `pii_reduction.patterns.is_identifier_shaped`.

1. filter invalid spans,
2. normalize entity labels,
3. apply entity-specific minimum confidence,
3b. reject identifier-shaped surfaces for entity types in the guard scope,
4. sort candidates by priority, confidence, span length, provider priority,
5. accept non-overlapping spans,
6. record rejected overlaps and guard rejections for debug metrics,
7. return accepted spans ordered by start position.

## Reduction strategies

### Redact

Default portfolio behavior:

```text
Maria Rossi -> <PERSON>
+30 210 000 0000 -> <PHONE>
```

Advantages:

- safe,
- obvious in demos,
- easy to validate.

### Mask

Useful when preserving partial semantics matters.

Email example:

```text
maria.rossi@example.com -> ma***@example.com
```

Phone example:

```text
+30 210 000 1234 -> ***********1234
```

### Deterministic pseudonymization

Goal: preserve repeated-entity linkage without preserving the original value.

Example:

```text
Maria Rossi -> PERSON_7F2A91
Maria Rossi -> PERSON_7F2A91
John Smith  -> PERSON_31B044
```

Design requirements:

- keyed hash or another controlled mapping,
- salt/key not committed,
- configurable scope: dataset, project, or global,
- collision handling,
- no reversible mapping by default.

### Synthetic replacement

Example:

```text
Maria Rossi -> Elena Novak
```

This may improve human readability but introduces complexity:

- gender/grammar mismatch,
- locale mismatch,
- accidental generation of a real identity,
- downstream analytical distortion.

Use only as an optional experiment.

## Span replacement algorithm

Apply replacements from highest start offset to lowest to avoid index shifts.

Example:

```python
for entity in sorted(entities, key=lambda x: x.start, reverse=True):
    text = text[:entity.start] + replacement(entity) + text[entity.end:]
```

The implementation must correctly handle Unicode offsets according to the provider's indexing semantics.

## Long text

Long ticket histories and transcripts may exceed provider token limits.

Chunking strategy must:

- preserve source offsets,
- use overlap where necessary,
- deduplicate entities found in overlapping chunks,
- avoid cutting obvious structured boundaries when a parser already provides them.

Prefer parser segments as natural chunk boundaries before generic token chunking.

## Entity policy

Each dataset/column can configure entities independently.

Example:

```yaml
columns:
  transcript:
    entities: [PERSON, EMAIL, PHONE, ADDRESS]
  short_description:
    entities: [PERSON, EMAIL]
```

## Provider routing

Provider choice can depend on language.

Example concept:

```yaml
routing:
  en: hybrid_en
  de: hybrid_de
  el: multilingual_transformer
  default: deterministic_only
```

Fallback behavior must be explicit.

## Auditability

Detection audit should capture:

- entity type,
- offsets,
- score,
- provider,
- recognizer/model,
- language,
- resolution result.

Avoid storing the original sensitive string in ordinary audit outputs.

## Benchmark dimensions

Every provider should eventually be evaluated by:

- entity type,
- language,
- document type,
- difficulty tier,
- text length,
- provider/model version,
- latency,
- throughput,
- failure rate.

## Required baseline

Before introducing sophisticated ensembles, establish simple baselines:

1. deterministic email + phone recognizers,
2. one Presidio configuration,
3. one multilingual NLP model where feasible.

A complex system is only justified if it beats simpler alternatives on measured outcomes.

# Multilingual Strategy

## Objective

PII detection quality varies significantly by language. The accelerator therefore treats language resolution, provider coverage, fallback behavior, and language-specific evaluation as explicit pipeline concerns.

## Language processing is not a single step

A naive design performs:

```text
row -> detect one language -> process everything with that language
```

That is insufficient for operational text because one cell may contain:

- an English system header,
- a Greek customer sentence,
- a product name in German,
- an email address,
- a copied English error message.

The project should support multiple language-resolution scopes.

## Resolution scopes

### Field-level

Best for ordinary prose with enough text.

### Segment-level

Best for:

- transcript turns,
- note bodies,
- multi-entry comment histories.

### Aggregate-level

For multiple very short segments, combine eligible text for detection and reuse the result when confidence is sufficient.

### Explicit source language

If a trusted source column already provides language, configuration may prefer that value over inference.

## Language result contract

```python
LanguageResult(
    language="de",
    confidence=0.91,
    detector="fasttext",
    supported=True,
    fallback_used=False,
    reason=None,
)
```

Possible language states:

- known + supported,
- known + unsupported,
- unknown due to low confidence,
- unknown due to insufficient text,
- mixed/ambiguous if supported by detector logic.

## Short-text policy

Examples such as:

```text
Thanks
Resolved
Call me
OK
```

should not be assigned high-confidence language solely because a detector returns a top label.

Suggested policy dimensions:

- minimum character count,
- minimum alphabetic character count,
- minimum confidence,
- optional aggregation with neighboring segments.

## Language detector abstraction

Suggested interface:

```python
class LanguageDetector(Protocol):
    def detect(self, text: str) -> LanguageResult: ...
    def detect_batch(self, texts: Sequence[str]) -> list[LanguageResult]: ...
```

Candidates can include fastText-style detectors, compact language detectors, transformer-based detectors, or provider-native language information.

The repository should benchmark detector quality only if language ground truth is available; otherwise treat language detection as routing metadata rather than a proven truth label.

## Provider-language registry

Maintain a configuration registry:

```yaml
providers:
  presidio_en:
    languages: [en]
  presidio_de:
    languages: [de]
  multilingual_ner:
    languages: [en, de, fr, es, it, pt, nl, el]
  deterministic:
    languages: ["*"]
```

This makes unsupported-language behavior visible.

## Fallback strategy

A safe default hierarchy could be:

```text
supported high-confidence language
    -> language-specific provider chain

unsupported or unknown language
    -> deterministic high-precision entities
    -> optional multilingual model
    -> record fallback status
```

Do not silently route all unknown text to English and report normal confidence.

## Mixed-language text

Code-switching is common in support environments.

Possible strategies:

### Strategy A: dominant language

Use one language for the entire segment.

Advantages:

- simple,
- fast.

Disadvantages:

- weaker on strongly mixed text.

### Strategy B: multilingual provider

Use a model trained to handle multiple languages without explicit routing.

### Strategy C: language-aware ensemble

Run deterministic recognizers plus a multilingual model, using language-specific models only when high confidence exists.

The repository should start with A or B and add C only when benchmark evidence justifies it.

## Entity-specific multilingual behavior

### Email

Mostly language-independent structurally, though surrounding punctuation and Unicode local parts may matter.

### Phone

Formatting is locale-sensitive but language inference is often unnecessary.

### Person

Strongly affected by:

- language,
- script,
- naming conventions,
- capitalization,
- transliteration.

### Address

Highly locale-sensitive:

- street ordering,
- postal codes,
- abbreviations,
- number placement,
- administrative regions.

Address should therefore receive particular attention in multilingual evaluation.

## Scripts

The benchmark should eventually include multiple scripts if supported:

- Latin,
- Greek,
- Cyrillic,
- possibly others in later phases.

Do not claim multilingual robustness based only on several Latin-script languages.

## Language benchmark matrix

A useful report layout:

| Language | Documents | PERSON F1 | EMAIL F1 | PHONE F1 | ADDRESS F1 | Leakage rate |
|---|---:|---:|---:|---:|---:|---:|
| English | ... | ... | ... | ... | ... | ... |
| German | ... | ... | ... | ... | ... | ... |
| Greek | ... | ... | ... | ... | ... | ... |

Also include support counts. A high F1 on 10 examples should not look equivalent to a high F1 on 5,000 examples.

## Language-aware test fixtures

Every supported language should have synthetic fixtures covering:

- person name,
- email,
- phone,
- address,
- non-PII operational identifier,
- transcript form,
- null/empty handling.

## Configuration example

```yaml
language:
  mode: detect
  detector: fasttext
  min_chars: 20
  min_confidence: 0.70
  unknown_language: und

routing:
  en: english_hybrid
  de: german_hybrid
  el: multilingual_hybrid
  default: safe_fallback
```

## Observability

Per run, report:

```text
language distribution
low-confidence count
unsupported-language count
fallback count
provider route count
```

These metrics can reveal source changes before PII metrics visibly degrade.

## Claims policy

README claims should distinguish:

- languages configured,
- languages tested,
- languages with sufficient benchmark support,
- languages merely accepted by an underlying model.

"Model supports 100 languages" is not equivalent to "this pipeline has validated PII quality in 100 languages."

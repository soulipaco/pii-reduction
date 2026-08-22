"""Microsoft Presidio adapter.

Presidio is wrapped, never adopted: its result objects, label vocabulary and engine
configuration stop at this boundary (``docs/04_PII_ENGINE.md``, ADR-0004). Everything
downstream sees normalized :class:`EntityMatch` objects and cannot tell which library
produced them.

**Supported languages / models** (ADR-0007): ``en`` → ``en_core_web_md``/``lg``,
``de`` → ``de_core_news_md``/``lg``, ``el`` → ``xx_ent_wiki_sm``. The Greek spaCy
models are CC BY-NC-SA and must never be used here; Greek routes through the
multilingual MIT model instead, with the boundary fuzziness that implies.

**Entity mapping:** ``PERSON``→PERSON, ``EMAIL_ADDRESS``→EMAIL, ``PHONE_NUMBER``→PHONE.
The adapter asks Presidio for exactly those three native labels, so ``URL`` (which
produced partial-match noise such as ``maria.ro`` in the session-2 probes) and
``LOCATION`` (which is not an address — ADR-0002) never arrive. The drop table below
is a safety net for anything a future Presidio version returns unbidden, and every
drop is counted rather than silently discarded.

**Label promotion** (``promote`` option, ADR-0020) widens that request for a
configured instance: a listed native label is asked for *and* normalized to PERSON.
It exists because ADR-0019 measured Greek names arriving with an exact span and the
wrong label — the name is found and then dropped — and Q4 established that the fix
must change the **request**, since an unrequested label never reaches the mapping
table at all. Promotion is per provider instance and therefore per language: the
shipped configuration promotes for Greek only, because promoting globally was
measured to cost English and German PERSON precision (0.833→0.694 and 0.963→0.839)
and to destroy a protected identifier.

**Span extension** (``extend_person_left``, ADR-0021) is the other opt-in repair: a
PERSON span may be widened over one preceding capitalised token when that is
structurally safe. It addresses the opposite error to promotion — the model returning
only the *surname* of a two-token Greek name — and like promotion it ships for Greek
only. The rule itself lives in ``providers/base.py`` because it is not
Presidio-specific; this adapter only decides whether to switch it on.

**What promotion cannot reach:** spaCy's ``MISC`` label. Measured on the Greek slice,
``xx_ent_wiki_sm`` emits ``PER 8, MISC 41, LOC 20, ORG 1``, and Presidio surfaces only
the first, third and fourth — ``MISC`` has no Presidio entity name and is dropped
inside Presidio, before this adapter. That caps what any promotion remedy here can
recover, and it is why ADR-0019's third mechanism is not addressed by ADR-0020.

**Confidence semantics:** Presidio scores are recognizer constants, not calibrated
probabilities — every spaCy-backed hit is exactly 0.85 whether right or wrong,
``EmailRecognizer`` emits 1.0 and ``PhoneRecognizer`` 0.40. Thresholds are therefore
per entity, and a single global threshold is forbidden (ADR-0005).

This adapter does **not** filter by threshold. Detection reports what was found with
the score it carries; thresholds are configuration policy applied once, by the
reconciler, which also records what each threshold rejected. Two enforcement points
would mean two places to look when a phone number goes missing.

**Runtime:** the analyzer engine is expensive to build (~8 s for three models) and is
cached per model configuration for the life of the process, so constructing this
provider twice does not reload anything. On Spark this makes it a worker-level
singleton rather than a per-row cost (``docs/01_ARCHITECTURE.md``, scalability).

**Known limitations:** Greek PERSON boundaries are unreliable (a probe had the
preceding verb absorbed into the span); the flat 0.85 score means false positives
cannot be filtered by confidence; ``.test``/``.invalid`` domains are rejected by the
default email recognizer, which is why the deterministic provider stays in the chain
(ADR-0003).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.mapping import LabelMapping
from pii_reduction.entities.taxonomy import EMAIL, PERSON, PHONE
from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.errors import ProviderError, ProviderNotAvailableError

__all__ = [
    "DEFAULT_MODELS",
    "RECOMMENDED_THRESHOLDS",
    "PresidioProvider",
    "reset_engine_cache",
]

INSTALL_HINT = (
    "install the extra and the models:\n"
    "  pip install 'pii-reduction[presidio]'\n"
    "  python -m spacy download en_core_web_md\n"
    "  python -m spacy download de_core_news_md\n"
    "  python -m spacy download xx_ent_wiki_sm"
)

#: Language to spaCy model. ``md`` in CI, ``lg`` for benchmark runs (ADR-0009).
DEFAULT_MODELS: dict[str, str] = {
    "en": "en_core_web_md",
    "de": "de_core_news_md",
    # MIT-licensed multilingual model; el_core_news_* is CC BY-NC-SA (ADR-0007).
    "el": "xx_ent_wiki_sm",
}

#: Recommended per-entity minimums, placed relative to the observed recognizer
#: constants (ADR-0005). These are what ``configs/providers.yaml`` sets; they are
#: applied by the reconciler, not here. Uncalibrated until Increment E.
RECOMMENDED_THRESHOLDS: dict[str, float] = {PERSON: 0.5, EMAIL: 0.6, PHONE: 0.3}

#: Native label -> normalized label. Owned by this adapter, not by ``entities/``.
NATIVE_LABELS: dict[str, str] = {
    "PERSON": PERSON,
    "EMAIL_ADDRESS": EMAIL,
    "PHONE_NUMBER": PHONE,
}

#: Native labels deliberately discarded if they ever arrive (ADR-0004, ADR-0002).
DROPPED_LABELS = frozenset({"URL", "LOCATION", "NRP", "DATE_TIME", "IP_ADDRESS"})

#: Native labels the ``promote`` option may map to PERSON (ADR-0020). Restricted to
#: the three the underlying NER can carry a person's name under; promoting ``URL``,
#: ``DATE_TIME`` or ``IP_ADDRESS`` would be a category error, not a coverage choice.
PROMOTABLE_LABELS = frozenset({"LOCATION", "ORGANIZATION", "NRP"})

DEFAULT_OPTIONS: dict[str, Any] = {
    "models": DEFAULT_MODELS,
    #: Native labels normalized to PERSON *and* added to the request (ADR-0020).
    #: Empty by default: promotion is opt-in per instance, never a global default.
    "promote": (),
    #: Opt in to the ADR-0021 PERSON left-extension. Off by default for the same
    #: reason as promotion: it was measured to cost English and German recall.
    "extend_person_left": False,
}

#: Analyzer engines by model configuration. Building one loads every model, so this
#: cache is what keeps model initialization to once per process (or worker).
_ENGINE_CACHE: dict[tuple[tuple[str, str], ...], Any] = {}

#: Batch wrappers, keyed by the identity of the analyzer they wrap. See `_batch_engine`.
_BATCH_ENGINE_CACHE: dict[int, Any] = {}

#: Texts per `nlp.pipe` chunk inside `analyze_iterator` (ADR-0033).
#:
#: Measured on the committed corpora, English plain text, best of five: the gain is
#: flat from 32 upward within measurement noise — 1.69x at 32, 1.75x at 64, 1.77x at
#: 128, 1.74x at 256 — while a larger value only holds more parsed `Doc` objects in
#: memory at once, which on a Databricks worker is the constraint that matters rather
#: than throughput. 32 is the knee, not the maximum.
PRESIDIO_BATCH_SIZE = 32


def reset_engine_cache() -> None:
    """Drop cached engines. For tests; a running pipeline should never need this."""
    _ENGINE_CACHE.clear()
    _BATCH_ENGINE_CACHE.clear()


def _build_engine(models: dict[str, str]) -> Any:
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ProviderNotAvailableError(
            f"provider 'presidio' requires presidio-analyzer and spaCy. {INSTALL_HINT}"
        ) from exc

    configuration = {
        "nlp_engine_name": "spacy",
        "models": [
            {"lang_code": language, "model_name": model}
            for language, model in sorted(models.items())
        ],
    }
    try:
        nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
    except OSError as exc:
        raise ProviderNotAvailableError(
            f"provider 'presidio': a configured spaCy model is not installed. {INSTALL_HINT}"
        ) from exc
    return AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=sorted(models))


def _engine_for(models: dict[str, str]) -> Any:
    key = tuple(sorted(models.items()))
    engine = _ENGINE_CACHE.get(key)
    if engine is None:
        engine = _build_engine(models)
        _ENGINE_CACHE[key] = engine
    return engine


def _batch_engine(engine: Any) -> Any:
    """The batch wrapper for an analyzer, cached alongside it.

    `BatchAnalyzerEngine` holds no models of its own — it delegates to the analyzer it
    wraps — but constructing one per call would still be per-row garbage on the hot
    path. Keyed by the analyzer's identity so it follows `_ENGINE_CACHE`'s lifetime
    exactly: one per model set, per process, which is `AGENTS.md`'s
    "initialize expensive NLP models once per process/worker".
    """
    wrapper = _BATCH_ENGINE_CACHE.get(id(engine))
    if wrapper is None:
        from presidio_analyzer import BatchAnalyzerEngine

        wrapper = BatchAnalyzerEngine(analyzer_engine=engine)
        _BATCH_ENGINE_CACHE[id(engine)] = wrapper
    return wrapper


class PresidioProvider(BaseProvider):
    """NER-backed PERSON detection (plus Presidio's own EMAIL/PHONE recognizers)."""

    name = "presidio"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ProviderError(
                f"provider {self.name!r}: unknown options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        models = merged["models"]
        if not isinstance(models, dict) or not models:
            raise ProviderError(
                f"provider {self.name!r}: models must be a mapping of language to spaCy "
                "model name, e.g. {en: en_core_web_md}"
            )
        for language, model in models.items():
            if str(model).startswith("el_core_news"):
                raise ProviderError(
                    f"provider {self.name!r}: model {model!r} for language {language!r} is "
                    "CC BY-NC-SA licensed and cannot be used in this MIT project (ADR-0007). "
                    "Use xx_ent_wiki_sm for Greek"
                )

        promote = merged["promote"] or ()
        if isinstance(promote, str):
            raise ProviderError(
                f"provider {self.name!r}: promote must be a list of native labels, not a "
                f"string; got {promote!r}"
            )
        promoted = tuple(str(label) for label in promote)
        unknown = sorted(set(promoted) - PROMOTABLE_LABELS)
        if unknown:
            raise ProviderError(
                f"provider {self.name!r}: cannot promote {', '.join(unknown)} "
                f"(promotable: {', '.join(sorted(PROMOTABLE_LABELS))})"
            )
        self.options = merged
        self.extend_person_left = bool(merged["extend_person_left"])
        self._models = {str(language): str(model) for language, model in models.items()}
        self._promoted = frozenset(promoted)
        # The promoted labels join the table *and* leave the drop set: a label that is
        # still "dropped" would be counted as an unbidden arrival on every hit, which
        # is the drop_counter reporting a fault where a configured behaviour occurred.
        # Built here so an invalid table fails at construction rather than at first
        # detection; re-stamped with the instance name on access, see `_mapping`.
        self._label_mapping = LabelMapping(
            provider=self.name,
            table={**NATIVE_LABELS, **dict.fromkeys(promoted, PERSON)},
            dropped=DROPPED_LABELS - self._promoted,
        )

    @property
    def _mapping(self) -> LabelMapping:
        """The label mapping, carrying *this instance's* configured name.

        ``build_provider`` assigns ``name`` after the constructor returns, so a
        mapping built in ``__init__`` keeps the class default. With one Presidio
        instance that was invisible; with two (ADR-0020) it files every dropped label
        under ``presidio`` regardless of which instance dropped it, and
        ``pipeline`` merges the per-provider counters into one ``Counter`` — so the
        Greek instance's drops would silently sum into the English one's key. That
        defeats the reason drops are counted at all: ADR-0004 keeps them so a provider
        upgrade that starts emitting an unmapped label cannot lose coverage quietly.
        """
        if self._label_mapping.provider != self.name:
            self._label_mapping = replace(self._label_mapping, provider=self.name)
        return self._label_mapping

    @property
    def models(self) -> dict[str, str]:
        return dict(self._models)

    def supported_entities(self) -> frozenset[str]:
        return self._mapping.supported_entities()

    def supported_languages(self) -> frozenset[str]:
        return frozenset(self._models)

    def engine(self) -> Any:
        """The cached analyzer engine. Loads models on first use, once per process."""
        return _engine_for(self._models)

    def _native_labels_to_request(self, entities: frozenset[str]) -> list[str]:
        """The native labels to ask Presidio for, given the normalized scope.

        The instance table, not ``NATIVE_LABELS``: a promoted label has to be *asked
        for*. Q4 measured that an unrequested label never arrives, so promotion
        implemented only in the mapping table would be a silent no-op (ADR-0020).
        """
        return sorted(
            {native for native, normalized in self._mapping.table.items() if normalized in entities}
        )

    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        if language is None or language not in self._models:
            # An unsupported language is not an error: the chain's fallback provider
            # still runs, and the run metrics record the language distribution.
            return []

        native_requested = self._native_labels_to_request(entities)
        if not native_requested:
            return []

        results = self.engine().analyze(
            text=text,
            language=language,
            entities=native_requested,
            score_threshold=0.0,
        )
        return self._normalize(results, language=language, entities=entities)

    def _detect_batch(
        self,
        texts: Sequence[str],
        *,
        languages: Sequence[str | None],
        entities: frozenset[str],
    ) -> list[list[EntityMatch]]:
        """One spaCy pass over the whole batch instead of one per text (ADR-0033).

        **96% of a Presidio detection is the spaCy pass**, and `nlp.pipe` is the only
        part of it that gets faster in bulk. `BatchAnalyzerEngine.analyze_iterator`
        runs exactly that pass through `NlpEngine.process_batch` and then calls the
        ordinary `analyze` per text with the artifacts already computed — so the
        recognizers, the context enhancer and the scores are the ones the scalar path
        produces. Output identity is asserted, not assumed.

        `analyze_iterator` takes **one** language for the whole call, so the batch is
        grouped by language here. In the shipped pipeline each group is the whole
        batch, because a row's language is resolved once before any segment is
        detected — but the contract allows a mixed batch and this must not be the
        place that quietly refuses one.
        """
        native_requested = self._native_labels_to_request(entities)
        results: list[list[EntityMatch]] = [[] for _ in texts]
        if not native_requested:
            return results

        by_language: dict[str, list[int]] = {}
        for position, language in enumerate(languages):
            if language is None or language not in self._models:
                # Same ruling as `_detect`: an unsupported language yields nothing and
                # is not an error. Its slot stays the empty list it was seeded with.
                continue
            by_language.setdefault(language, []).append(position)

        batcher = None
        for language, positions in by_language.items():
            if len(positions) == 1:
                # **One text is not a batch, and routing it through the batch
                # machinery costs about 3%** — measured on the plain-text corpus,
                # where a row is exactly one segment and this is therefore the common
                # case, not the corner one. Delegating to the scalar path also makes
                # identity for a single text true by construction rather than by
                # assertion.
                position = positions[0]
                results[position] = self._detect(
                    texts[position], language=language, entities=entities
                )
                continue
            if batcher is None:
                batcher = _batch_engine(self.engine())
            analyzed = batcher.analyze_iterator(
                [texts[position] for position in positions],
                language=language,
                entities=native_requested,
                score_threshold=0.0,
                batch_size=PRESIDIO_BATCH_SIZE,
            )
            for position, raw in zip(positions, analyzed, strict=True):
                results[position] = self._normalize(raw, language=language, entities=entities)
        return results

    def _normalize(
        self, results: Any, *, language: str, entities: frozenset[str]
    ) -> list[EntityMatch]:
        """Presidio results to normalized matches. The one place the mapping happens."""
        matches: list[EntityMatch] = []
        for result in results:
            normalized = self._mapping.normalize(result.entity_type, counter=self.drop_counter)
            if normalized is None or normalized not in entities:
                continue
            matches.append(
                EntityMatch(
                    start=result.start,
                    end=result.end,
                    entity_type=normalized,
                    score=float(result.score),
                    provider=self.name,
                    recognizer=_recognizer_name(result),
                    language=language,
                    metadata={
                        "native_label": result.entity_type,
                        # In-process provenance only: `AUDIT_COLUMNS` is a closed,
                        # metadata-only set and no audit row carries this today. It
                        # is here so the distinction exists at the boundary that
                        # knows it, for a future audit column or a debugging session.
                        "promoted": result.entity_type in self._promoted,
                    },
                )
            )
        return matches


def _recognizer_name(result: Any) -> str | None:
    metadata = getattr(result, "recognition_metadata", None) or {}
    name = metadata.get("recognizer_name")
    return str(name) if name else None

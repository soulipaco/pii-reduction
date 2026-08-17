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

from typing import Any

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.mapping import DropCounter, LabelMapping
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

DEFAULT_OPTIONS: dict[str, Any] = {
    "models": DEFAULT_MODELS,
}

#: Analyzer engines by model configuration. Building one loads every model, so this
#: cache is what keeps model initialization to once per process (or worker).
_ENGINE_CACHE: dict[tuple[tuple[str, str], ...], Any] = {}


def reset_engine_cache() -> None:
    """Drop cached engines. For tests; a running pipeline should never need this."""
    _ENGINE_CACHE.clear()


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

        self.options = merged
        self._models = {str(language): str(model) for language, model in models.items()}
        self._mapping = LabelMapping(
            provider=self.name, table=NATIVE_LABELS, dropped=DROPPED_LABELS
        )
        self.drop_counter = DropCounter()

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

    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        if language is None or language not in self._models:
            # An unsupported language is not an error: the chain's fallback provider
            # still runs, and the run metrics record the language distribution.
            return []

        native_requested = sorted(
            {native for native, normalized in NATIVE_LABELS.items() if normalized in entities}
        )
        if not native_requested:
            return []

        results = self.engine().analyze(
            text=text,
            language=language,
            entities=native_requested,
            score_threshold=0.0,
        )

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
                    metadata={"native_label": result.entity_type},
                )
            )
        return matches


def _recognizer_name(result: Any) -> str | None:
    metadata = getattr(result, "recognition_metadata", None) or {}
    name = metadata.get("recognizer_name")
    return str(name) if name else None

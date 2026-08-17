"""Span matching (``docs/08_EVALUATION_BENCHMARKING.md``, ADR-0011).

Strict matching — same type, same start, same end — is the primary metric, because
reduction rewrites exactly the span it is given: a boundary that is one character off
leaves one character of the value behind.

Relaxed matching (same type, IoU >= 0.5) is always reported beside it. The gap
between the two *is* the signal: it is where boundary quality lives, and the session-2
probe showed a multilingual model swallowing the preceding verb into a Greek PERSON
span — fully covering the name while failing strict matching entirely.

This module knows nothing about providers or pipelines; it compares two lists.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

__all__ = [
    "MatchMode",
    "MatchResult",
    "Prediction",
    "TruthSpan",
    "iou",
    "match_spans",
]

STRICT = "strict"
RELAXED = "relaxed"
MatchMode = str

DEFAULT_IOU_THRESHOLD = 0.5


@dataclass(frozen=True)
class TruthSpan:
    """The evaluation-facing view of one ground-truth entity."""

    document_id: str
    entity_id: str
    entity_type: str
    start: int
    end: int
    language: str = ""
    difficulty_tier: int = 0
    document_type: str = ""


@dataclass(frozen=True)
class Prediction:
    """One predicted span, as produced by a run."""

    document_id: str
    entity_type: str
    start: int
    end: int
    provider: str = ""
    score: float | None = None


@dataclass(frozen=True)
class MatchResult:
    matched: tuple[tuple[TruthSpan, Prediction], ...] = ()
    missed: tuple[TruthSpan, ...] = ()
    spurious: tuple[Prediction, ...] = ()

    @property
    def true_positives(self) -> int:
        return len(self.matched)

    @property
    def false_negatives(self) -> int:
        return len(self.missed)

    @property
    def false_positives(self) -> int:
        return len(self.spurious)


def iou(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    """Intersection over union of two half-open ranges."""
    intersection = max(0, min(end_a, end_b) - max(start_a, start_b))
    if intersection == 0:
        return 0.0
    union = max(end_a, end_b) - min(start_a, start_b)
    return intersection / union


def match_spans(
    truths: Iterable[TruthSpan],
    predictions: Iterable[Prediction],
    *,
    mode: MatchMode = STRICT,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> MatchResult:
    """Match predictions to ground truth one-to-one.

    Strict mode pairs exact (type, start, end) matches. Relaxed mode pairs the
    highest-overlap candidate first, so a prediction cannot be counted twice and the
    best available pairing wins.
    """
    truth_list = list(truths)
    prediction_list = list(predictions)
    if mode == STRICT:
        return _match_strict(truth_list, prediction_list)
    if mode == RELAXED:
        return _match_relaxed(truth_list, prediction_list, iou_threshold=iou_threshold)
    raise ValueError(f"unknown match mode {mode!r} (known: {STRICT}, {RELAXED})")


def _key(item: TruthSpan | Prediction) -> tuple[str, str, int, int]:
    return (item.document_id, item.entity_type, item.start, item.end)


def _match_strict(truths: Sequence[TruthSpan], predictions: Sequence[Prediction]) -> MatchResult:
    remaining: dict[tuple[str, str, int, int], list[Prediction]] = {}
    for prediction in predictions:
        remaining.setdefault(_key(prediction), []).append(prediction)

    matched: list[tuple[TruthSpan, Prediction]] = []
    missed: list[TruthSpan] = []
    for truth in truths:
        candidates = remaining.get(_key(truth))
        if candidates:
            matched.append((truth, candidates.pop(0)))
        else:
            missed.append(truth)

    spurious = [prediction for group in remaining.values() for prediction in group]
    return MatchResult(matched=tuple(matched), missed=tuple(missed), spurious=tuple(spurious))


def _match_relaxed(
    truths: Sequence[TruthSpan],
    predictions: Sequence[Prediction],
    *,
    iou_threshold: float,
) -> MatchResult:
    pairs: list[tuple[float, int, int]] = []
    for truth_index, truth in enumerate(truths):
        for prediction_index, prediction in enumerate(predictions):
            if truth.document_id != prediction.document_id:
                continue
            if truth.entity_type != prediction.entity_type:
                continue
            overlap = iou(truth.start, truth.end, prediction.start, prediction.end)
            if overlap >= iou_threshold:
                pairs.append((overlap, truth_index, prediction_index))

    # Highest overlap first; ties resolved by position so the result is deterministic.
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))

    used_truths: set[int] = set()
    used_predictions: set[int] = set()
    matched: list[tuple[TruthSpan, Prediction]] = []
    for _, truth_index, prediction_index in pairs:
        if truth_index in used_truths or prediction_index in used_predictions:
            continue
        used_truths.add(truth_index)
        used_predictions.add(prediction_index)
        matched.append((truths[truth_index], predictions[prediction_index]))

    missed = [truth for index, truth in enumerate(truths) if index not in used_truths]
    spurious = [
        prediction for index, prediction in enumerate(predictions) if index not in used_predictions
    ]
    return MatchResult(matched=tuple(matched), missed=tuple(missed), spurious=tuple(spurious))

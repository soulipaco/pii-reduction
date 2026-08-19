"""Detection, reduction and preservation metrics.

Support counts travel with every number. A recall of 1.00 over three entities and a
recall of 1.00 over three thousand are not the same claim, and a benchmark table that
hides the difference is misleading rather than merely terse
(``docs/08_EVALUATION_BENCHMARKING.md``).

Empty slices report 0.0 with support 0 rather than raising or silently vanishing.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from pii_reduction.evaluation.matching import (
    STRICT,
    MatchMode,
    Prediction,
    TruthSpan,
    match_spans,
)

__all__ = [
    "DEFAULT_FRAGMENT_LENGTH",
    "DetectionMetric",
    "FragmentLeakageMetric",
    "LeakageMetric",
    "OverRedactionMetric",
    "detection_metrics",
    "detection_metrics_by",
    "fragment_leakage_metrics",
    "leakage_metrics",
    "over_redaction_metrics",
    "precision_recall_f1",
]


@dataclass(frozen=True)
class DetectionMetric:
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def support(self) -> int:
        """Ground-truth entities in this slice."""
        return self.true_positives + self.false_negatives

    @property
    def precision(self) -> float:
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> float:
        return _ratio(self.true_positives, self.true_positives + self.false_negatives)

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class LeakageMetric:
    """Reduction-centric: did the value survive in the output?

    ``leaked`` counts ground-truth entities whose exact surface string is still
    present in the reduced text (ADR-0011). ``document_clean_rate`` is the share of
    PII-bearing documents with nothing left behind.

    For masking this number must be read differently — a masked value deliberately
    retains part of the original, so a mask run's leakage is not comparable with a
    redaction run's (ADR-0013 §5). ``strategy`` records which was used.
    """

    leaked: int
    total: int
    clean_documents: int
    documents_with_pii: int
    strategy: str = ""

    @property
    def rate(self) -> float:
        return _ratio(self.leaked, self.total)

    @property
    def document_clean_rate(self) -> float:
        return _ratio(self.clean_documents, self.documents_with_pii)


@dataclass(frozen=True)
class FragmentLeakageMetric:
    """Did any *recognisable piece* of the value survive? (ADR-0013 §5)

    ``LeakageMetric`` counts only the exact full surface, which two facts make
    insufficient on its own. Masking *deliberately* retains part of the value —
    ``ma***@example.com`` keeps the domain, ``last4`` keeps four digits — so a mask
    run's full-value leakage is trivially low while identifying fragments remain.
    And a boundary error can redact half a name and leave the other half, which the
    full-surface match scores as clean (found in session 5: the gate held at 0.117
    while a repair rule leaked half-names).

    ``retained`` counts entities where any whitespace-free window of
    ``fragment_length`` characters of the surface survives in the reduced text —
    excluding windows that already occur in the source document *outside every
    entity span*, because their survival is not evidence: the German word
    ``Rechnername`` contains ``chne`` from ``…schneider@…``, and counting it would
    charge the reducer with leaking a word it never touched. With that exclusion a
    full survival still retains every window, so on like-for-like text this is a
    superset measure: ``fragment rate >= full-value rate``.

    **Never compare this across strategies as if it were one number.** For ``mask``
    a non-zero rate is the configured behaviour; for ``redact`` and ``pseudonymize``
    it is a leak. ``strategy`` records which reading applies.
    """

    retained: int
    total: int
    fragment_length: int
    strategy: str = ""

    @property
    def rate(self) -> float:
        return _ratio(self.retained, self.total)


@dataclass(frozen=True)
class OverRedactionMetric:
    """Preservation: protected non-PII tokens that did not survive unchanged."""

    modified: int
    total: int
    modified_kinds: tuple[str, ...] = ()

    @property
    def rate(self) -> float:
        return _ratio(self.modified, self.total)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def precision_recall_f1(
    true_positives: int, false_positives: int, false_negatives: int
) -> tuple[float, float, float]:
    metric = DetectionMetric(true_positives, false_positives, false_negatives)
    return metric.precision, metric.recall, metric.f1


def detection_metrics(
    truths: Iterable[TruthSpan],
    predictions: Iterable[Prediction],
    *,
    mode: MatchMode = STRICT,
    iou_threshold: float = 0.5,
) -> DetectionMetric:
    result = match_spans(truths, predictions, mode=mode, iou_threshold=iou_threshold)
    return DetectionMetric(
        true_positives=result.true_positives,
        false_positives=result.false_positives,
        false_negatives=result.false_negatives,
    )


def detection_metrics_by(
    truths: Sequence[TruthSpan],
    predictions: Sequence[Prediction],
    *,
    dimensions: Sequence[str],
    mode: MatchMode = STRICT,
    iou_threshold: float = 0.5,
) -> dict[tuple[str, ...], DetectionMetric]:
    """Slice metrics by ground-truth attributes (entity type, language, tier, ...).

    Predictions are attributed to a slice through the document they belong to, so a
    prediction in a document of a given language counts as a false positive for that
    language. Slices are keyed by the dimension values in the order requested.
    """
    document_slices = _document_slices(truths, dimensions)
    truth_groups: dict[tuple[str, ...], list[TruthSpan]] = {}
    for truth in truths:
        truth_groups.setdefault(_slice_key(truth, dimensions), []).append(truth)

    prediction_groups: dict[tuple[str, ...], list[Prediction]] = {}
    for prediction in predictions:
        key = _prediction_slice_key(prediction, dimensions, document_slices)
        if key is None:
            continue
        prediction_groups.setdefault(key, []).append(prediction)

    metrics: dict[tuple[str, ...], DetectionMetric] = {}
    for key in sorted(set(truth_groups) | set(prediction_groups)):
        metrics[key] = detection_metrics(
            truth_groups.get(key, []),
            prediction_groups.get(key, []),
            mode=mode,
            iou_threshold=iou_threshold,
        )
    return metrics


def _slice_key(truth: TruthSpan, dimensions: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(getattr(truth, dimension)) for dimension in dimensions)


def _document_slices(
    truths: Sequence[TruthSpan], dimensions: Sequence[str]
) -> dict[str, dict[str, str]]:
    """Document-level attribute values, used to place predictions into slices.

    Language, tier and document type are properties of a document, not of an entity
    within it, so the first value seen for a document wins and later entities cannot
    silently move the document into a different slice. (Entity type is per span and is
    taken from the prediction itself.)
    """
    document_attributes: dict[str, dict[str, str]] = {}
    for truth in truths:
        attributes = document_attributes.setdefault(truth.document_id, {})
        for dimension in dimensions:
            if dimension != "entity_type":
                attributes.setdefault(dimension, str(getattr(truth, dimension)))
    return document_attributes


def _prediction_slice_key(
    prediction: Prediction,
    dimensions: Sequence[str],
    document_slices: Mapping[str, Mapping[str, str]],
) -> tuple[str, ...] | None:
    attributes = document_slices.get(prediction.document_id)
    if attributes is None:
        # A prediction in a document with no ground truth cannot be sliced by
        # document attributes; it is counted in the overall metric only.
        return None
    values = []
    for dimension in dimensions:
        if dimension == "entity_type":
            values.append(prediction.entity_type)
        else:
            values.append(attributes.get(dimension, ""))
    return tuple(values)


def leakage_metrics(
    truths: Iterable[TruthSpan],
    reduced_texts: Mapping[str, str],
    surfaces: Mapping[str, str],
    *,
    strategy: str = "",
) -> LeakageMetric:
    """Count ground-truth values whose exact surface survives in the reduced text.

    ``surfaces`` maps entity id to the injected value. Documents absent from
    ``reduced_texts`` (for example a null field) count as leaked, because the value
    was demonstrably not removed.
    """
    leaked = 0
    total = 0
    per_document: dict[str, int] = {}
    for truth in truths:
        total += 1
        per_document.setdefault(truth.document_id, 0)
        surface = surfaces.get(truth.entity_id)
        reduced = reduced_texts.get(truth.document_id)
        if surface is None or reduced is None or surface in reduced:
            leaked += 1
            per_document[truth.document_id] += 1

    clean = sum(1 for count in per_document.values() if count == 0)
    return LeakageMetric(
        leaked=leaked,
        total=total,
        clean_documents=clean,
        documents_with_pii=len(per_document),
        strategy=strategy,
    )


#: Window size for :func:`fragment_leakage_metrics`. Four is the smallest piece the
#: shipped mask rules deliberately keep (``last4`` on a phone number), so anything the
#: masker retains on purpose is visible at this length — and it is long enough that a
#: name fragment surviving in ordinary prose by coincidence is rare rather than routine.
DEFAULT_FRAGMENT_LENGTH = 4


def _fragment_windows(surface: str, length: int) -> Iterator[str]:
    """Whitespace-free windows of ``length`` characters; the whole surface if shorter.

    Windows spanning whitespace are skipped because they straddle tokens — ``a R`` from
    ``Maria Rossi`` says nothing recognisable — and a surface shorter than the window
    falls back to itself, so a three-letter name is not silently unmeasurable.
    """
    if len(surface) <= length:
        yield surface
        return
    for index in range(len(surface) - length + 1):
        window = surface[index : index + length]
        if not any(character.isspace() for character in window):
            yield window


def _ambient_texts(truths: Sequence[TruthSpan], source_texts: Mapping[str, str]) -> dict[str, str]:
    """Each document's text with every entity span blanked out.

    What remains is the prose the reducer was never asked to touch. A fragment that
    occurs here can survive reduction without any value having leaked — but a fragment
    that occurs only inside entity spans (two emails sharing a domain, say) is still
    evidence, which is why the spans are blanked rather than the whole document
    excluded.
    """
    spans: dict[str, list[tuple[int, int]]] = {}
    for truth in truths:
        spans.setdefault(truth.document_id, []).append((truth.start, truth.end))
    ambient: dict[str, str] = {}
    for document_id, text in source_texts.items():
        characters = list(text)
        for start, end in spans.get(document_id, []):
            characters[start:end] = "\x00" * (end - start)
        ambient[document_id] = "".join(characters)
    return ambient


def fragment_leakage_metrics(
    truths: Sequence[TruthSpan],
    reduced_texts: Mapping[str, str],
    surfaces: Mapping[str, str],
    *,
    source_texts: Mapping[str, str] | None = None,
    strategy: str = "",
    fragment_length: int = DEFAULT_FRAGMENT_LENGTH,
) -> FragmentLeakageMetric:
    """Count ground-truth values with any surviving fragment (ADR-0013 §5).

    Same conventions as :func:`leakage_metrics`: ``surfaces`` maps entity id to the
    injected value, and a document absent from ``reduced_texts`` counts as retained,
    because the value was demonstrably not removed.

    ``source_texts`` enables the ambient exclusion described on
    :class:`FragmentLeakageMetric`. Without it every surviving window counts, which
    overstates leakage wherever a value shares four letters with ordinary prose.
    """
    ambient = _ambient_texts(truths, source_texts) if source_texts is not None else {}
    retained = 0
    total = 0
    for truth in truths:
        total += 1
        surface = surfaces.get(truth.entity_id)
        reduced = reduced_texts.get(truth.document_id)
        if surface is None or reduced is None:
            retained += 1
            continue
        background = ambient.get(truth.document_id, "")
        if any(
            window in reduced
            for window in _fragment_windows(surface, fragment_length)
            if window not in background
        ):
            retained += 1
    return FragmentLeakageMetric(
        retained=retained,
        total=total,
        fragment_length=fragment_length,
        strategy=strategy,
    )


def over_redaction_metrics(
    protected: Iterable[tuple[str, str, str]],
    reduced_texts: Mapping[str, str],
) -> OverRedactionMetric:
    """Count protected tokens that did not survive reduction.

    ``protected`` is ``(document_id, token, kind)``. A token missing from the reduced
    text was modified — the exact failure ``docs/10_TESTING_QA.md`` §6 protects
    against.
    """
    modified = 0
    total = 0
    kinds: set[str] = set()
    for document_id, token, kind in protected:
        total += 1
        reduced = reduced_texts.get(document_id)
        if reduced is None or token not in reduced:
            modified += 1
            kinds.add(kind)
    return OverRedactionMetric(modified=modified, total=total, modified_kinds=tuple(sorted(kinds)))

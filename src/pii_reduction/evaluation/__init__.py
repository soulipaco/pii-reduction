"""Evaluation: span matching, metrics, benchmark reporting.

Imported by benchmark entry points only. ``processing/`` must never import this —
production transformation and its evaluation stay separate (``AGENTS.md``).
"""

from pii_reduction.evaluation.matching import (
    RELAXED,
    STRICT,
    MatchResult,
    Prediction,
    TruthSpan,
    iou,
    match_spans,
)
from pii_reduction.evaluation.metrics import (
    DetectionMetric,
    LeakageMetric,
    OverRedactionMetric,
    detection_metrics,
    detection_metrics_by,
    leakage_metrics,
    over_redaction_metrics,
    precision_recall_f1,
)
from pii_reduction.evaluation.report import MetricRow, render_markdown, render_table

__all__ = [
    "RELAXED",
    "STRICT",
    "DetectionMetric",
    "LeakageMetric",
    "MatchResult",
    "MetricRow",
    "OverRedactionMetric",
    "Prediction",
    "TruthSpan",
    "detection_metrics",
    "detection_metrics_by",
    "iou",
    "leakage_metrics",
    "match_spans",
    "over_redaction_metrics",
    "precision_recall_f1",
    "render_markdown",
    "render_table",
]

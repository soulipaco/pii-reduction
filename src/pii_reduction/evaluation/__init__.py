"""Evaluation: span matching, metrics, benchmark reporting.

Imported by benchmark entry points only. ``processing/`` must never import this —
production transformation and its evaluation stay separate (``AGENTS.md``).
"""

from pii_reduction.evaluation.gates import (
    Gate,
    GateConfigurationError,
    GateReport,
    GateResult,
    evaluate_gates,
    load_gate_file,
)
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
    "Gate",
    "GateConfigurationError",
    "GateReport",
    "GateResult",
    "LeakageMetric",
    "MatchResult",
    "MetricRow",
    "OverRedactionMetric",
    "Prediction",
    "TruthSpan",
    "detection_metrics",
    "detection_metrics_by",
    "evaluate_gates",
    "iou",
    "leakage_metrics",
    "load_gate_file",
    "match_spans",
    "over_redaction_metrics",
    "precision_recall_f1",
    "render_markdown",
    "render_table",
]

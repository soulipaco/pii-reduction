"""Benchmark report rows and rendering.

Rows follow the metric grain of ``docs/03_DATA_CONTRACTS.md`` §15
(``benchmark_run_id, provider, language, entity_type, document_type,
difficulty_tier, metric_name, metric_value, support``), so a report can be persisted
to a table as easily as printed.

Rendering is deliberately plain text: a benchmark that needs a dashboard to be read
does not get read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

__all__ = ["MetricRow", "render_markdown", "render_table"]


@dataclass(frozen=True)
class MetricRow:
    benchmark_run_id: str
    provider: str
    language: str
    entity_type: str
    document_type: str
    difficulty_tier: str
    metric_name: str
    metric_value: float
    support: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


COLUMNS = (
    ("language", "language"),
    ("entity_type", "entity"),
    ("document_type", "doc type"),
    ("difficulty_tier", "tier"),
    ("metric_name", "metric"),
    ("metric_value", "value"),
    ("support", "support"),
)


def _cell(row: MetricRow, field: str) -> str:
    value = getattr(row, field)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_table(rows: Sequence[MetricRow], *, title: str = "") -> str:
    """Fixed-width table for terminals."""
    if not rows:
        return f"{title}\n(no metrics)" if title else "(no metrics)"

    headers = [header for _, header in COLUMNS]
    body = [[_cell(row, field) for field, _ in COLUMNS] for row in rows]
    widths = [
        max(len(headers[index]), max(len(line[index]) for line in body))
        for index in range(len(headers))
    ]

    def format_line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    lines = []
    if title:
        lines.extend([title, "=" * len(title)])
    lines.append(format_line(headers))
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(format_line(line) for line in body)
    return "\n".join(lines)


def render_markdown(rows: Sequence[MetricRow], *, title: str = "") -> str:
    """Markdown table for the benchmark report of Increment E."""
    if not rows:
        return f"## {title}\n\n_(no metrics)_" if title else "_(no metrics)_"
    headers = [header for _, header in COLUMNS]
    lines = []
    if title:
        lines.extend([f"## {title}", ""])
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_cell(row, field) for field, _ in COLUMNS) + " |")
    return "\n".join(lines)

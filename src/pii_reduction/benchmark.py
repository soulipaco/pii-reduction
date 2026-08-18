"""Benchmark entry point: run the pipeline over a corpus and score it.

This module is an *entry point*, not a layer: it is the only place that imports both
``processing`` and ``evaluation``. Keeping them apart everywhere else is what stops
evaluation logic leaking into production transformation, and vice versa
(``AGENTS.md``, plan §3).

The report it prints is deliberately unflattering. At v0.1 the shipped chain detects
EMAIL and PHONE only, so PERSON appears with recall 0.000 and its full support count
rather than being filtered out of the table.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from pii_reduction.config.errors import ConfigurationError
from pii_reduction.config.loader import load_resolved_dataset
from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.evaluation.matching import RELAXED, STRICT, Prediction, TruthSpan
from pii_reduction.evaluation.metrics import (
    DetectionMetric,
    LeakageMetric,
    OverRedactionMetric,
    detection_metrics,
    detection_metrics_by,
    leakage_metrics,
    over_redaction_metrics,
)
from pii_reduction.evaluation.report import MetricRow, render_table
from pii_reduction.processing.pipeline import build_pipeline
from pii_reduction.sources.local import PandasSource
from pii_reduction.synthetic.corpus import Corpus, load_corpus

__all__ = ["DEFAULT_DATASETS", "BenchmarkOutcome", "run_benchmark"]

#: Dataset config per document type. One parser per dataset is the real-world shape:
#: transcripts and free-text notes are different contracts, not a runtime branch.
DEFAULT_DATASETS: dict[str, str] = {
    "plain": "benchmark_plain",
    "transcript": "benchmark_transcript",
}

SLICE_DIMENSIONS = ("entity_type", "language", "difficulty_tier")


@dataclass(frozen=True)
class BenchmarkOutcome:
    benchmark_run_id: str
    provider_chain: str
    strategy: str
    strict: DetectionMetric
    relaxed: DetectionMetric
    leakage: LeakageMetric
    over_redaction: OverRedactionMetric
    rows: tuple[MetricRow, ...] = ()
    # repr is suppressed on both: a bare `outcome` in a notebook cell would otherwise
    # dump every reduced document to the screen and into the saved notebook.
    predictions: tuple[Prediction, ...] = field(default=(), repr=False)
    reduced_texts: dict[str, str] = field(default_factory=dict, repr=False)
    documents: int = 0
    #: Splits this result covers; empty means the whole corpus. Recorded because
    #: ``AGENTS.md`` rule 9 requires it to reproduce a result, and because a
    #: ``--split dev`` table is otherwise indistinguishable from a whole-corpus one
    #: except by its support counts — which is how a partial number gets pasted into
    #: documentation as if it were the headline.
    splits: tuple[str, ...] = ()

    def table(self, *, title: str = "PII reduction benchmark") -> str:
        return render_table(self.rows, title=title)


def _truth_spans(corpus: Corpus) -> list[TruthSpan]:
    return [
        TruthSpan(
            document_id=entity.document_id,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            start=entity.start,
            end=entity.end,
            language=entity.language,
            difficulty_tier=entity.difficulty_tier,
            document_type=entity.document_type,
        )
        for entity in corpus.entities
    ]


def with_chain(config: ResolvedDataset, chain_name: str) -> ResolvedDataset:
    """Return the same dataset configuration with a different provider chain.

    Comparing chains is what a benchmark is for, and duplicating a dataset file per
    chain would put the comparison at the mercy of two files drifting apart. The
    override goes through the chain definition in the configuration, so an unknown
    chain still fails loudly.
    """
    chain = config.chains.get(chain_name)
    if chain is None:
        raise ConfigurationError(
            f"provider chain {chain_name!r} is not defined "
            f"(defined: {', '.join(sorted(config.chains))})"
        )
    columns = tuple(
        column.model_copy(
            update={
                "provider_chain": chain_name,
                "providers": chain.providers,
                "overlap_policy": chain.overlap_policy,
            }
        )
        for column in config.columns
    )
    return config.model_copy(update={"columns": columns})


def run_benchmark(
    *,
    corpus_dir: str | Path,
    configs_dir: str | Path,
    datasets: dict[str, str] | None = None,
    splits: Sequence[str] | None = None,
    provider_chain: str | None = None,
    benchmark_run_id: str | None = None,
) -> BenchmarkOutcome:
    """Process every document with its configured parser, then score the result."""
    corpus = load_corpus(corpus_dir)
    run_id = benchmark_run_id or uuid.uuid4().hex
    selected = datasets or DEFAULT_DATASETS

    frame = corpus.to_frame()
    if splits:
        frame = frame[frame["split"].isin(list(splits))]

    predictions: list[Prediction] = []
    reduced_texts: dict[str, str] = {}
    chains: set[str] = set()
    strategies: set[str] = set()
    #: Documents that actually ran. Accumulated here rather than derived from the
    #: split-filtered frame, because a narrowed ``datasets`` mapping skips whole
    #: document types (below) — deriving it from the frame would score those skipped
    #: documents as missed, which is the bug this exists to prevent.
    scored: set[str] = set()

    for document_type, dataset_name in selected.items():
        subset = frame[frame["document_type"] == document_type]
        if subset.empty:
            continue
        config = load_resolved_dataset(Path(configs_dir), dataset_name)
        if provider_chain is not None:
            config = with_chain(config, provider_chain)
        policy = config.columns[0]
        chains.add(policy.provider_chain)
        strategies.add(policy.reducer)

        pipeline = build_pipeline(config, run_id=f"{run_id}_{document_type}")
        outcome = pipeline.process(PandasSource(subset, name=config.dataset.name).load())

        scored.update(str(document_id) for document_id in subset["document_id"])
        predictions.extend(
            Prediction(
                document_id=str(row["row_id"]),
                entity_type=str(row["entity_type"]),
                start=int(row["start"]),
                end=int(row["end"]),
                provider=str(row["provider"]),
                score=_optional_float(row.get("score")),
            )
            for row in outcome.audit
        )
        reduced_texts.update(
            {
                str(row[config.dataset.row_id]): str(row[policy.output_column])
                for row in outcome.frame.to_dict(orient="records")
                if row[policy.output_column] is not None
            }
        )

    # Ground truth is restricted to the documents that actually ran. Scoring a subset
    # against the whole corpus's truth counts every unprocessed document's entities as
    # missed and every unprocessed protected token as destroyed, which understates
    # recall and invents over-redaction — measured, not theoretical: a dev+calibration
    # run reported over-redaction 0.627 against a true 0.000. Increment E's split
    # discipline depends on these numbers being right.
    truths = [truth for truth in _truth_spans(corpus) if truth.document_id in scored]
    surfaces = {entity.entity_id: entity.surface for entity in corpus.entities}
    strategy = ", ".join(sorted(strategies))
    chain = ", ".join(sorted(chains))

    strict = detection_metrics(truths, predictions, mode=STRICT)
    relaxed = detection_metrics(truths, predictions, mode=RELAXED)
    leakage = leakage_metrics(truths, reduced_texts, surfaces, strategy=strategy)
    over_redaction = over_redaction_metrics(
        (
            (token.document_id, token.token, token.kind)
            for token in corpus.protected
            if token.document_id in scored
        ),
        reduced_texts,
    )

    rows = _build_rows(
        benchmark_run_id=run_id,
        provider=chain,
        truths=truths,
        predictions=predictions,
        strict=strict,
        relaxed=relaxed,
        leakage=leakage,
        over_redaction=over_redaction,
    )
    return BenchmarkOutcome(
        benchmark_run_id=run_id,
        provider_chain=chain,
        strategy=strategy,
        strict=strict,
        relaxed=relaxed,
        leakage=leakage,
        over_redaction=over_redaction,
        rows=tuple(rows),
        predictions=tuple(predictions),
        reduced_texts=reduced_texts,
        # What ran, not what was selected: a narrowed `datasets` mapping skips whole
        # document types, and reporting the frame size would overstate coverage.
        documents=len(scored),
        splits=tuple(splits) if splits else (),
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    return float(value)  # type: ignore[arg-type]


def _build_rows(
    *,
    benchmark_run_id: str,
    provider: str,
    truths: Sequence[TruthSpan],
    predictions: Sequence[Prediction],
    strict: DetectionMetric,
    relaxed: DetectionMetric,
    leakage: LeakageMetric,
    over_redaction: OverRedactionMetric,
) -> list[MetricRow]:
    def row(
        *,
        language: str,
        entity_type: str,
        document_type: str,
        tier: str,
        metric_name: str,
        metric_value: float,
        support: int,
    ) -> MetricRow:
        return MetricRow(
            benchmark_run_id=benchmark_run_id,
            provider=provider,
            language=language,
            entity_type=entity_type,
            document_type=document_type,
            difficulty_tier=tier,
            metric_name=metric_name,
            metric_value=metric_value,
            support=support,
        )

    rows: list[MetricRow] = []
    overall = {
        "strict_precision": strict.precision,
        "strict_recall": strict.recall,
        "strict_f1": strict.f1,
        "relaxed_f1": relaxed.f1,
        "leakage_rate": leakage.rate,
        "document_clean_rate": leakage.document_clean_rate,
        "over_redaction_rate": over_redaction.rate,
    }
    for name, value in overall.items():
        support = (
            over_redaction.total
            if name == "over_redaction_rate"
            else leakage.documents_with_pii
            if name == "document_clean_rate"
            else strict.support
        )
        rows.append(
            row(
                language="*",
                entity_type="*",
                document_type="*",
                tier="*",
                metric_name=name,
                metric_value=value,
                support=support,
            )
        )

    by_entity = detection_metrics_by(truths, predictions, dimensions=("entity_type",))
    for (entity_type,), metric in sorted(by_entity.items()):
        for name, value in (
            ("strict_precision", metric.precision),
            ("strict_recall", metric.recall),
            ("strict_f1", metric.f1),
        ):
            rows.append(
                row(
                    language="*",
                    entity_type=entity_type,
                    document_type="*",
                    tier="*",
                    metric_name=name,
                    metric_value=value,
                    support=metric.support,
                )
            )

    sliced = detection_metrics_by(truths, predictions, dimensions=SLICE_DIMENSIONS)
    for (entity_type, language, tier), metric in sorted(sliced.items()):
        rows.append(
            row(
                language=language,
                entity_type=entity_type,
                document_type="*",
                tier=tier,
                metric_name="strict_recall",
                metric_value=metric.recall,
                support=metric.support,
            )
        )

    by_document_type = detection_metrics_by(truths, predictions, dimensions=("document_type",))
    for (document_type,), metric in sorted(by_document_type.items()):
        rows.append(
            row(
                language="*",
                entity_type="*",
                document_type=document_type,
                tier="*",
                metric_name="strict_f1",
                metric_value=metric.f1,
                support=metric.support,
            )
        )
    return rows


def summarise(outcome: BenchmarkOutcome) -> str:
    """One-paragraph summary printed under the table."""
    splits = ", ".join(outcome.splits) if outcome.splits else "all"
    return (
        f"documents={outcome.documents} entities={outcome.strict.support} "
        f"splits={splits} chain={outcome.provider_chain} strategy={outcome.strategy}\n"
        f"strict f1={outcome.strict.f1:.3f} relaxed f1={outcome.relaxed.f1:.3f} "
        f"leakage={outcome.leakage.rate:.3f} "
        f"document clean rate={outcome.leakage.document_clean_rate:.3f} "
        f"over-redaction={outcome.over_redaction.rate:.3f}"
    )


def load_corpus_frame(corpus_dir: str | Path) -> pd.DataFrame:
    """Convenience for notebooks: the corpus as a frame."""
    return load_corpus(corpus_dir).to_frame()

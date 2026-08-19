"""Pipeline construction and execution.

``build_pipeline(config)`` then ``pipeline.process(dataset)`` — the same two calls
local and Databricks runners make (``docs/01_ARCHITECTURE.md``, local/Databricks
parity). What differs between runtimes is the source and output adapter, never the
entity logic.

This module is the one place that knows about *both* configuration and the component
registries; every other package is built from primitives so it stays config-free.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pii_reduction import __version__
from pii_reduction.config.fingerprint import config_fingerprint
from pii_reduction.config.models import FailureMode, LanguageMode
from pii_reduction.config.resolved import ResolvedColumnPolicy, ResolvedDataset
from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.contracts.results import (
    ProcessedFieldResult,
    ProcessingStatus,
    RowResult,
    RunMetadata,
)
from pii_reduction.entities.reconcile import ReconciliationPolicy
from pii_reduction.language.base import LanguageResolver
from pii_reduction.language.gate import ShortTextGate
from pii_reduction.language.registry import DETECTOR_DISTRIBUTIONS, build_resolver
from pii_reduction.observability.logging import get_logger, safe_fields
from pii_reduction.observability.metrics import RunMetricsAccumulator
from pii_reduction.observability.versions import describe_versions
from pii_reduction.outputs.local import write_json
from pii_reduction.outputs.registry import build_output
from pii_reduction.parsers.registry import build_parser
from pii_reduction.processing.errors import ProcessingError
from pii_reduction.processing.field_processor import FieldProcessor, ProviderChain
from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.registry import build_provider, provider_distributions
from pii_reduction.reducers.registry import build_reducer
from pii_reduction.sources.base import SourceDataset
from pii_reduction.sources.registry import build_source

__all__ = ["Pipeline", "ProcessingOutcome", "build_pipeline"]

STATUS_COLUMN = "pii_status"
RUN_ID_COLUMN = "pii_run_id"

logger = get_logger("processing")


@dataclass(frozen=True)
class ProcessingOutcome:
    """Everything one run produced, in memory."""

    frame: pd.DataFrame
    run: RunMetadata
    row_results: tuple[RowResult, ...] = ()
    audit: tuple[dict[str, Any], ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)
    written: dict[str, str] = field(default_factory=dict)

    def metrics_payload(self) -> dict[str, Any]:
        """The run-metrics document: run record plus distributions. Metadata only."""
        return {"run": self.run.model_dump(mode="json"), "detail": self.detail}


class Pipeline:
    """A configured dataset, ready to run."""

    def __init__(
        self,
        config: ResolvedDataset,
        *,
        run_id: str | None = None,
        pipeline_version: str = __version__,
    ) -> None:
        self.config = config
        self.run_id = run_id or uuid.uuid4().hex
        self.pipeline_version = pipeline_version
        self.config_hash = config_fingerprint(config)
        # Providers and chains are shared across columns and language routes: two
        # chains naming the same provider must not each load its models.
        self._providers: dict[str, BaseProvider] = {}
        self._chains: dict[str, ProviderChain] = {}
        self._processors = tuple(self._build_processor(policy) for policy in config.columns)
        self._failure_modes = {policy.column: policy.failure_mode for policy in config.columns}

    # -- construction ------------------------------------------------------------

    def _provider(self, name: str) -> BaseProvider:
        """Build a provider instance once and share it across every chain using it.

        Two chains naming the same provider must not each load its models.
        """
        provider = self._providers.get(name)
        if provider is None:
            settings = self.config.providers[name]
            provider = build_provider(settings.type, dict(settings.options), name=name)
            self._providers[name] = provider
        return provider

    def _chain(self, chain_name: str, policy: ResolvedColumnPolicy) -> ProviderChain:
        chain = self._chains.get(chain_name)
        if chain is not None:
            return chain
        settings = self.config.chains[chain_name]
        providers = tuple(self._provider(name) for name in settings.providers)
        chain = ProviderChain(
            name=chain_name,
            providers=providers,
            policy=ReconciliationPolicy(
                priorities={
                    label: entity.priority for label, entity in self.config.entities.items()
                },
                provider_order=settings.providers,
                thresholds={
                    name: dict(self.config.providers[name].thresholds)
                    for name in settings.providers
                },
                entities=frozenset(policy.entities),
                name=settings.overlap_policy,
            ),
            entity_scopes={
                name: frozenset(self.config.providers[name].entities)
                for name in settings.providers
                if self.config.providers[name].entities
            },
            language_scopes={
                name: frozenset(languages)
                for name in settings.providers
                if (languages := self.config.providers[name].languages)
            },
        )
        self._chains[chain_name] = chain
        return chain

    def _build_processor(self, policy: ResolvedColumnPolicy) -> FieldProcessor:
        reducer_settings = self.config.reducers.get(policy.reducer)
        reducer = build_reducer(
            policy.reducer,
            dict(reducer_settings.options) if reducer_settings else None,
            replacements={
                label: entity.replacement for label, entity in self.config.entities.items()
            },
            scope_value=self.config.dataset.name,
        )
        # Per-language routes from the `languages:` block; unrouted languages take the
        # column's own chain, and unknown/unsupported ones the safe fallback.
        routing = {
            code: self._chain(route.chain, policy) for code, route in self.config.languages.items()
        }
        fallback_name = policy.language.fallback_chain
        fallback = self._chain(fallback_name, policy) if fallback_name else None

        return FieldProcessor(
            column=policy.column,
            output_column=policy.output_column,
            parser=build_parser(policy.parser, dict(policy.parser_options)),
            resolver=_build_language_resolver(policy),
            reducer=reducer,
            entities=frozenset(policy.entities),
            default_chain=self._chain(policy.provider_chain, policy),
            routing=routing,
            fallback_chain=fallback,
        )

    # -- execution ---------------------------------------------------------------

    def load(self) -> SourceDataset:
        source = build_source(
            self.config.source.type,
            name=self.config.dataset.name,
            path=self.config.source.path,
            options=dict(self.config.source.options),
        )
        return source.load()

    def run(self) -> ProcessingOutcome:
        """Load from the configured source, process, and write the configured outputs."""
        outcome = self.process(self.load())
        return self.write(outcome)

    def process(self, dataset: SourceDataset) -> ProcessingOutcome:
        """Process an already-loaded dataset. The same call on every runtime."""
        frame = dataset.frame.copy()
        self._validate_source(frame)

        metrics = RunMetricsAccumulator(
            run_id=self.run_id,
            pipeline_version=self.pipeline_version,
            config_hash=self.config_hash,
            source_dataset=self.config.dataset.name,
            source_version=dataset.source_version or self.config.dataset.source_version,
        )
        metrics.rows_read = len(frame)
        # Each value is the provider type plus the installed versions of the
        # libraries and models behind it (importlib.metadata only — nothing is
        # imported and no model is loaded). Like `threshold_calibration` below,
        # this describes the CONFIGURED providers, not which ones this run's
        # chain reached; the name prefix keeps that honest. On a machine without
        # an extra installed the value degrades to the bare type string, which is
        # exactly what this field carried before session 9.
        metrics.provider_versions = {
            name: describe_versions(
                settings.type, provider_distributions(settings.type, settings.options)
            )
            for name, settings in self.config.providers.items()
        }
        detector_names = sorted(
            {
                policy.language.detector
                for policy in self.config.columns
                if policy.language.mode is LanguageMode.DETECT
                and policy.language.detector != "none"
            }
        )
        if detector_names:
            metrics.language_detector_version = "; ".join(
                describe_versions(name, DETECTOR_DISTRIBUTIONS.get(name, ()))
                for name in detector_names
            )
        # A run is attributable to the pseudonymization key that produced its
        # tokens. `key_id` is a contract attribute on `BaseReducer` (a non-secret
        # truncated digest, never the key), read through getattr because the
        # field processor types its reducer as the structural protocol.
        # Comma-joined when columns are configured with different keys.
        key_ids = sorted(
            {
                key_id
                for processor in self._processors
                if (key_id := getattr(processor.reducer, "key_id", None)) is not None
            }
        )
        if key_ids:
            metrics.pseudonymization_key_id = ",".join(key_ids)
        # Calibration state of the CONFIGURED providers, each note attributed to its
        # provider by name — like `provider_versions` above, this describes the
        # configuration, not which providers this particular run's chain reached. A
        # deterministic-only run therefore carries `presidio=...` too, and the prefix
        # is what keeps that honest rather than misattributed. No notes at all keeps
        # the accumulator's default ("default_uncalibrated").
        notes = sorted(
            f"{name}={settings.calibration}"
            for name, settings in self.config.providers.items()
            if settings.calibration
        )
        if notes:
            metrics.threshold_calibration = "; ".join(notes)

        outputs: dict[str, list[str | None]] = {
            processor.output_column: [] for processor in self._processors
        }
        row_results: list[RowResult] = []
        audit: list[dict[str, Any]] = []

        row_id_column = self.config.dataset.row_id
        # Column labels are Hashable to pandas; the field processor works with names.
        records = [
            {str(key): value for key, value in record.items()}
            for record in frame.to_dict(orient="records")
        ]
        for record in records:
            started = time.perf_counter()
            row_id = str(record[row_id_column])
            field_results = []
            row_status = ProcessingStatus.SUCCESS

            for processor in self._processors:
                original = record.get(processor.column)
                try:
                    field_outcome = processor.process(
                        original, row=record, run_id=self.run_id, row_id=row_id
                    )
                except Exception as exc:
                    result, output_value, failure_status = self._handle_failure(
                        processor, exc, original=original, row_id=row_id
                    )
                    metrics.fields_failed += 1
                    metrics.error_categories[type(exc).__name__] += 1
                    outputs[processor.output_column].append(output_value)
                    field_results.append(result)
                    row_status = failure_status
                    continue

                result = field_outcome.result
                outputs[processor.output_column].append(result.output_text)
                field_results.append(result)
                audit.extend(field_outcome.audit)

                if result.status is ProcessingStatus.SKIPPED:
                    metrics.rows_skipped += 1
                else:
                    metrics.fields_processed += 1
                    metrics.entities_detected += result.entities_detected
                    metrics.entities_reduced += result.entities_reduced
                    metrics.reduction_strategies[processor.reducer.name] += result.entities_reduced
                    for label, count in result.entity_counts.items():
                        metrics.entity_counts[label] += count
                if field_outcome.language is not None:
                    metrics.record_language(
                        field_outcome.language.language,
                        fallback_used=field_outcome.language.fallback_used,
                    )
                metrics.record_fallbacks(field_outcome.fallbacks)
                metrics.record_rejections(field_outcome.rejections)
                if result.status is ProcessingStatus.SUCCESS_WITH_FALLBACK:
                    metrics.fields_with_fallback += 1
                    row_status = (
                        ProcessingStatus.SUCCESS_WITH_FALLBACK
                        if row_status is ProcessingStatus.SUCCESS
                        else row_status
                    )

            elapsed_ms = (time.perf_counter() - started) * 1000
            metrics.processing_ms += elapsed_ms
            metrics.row_statuses[row_status.value] += 1
            row_results.append(
                RowResult(
                    dataset=self.config.dataset.name,
                    row_id=row_id,
                    run_id=self.run_id,
                    field_results=tuple(field_results),
                    processing_ms=elapsed_ms,
                    status=row_status,
                )
            )

        # ADR-0004: dropped native labels must reach observability output. A provider
        # upgrade that starts emitting an unmapped label loses coverage silently
        # otherwise, and `dropped_labels: {}` would read as "nothing was dropped".
        for processor in self._processors:
            for provider in processor.providers:
                metrics.dropped_labels.update(provider.drop_counter.as_dict())

        for column, values in outputs.items():
            frame[column] = values
        frame[RUN_ID_COLUMN] = self.run_id
        frame[STATUS_COLUMN] = [result.status.value for result in row_results]

        metrics.rows_written = len(frame)
        outcome = ProcessingOutcome(
            frame=frame,
            run=metrics.build(completed_at=datetime.now(UTC)),
            row_results=tuple(row_results),
            audit=tuple(audit),
            detail=metrics.detail(),
        )
        self._validate_output(dataset, outcome)
        logger.info(
            "run complete %s",
            safe_fields(
                dataset=self.config.dataset.name,
                run_id=self.run_id,
                rows_read=outcome.run.rows_read,
                rows_written=outcome.run.rows_written,
                fields_processed=outcome.run.fields_processed,
                fields_failed=outcome.run.fields_failed,
                entities_reduced=outcome.run.entities_reduced,
                config_hash=self.config_hash,
                status=outcome.run.status.value,
            ),
        )
        return outcome

    def write(self, outcome: ProcessingOutcome) -> ProcessingOutcome:
        """Persist the reduced dataset, the run metrics, and optionally the audit rows."""
        destination = self.config.destination
        adapter = build_output(destination.type, path=destination.path, mode=destination.mode)
        name = self.config.dataset.name
        written = {"dataset": adapter.write(outcome.frame, name=name)}

        base = Path(destination.path)
        directory = base.parent if base.suffix else base
        written["run_metrics"] = write_json(
            directory / f"{name}_run_metrics.json", outcome.metrics_payload()
        )
        if self.config.observability.write_detection_audit and outcome.audit:
            written["audit"] = adapter.write(
                pd.DataFrame(list(outcome.audit)), name=f"{name}_pii_audit"
            )

        logger.info(
            "outputs written %s",
            safe_fields(dataset=name, run_id=self.run_id, destination=destination.type),
        )
        return ProcessingOutcome(
            frame=outcome.frame,
            run=outcome.run,
            row_results=outcome.row_results,
            audit=outcome.audit,
            detail=outcome.detail,
            written=written,
        )

    # -- failure policy and validation -------------------------------------------

    def _handle_failure(
        self,
        processor: FieldProcessor,
        exc: Exception,
        *,
        original: object,
        row_id: str,
    ) -> tuple[ProcessedFieldResult, str | None, ProcessingStatus]:
        """Apply the configured failure mode (``docs/01_ARCHITECTURE.md``, failure strategy).

        Returns the field result, the value written to the output column, and the
        status the row takes.

        The recorded message is kept only for this package's own exceptions, which are
        written to be privacy-safe. A third-party exception could quote a cell value,
        so only its type is retained.
        """
        policy = self._failure_modes[processor.column]
        category = type(exc).__name__
        message = str(exc) if isinstance(exc, PiiReductionError) else None

        logger.warning(
            "field failed %s",
            safe_fields(
                dataset=self.config.dataset.name,
                run_id=self.run_id,
                row_id=row_id,
                column=processor.column,
                error_category=category,
            ),
        )
        if policy is FailureMode.FAIL_FAST:
            raise ProcessingError(
                f"dataset {self.config.dataset.name!r}, row {row_id!r}, column "
                f"{processor.column!r}: processing failed ({category}); failure_mode is "
                "'fail_fast'"
            ) from exc

        result = processor.failed(error_category=category, error=message)
        if policy is FailureMode.QUARANTINE_ROW:
            # The row stays (row count is preserved) but carries no reduced value,
            # so nothing unreviewed can be mistaken for reduced output.
            return result, None, ProcessingStatus.FAILED
        # preserve_original_and_record_error: the source text passes through unchanged.
        return (
            result,
            original if isinstance(original, str) else None,
            ProcessingStatus.PARTIAL_FAILURE,
        )

    def _validate_source(self, frame: pd.DataFrame) -> None:
        row_id_column = self.config.dataset.row_id
        if row_id_column not in frame.columns:
            raise ProcessingError(
                f"dataset {self.config.dataset.name!r}: row id column {row_id_column!r} is not "
                f"present in the source (columns: {', '.join(map(str, frame.columns))})"
            )
        if frame[row_id_column].isna().any():
            raise ProcessingError(
                f"dataset {self.config.dataset.name!r}: row id column {row_id_column!r} contains "
                "null values; row identity must be stable"
            )
        duplicates = frame[row_id_column].duplicated()
        if duplicates.any():
            raise ProcessingError(
                f"dataset {self.config.dataset.name!r}: row id column {row_id_column!r} has "
                f"{int(duplicates.sum())} duplicate values; row identity must be unique"
            )
        for processor in self._processors:
            if processor.column not in frame.columns:
                raise ProcessingError(
                    f"dataset {self.config.dataset.name!r}: configured column "
                    f"{processor.column!r} is not present in the source "
                    f"(columns: {', '.join(map(str, frame.columns))})"
                )
            if processor.output_column in frame.columns:
                raise ProcessingError(
                    f"dataset {self.config.dataset.name!r}: output column "
                    f"{processor.output_column!r} already exists in the source"
                )

    def _validate_output(self, dataset: SourceDataset, outcome: ProcessingOutcome) -> None:
        rules = self.config.validation
        if rules.require_row_count_match and len(outcome.frame) != len(dataset.frame):
            raise ProcessingError(
                f"dataset {self.config.dataset.name!r}: row count changed from "
                f"{len(dataset.frame)} to {len(outcome.frame)}"
            )
        if rules.require_output_columns:
            missing = [
                processor.output_column
                for processor in self._processors
                if processor.output_column not in outcome.frame.columns
            ]
            if missing:
                raise ProcessingError(
                    f"dataset {self.config.dataset.name!r}: output columns missing: "
                    f"{', '.join(missing)}"
                )
        if rules.require_original_unchanged:
            for processor in self._processors:
                original = dataset.frame[processor.column]
                if not original.equals(outcome.frame[processor.column]):
                    raise ProcessingError(
                        f"dataset {self.config.dataset.name!r}: source column "
                        f"{processor.column!r} was modified; reduction must be non-destructive"
                    )


def _build_language_resolver(policy: ResolvedColumnPolicy) -> LanguageResolver:
    settings = policy.language
    return build_resolver(
        settings.mode.value,
        supported=settings.supported,
        detector=settings.detector,
        static_language=settings.static_language,
        language_column=settings.language_column,
        unknown_language=settings.unknown_language,
        gate=ShortTextGate(
            min_chars=settings.min_chars,
            min_alpha_chars=settings.min_alpha_chars,
            min_confidence=settings.min_confidence,
        ),
    )


def build_pipeline(
    config: ResolvedDataset,
    *,
    run_id: str | None = None,
    pipeline_version: str = __version__,
) -> Pipeline:
    """Construct the pipeline for a resolved dataset configuration."""
    return Pipeline(config, run_id=run_id, pipeline_version=pipeline_version)

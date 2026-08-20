"""The local runtime: the same ``build_pipeline(config).run()`` a person types.

There is no second implementation here and there must never be one (`AGENTS.md`
rule 10). The whole module is a call and a conversion, and the conversion is the
part that matters: ``ProcessingOutcome`` carries ``frame`` — the source frame with
reduced columns appended — and ``row_results``, whose per-field records hold the
reduced text and any error message raised below this layer. None of that may reach
the run store, so the boundary is here (ADR-0026 rule 3).
"""

from __future__ import annotations

from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.processing.pipeline import build_pipeline
from pii_reduction.service.models import RunSummary

__all__ = ["local_runtime"]


def local_runtime(config: ResolvedDataset) -> RunSummary:
    """Run the dataset locally and return metadata about the run.

    ``written`` is the map of artifact name to destination path. Those paths came
    from the dataset's own destination configuration, which is the one place
    `docs/09`'s display rules permit a configuration-derived file name.
    """
    outcome = build_pipeline(config).run()
    run = outcome.run
    return RunSummary(
        engine_run_id=run.run_id,
        config_hash=run.config_hash,
        status=run.status.value,
        rows_read=run.rows_read,
        rows_written=run.rows_written,
        fields_processed=run.fields_processed,
        fields_failed=run.fields_failed,
        entities_detected=run.entities_detected,
        entities_reduced=run.entities_reduced,
        outputs=dict(outcome.written),
    )

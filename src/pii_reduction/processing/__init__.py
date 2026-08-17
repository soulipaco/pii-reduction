"""Orchestration: build a pipeline from configuration and run it."""

from pii_reduction.processing.errors import ProcessingError
from pii_reduction.processing.field_processor import FieldOutcome, FieldProcessor
from pii_reduction.processing.pipeline import (
    RUN_ID_COLUMN,
    STATUS_COLUMN,
    Pipeline,
    ProcessingOutcome,
    build_pipeline,
)

__all__ = [
    "RUN_ID_COLUMN",
    "STATUS_COLUMN",
    "FieldOutcome",
    "FieldProcessor",
    "Pipeline",
    "ProcessingError",
    "ProcessingOutcome",
    "build_pipeline",
]

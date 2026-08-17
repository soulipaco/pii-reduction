"""Synthetic corpus generation with injection-time ground truth."""

from pii_reduction.synthetic.corpus import (
    Corpus,
    ProtectedToken,
    SyntheticDocument,
    TruthEntity,
    build_corpus,
    load_corpus,
    write_corpus,
)
from pii_reduction.synthetic.errors import CorpusError, GroundTruthError
from pii_reduction.synthetic.values import PoolValueProvider, SyntheticValue, ValueProvider

__all__ = [
    "Corpus",
    "CorpusError",
    "GroundTruthError",
    "PoolValueProvider",
    "ProtectedToken",
    "SyntheticDocument",
    "SyntheticValue",
    "TruthEntity",
    "ValueProvider",
    "build_corpus",
    "load_corpus",
    "write_corpus",
]

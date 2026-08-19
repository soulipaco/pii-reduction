"""Referential consistency of pseudonymization, measured end to end (docs/17 D5).

The unit tests pin the metric's arithmetic; the corpus measurement runs the real
benchmark pipelines over the committed corpus with the `pseudonymize` strategy and
measures the property that was previously only asserted: same value → same token,
distinct values → distinct tokens, within a dataset scope — and different tokens
for the same value *across* dataset scopes, which is scope isolation working.

Default tier: the deterministic chain needs no models, and EMAIL/PHONE recall and
precision are 1.000 on this corpus (gated), which is what makes the positional
truth-to-token pairing below sound — every truth span of those types becomes
exactly one token, in order.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

from pii_reduction.benchmark import BenchmarkOutcome, run_benchmark
from pii_reduction.evaluation.consistency import referential_consistency
from pii_reduction.reducers.pseudonymize import DEFAULT_KEY_ENV
from pii_reduction.synthetic.corpus import Corpus, TruthEntity, load_corpus

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "corpus"
CONFIGS_DIR = REPO_ROOT / "configs"

TEST_KEY = "test-key-not-a-real-secret-0123456789"

#: The deterministic entity types: recall and precision 1.000 on this corpus, so
#: positional pairing of truths and tokens is exact. That precondition is not an
#: assumption — `configs/benchmark_gates.yaml` pins both at min 1.000 with
#: support 51 each, in the same CI tier this test runs in; if those gates ever
#: move, the per-document count assertion below fails loudly as well.
DETERMINISTIC_TYPES = ("EMAIL", "PHONE")


class TestMetricArithmetic:
    def test_perfect_consistency(self) -> None:
        (result,) = referential_consistency(
            [
                ("EMAIL", "a@example.com", "EMAIL_AAAAAA"),
                ("EMAIL", "a@example.com", "EMAIL_AAAAAA"),
                ("EMAIL", "b@example.com", "EMAIL_BBBBBB"),
            ]
        )
        assert result.occurrences == 3
        assert result.distinct_values == 2 and result.distinct_tokens == 2
        assert result.consistency_rate == 1.0 and result.distinctness_rate == 1.0

    def test_an_inconsistent_value_is_counted(self) -> None:
        # One value, two tokens: one subject split across join keys.
        (result,) = referential_consistency(
            [
                ("EMAIL", "a@example.com", "EMAIL_AAAAAA"),
                ("EMAIL", "a@example.com", "EMAIL_CCCCCC"),
            ]
        )
        assert result.inconsistent_values == 1
        assert result.consistency_rate == 0.0

    def test_a_merged_token_is_counted(self) -> None:
        # Two values, one token: two subjects fused — the collision failure.
        (result,) = referential_consistency(
            [
                ("EMAIL", "a@example.com", "EMAIL_AAAAAA"),
                ("EMAIL", "b@example.com", "EMAIL_AAAAAA"),
            ]
        )
        assert result.merged_tokens == 1
        assert result.distinctness_rate == 0.0

    def test_types_are_measured_separately(self) -> None:
        results = referential_consistency(
            [
                ("EMAIL", "a@example.com", "EMAIL_AAAAAA"),
                ("PHONE", "+1 (202) 555-0143", "PHONE_DDDDDD"),
            ]
        )
        assert [result.entity_type for result in results] == ["EMAIL", "PHONE"]

    def test_no_observations_yield_no_rows_and_zero_rates(self) -> None:
        assert referential_consistency([]) == ()


def _token_pattern(entity_type: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(entity_type)}_[0-9A-F]{{6}}\b")


def _observations(
    corpus: Corpus,
    reduced_texts: dict[str, str],
    document_type: str,
) -> list[tuple[str, str, str]]:
    """Pair each deterministic truth with its token, positionally per document."""
    type_of = {document.document_id: document.document_type for document in corpus.documents}
    truths_by_document: dict[str, list[TruthEntity]] = defaultdict(list)
    for entity in corpus.entities:
        if entity.entity_type in DETERMINISTIC_TYPES and type_of[entity.document_id] == (
            document_type
        ):
            truths_by_document[entity.document_id].append(entity)

    observations: list[tuple[str, str, str]] = []
    for document_id, truths in truths_by_document.items():
        reduced = reduced_texts[document_id]
        for entity_type in DETERMINISTIC_TYPES:
            typed = sorted(
                (truth for truth in truths if truth.entity_type == entity_type),
                key=lambda truth: truth.start,
            )
            tokens = _token_pattern(entity_type).findall(reduced)
            assert len(tokens) == len(typed), (
                f"document {document_id}: {len(typed)} {entity_type} truths but "
                f"{len(tokens)} tokens — the 1.000 recall/precision precondition broke"
            )
            observations.extend(
                (entity_type, truth.surface, token)
                for truth, token in zip(typed, tokens, strict=True)
            )
    return observations


@pytest.fixture(scope="module")
def measurement() -> tuple[Corpus, BenchmarkOutcome]:
    # MonkeyPatch.context rather than raw os.environ: a developer with a real key
    # exported in their shell must get it back after this module runs.
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setenv(DEFAULT_KEY_ENV, TEST_KEY)
        outcome = run_benchmark(
            corpus_dir=CORPUS_DIR,
            configs_dir=CONFIGS_DIR,
            reducer="pseudonymize",
            benchmark_run_id="consistency_measurement",
        )
    corpus = load_corpus(CORPUS_DIR)
    return corpus, outcome


class TestMeasuredOnTheCommittedCorpus:
    def test_consistency_and_distinctness_are_measured_perfect(self, measurement) -> None:  # type: ignore[no-untyped-def]
        """The D5 number: within each dataset scope, 1.000 on both rates.

        102 deterministic occurrences (51 EMAIL + 51 PHONE) across the two
        document types; every repeated value shares its token, no token covers
        two values.
        """
        corpus, outcome = measurement
        total_occurrences = 0
        for document_type in ("plain", "transcript"):
            observations = _observations(corpus, outcome.reduced_texts, document_type)
            for result in referential_consistency(observations):
                assert result.consistency_rate == 1.0, (
                    f"{document_type}/{result.entity_type}: "
                    f"{result.inconsistent_values} values with more than one token"
                )
                assert result.distinctness_rate == 1.0, (
                    f"{document_type}/{result.entity_type}: "
                    f"{result.merged_tokens} tokens covering more than one value"
                )
                total_occurrences += result.occurrences
        assert total_occurrences == 102  # 51 EMAIL + 51 PHONE, the gated support

    def test_dataset_scope_isolates_tokens_across_document_types(self, measurement) -> None:  # type: ignore[no-untyped-def]
        """The same value in the plain and transcript datasets gets different
        tokens: scope is mixed into the HMAC message, so dataset scope means
        dataset-bounded linkage (`reducers/pseudonymize.py`)."""
        corpus, outcome = measurement
        tokens_by_scope: dict[str, dict[tuple[str, str], set[str]]] = {}
        for document_type in ("plain", "transcript"):
            grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
            for entity_type, value, token in _observations(
                corpus, outcome.reduced_texts, document_type
            ):
                grouped[(entity_type, value)].add(token)
            tokens_by_scope[document_type] = grouped

        shared = set(tokens_by_scope["plain"]) & set(tokens_by_scope["transcript"])
        assert shared, "the corpus pools repeat values across document types by design"
        for key in shared:
            assert tokens_by_scope["plain"][key].isdisjoint(tokens_by_scope["transcript"][key]), (
                f"{key[0]}: the same value received the same token in both datasets — "
                "dataset scope is not isolating"
            )

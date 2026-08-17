"""Language-driven provider routing (``docs/04_PII_ENGINE.md``, provider routing).

These run in the default tier and use the column resolver rather than a detector: the
question here is what the pipeline *does* with a language claim, which is separable
from how the claim was produced. Detection quality is covered by
``tests/test_language_detection.py``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.config import load_resolved_dataset
from pii_reduction.processing import build_pipeline
from pii_reduction.sources import PandasSource
from tests.conftest import write_configs

pytestmark = pytest.mark.unit

ROUTING_PROJECT = """
project:
  name: routing-test
  environment: local

processing:
  default_parser: plain_text
  default_reducer: redact
  default_provider_chain: email_only
  output_suffix: _pii_redacted

language:
  mode: column
  detector: none
  language_column: language
  supported: [en, de, el]
  fallback_chain: safe_fallback

providers:
  email_provider:
    type: deterministic
    entities: [EMAIL]
    options:
      regions: [GR]
  phone_provider:
    type: deterministic
    entities: [PHONE]

chains:
  email_only:
    providers: [email_provider]
  phone_only:
    providers: [phone_provider]
  safe_fallback:
    providers: [email_provider]

languages:
  de:
    chain: phone_only
"""

ROUTING_DATASET = """
dataset:
  name: routing_demo
  row_id: row_id

source:
  type: csv
  path: unused.csv

destination:
  type: csv
  path: out/

columns:
  body:
    parser: plain_text
    entities: [EMAIL, PHONE]
"""

TEXT = "write to maria@example.com or call +30 210 000 0020"

ROWS = [
    {"row_id": "r1", "language": "en", "body": TEXT},
    {"row_id": "r2", "language": "de", "body": TEXT},
    {"row_id": "r3", "language": "fr", "body": TEXT},
    {"row_id": "r4", "language": "", "body": TEXT},
]


@pytest.fixture
def routed(tmp_path: Path):  # type: ignore[no-untyped-def]
    configs = write_configs(tmp_path, project_yaml=ROUTING_PROJECT, dataset_yaml=ROUTING_DATASET)
    config = load_resolved_dataset(configs, "demo_smoke")
    pipeline = build_pipeline(config, run_id="routing_run")
    dataset = PandasSource(pd.DataFrame(ROWS), name="routing_demo").load()
    outcome = pipeline.process(dataset)
    return {row["row_id"]: row for row in outcome.frame.to_dict(orient="records")}, outcome


class TestRouting:
    def test_an_unrouted_language_uses_the_column_chain(self, routed) -> None:  # type: ignore[no-untyped-def]
        rows, _ = routed
        # en has no explicit route, so the default chain (EMAIL only) applies.
        assert "<EMAIL>" in rows["r1"]["body_pii_redacted"]
        assert "+30 210 000 0020" in rows["r1"]["body_pii_redacted"]

    def test_a_routed_language_uses_its_own_chain(self, routed) -> None:  # type: ignore[no-untyped-def]
        rows, _ = routed
        # de is routed to phone_only, so the phone goes and the email stays.
        assert "<PHONE>" in rows["r2"]["body_pii_redacted"]
        assert "maria@example.com" in rows["r2"]["body_pii_redacted"]

    def test_an_unsupported_language_takes_the_safe_fallback(self, routed) -> None:  # type: ignore[no-untyped-def]
        rows, _ = routed
        # fr is not supported: the fallback chain runs, never the German route.
        assert "<EMAIL>" in rows["r3"]["body_pii_redacted"]
        assert "+30 210 000 0020" in rows["r3"]["body_pii_redacted"]

    def test_a_missing_language_takes_the_safe_fallback(self, routed) -> None:  # type: ignore[no-untyped-def]
        rows, _ = routed
        assert "<EMAIL>" in rows["r4"]["body_pii_redacted"]

    def test_the_chain_used_is_recorded_on_the_result(self, routed) -> None:  # type: ignore[no-untyped-def]
        _, outcome = routed
        chains = {
            result.row_id: result.field_results[0].provider_chain[0]
            for result in outcome.row_results
        }
        assert chains == {
            "r1": "email_only",
            "r2": "phone_only",
            "r3": "safe_fallback",
            "r4": "safe_fallback",
        }

    def test_language_distribution_and_fallbacks_reach_run_metrics(self, routed) -> None:  # type: ignore[no-untyped-def]
        _, outcome = routed
        counts = outcome.detail["language_counts"]
        assert counts["en"] == 1
        assert counts["de"] == 1
        assert counts["fr"] == 1
        assert counts["und"] == 1
        # fr (unsupported) and the blank one (unknown) both count as fallbacks.
        assert counts["_fallback"] == 2

    def test_providers_are_shared_between_chains(self, tmp_path: Path) -> None:
        # email_provider appears in two chains; building it twice would mean loading
        # any models it needs twice, which is the cost this must not pay.
        configs = write_configs(
            tmp_path, project_yaml=ROUTING_PROJECT, dataset_yaml=ROUTING_DATASET
        )
        pipeline = build_pipeline(load_resolved_dataset(configs, "demo_smoke"))
        processor = pipeline._processors[0]
        default_provider = processor.default_chain.providers[0]
        fallback = processor.fallback_chain
        assert fallback is not None
        assert fallback.providers[0] is default_provider

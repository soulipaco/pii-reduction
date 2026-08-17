"""A synthetic 20-row dataset and the configuration that processes it.

Everything here is invented. Emails use RFC 2606 reserved domains (ADR-0003), phone
numbers come from published permanently-unassigned ranges (ADR-0014: NANP 555-01xx,
the Bundesnetzagentur Berlin drama block, and the Greek compromise), and the
identifiers
(``INC…``, ``KB…``, ``DEMO-PC-…``) follow the negative-example list of
``docs/10_TESTING_QA.md`` §6 so over-redaction is measurable from the first run.

The corpus mixes en/de/el, plain and transcript shapes, nulls, empty strings and rows
with no PII at all. The seeded generator of Increment A6 replaces this; it exists now
so the pipeline has something honest to run on.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

__all__ = [
    "DATASET_YAML",
    "KNOWN_EMAILS",
    "KNOWN_PHONES",
    "PROJECT_YAML",
    "ROWS",
    "build_frame",
    "write_dataset_csv",
]

# (row_id, language, kind, body)
ROWS: list[tuple[str, str, str, str | None]] = [
    ("row_0001", "en", "plain", "Contact maria.rossi@example.com about ticket INC00128492."),
    ("row_0002", "en", "plain", "Please call +30 210 000 0000 after 09:15 tomorrow."),
    ("row_0003", "en", "plain", "Machine DEMO-PC-6915 rebooted; see KB000002715."),
    ("row_0004", "de", "plain", "Bitte schreiben Sie an jan.becker@example.org."),
    ("row_0005", "de", "plain", "Rufen Sie +49 30 23125 020 an, Vorgang INC00128499."),
    ("row_0006", "el", "plain", "Το email μου είναι eleni.pappa@example.net."),
    ("row_0007", "el", "plain", "Τηλέφωνο +30 210 000 0001 για το αίτημα."),
    ("row_0008", "en", "plain", "Upgraded to v4.12.3 last night. No action needed."),
    ("row_0009", "en", "plain", ""),
    ("row_0010", "en", "plain", None),
    (
        "row_0011",
        "en",
        "transcript",
        "2026-04-03 09:15:04 - Agent: Hello, how can I help?\n"
        "2026-04-03 09:15:13 - Guest: My email is guest.one@example.com.\n",
    ),
    (
        "row_0012",
        "de",
        "transcript",
        "2026-04-03 10:02:11 - Berater: Guten Tag.\n"
        "2026-04-03 10:02:30 - Kunde: Meine Nummer ist +49 30 23125 021.\n",
    ),
    (
        "row_0013",
        "el",
        "transcript",
        "2026-04-03 11:20:00 - Πράκτορας: Καλημέρα.\n"
        "2026-04-03 11:20:24 - Πελάτης: Το email είναι pelatis@example.org.\n",
    ),
    ("row_0014", "en", "transcript", "Agent: The ratio is 3:1, nothing sensitive here.\n"),
    ("row_0015", "en", "transcript", "Guest:\nAgent: Empty turn above.\n"),
    ("row_0016", "en", "plain", "Two contacts: a.one@example.com and b.two@example.net."),
    ("row_0017", "fr", "plain", "Bonjour, mon email est claude.dupont@example.com."),
    ("row_0018", "en", "plain", "Department: Support. Order 12345 shipped."),
    ("row_0019", "en", "transcript", "2026-04-03 12:00:00 - Agent: Call +1 (202) 555-0143.\r\n"),
    ("row_0020", "en", "plain", "No delimiter and no personal data in this note at all."),
]

#: Values the privacy tests assert never reach logs or exception messages.
KNOWN_EMAILS = (
    "maria.rossi@example.com",
    "jan.becker@example.org",
    "eleni.pappa@example.net",
    "guest.one@example.com",
    "pelatis@example.org",
    "a.one@example.com",
    "b.two@example.net",
    "claude.dupont@example.com",
)
KNOWN_PHONES = (
    "+30 210 000 0000",
    "+49 30 23125 020",
    "+30 210 000 0001",
    "+49 30 23125 021",
    "+1 (202) 555-0143",
)

PROJECT_YAML = """
project:
  name: test-project
  environment: local
  seed: 42

processing:
  default_parser: plain_text
  default_reducer: redact
  default_provider_chain: deterministic_only
  output_suffix: _pii_redacted
  failure_mode: preserve_original_and_record_error

language:
  mode: column
  detector: none
  language_column: language
  supported: [en, de, el]

observability:
  write_detection_audit: true

providers:
  deterministic:
    type: deterministic
    entities: [EMAIL, PHONE]

chains:
  deterministic_only:
    providers: [deterministic]
"""

DATASET_YAML = """
dataset:
  name: demo_smoke
  row_id: row_id

source:
  type: csv
  path: {source_path}

destination:
  type: csv
  path: {destination_path}

columns:
  body:
    parser: plain_text
    entities: [EMAIL, PHONE]
"""


def build_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"row_id": row_id, "language": language, "kind": kind, "body": body}
            for row_id, language, kind, body in ROWS
        ]
    )


def write_dataset_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_frame().to_csv(path, index=False, encoding="utf-8")
    return path

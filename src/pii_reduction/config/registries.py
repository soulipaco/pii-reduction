"""Names configuration is allowed to reference.

A name appears here only in the increment that implements it, so an unimplemented
parser or reducer fails config validation instead of failing halfway through a run.
Later increments extend these sets together with the implementation and a test that
every registered name resolves.

Keeping the sets here (rather than importing the implementing packages) preserves the
dependency direction: ``config`` stays free of ``parsers``/``providers``/``sources``.
"""

from __future__ import annotations

__all__ = [
    "DATABRICKS_DESTINATION_TYPES",
    "DATABRICKS_SOURCE_TYPES",
    "KNOWN_DESTINATION_TYPES",
    "KNOWN_LANGUAGE_DETECTORS",
    "KNOWN_OVERLAP_POLICIES",
    "KNOWN_PARSERS",
    "KNOWN_PARSER_OPTIONS",
    "KNOWN_PROVIDER_TYPES",
    "KNOWN_REDUCERS",
    "KNOWN_SOURCE_TYPES",
]

#: Increment A2; ``key_value`` added in session 5 (ADR-0016). ``note_history``
#: remains deferred (plan §5, §6).
KNOWN_PARSERS = frozenset({"plain_text", "transcript", "key_value"})

#: Every option name each parser accepts, so a typo in a dataset YAML's
#: ``parser_options`` is a configuration error rather than a ``ParserError`` raised
#: when the pipeline is built — which is after the source has been resolved and,
#: on the Databricks path, after a session exists (ADR-0034).
#:
#: Restated rather than imported, exactly like ``KNOWN_PARSERS`` above and for the
#: same reason: ``config`` stays free of ``parsers``. The duplication is pinned by
#: ``tests/test_parsers.py``, which asserts this table equals each parser's real
#: ``DEFAULT_OPTIONS`` keys — an equality in both directions, so a new option fails
#: the test rather than passing unnoticed.
#:
#: **This is validity, not policy.** Which of these a *service caller* may set is a
#: separate and much smaller question, answered by
#: ``service/templates.py``'s ``OFFERABLE_PARSER_OPTIONS``.
KNOWN_PARSER_OPTIONS: dict[str, frozenset[str]] = {
    "plain_text": frozenset({"split_lines"}),
    "transcript": frozenset(
        {
            "fallback",
            "line_mode",
            "max_speaker_length",
            "max_speaker_words",
            "preserve_prefix",
            "speaker_delimiters",
        }
    ),
    "key_value": frozenset({"key_delimiters", "max_key_length", "max_key_words", "preserve_key"}),
}

#: Increment A4. ``mask`` and ``pseudonymize`` were pulled forward from roadmap
#: Phase 8 by explicit decision (ADR-0013).
KNOWN_REDUCERS = frozenset({"redact", "mask", "pseudonymize"})

#: ``deterministic`` lands in A3, ``presidio`` in Increment B.
KNOWN_PROVIDER_TYPES = frozenset({"deterministic", "presidio"})

#: Types whose adapters need a live Spark session and therefore ship under
#: ``databricks/`` rather than ``sources/``/``outputs/`` (`docs/01_ARCHITECTURE.md`,
#: *Package dependency direction*). Configuration may **name** them — a name is a
#: string, so this module still imports nothing — but only an execution surface that
#: has a session can build them: `databricks.runner.run_driver`. The local
#: registries refuse them with that instruction rather than a bare "not registered".
#:
#: This is the resolution of the design point docs/06 left open (ADR-0025 P2):
#: config names the table, the runtime supplies the session.
DATABRICKS_SOURCE_TYPES = frozenset({"spark_table"})
DATABRICKS_DESTINATION_TYPES = frozenset({"delta_table"})

#: Increment A5, extended in session 10. Excel is still deferred with the
#: note-history parser.
KNOWN_SOURCE_TYPES = frozenset({"csv", "parquet"}) | DATABRICKS_SOURCE_TYPES
KNOWN_DESTINATION_TYPES = frozenset({"csv", "parquet"}) | DATABRICKS_DESTINATION_TYPES

#: The reconciler policy of ``docs/04_PII_ENGINE.md`` (Increment A4).
KNOWN_OVERLAP_POLICIES = frozenset({"priority_score_length"})

#: ``lingua`` arrives with Increment C; ``none`` means static or column-driven language.
KNOWN_LANGUAGE_DETECTORS = frozenset({"lingua", "none"})

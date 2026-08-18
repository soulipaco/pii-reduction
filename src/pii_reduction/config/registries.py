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
    "KNOWN_DESTINATION_TYPES",
    "KNOWN_LANGUAGE_DETECTORS",
    "KNOWN_OVERLAP_POLICIES",
    "KNOWN_PARSERS",
    "KNOWN_PROVIDER_TYPES",
    "KNOWN_REDUCERS",
    "KNOWN_SOURCE_TYPES",
]

#: Increment A2; ``key_value`` added in session 5 (ADR-0016). ``note_history``
#: remains deferred (plan §5, §6).
KNOWN_PARSERS = frozenset({"plain_text", "transcript", "key_value"})

#: Increment A4. ``mask`` and ``pseudonymize`` were pulled forward from roadmap
#: Phase 8 by explicit decision (ADR-0013).
KNOWN_REDUCERS = frozenset({"redact", "mask", "pseudonymize"})

#: ``deterministic`` lands in A3, ``presidio`` in Increment B.
KNOWN_PROVIDER_TYPES = frozenset({"deterministic", "presidio"})

#: Increment A5. ``excel`` arrives with Increment D, Spark/Delta with Increment F.
KNOWN_SOURCE_TYPES = frozenset({"csv", "parquet"})
KNOWN_DESTINATION_TYPES = frozenset({"csv", "parquet"})

#: The reconciler policy of ``docs/04_PII_ENGINE.md`` (Increment A4).
KNOWN_OVERLAP_POLICIES = frozenset({"priority_score_length"})

#: ``lingua`` arrives with Increment C; ``none`` means static or column-driven language.
KNOWN_LANGUAGE_DETECTORS = frozenset({"lingua", "none"})

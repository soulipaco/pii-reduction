"""Transcript parser.

Handles the two shapes ``docs/01_ARCHITECTURE.md`` describes::

    2026-04-03 09:15:04 - Agent Smith: Hello Maria, how can I help?
    Guest: My email is maria@example.com

The prefix (timestamp, separator, speaker, delimiter) is preserved as a
non-processable segment; only the body is eligible for PII processing.

The hard part is *not* splitting on every colon (``docs/10_TESTING_QA.md`` §2). A
body may contain times (``call me at 09:15``), URLs (``https://example.com``) and
ratios (``3:1``), and a timestamp prefix contains colons of its own. So a colon only
starts a body when the text before it also *looks* like a speaker: short, containing
a letter, not ending in a digit, and not a URL scheme. Everything else falls back to
"the whole line is body", with the reason recorded — never dropped, never guessed at
silently.
"""

from __future__ import annotations

import re
from typing import Any

from pii_reduction.parsers.errors import ParserError
from pii_reduction.parsers.lines import LabelledLineParser

__all__ = ["TranscriptParser"]

SEGMENT_TYPE_PREFIX = "transcript_prefix"
SEGMENT_TYPE_BODY = "transcript_body"

#: Fallback reasons recorded on the parse result (counted in run metrics).
FALLBACK_NO_SPEAKER_PREFIX = "no_speaker_prefix"

_TIMESTAMP = (
    r"\d{4}[-/]\d{2}[-/]\d{2}"  # 2026-04-03 or 2026/04/03
    r"[ T]\d{1,2}:\d{2}(?::\d{2})?"  # 09:15 or 09:15:04
    r"(?:\s*[APap]\.?[Mm]\.?)?"  # optional AM/PM
)

DEFAULT_OPTIONS: dict[str, Any] = {
    "speaker_delimiters": [":"],
    "preserve_prefix": True,
    "fallback": "preserve_line",
    "line_mode": "auto",
    "max_speaker_length": 40,
    "max_speaker_words": 5,
}

KNOWN_FALLBACK_POLICIES = frozenset({"preserve_line"})
KNOWN_LINE_MODES = frozenset({"auto"})


class TranscriptParser(LabelledLineParser):
    """Line-oriented transcript segmenter with byte-exact reconstruction."""

    name = "transcript"
    segment_type_prefix = SEGMENT_TYPE_PREFIX
    segment_type_body = SEGMENT_TYPE_BODY
    fallback_no_prefix = FALLBACK_NO_SPEAKER_PREFIX

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ParserError(
                f"parser {self.name!r}: unknown parser_options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        delimiters = merged["speaker_delimiters"]
        if not delimiters or not all(isinstance(d, str) and len(d) == 1 for d in delimiters):
            raise ParserError(
                f"parser {self.name!r}: speaker_delimiters must be a non-empty list of "
                "single characters, e.g. [':']"
            )
        if merged["fallback"] not in KNOWN_FALLBACK_POLICIES:
            raise ParserError(
                f"parser {self.name!r}: fallback {merged['fallback']!r} is not supported "
                f"(known: {', '.join(sorted(KNOWN_FALLBACK_POLICIES))})"
            )
        if merged["line_mode"] not in KNOWN_LINE_MODES:
            raise ParserError(
                f"parser {self.name!r}: line_mode {merged['line_mode']!r} is not supported "
                f"(known: {', '.join(sorted(KNOWN_LINE_MODES))})"
            )

        super().__init__(
            max_label_length=int(merged["max_speaker_length"]),
            max_label_words=int(merged["max_speaker_words"]),
        )
        self.options = merged
        self._preserve_prefix = bool(merged["preserve_prefix"])

        delimiter_class = re.escape("".join(delimiters))
        self._timestamped_re = re.compile(
            rf"^(?P<lead>\s*{_TIMESTAMP}\s*[-–]\s*)"
            rf"(?P<speaker>[^{delimiter_class}\n]{{1,80}})"
            rf"(?P<delim>[{delimiter_class}])(?P<body>.*)$",
            re.DOTALL,
        )
        self._speaker_re = re.compile(
            rf"^(?P<lead>\s*)(?P<speaker>[^{delimiter_class}\n]{{1,80}})"
            rf"(?P<delim>[{delimiter_class}])(?P<body>.*)$",
            re.DOTALL,
        )

    # -- line splitting ----------------------------------------------------------

    def _split_line(self, line: str) -> tuple[str | None, str]:
        """Return ``(prefix, body)``; ``prefix`` is ``None`` when the line is all body."""
        for pattern in (self._timestamped_re, self._speaker_re):
            match = pattern.match(line)
            if match is None:
                continue
            if not self._is_label(match.group("speaker"), body=match.group("body")):
                continue
            prefix = match.group("lead") + match.group("speaker") + match.group("delim")
            if not self._preserve_prefix:
                return None, line
            return prefix, match.group("body")
        return None, line

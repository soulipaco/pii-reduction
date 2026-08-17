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
from collections.abc import Iterator
from typing import Any

from pii_reduction.contracts.segments import TextSegment
from pii_reduction.parsers.base import BaseParser, ParseResult
from pii_reduction.parsers.errors import ParserError

__all__ = ["TranscriptParser"]

SEGMENT_TYPE_PREFIX = "transcript_prefix"
SEGMENT_TYPE_BODY = "transcript_body"
SEGMENT_TYPE_BREAK = "line_break"

#: Fallback reasons recorded on the parse result (counted in run metrics).
FALLBACK_NO_SPEAKER_PREFIX = "no_speaker_prefix"

#: A colon directly after one of these is a URI scheme, not a speaker delimiter.
URI_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "mailto", "tel", "file", "data", "sip"})

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")

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


class TranscriptParser(BaseParser):
    """Line-oriented transcript segmenter with byte-exact reconstruction."""

    name = "transcript"

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

        self.options = merged
        self._max_speaker_length = int(merged["max_speaker_length"])
        self._max_speaker_words = int(merged["max_speaker_words"])
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

    # -- parsing -----------------------------------------------------------------

    def parse(self, text: str) -> ParseResult:
        self._require_text(text)

        segments: list[TextSegment] = []
        fallbacks: list[str] = []
        ordinal = 0

        for line_no, (line, break_text, start) in enumerate(_iter_lines(text)):
            if line:
                prefix, body = self._split_line(line)
                if prefix is None:
                    fallbacks.append(FALLBACK_NO_SPEAKER_PREFIX)
                else:
                    segments.append(
                        TextSegment(
                            segment_id=f"line_{line_no:04d}_prefix",
                            ordinal=ordinal,
                            text=prefix,
                            processable=False,
                            segment_type=SEGMENT_TYPE_PREFIX,
                            source_start=start,
                            source_end=start + len(prefix),
                            metadata={"line_no": line_no},
                        )
                    )
                    ordinal += 1
                body_start = start + (len(prefix) if prefix else 0)
                segments.append(
                    TextSegment(
                        segment_id=f"line_{line_no:04d}_body",
                        ordinal=ordinal,
                        text=body,
                        processable=True,
                        segment_type=SEGMENT_TYPE_BODY,
                        source_start=body_start,
                        source_end=body_start + len(body),
                        metadata={"line_no": line_no, "has_prefix": prefix is not None},
                    )
                )
                ordinal += 1

            if break_text:
                segments.append(
                    TextSegment(
                        segment_id=f"line_{line_no:04d}_break",
                        ordinal=ordinal,
                        text=break_text,
                        processable=False,
                        segment_type=SEGMENT_TYPE_BREAK,
                        source_start=start + len(line),
                        source_end=start + len(line) + len(break_text),
                        metadata={"line_no": line_no},
                    )
                )
                ordinal += 1

        if not segments:
            # Empty field: still emit one (empty) body so downstream code has a
            # segment to process and the round-trip holds.
            segments.append(
                TextSegment(
                    segment_id="line_0000_body",
                    ordinal=0,
                    text="",
                    processable=True,
                    segment_type=SEGMENT_TYPE_BODY,
                    source_start=0,
                    source_end=0,
                    metadata={"line_no": 0, "has_prefix": False},
                )
            )

        return ParseResult(
            parser=self.name,
            segments=tuple(segments),
            fallbacks=tuple(fallbacks),
        )

    # -- line splitting ----------------------------------------------------------

    def _split_line(self, line: str) -> tuple[str | None, str]:
        """Return ``(prefix, body)``; ``prefix`` is ``None`` when the line is all body."""
        for pattern in (self._timestamped_re, self._speaker_re):
            match = pattern.match(line)
            if match is None:
                continue
            if not self._is_speaker(match.group("speaker"), body=match.group("body")):
                continue
            prefix = match.group("lead") + match.group("speaker") + match.group("delim")
            if not self._preserve_prefix:
                return None, line
            return prefix, match.group("body")
        return None, line

    def _is_speaker(self, candidate: str, *, body: str) -> bool:
        """Decide whether the text before a delimiter is a speaker or ordinary prose."""
        speaker = candidate.strip()
        if not speaker:
            return False
        if len(speaker) > self._max_speaker_length:
            return False
        if len(speaker.split()) > self._max_speaker_words:
            return False
        if not any(character.isalpha() for character in speaker):
            return False
        # "call me at 09:15" - a digit right before the delimiter means a time or ratio.
        if speaker[-1].isdigit():
            return False
        # "https://example.com" and "mailto:someone@example.com".
        return not (body.startswith("//") or speaker.split()[-1].lower() in URI_SCHEMES)


def _iter_lines(text: str) -> Iterator[tuple[str, str, int]]:
    """Yield ``(line, line_break, start_offset)`` preserving the exact break characters.

    ``str.splitlines`` also breaks on characters such as U+2028, which would change
    what counts as a line; this splits on CR, LF and CRLF only.
    """
    position = 0
    for match in _LINE_BREAK_RE.finditer(text):
        yield text[position : match.start()], match.group(0), position
        position = match.end()
    if position < len(text):
        yield text[position:], "", position

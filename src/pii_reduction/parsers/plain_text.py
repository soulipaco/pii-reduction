"""Plain-text parser: the whole field is one processable segment — or one per line.

``split_lines`` exists because of a measured failure, not a hypothetical one. Handed a
key/value block as a single segment::

    Customer: Grace Okafor
    Mobile number: +1 202 555 0140

spaCy's NER returns the PERSON span ``Grace Okafor\\nMobile`` — it runs the entity
boundary straight through the line break and swallows the next line's first word. The
name is *found*; the span is wrong, so strict matching scores it as both a miss and a
false positive. On the committed corpus this alone accounted for English tier-3 PERSON
strict recall of 0.333 whole-corpus, and 0.000 on the dev+calibration splits where the
remedy was developed (session 5, ``deterministic_presidio``). The transcript parser
never had the problem because it is line-oriented already, which is why tier-4
transcripts scored 1.000 with the same model and the same names.

It is **off by default**. Splitting lines is wrong for prose that wraps mid-sentence:
a name broken across a line break would then be unfindable, and free text is what this
parser is named for. Turn it on per column, for columns that are known to hold
line-structured text::

    columns:
      incident_details:
        parser: plain_text
        parser_options:
          split_lines: true
"""

from __future__ import annotations

from typing import Any

from pii_reduction.contracts.segments import TextSegment
from pii_reduction.parsers.base import BaseParser, ParseResult
from pii_reduction.parsers.errors import ParserError
from pii_reduction.parsers.lines import LINE_BREAK_RE, SEGMENT_TYPE_BREAK

__all__ = ["PlainTextParser"]

SEGMENT_ID = "field_0000"
SEGMENT_TYPE = "plain_text"

DEFAULT_OPTIONS: dict[str, Any] = {
    "split_lines": False,
}


class PlainTextParser(BaseParser):
    """One field in, one segment out — or one segment per line when asked."""

    name = "plain_text"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ParserError(
                f"parser {self.name!r}: unknown parser_options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        split_lines = merged["split_lines"]
        if not isinstance(split_lines, bool):
            raise ParserError(
                f"parser {self.name!r}: 'split_lines' must be true or false, "
                f"got {type(split_lines).__name__}"
            )
        self._split_lines = split_lines

    def parse(self, text: str) -> ParseResult:
        self._require_text(text)
        segments = self._split(text) if self._split_lines else self._whole(text)
        return ParseResult(parser=self.name, segments=segments)

    def _whole(self, text: str) -> tuple[TextSegment, ...]:
        return (
            TextSegment(
                segment_id=SEGMENT_ID,
                ordinal=0,
                text=text,
                processable=True,
                segment_type=SEGMENT_TYPE,
                source_start=0,
                source_end=len(text),
            ),
        )

    def _split(self, text: str) -> tuple[TextSegment, ...]:
        """One processable segment per line, with each break its own segment.

        Empty lines still become segments. They carry no text to detect in, but
        dropping them would break the tiling the round-trip invariant depends on.
        """
        segments: list[TextSegment] = []
        cursor = 0

        def add(body: str, *, segment_id: str, processable: bool, segment_type: str) -> None:
            nonlocal cursor
            segments.append(
                TextSegment(
                    segment_id=segment_id,
                    ordinal=len(segments),
                    text=body,
                    processable=processable,
                    segment_type=segment_type,
                    source_start=cursor,
                    source_end=cursor + len(body),
                )
            )
            cursor += len(body)

        # Ids are keyed on the line index, not the segment ordinal, and a break is
        # named as a break. `segment_id` is persisted into the audit table, so
        # numbering the break between lines 0 and 1 as `line_0001` would make the
        # audit disagree with the transcript parser about what the number means.
        for index, piece in enumerate(LINE_BREAK_RE.split(text)):
            if index:
                match = LINE_BREAK_RE.match(text, cursor)
                if match is None:  # pragma: no cover - split guarantees a break here
                    raise ParserError(f"parser {self.name!r}: line break expected at {cursor}")
                add(
                    match.group(),
                    segment_id=f"break_{index - 1:04d}",
                    processable=False,
                    segment_type=SEGMENT_TYPE_BREAK,
                )
            add(
                piece,
                segment_id=f"line_{index:04d}",
                processable=True,
                segment_type=SEGMENT_TYPE,
            )

        return tuple(segments)

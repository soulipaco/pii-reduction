"""Plain-text parser: the whole field is one processable segment."""

from __future__ import annotations

from typing import Any

from pii_reduction.contracts.segments import TextSegment
from pii_reduction.parsers.base import BaseParser, ParseResult
from pii_reduction.parsers.errors import ParserError

__all__ = ["PlainTextParser"]

SEGMENT_ID = "field_0000"
SEGMENT_TYPE = "plain_text"


class PlainTextParser(BaseParser):
    """One field in, one segment out. The trivial case still owes the round-trip."""

    name = "plain_text"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        if options:
            raise ParserError(
                f"parser {self.name!r}: unknown parser_options "
                f"{', '.join(sorted(options))} (this parser takes none)"
            )

    def parse(self, text: str) -> ParseResult:
        self._require_text(text)
        segment = TextSegment(
            segment_id=SEGMENT_ID,
            ordinal=0,
            text=text,
            processable=True,
            segment_type=SEGMENT_TYPE,
            source_start=0,
            source_end=len(text),
        )
        return ParseResult(parser=self.name, segments=(segment,))

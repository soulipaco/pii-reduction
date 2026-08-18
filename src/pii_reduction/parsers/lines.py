"""Line-oriented parsing: what a line is, and how a labelled line splits.

Two parsers segment ``Label: value`` lines — the transcript parser (where the label is
a speaker) and the key/value parser (where it is a field name). They differ in one
thing only: a transcript line may carry a leading timestamp. Everything else — what
counts as a line break, what distinguishes a label from ordinary prose containing a
colon, and how the pieces become segments that tile the source — is identical, and
lives here so the two cannot drift apart.

The hard part is *not* splitting on every colon (``docs/10_TESTING_QA.md`` §2). A body
may contain times (``call me at 09:15``), URLs (``https://example.com``) and ratios
(``3:1``). So a colon only starts a body when the text before it also *looks* like a
label: short, containing a letter, not ending in a digit, and not a URI scheme.
Everything else falls back to "the whole line is body", with the reason recorded —
never dropped, never silently guessed at.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from collections.abc import Iterator

from pii_reduction.contracts.segments import TextSegment
from pii_reduction.parsers.base import BaseParser, ParseResult

__all__ = [
    "LINE_BREAK_RE",
    "SEGMENT_TYPE_BREAK",
    "URI_SCHEMES",
    "LabelledLineParser",
    "iter_lines",
]

#: CR, LF and CRLF only. Deliberately not ``str.splitlines``, which also breaks on
#: U+2028, U+0085 and friends — that would silently change what counts as a line for
#: the multilingual text this project is full of.
LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")

#: The break is its own non-processable segment, which is what keeps CRLF byte-exact
#: through reconstruction without special-casing it anywhere downstream.
SEGMENT_TYPE_BREAK = "line_break"

#: A colon directly after one of these is a URI scheme, not a label delimiter.
URI_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "mailto", "tel", "file", "data", "sip"})


def iter_lines(text: str) -> Iterator[tuple[str, str, int]]:
    """Yield ``(line, line_break, start_offset)``, preserving the exact break characters."""
    position = 0
    for match in LINE_BREAK_RE.finditer(text):
        yield text[position : match.start()], match.group(0), position
        position = match.end()
    if position < len(text):
        yield text[position:], "", position


class LabelledLineParser(BaseParser):
    """A line-oriented parser whose lines may carry a non-processable label prefix.

    Subclasses supply the segment-type names, the fallback reason, and ``_split_line``.
    Emission, offsets and the empty-field case are implemented once here so a new
    line-oriented parser cannot get the tiling — and therefore the round-trip — subtly
    wrong.

    The prefix is **not** processable, which means a value appearing in the label
    position is never detected. That is correct for field names and speaker roles, and
    it is a real limitation when a person's name *is* the label (``Maria Rossi: called
    back``). Parsers built on this class should say so in their own docstring rather
    than leave it implicit.
    """

    #: Segment type for the label prefix, e.g. ``transcript_prefix``.
    segment_type_prefix: str = ""
    #: Segment type for the processable remainder of the line.
    segment_type_body: str = ""
    #: Reason code recorded when a line has no recognisable label.
    fallback_no_prefix: str = ""

    def __init__(self, *, max_label_length: int, max_label_words: int) -> None:
        self._max_label_length = max_label_length
        self._max_label_words = max_label_words

    @abstractmethod
    def _split_line(self, line: str) -> tuple[str | None, str]:
        """Return ``(prefix, body)``; ``prefix`` is ``None`` when the line is all body."""

    def parse(self, text: str) -> ParseResult:
        self._require_text(text)

        segments: list[TextSegment] = []
        fallbacks: list[str] = []
        ordinal = 0

        for line_no, (line, break_text, start) in enumerate(iter_lines(text)):
            if line:
                prefix, body = self._split_line(line)
                if prefix is None:
                    fallbacks.append(self.fallback_no_prefix)
                else:
                    segments.append(
                        TextSegment(
                            segment_id=f"line_{line_no:04d}_prefix",
                            ordinal=ordinal,
                            text=prefix,
                            processable=False,
                            segment_type=self.segment_type_prefix,
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
                        segment_type=self.segment_type_body,
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
                    segment_type=self.segment_type_body,
                    source_start=0,
                    source_end=0,
                    metadata={"line_no": 0, "has_prefix": False},
                )
            )

        return ParseResult(parser=self.name, segments=tuple(segments), fallbacks=tuple(fallbacks))

    def _is_label(self, candidate: str, *, body: str) -> bool:
        """Decide whether the text before a delimiter is a label or ordinary prose."""
        label = candidate.strip()
        if not label:
            return False
        if len(label) > self._max_label_length:
            return False
        if len(label.split()) > self._max_label_words:
            return False
        if not any(character.isalpha() for character in label):
            return False
        # "call me at 09:15" — a digit right before the delimiter means a time or ratio.
        if label[-1].isdigit():
            return False
        # "https://example.com" and "mailto:someone@example.com".
        return not (body.startswith("//") or label.split()[-1].lower() in URI_SCHEMES)

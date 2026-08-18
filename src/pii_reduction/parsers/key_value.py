"""Key/value parser: ``Field name: value`` lines, one record per line.

The shape this exists for::

    Customer: Grace Okafor
    Mobile number: +1 202 555 0140
    Machine name: DEMO-PC-6928

Two measured failures motivate it, both from session 5 (ADR-0016):

1. Handed the block as **one** segment, spaCy runs the PERSON boundary through the
   line break and returns ``Grace Okafor\\nMobile``. The name is found; the span is
   wrong, so strict matching scores a miss *and* a false positive — and reduction
   destroys the next line's label.
2. Splitting into lines but leaving the label processable fixes the span and
   introduces a new false positive: on its own line the German ``Rechnername:``
   ("computer name") is tagged PERSON, where whole-block context had suppressed it.

Marking the label non-processable resolves both. Probed directly:
``'Rechnername: DEMO-PC-6949'`` yields the false positive, ``'DEMO-PC-6949'`` alone
yields nothing, and ``'Grace Okafor'`` alone is still an exact PERSON span — the value
does not need its label for context.

**The label is never processed, so PII in the label position is never detected.** For
field names that is exactly right. It is wrong for a note whose lines read
``Maria Rossi: called back`` — that is transcript-shaped text, and `TranscriptParser`
is the parser for it. Choose per column, deliberately; this parser is not a safe
default for unknown text.

A line with no recognisable label is kept whole and processable, with the reason
recorded as a fallback — never dropped, never silently guessed at.
"""

from __future__ import annotations

import re
from typing import Any

from pii_reduction.parsers.errors import ParserError
from pii_reduction.parsers.lines import LabelledLineParser

__all__ = ["KeyValueParser"]

SEGMENT_TYPE_KEY = "key_value_key"
SEGMENT_TYPE_VALUE = "key_value_value"

#: Recorded when a line carries no label. Reason codes only — never text.
FALLBACK_NO_KEY = "no_key_prefix"

DEFAULT_OPTIONS: dict[str, Any] = {
    "key_delimiters": [":"],
    "preserve_key": True,
    "max_key_length": 40,
    "max_key_words": 5,
}


class KeyValueParser(LabelledLineParser):
    """Line-oriented key/value segmenter with byte-exact reconstruction."""

    name = "key_value"
    segment_type_prefix = SEGMENT_TYPE_KEY
    segment_type_body = SEGMENT_TYPE_VALUE
    fallback_no_prefix = FALLBACK_NO_KEY

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ParserError(
                f"parser {self.name!r}: unknown parser_options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        delimiters = merged["key_delimiters"]
        if not delimiters or not all(isinstance(d, str) and len(d) == 1 for d in delimiters):
            raise ParserError(
                f"parser {self.name!r}: key_delimiters must be a non-empty list of "
                "single characters, e.g. [':']"
            )
        for name in ("max_key_length", "max_key_words"):
            value = merged[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ParserError(f"parser {self.name!r}: {name} must be a positive integer")

        super().__init__(
            max_label_length=int(merged["max_key_length"]),
            max_label_words=int(merged["max_key_words"]),
        )
        self.options = merged
        self._preserve_key = bool(merged["preserve_key"])

        delimiter_class = re.escape("".join(delimiters))
        self._key_re = re.compile(
            rf"^(?P<lead>\s*)(?P<key>[^{delimiter_class}\n]{{1,80}})"
            rf"(?P<delim>[{delimiter_class}])(?P<body>.*)$",
            re.DOTALL,
        )

    def _split_line(self, line: str) -> tuple[str | None, str]:
        """Return ``(key, value)``; ``key`` is ``None`` when the line has no label.

        Unlike the transcript parser there is no timestamp form to try first: a
        key/value line has no leading metadata, and treating one as a timestamp would
        only misread values that happen to start with a date.
        """
        match = self._key_re.match(line)
        if match is None:
            return None, line
        if not self._is_label(match.group("key"), body=match.group("body")):
            return None, line
        if not self._preserve_key:
            return None, line
        return match.group("lead") + match.group("key") + match.group("delim"), match.group("body")

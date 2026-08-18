"""Parser construction by configured name.

``config.registries.KNOWN_PARSERS`` is what configuration validates against; this is
what actually builds one. A test asserts the two agree, so a name can never be
configurable without being constructible.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pii_reduction.parsers.base import BaseParser
from pii_reduction.parsers.errors import ParserError
from pii_reduction.parsers.key_value import KeyValueParser
from pii_reduction.parsers.plain_text import PlainTextParser
from pii_reduction.parsers.transcript import TranscriptParser

__all__ = ["available_parsers", "build_parser"]

_PARSERS: dict[str, Callable[[dict[str, Any] | None], BaseParser]] = {
    KeyValueParser.name: KeyValueParser,
    PlainTextParser.name: PlainTextParser,
    TranscriptParser.name: TranscriptParser,
}


def available_parsers() -> frozenset[str]:
    return frozenset(_PARSERS)


def build_parser(name: str, options: dict[str, Any] | None = None) -> BaseParser:
    """Construct a parser by registry name."""
    factory = _PARSERS.get(name)
    if factory is None:
        raise ParserError(
            f"parser {name!r} is not registered (known: {', '.join(sorted(_PARSERS))})"
        )
    return factory(options)

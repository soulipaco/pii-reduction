"""Parsers: source field in, ordered segments out, byte-exact reconstruction back."""

from pii_reduction.parsers.base import BaseParser, Parser, ParseResult
from pii_reduction.parsers.errors import ParserError
from pii_reduction.parsers.plain_text import PlainTextParser
from pii_reduction.parsers.registry import available_parsers, build_parser
from pii_reduction.parsers.transcript import TranscriptParser

__all__ = [
    "BaseParser",
    "ParseResult",
    "Parser",
    "ParserError",
    "PlainTextParser",
    "TranscriptParser",
    "available_parsers",
    "build_parser",
]

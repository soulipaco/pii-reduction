"""Structural text patterns shared across layers.

The deterministic EMAIL recognizer and the short-text language gate must agree on
what an email looks like: the gate strips emails, URLs and digits before counting
alphabetic characters (ADR-0012), and it would be a quiet bug if the two disagreed
about where an address starts and ends. So the patterns live here, imported by both,
and this module imports nothing from the project.

``EMAIL`` deliberately accepts any dot-TLD of two or more ASCII letters, including
RFC-reserved ones such as ``.test`` and ``.invalid``. That is broader than Presidio's
default recognizer, which rejects them (ADR-0003) — the difference is measured by the
benchmark rather than hidden by making the fixtures fit the tool.
"""

from __future__ import annotations

import re

__all__ = ["DIGIT_RUN_PATTERN", "EMAIL_PATTERN", "URL_PATTERN"]

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"

#: Local part, ``@``, dot-separated labels, dot-TLD of >=2 ASCII letters. The
#: look-around stops a match from starting or ending inside a longer token.
EMAIL_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@{_LABEL}(?:\.{_LABEL})*\.[A-Za-z]{{2,}}"
    r"(?![A-Za-z0-9-])"
)

URL_PATTERN = re.compile(r"\b(?:https?|ftp)://[^\s<>\"]+|\bwww\.[^\s<>\"]+", re.IGNORECASE)

DIGIT_RUN_PATTERN = re.compile(r"\d+")

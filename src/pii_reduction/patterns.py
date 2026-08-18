"""Structural text patterns and predicates shared across layers.

The deterministic EMAIL recognizer and the short-text language gate must agree on
what an email looks like: the gate strips emails, URLs and digits before counting
alphabetic characters (ADR-0012), and it would be a quiet bug if the two disagreed
about where an address starts and ends. So the patterns live here, imported by both,
and this module imports nothing from the project.

The module also holds structural *predicates* — currently
:func:`is_identifier_shaped`, which the reconciler uses to tell a machine identifier
from a name. It lives here rather than beside its one consumer because it is a
judgement about text shape with no dependency on the taxonomy, the providers or the
pipeline, and because the same question ("is this surface a code?") is one a provider
guard or a future recognizer would ask independently. Like everything here, it imports
nothing from the project.

``EMAIL`` deliberately accepts any dot-TLD of two or more ASCII letters, including
RFC-reserved ones such as ``.test`` and ``.invalid``. That is broader than Presidio's
default recognizer, which rejects them (ADR-0003) — the difference is measured by the
benchmark rather than hidden by making the fixtures fit the tool.
"""

from __future__ import annotations

import re

__all__ = [
    "DIGIT_RUN_PATTERN",
    "EMAIL_PATTERN",
    "URL_PATTERN",
    "is_identifier_shaped",
]

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"

#: Local part, ``@``, dot-separated labels, dot-TLD of >=2 ASCII letters. The
#: look-around stops a match from starting or ending inside a longer token.
EMAIL_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@{_LABEL}(?:\.{_LABEL})*\.[A-Za-z]{{2,}}"
    r"(?![A-Za-z0-9-])"
)

URL_PATTERN = re.compile(r"\b(?:https?|ftp)://[^\s<>\"]+|\bwww\.[^\s<>\"]+", re.IGNORECASE)

DIGIT_RUN_PATTERN = re.compile(r"\d+")


def is_identifier_shaped(surface: str) -> bool:
    """True when nothing in ``surface`` could be a name — every token reads as a code.

    Machine-generated identifiers and human names differ structurally:
    ``INC00100000``, ``KB000002739``, ``DEMO-PC-6963``, ``v4.12.3`` and ``12345`` read
    as codes, while ``Grace Okafor``, ``Jürgen Müller``, ``Μαρία Παπαδοπούλου`` and
    ``Иванов2024`` do not.

    **The rule assumes a cased script.** Its second clause below rests on the
    convention that identifiers are upper case, which does not exist in Arabic,
    Hebrew, CJK or Thai — a name in those scripts with digits attached is classified
    as an identifier. That is within the shipped language set (en/de/el, all cased,
    ``configs/providers.yaml``) but ``docs/05_MULTILINGUAL_STRATEGY.md`` warns against
    claiming multilingual robustness from Latin-script evidence, so this limit is
    stated rather than assumed away.

    Deliberately **not** a list of known identifier formats. A pattern list tuned to
    the shapes in the committed corpus would fit the fixture rather than the problem
    and would silently stop working on the public datasets of Increment D
    (``AGENTS.md`` benchmark integrity). This rule is about what a name *is*.

    A token counts as name-like when it holds at least two letters and either carries
    no digit at all, or carries a run of three or more lowercase letters. The second
    clause exists because counting letters and digits does not separate the two cases
    that matter: ``DEMO-PC-6963`` has six letters and four digits, ``Mueller2024`` has
    seven and four. Case does separate them — machine identifiers are conventionally
    upper case, and a lowercase run of three is a word rather than a code. Without that
    clause ``Mueller2024``, ``jmueller01`` and ``grace.okafor2`` were all classified as
    identifiers, and a rejected PERSON span means the name is **not** redacted.

    The verdict is "no token is name-like", not "some token looks like an identifier".
    That asymmetry keeps ``Maria Rossi 2026`` and ``MARIA MUELLER2024`` classified as
    names: rejecting them would leave the name unredacted, and leaking a name is worse
    than over-redacting a year.

    Known limitation, stated as the rule rather than one example of it: a **single**
    token whose lowercase run is shorter than three is classified as an identifier and
    would not be redacted. That covers ``MUELLER2024`` (no lowercase at all) and also
    ``Wei2``, ``Li3``, ``Bo2`` — short given names with a digit attached. Beside any
    other token the asymmetry still protects them (``MARIA MUELLER2024`` is a name).
    Separating a lone short token from a genuine asset code is not possible
    structurally without more context, and no shipped corpus exercises it. Increment
    D's public data is where to re-test this.
    """
    return not any(_is_name_like(token) for token in surface.split())


def _is_name_like(token: str) -> bool:
    """Could this whitespace-separated token be part of a person or place name?"""
    if sum(1 for character in token if character.isalpha()) < 2:
        return False
    if not any(character.isdigit() for character in token):
        return True
    run = 0
    for character in token:
        run = run + 1 if character.isalpha() and character.islower() else 0
        if run >= 3:
            return True
    return False

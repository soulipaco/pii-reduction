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

It also holds the one **closed vocabulary** in this package — the HTML/BBCode element
and attribute names of ADR-0027. ADR-0019 prefers structural rules to word lists and
this module's other contents obey that; this one is the exception, and it is not
corpus tuning: it enumerates the markup dialects :data:`MARKUP_PATTERN` claims to
recognise, so it is a definition of the pattern rather than a list of words a model
gets wrong. Nothing here is derived from any corpus.

``EMAIL`` deliberately accepts any dot-TLD of two or more ASCII letters, including
RFC-reserved ones such as ``.test`` and ``.invalid``. That is broader than Presidio's
default recognizer, which rejects them (ADR-0003) — the difference is measured by the
benchmark rather than hidden by making the fixtures fit the tool.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

__all__ = [
    "DIGIT_RUN_PATTERN",
    "EMAIL_PATTERN",
    "MARKUP_DELIMITER_PATTERN",
    "MARKUP_HINT_PATTERN",
    "MARKUP_PATTERN",
    "MARKUP_TOKEN_VOCABULARY",
    "URL_PATTERN",
    "is_identifier_shaped",
    "markup_free_fragments",
    "markup_regions",
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

#: Element names an HTML or BBCode tag may carry.
#:
#: **The name is required, and that is a privacy decision rather than a precision
#: one.** An earlier draft matched any bracketed word run — ``</?[A-Za-z][^<>\n]*>``
#: — which reads ``<Grace Okafor>`` as a tag. Chat exports write a display name in
#: exactly that shape, and a PERSON span lying wholly inside a "tag" was then
#: discarded by the ADR-0027 guard, so the name went out **unredacted**: a leak, the
#: invisible error, produced by the guard that exists to prevent the visible one. The
#: cost of requiring a name is that an unknown dialect's tag is no longer protected
#: from over-redaction, which is the trade this project makes everywhere else.
_HTML_TAG_NAMES = (
    "a|abbr|address|article|aside|audio|b|big|blockquote|body|br|button|canvas|caption"
    "|center|cite|code|col|colgroup|dd|del|details|div|dl|dt|em|embed|fieldset|figure"
    "|font|footer|form|h1|h2|h3|h4|h5|h6|head|header|hr|html|i|iframe|img|input|ins"
    "|label|legend|li|link|main|mark|meta|nav|object|ol|option|p|param|pre|q|s|script"
    "|section|select|small|source|span|strike|strong|style|sub|summary|sup|svg|table"
    "|tbody|td|textarea|tfoot|th|thead|time|title|tr|track|u|ul|var|video|wbr"
)

#: BBCode element names. Narrower than the HTML set and mostly disjoint from it.
_BBCODE_TAG_NAMES = (
    "attachment|b|center|code|color|email|font|i|img|left|list|quote|right|s|size"
    "|spoiler|table|td|tr|u|url"
)

#: An HTML or BBCode tag. Both are bounded so a stray bracket cannot swallow a
#: paragraph, and neither may contain a line break — which is what makes a line-local
#: scan equivalent to a whole-text one. ``\b`` after the name stops ``<about>`` from
#: matching on ``a``.
_TAG = (
    rf"</?(?:{_HTML_TAG_NAMES})\b[^<>\n]{{0,200}}>"
    rf"|\[/?(?:{_BBCODE_TAG_NAMES})(?:=[^\]\n]{{0,80}})?\]"
)

#: Characters that are markup syntax wherever they appear. Used to judge a span that
#: lies **wholly** inside a markup region: a surface carrying one of these is machine
#: syntax and may be discarded, while a plain surface sitting inside a URL path or a
#: bracketed handle is a name and must not be. Deliberately only the four unambiguous
#: bracket characters — ``/``, ``=`` and ``&`` occur inside URLs, which is exactly
#: where a name can legitimately live.
MARKUP_DELIMITER_PATTERN = re.compile(r"[<>\[\]]")

#: A named or numeric HTML entity: ``&nbsp;``, ``&#8203;``.
_HTML_ENTITY = r"&[A-Za-z#][A-Za-z0-9]{1,10};"

#: Zero-width and bidirectional control runs. They carry no prose and an NER model
#: routinely attaches them to a neighbouring span.
_INVISIBLE = r"[\u200b-\u200f\u2060\ufeff]+"

#: Regions of a text that are machine syntax rather than prose (ADR-0027).
#:
#: ``URL_PATTERN`` is composed in rather than restated, for the reason this module
#: exists: two spellings of "what a URL looks like" drift, and here they would drift
#: into a redaction that damages a link.
MARKUP_PATTERN = re.compile(
    f"{_TAG}|{URL_PATTERN.pattern}|{_HTML_ENTITY}|{_INVISIBLE}", re.IGNORECASE
)

#: Cheap pre-check. **Must stay a strict superset of what MARKUP_PATTERN can start
#: on**, or a real markup region is skipped: ``www.`` is listed for exactly that
#: reason, since the bare-host alternation needs no ``://``.
MARKUP_HINT_PATTERN = re.compile(r"[<>\[\]&]|://|www\.|[\u200b-\u200f\u2060\ufeff]", re.IGNORECASE)

#: Tag and attribute names an NER model mistakes for proper nouns once the angle
#: brackets around them have been clipped away. Nobody is named ``div``.
#:
#: Deliberately small and structural. It is not a denylist of words a model gets
#: wrong — that would be corpus tuning — but the vocabulary of the markup dialects
#: :data:`MARKUP_PATTERN` recognises, which is the only thing this guard claims to
#: know about.
MARKUP_TOKEN_VOCABULARY: frozenset[str] = frozenset(
    {
        "a",
        "align",
        "alt",
        "amp",
        "apos",
        "b",
        "bgcolor",
        "blockquote",
        "body",
        "border",
        "br",
        "button",
        "canvas",
        "caption",
        "cellpadding",
        "cellspacing",
        "class",
        "code",
        "col",
        "colgroup",
        "colspan",
        "color",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "embed",
        "face",
        "fieldset",
        "font",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "height",
        "hr",
        "href",
        "html",
        "i",
        "iframe",
        "img",
        "input",
        "label",
        "li",
        "link",
        "list",
        "margin",
        "meta",
        "name",
        "nbsp",
        "object",
        "ol",
        "option",
        "p",
        "padding",
        "pre",
        "quote",
        "rel",
        "rowspan",
        "s",
        "script",
        "select",
        "size",
        "small",
        "span",
        "src",
        "strong",
        "style",
        "sub",
        "sup",
        "svg",
        "table",
        "target",
        "tbody",
        "td",
        "textarea",
        "tfoot",
        "th",
        "thead",
        "title",
        "tr",
        "u",
        "ul",
        "url",
        "valign",
        "value",
        "video",
        "width",
    }
)


def markup_regions(text: str) -> list[tuple[int, int]]:
    """Sorted, merged ``(start, end)`` of every markup region in ``text``.

    Empty when the cheap hint does not fire, which is the common case: on prose with
    no tag, URL or entity in it this function does no regex work beyond the hint and
    the guard above it is a verified no-op.
    """
    if not text or not MARKUP_HINT_PATTERN.search(text):
        return []
    merged: list[list[int]] = []
    for found in MARKUP_PATTERN.finditer(text):
        start, end = found.start(), found.end()
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def markup_free_fragments(
    start: int, end: int, regions: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    """The sub-ranges of ``[start, end)`` that no region in ``regions`` covers.

    ``regions`` must be sorted and non-overlapping — what :func:`markup_regions`
    returns. An empty result means the span lay wholly inside markup.
    """
    fragments: list[tuple[int, int]] = []
    cursor = start
    for region_start, region_end in regions:
        if region_end <= cursor:
            continue
        if region_start >= end:
            break
        if region_start > cursor:
            fragments.append((cursor, min(region_start, end)))
        cursor = max(cursor, region_end)
        if cursor >= end:
            return fragments
    if cursor < end:
        fragments.append((cursor, end))
    return fragments


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

"""Output fidelity checks: assertions about the written result, not about the run.

`AGENTS.md` rule 5 says a reduction must not damage structure the parser marked
ineligible, and the parser/reconstructor contract makes that a structural guarantee
for everything *outside* a processable segment. It guarantees nothing *inside* one.
A ServiceNow note body containing quoted HTML is correctly offered for scanning, and
an NER model reading ``[code]<div`` as a person's name destroys the tag without
crossing any boundary. ADR-0027 records the measurement; this module is the
independent half of the remedy.

**Independent is the point.** The guard that clips such spans lives at the provider
boundary and keys off `patterns.MARKUP_PATTERN`. This module deliberately spells out
its own tag vocabulary and its own expression, and imports neither: a validator that
shares the detector's idea of markup rubber-stamps a shared mistake, and the failure
that motivated both was precisely a *fixed pattern set* meeting a dialect it did not
know. `tests/test_markup_guard.py` pins the independence.

Two severities, of which this module implements one. A structural loss is a
**fidelity** failure and stops the run (`Pipeline._validate_output` raises, and
ADR-0023's fail-closed posture carries it to a non-zero exit). A detector missing a
name is a **recall** failure and is reported by the benchmark, never by a gate on a
production run — recall is never 1.0, so gating on it means nothing ever ships.

Results carry counts only. No source text, no fragment, no offset, no tag name
reaches a message (`AGENTS.md` rule 8): a tag name is drawn from a closed vocabulary
and would disclose little, but "little" is not the standard this project holds itself
to, and the guard above makes a failure here rare enough that counts are enough to
start from.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

__all__ = [
    "KNOWN_MARKUP_TAGS",
    "MarkupCheckError",
    "MarkupLoss",
    "markup_losses",
    "markup_tag_counts",
]


class MarkupCheckError(Exception):
    """The check cannot be computed, as distinct from a check that failed.

    Its own type, and defined here rather than imported, because this module imports
    nothing from the project — that independence is the point of it (see above). The
    validation stage translates it into a ``ProcessingError`` so the pipeline's error
    contract is unchanged.
    """


#: A tag *name*, HTML or BBCode. Names only, because a name living inside an
#: attribute (``<a title='Peter Novak'>``) is legitimately redacted and must not read as
#: a lost tag. The attribute tail forbids ``<`` and ``>`` so an RFC-style bracketed
#: address (``<support@example.com>``) is not mistaken for a tag.
_TAG_NAME = re.compile(
    r"</?([A-Za-z][A-Za-z0-9]{0,15})(?:\s[^<>\n]{0,200})?\s*/?>|\[/?([A-Za-z][A-Za-z0-9]{0,15})\]"
)

#: An angle-bracketed replacement label, removed from **both** sides before counting.
#: The shipped redact reducer writes ``<PERSON>``; a name redacted inside an attribute
#: would otherwise turn ``<a title='Peter Novak'>`` into text this expression can no
#: longer read as a tag, manufacturing a failure out of a correct redaction. Stripping
#: both sides keeps the comparison symmetric, so it can never invent one.
#: (`mask` retains the original characters and `pseudonymize` writes ``PERSON_A1B2C3``
#: — neither introduces angle brackets, so neither needs handling here.)
_REPLACEMENT_LABEL = re.compile(r"<[A-Z][A-Za-z0-9_]*>")

#: Tag names whose loss counts. **Deliberately spelled out here rather than imported
#: from `patterns.py`** — see the module docstring. It also stops ``<Grace Okafor>``
#: written in prose from being defended as though it were a tag.
KNOWN_MARKUP_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "attachment",
        "audio",
        "b",
        "big",
        "blockquote",
        "body",
        "br",
        "button",
        "canvas",
        "caption",
        "center",
        "code",
        "col",
        "colgroup",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "embed",
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
        "hr",
        "html",
        "i",
        "iframe",
        "img",
        "input",
        "label",
        "li",
        "link",
        "meta",
        "object",
        "ol",
        "option",
        "p",
        "pre",
        "quote",
        "s",
        "script",
        "select",
        "size",
        "small",
        "source",
        "span",
        "strong",
        "style",
        "sub",
        "sup",
        "svg",
        "table",
        "tbody",
        "td",
        "textarea",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
        "url",
        "video",
    }
)


class MarkupLoss:
    """How much known markup a reduction destroyed. Counts only, never text."""

    __slots__ = ("rows", "tags")

    def __init__(self, rows: int = 0, tags: int = 0) -> None:
        #: Rows in which at least one known tag was lost.
        self.rows = rows
        #: Known tags lost across those rows.
        self.tags = tags

    def __bool__(self) -> bool:
        return self.tags > 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"MarkupLoss(rows={self.rows}, tags={self.tags})"


def markup_tag_counts(text: str) -> Counter[str]:
    """Known markup tag names in ``text``, by name, after removing replacement labels."""
    if "<" not in text and "[" not in text:
        return Counter()
    stripped = _REPLACEMENT_LABEL.sub("", text)
    counts: Counter[str] = Counter()
    for html_name, bbcode_name in _TAG_NAME.findall(stripped):
        name = (html_name or bbcode_name).lower()
        if name in KNOWN_MARKUP_TAGS:
            counts[name] += 1
    return counts


def markup_losses(originals: Iterable[object], outputs: Iterable[object]) -> MarkupLoss:
    """Compare two aligned sequences of cell values and count destroyed markup.

    A non-string on either side is skipped: a null field has no structure to lose, and
    the quarantine path writes ``None`` deliberately (ADR-0023). Only *losses* count —
    a reduction that somehow added a tag is a different fault, and counting it here
    would make this check fire on the wrong evidence.
    """
    left = list(originals)
    right = list(outputs)
    if len(left) != len(right):
        # Reachable only when `require_row_count_match` is off and the count changed.
        # A row-aligned comparison is not defined then, and `zip(strict=True)` would
        # escape the validation stage as a bare `ValueError` rather than as the
        # `ProcessingError` that stage promises.
        raise MarkupCheckError(
            f"cannot check markup fidelity: {len(left)} source rows against "
            f"{len(right)} output rows. Enable validation.require_row_count_match, "
            "or disable validation.require_markup_preserved"
        )

    loss = MarkupLoss()
    for original, output in zip(left, right, strict=True):
        if not isinstance(original, str) or not isinstance(output, str):
            continue
        before = markup_tag_counts(original)
        if not before:
            continue
        after = markup_tag_counts(output)
        missing = sum(max(count - after[name], 0) for name, count in before.items())
        if missing:
            loss.rows += 1
            loss.tags += missing
    return loss

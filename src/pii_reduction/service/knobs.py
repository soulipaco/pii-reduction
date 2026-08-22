"""Which engine settings a *caller* may move, and which stay server-side (ADR-0034).

This module holds **policy**, and it is deliberately separate from validity:

* ``config/registries.py``'s ``KNOWN_PARSER_OPTIONS`` says which options a parser
  *accepts*. That is engine knowledge, it governs every entry point — `describe`,
  `run`, the Databricks driver and this service — and a violation is a
  ``ConfigurationError`` from the layer that owns configuration.
* This table says which of those a caller may set **over HTTP**. That is a much
  smaller set, it is a privacy-and-surface decision rather than an engine one, and it
  belongs to the service.

It is its own module rather than living in ``templates.py`` because ``catalog.py``
needs it too and ``templates.py`` already imports ``catalog.py`` — a shared constant
between them has to sit below both.

**The rule these tables encode** (ADR-0034): a caller may choose anything whose worst
outcome is a measurable quality result, and never anything whose worst outcome is data
in a place, or raw text in a column, the operator did not sanction.
"""

from __future__ import annotations

__all__ = [
    "CONSIDERED_AND_NOT_OFFERED",
    "OFFERABLE_OPTION_NAMES",
    "OFFERABLE_PARSER_OPTIONS",
    "OFFERED_OPTION_CAPTIONS",
    "OFFERED_OPTION_DEFAULTS",
]

#: Boolean parser options a template may put on a caller's menu, by parser.
#:
#: **Boolean-only, and that is the security property rather than an economy**: a
#: caller's choice is a selection, never a free-form value, so no string a request
#: supplies can reach a parser's delimiter list, fallback policy or length limits.
#:
#: `split_lines`     — `plain_text`; ADR-0016. Right for line-structured records,
#:                     wrong for prose that wraps mid-sentence, where a name broken
#:                     across the wrap becomes undetectable.
#: `preserve_prefix` — `transcript`; ADR-0032. `false` puts a named speaker in scope,
#:                     and was measured to cost PERSON precision where speakers are
#:                     roles.
#:
#: Both change what the *model sees*, so either can trade one error for another. A
#: template opts in per option, and no surface may present them as improvements.
OFFERABLE_PARSER_OPTIONS: dict[str, frozenset[str]] = {
    "plain_text": frozenset({"split_lines"}),
    "transcript": frozenset({"preserve_prefix"}),
}

#: Booleans that exist on a parser and are **deliberately not offered**, so silence
#: cannot be mistaken for an oversight.
#:
#: `key_value.preserve_key` — the same species of switch as `preserve_prefix`, on a
#: parser no shipped template uses and no corpus measures. ADR-0016 records that
#: `key_value` lost to `split_lines` on the measurement that produced both, so
#: offering a knob on the parser that was *not* adopted would be widening the surface
#: ahead of any evidence. Reopens if a template ever uses `key_value`.
#:
#: `tests/test_service_parser_options.py` asserts every boolean of every parser is in
#: exactly one of these two tables, so adding a boolean to a parser fails a test
#: rather than passing unnoticed.
CONSIDERED_AND_NOT_OFFERED: dict[str, frozenset[str]] = {
    "key_value": frozenset({"preserve_key"}),
}

#: Every option name any parser will accept from a caller, flattened.
OFFERABLE_OPTION_NAMES: frozenset[str] = frozenset().union(*OFFERABLE_PARSER_OPTIONS.values())

#: The engine's own default for each offered option, so a **client does not have to
#: remember it** (ADR-0035).
#:
#: Without this the control panel kept its own copy — `preserve_prefix` pre-ticked
#: because that is what ADR-0032 ruled — and a saved configuration would then record
#: the *page's* belief rather than the engine's. If a default ever changes, a page that
#: remembers is a page that silently overrides. Reported through `GET /templates`, so
#: the client renders what is true rather than what it was told once.
#:
#: Flat because an option name belongs to exactly one parser, which is asserted.
#: Pinned against each parser's real `DEFAULT_OPTIONS` **by value**, so a changed
#: default fails a test here before it can disagree with a rendered checkbox.
OFFERED_OPTION_DEFAULTS: dict[str, bool] = {
    "split_lines": False,
    "preserve_prefix": True,
}

#: What each offered option *means*, in the words a surface should use.
#:
#: Server-side for the same reason as the defaults, and for one more: `docs/19` says a
#: client "must not present them as improvements", and a caption a client writes is a
#: caption nobody reviewed. Each describes the **shape of text the option suits** and
#: names the error it trades for — never "better".
#:
#: A test asserts every offered option has one, so a third knob cannot ship
#: uncaptioned and be rendered as a bare toggle.
OFFERED_OPTION_CAPTIONS: dict[str, str] = {
    "split_lines": (
        "Treat each line as its own record. Right for line-structured notes and "
        "exported form fields; wrong for prose that wraps mid-sentence, where a name "
        "split across the wrap becomes undetectable (ADR-0016)."
    ),
    "preserve_prefix": (
        "Keep the timestamp and speaker label out of scope for detection. Correct when "
        "the speaker is a role — Customer, Agent — and a leak when it is a person's "
        "name, such as a work-note author. Turning it off puts that name in scope and "
        "was measured to cost PERSON precision where speakers are roles (ADR-0032)."
    ),
}

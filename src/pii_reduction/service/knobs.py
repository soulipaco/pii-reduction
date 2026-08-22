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

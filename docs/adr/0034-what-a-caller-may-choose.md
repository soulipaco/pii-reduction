# ADR-0034: What a caller may choose — quality knobs yes, privacy boundaries never

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 14

## Context

ADR-0026 gave the service a server-side template and let a caller pick from its menu:
columns, entity labels, parser, provider chain, reducer. That menu is **narrower than
the engine's configuration**, and the gap is exactly where this project's accuracy work
lives:

| knob | where the accuracy is | reachable through the API before this ADR |
|---|---|---|
| `split_lines` (ADR-0016) | took English tier-3 PERSON recall 0.333 → 1.000 | **no** |
| `preserve_prefix` (ADR-0032) | takes incident strict F1 0.761 → 0.844 | **no** |
| per-entity thresholds (ADR-0005) | calibrated, locked | no |
| Greek label promotion (ADR-0020) | recall 0.154 → 0.500 | no (provider-instance config) |

So the surface that exists to make this engine usable withheld the two settings most
likely to change a result on somebody's real column — and the reason was never
decided, only unaddressed. ADR-0026 rule 4 says which things stay server-side; it never
said the remainder was closed.

**A rule proposed in discussion did not survive contact with the measurements.** The
first formulation was *"a knob is safe to expose when moving it can only redact more."*
It is wrong twice over:

- `split_lines: true` can redact **less** — ADR-0016 records that splitting is wrong for
  prose wrapping mid-sentence, where a name broken across the wrap becomes undetectable.
- `preserve_prefix: false` was measured by ADR-0032 to **trade one error for another**:
  it recovers the work-note author and simultaneously invents a false-positive PERSON in
  a Greek body, because it changes what the model sees.
- And `entities` — already caller-choosable since ADR-0026 — is not monotone either.
  Removing `PERSON` from the list means PERSON is not redacted.

Any rule phrased in terms of "more or less redaction" is therefore untrue of the surface
as it already ships. A different rule is needed.

## Decision

**A caller may choose anything whose worst outcome is a measurable quality result. A
caller may never choose anything whose worst outcome is data in a place, or raw text in
a column, that the operator did not sanction.**

Two classes, and the line between them is *what the mistake costs*, not which direction
the redaction moves.

### Class 1 — Boundary. Never a caller's choice.

| setting | what a wrong value does |
|---|---|
| `source` | points the service principal's credentials at data the caller may not read |
| `destination` | lands output where the caller may not be entitled to put it |
| `failure_mode` | `preserve_original_and_record_error` writes **raw text** into the reduced column (ADR-0023) |
| `preserve_original` | `false` is the controlled replacement workflow `AGENTS.md` rule 4 requires a configuration to define explicitly |
| `destination.projection` | ADR-0024's grant boundary |

These come from the template. This restates ADR-0026 rule 4 rather than changing it, and
`tests/test_service_parser_options.py` asserts that none of the five is a field on any
request model — so the guarantee is the absence of a field, not a check somebody can
forget. The request models are found by **reflection** rather than from a hand-written
list, because a hand-written list is how `RunRequest` came to be missing from the first
draft of that test, and `RunRequest` is exactly where "run this dataset, but write it
over *there*" would be added.

### Class 2 — Quality. Offerable, from a server-side menu.

Entity selection, parser, provider chain, reducer — all already shipped — **and now
parser options**. A wrong value here produces a worse number. The number is measured,
gated, and published; that is the whole apparatus this repository has for the purpose.

Three constraints on how a Class 2 knob is offered:

1. **A selection, never a free-form value.** `ColumnRequest.parser_options` is typed
   `dict[str, bool]`. The annotation is the guard: no delimiter, path, policy name or
   length can reach a parser through a request, because a non-boolean is a 422 before
   the builder is entered. Only the two booleans in `service/knobs.py`'s
   `OFFERABLE_PARSER_OPTIONS` are offerable; every other parser option stays
   template-side.
2. **The template opts in, per option.** The default is an empty menu. The operator is
   the one who knows whether their text wraps mid-sentence — `split_lines` is right for
   a line-structured work-notes column and wrong for a wrapped description column, and
   only their data says which they have.
3. **A refusal happens at build time, not at run time.** `parser_options` requires
   `parser` in the same request. Otherwise `POST /configs` returns 201 and the run
   dies when the pipeline constructs the parser — "a pre-flight check that reports a
   broken dataset which works is worse than no check" (ADR-0031), and its mirror image
   is worse still.

### Validity and policy are different facts, and they live in different layers

The first draft of this decision put *both* in `service/`, and an architecture review
was right that it should not have. They are different questions:

| | question | where | applies to |
|---|---|---|---|
| **validity** | does `transcript` accept `split_lines`? | `config/registries.py`'s `KNOWN_PARSER_OPTIONS` | every entry point — `describe`, `run`, the Databricks driver, the service |
| **policy** | may a *caller* set it over HTTP? | `service/knobs.py`'s `OFFERABLE_PARSER_OPTIONS` | the service alone |

The draft rejected `config/` on the grounds that it "cannot import `parsers/`". That is
a non-sequitur: `config/registries.py` does not import `parsers/` either — it
**restates**, which is the trade this ADR invokes two paragraphs earlier.

**Putting validity where it belongs fixed a pre-existing bug this ADR did not set out
to touch.** A typo in a hand-written dataset YAML's `parser_options` survived every
check the configuration layer performs and surfaced as a `ParserError` when the
pipeline was built — after the source had been resolved and, on the Databricks path,
after a Spark session existed. All four entry points gain the check at once, and
`service/builder.py` goes back to pure menu validation, which is what its own docstring
promises.

### Thresholds are Class 2 and stay closed anyway

The per-entity thresholds are the most tempting knob and are deliberately **not**
offered. Not because a wrong value is dangerous — a lower threshold redacts more, a
higher one leaks — but because they were **calibrated on a held-out split and locked**
(`docs/14` §8, Increment E), and `AGENTS.md` forbids tuning a benchmark to the model. A
UI slider on a calibrated constant is an invitation to move a published number by hand
and then keep quoting it.

**The shape that would work, recorded and not built:** named profiles declared
server-side — `thresholds: [calibrated, aggressive]` — so the constants stay in
reviewed configuration, the caller picks between measured alternatives, and each profile
can carry its own gate set. That is a Class 2 knob offered as a selection, which is
rule 1 applied to numbers. It needs a measurement per profile before it means anything.

## Consequences

- **The two settings that most change a result on a real column are reachable**, per
  column, from a menu the operator controls.
- **`GET /templates` reports which parser accepts each offered option**, so a UI can
  attach a toggle to the right parser rather than guess, and `GET /datasets/{name}`
  reports the options a saved dataset resolved to — filtered to the governed subset
  and typed `bool`, so what comes back can be sent again and a hand-written
  template-side option cannot be echoed out of a file.
- **Two restated tables, both pinned, and pinned differently on purpose.**
  `KNOWN_PARSER_OPTIONS` is pinned by an **equality** against each parser's real
  `DEFAULT_OPTIONS` — the same strength as `KNOWN_PARSERS` itself — so an option added
  to a parser fails a test rather than becoming a setting configuration silently
  refuses. `OFFERABLE_PARSER_OPTIONS` is pinned by a **partition**: every boolean of
  every parser must appear in either it or `CONSIDERED_AND_NOT_OFFERED`, so a new
  boolean fails a test until somebody decides, and silence can never be mistaken for an
  oversight. `key_value.preserve_key` is the first member of the second set, and an
  earlier draft had it in neither — precisely the hole the partition closes.
- **The shipped `synthetic_corpus` template offers both**, because it is Class A
  synthetic throughout and contains both document shapes — it is the template someone
  can experiment on without touching real data. **The commented Unity Catalog template
  offers neither**, with a note saying to measure on your own text first.
- **No surface may present these as improvements.** Both change what the model sees.
  ADR-0032 measured `preserve_prefix` helping on one corpus and hurting on another; §8's
  Q2 measured the same of `split_lines` twice. The honest framing is "this matches the
  shape of my text", not "this makes it better".
- **No published number moves.** No default changes; every gate is unchanged.

## What would reopen this

- **A third parser option worth offering** — it moves from `CONSIDERED_AND_NOT_OFFERED`
  to `OFFERABLE_PARSER_OPTIONS` with its measurement, and the partition test insists a
  decision is made rather than skipped. `key_value.preserve_key` is the standing
  candidate, and reopens if a template ever uses that parser.
- **A non-boolean knob with a genuine case**, e.g. `speaker_delimiters` for a transcript
  format whose delimiter is not `:`. That needs a different mechanism than "type it into
  a request", because rule 1 exists to keep free-form strings out of parsers — most
  likely a named format on the template, selected by name.
- **Threshold profiles**, once at least two exist and each has been measured on a corpus
  that ships.
- **A parser option that moves a privacy boundary.** None does today. If one arrives it
  is Class 1, and `NEVER_OFFERABLE` in the test module is where it goes.

## Alternatives rejected

- **Expose `parser_options` as free-form `dict[str, Any]`.** It is one line and it hands
  a caller a string channel into the parser layer — delimiters, fallback policies,
  length limits. `models.py`'s whole claim is that no request model can carry content;
  `Any` would be the field that breaks it.

  The contract test that was supposed to defend that claim **would not have caught it**:
  it matches field *names* against a forbidden vocabulary, and `parser_options` contains
  no forbidden token. Found by the privacy audit, and closed by a second guard that
  walks every request field's *annotation* and refuses `Any`, `object`, and any bare
  `str` without a pattern constraint.
- **Let the caller set options without naming the parser**, resolving it from the
  template default. It builds a configuration the pipeline then refuses, which is the
  201-then-failed-run this ADR's rule 3 exists to prevent.
- ~~**Validate the option against the parser in `config/`.**~~ **Adopted**, after an
  architecture review showed the reason for rejecting it was a non-sequitur — see
  *Validity and policy are different facts* above. The original text read: "it is where
  validity belongs, but `config/` is bounded to `contracts/` and `entities/` and cannot
  import `parsers/`." `config/registries.py` restates rather than imports, which is
  exactly the trade this ADR relies on elsewhere.
- **Offer every boolean parser option automatically.** It makes the *parser's* internals
  the API's surface area, so adding an internal boolean would silently widen what a
  caller can do. An explicit table is a decision; a reflection loop is an accident
  waiting for a future commit.

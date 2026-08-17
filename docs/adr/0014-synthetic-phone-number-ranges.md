# ADR-0014: Synthetic phone numbers come from published permanently-unassigned ranges

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 3

## Context

The committed benchmark corpus (`tests/fixtures/corpus/`) contains phone numbers as
ground-truth PII, the manifest stores their exact surface strings, and the README
quickstart prints documents containing them. ADR-0003 settled the equivalent question
for email addresses (RFC 2606 reserved domains); phone numbers were not given the same
treatment and the first implementation got it wrong.

The privacy audit before the first commit found that the German pool was generated as
`+49 30 9018xx` — the Berlin national prefix followed by a subscriber block that is
**allocated and routable**. `libphonenumber` reported every value valid and geocoded
them to Berlin. Seventeen dialable numbers had reached the committed corpus. Nobody's
data leaked; the harm runs the other way, which is a public repository publishing real
numbers as "call this number" example text.

Two requirements pull against each other:

1. **Valid.** `phonenumbers` must recognize the number, or the benchmark measures the
   recognizer's tolerance for malformed input rather than its detection quality. The
   deterministic provider runs at `leniency: valid` by default, so an invalid number
   would simply not be found.
2. **Unmistakably fake.** `AGENTS.md` rule 2 requires committed PII examples to be
   clearly synthetic, and `docs/02_PUBLIC_DATA_STRATEGY.md` asks for "fictional
   numbers or non-routable ranges where feasible".

Only a range that a numbering authority has published as *permanently unassigned*
satisfies both: it parses as a real number of that country, and it can never reach a
subscriber.

## Decision

Phone pools are drawn from published permanently-unassigned ranges, cited in
`src/pii_reduction/synthetic/values.py`:

| Language | Range | Source |
|---|---|---|
| `en` | `+1 202 555 01xx` | NANP `555-01xx`, reserved for fictional use |
| `de` | `+49 30 23125 0xx` | Bundesnetzagentur "Drama Numbers", Mitteilung 148/2021 (Amtsblatt 07/21, 14.04.2021): Berlin `030 23125 000`–`999`, usable in media without permission |
| `el` | `+30 210 000 00xx` | **No published Greek equivalent** — see below |

`_validate_phone_pools()` asserts every pooled value is
`phonenumbers.is_valid_number`, so requirement 1 cannot silently regress. The corpus
is deterministic, so changing a pool is a regeneration with a reviewable diff.

**Greece is the weak entry and is recorded as such.** EETT publishes no drama-number
range. The chosen block keeps the Athens `210` prefix for realism and fills the
subscriber part with `000 00xx`, which is not within the assigned Athens subscriber
ranges; `libphonenumber` accepts it because the Greek pattern is permissive. That is
weaker evidence than a published reservation, and it is the honest state of the art
for Greek synthetic data. If EETT ever publishes a reserved range, swap the pool and
regenerate.

The Bundesnetzagentur also lists Frankfurt (`069 90009`), Hamburg (`040 66969`),
Cologne (`0221 4710`), Munich (`089 99998`) and several mobile ranges, if more German
variety is needed later.

## Consequences

- Adding a language to the corpus now requires finding that country's reserved range
  first, or documenting explicitly that none exists. That is a deliberate speed bump.
- The German pool holds 24 of the 1,000 available Berlin drama numbers; there is ample
  room to grow, and the other four city blocks are available.
- Increment D's public datasets inherit the same rule: injected numbers come from these
  pools, never from the source corpus, and never invented ad hoc.
- The `valid`-and-`fake` tension is now stated in the module docstring, so the next
  person who "fixes" a failing validity check by loosening the pool sees why both
  properties are load-bearing.

# CLAUDE.md

This repository is designed to be developed with Claude Code as well as human contributors.

## Required context

**Start every session with these two**, in this order — they say what is already built
and what to do next, so you do not re-derive either:

1. `docs/14_IMPLEMENTATION_PLAN.md` — the build sequence. **§8 is the live status and
   work queue**: what is complete, what is in progress, what to pick up next, and the
   exit criterion for each.
2. `.claude/SESSION_HANDOFF.md` — what each session established, measured, and left
   open. Read the **most recent session's "Start here" block first**; the rest is
   evidence you can consult rather than repeat.

Then, before implementing or refactoring significant functionality:

3. `AGENTS.md` — repository-wide engineering rules.
4. `README.md` — product definition and documentation map.
5. `docs/00_PROJECT_CHARTER.md` — scope and non-goals.
6. `docs/01_ARCHITECTURE.md` — component boundaries and dependency direction.
7. `docs/adr/README.md` — the decision index. Every non-obvious choice in this
   codebase has an ADR; check it before proposing a different one, and write a new
   ADR rather than quietly diverging.
8. The specific design document related to the task, and `docs/15_PROVIDERS.md` when
   the task touches a provider.

`AGENTS.md` is the canonical agent policy. This file intentionally does not duplicate it.

## Working environment

`.venv` exists and is current. Use `.venv/Scripts/python.exe` on Windows.

```text
pytest -q                      default tier: fast, no models, no provider extras
pytest -q -m integration       needs the presidio + language extras and spaCy models
pii-reduction benchmark        the measured baseline, deterministic chain
pii-reduction benchmark --chain deterministic_presidio
```

Run `/qa` before claiming an increment complete, and `/gate` before committing. The
default `pytest` run deliberately excludes `integration`, `slow` and `databricks`
(ADR-0009), so say which tier you ran when reporting results.

## Development approach

Work incrementally. Preserve working behavior while moving toward the documented architecture.

For each task:

- inspect existing implementation before editing,
- identify the contract affected,
- prefer reusable library code over notebook logic,
- add or update tests with the implementation,
- keep examples synthetic/public-safe,
- update design documentation if behavior or architecture changes,
- run the relevant tests before claiming completion.

## Architectural checkpoints

Do not collapse these responsibilities into one large script:

```text
source loading
text parsing/segmentation
language resolution
PII detection
entity reconciliation
reduction
reconstruction
validation/evaluation
output persistence
```

Provider-specific APIs must remain behind provider adapters.

Databricks-specific code must not infect the local core library unless the functionality is genuinely Databricks-specific.

## Privacy checkpoints

Before writing tests, docs, fixtures, debug output, or examples, verify that the content is synthetic or explicitly public-safe.

Never copy production examples into the repository merely because they are convenient test cases.

Never print raw text while debugging the PII engine unless an explicitly local synthetic fixture is being used.

## Implementation priority

Unless a task explicitly changes priorities, follow `docs/11_ROADMAP.md`.

Prefer completing and measuring a simple baseline before adding another provider, model, framework, or UI surface.

## Completion report

When a substantial task is complete, summarize:

- files created/modified,
- behavior added,
- tests executed and results,
- benchmark changes if any,
- limitations or unresolved decisions,
- recommended next step.

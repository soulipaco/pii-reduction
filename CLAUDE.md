# CLAUDE.md

This repository is designed to be developed with Claude Code as well as human contributors.

## Required context

Before implementing or refactoring significant functionality, read:

1. `AGENTS.md` — repository-wide engineering rules.
2. `README.md` — product definition and documentation map.
3. `docs/00_PROJECT_CHARTER.md` — scope and non-goals.
4. `docs/01_ARCHITECTURE.md` — component boundaries and dependency direction.
5. The specific design document related to the task.

`AGENTS.md` is the canonical agent policy. This file intentionally does not duplicate it.

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

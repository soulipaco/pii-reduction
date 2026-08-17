---
description: Pre-commit gate — run tests, then privacy and architecture audits in parallel, and summarize
allowed-tools: Bash, Read, Glob, Grep, Agent
---

Run the full pre-commit gate for this repository before a commit, a PR, or a
roadmap-phase completion claim.

**Step 1 — quality gate.** Run `ruff format --check .`, `ruff check .`, `mypy src`
and `pytest -q` using the `.venv` interpreter. Record exact exit codes and counts.

**Step 2 — audits.** Launch both review agents in parallel, in a single message, and
scope them to the working-tree diff (`git diff HEAD` plus untracked files):

- the `privacy-auditor` agent,
- the `architecture-guardian` agent.

**Step 3 — report.** Their reports are not shown to the user, so relay what matters.
Produce one consolidated verdict:

- **Blocking** — test failures, privacy violations, contract violations. These must be
  fixed before committing.
- **Non-blocking** — observations and judgement calls worth a decision.
- **Clean** — what was verified and found sound.

End with a single recommendation: commit as-is, or fix the listed blockers first.

Do not fix anything in this command, and do not commit. Report and recommend only.

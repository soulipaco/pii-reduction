---
description: Produce the completion report that AGENTS.md requires at the end of an implementation task
argument-hint: "[roadmap phase or task name]"
allowed-tools: Bash, Read, Glob, Grep
---

Write the completion report that `AGENTS.md` ("Completion behavior for coding agents")
and `CLAUDE.md` require for: $ARGUMENTS

Gather evidence first — do not write the report from memory:

- `git status` and `git diff --stat HEAD` for the actual file list;
- the real test output (run the suite now if it has not been run since the last edit);
- `docs/11_ROADMAP.md` for the exit criteria of the phase in question.

Then report, in this order:

1. **Files changed** — created and modified, grouped by architecture layer.
2. **Behavior added** — what the code now does that it did not before, in terms of the
   pipeline contracts, not a restatement of the diff.
3. **Tests executed and exact results** — commands, counts, and which markers were
   skipped or deselected. Never round a skipped suite up to "passing".
4. **Benchmark changes** — metric deltas if evaluation ran; say "not run" if it did not.
5. **Exit criteria** — each criterion for this phase, marked met / not met / partially
   met, with the evidence for the claim.
6. **Known limitations** — including anything working only for the fixture at hand.
7. **Decisions to record in documentation** — assumptions taken, defaults chosen,
   inconsistencies resolved, and which file under `docs/` should capture each.
8. **Most logical next implementation step** — one step, with the reason it comes next.

Two rules on honesty, both from `AGENTS.md`: do not claim Databricks execution
succeeded unless it actually ran in a Databricks environment, and do not describe a
phase as complete when its exit criteria are only partially met — report the gap.

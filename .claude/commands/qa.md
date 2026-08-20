---
description: Run the full local quality gate (ruff, mypy, pytest) and report the exact results
argument-hint: "[optional pytest path or -k expression]"
allowed-tools: Bash, Read, Glob, Grep
---

Run this repository's local quality gate and report what actually happened.

Use the project virtualenv at `.venv` (`.venv/Scripts/python.exe` on Windows,
`.venv/bin/python` otherwise). If `pyproject.toml` does not exist yet, say so and
stop — the gate is not meaningful before Phase 0 is complete.

Run, in order, and do not stop early on failure — collect all four results:

1. `ruff format --check .`
2. `ruff check .`
3. `mypy src tests` — **both**, because that is what CI runs
   (`.github/workflows/ci.yml`). Checking `src` alone passed locally for two whole
   increments in session 10 while `tests` carried 21 errors that CI would have
   caught; a local gate that is weaker than the remote one is not a gate.
4. `pytest -q $ARGUMENTS` (omit the argument if none was given)

Then report:

- the exact command, exit code, and the failure summary for each step;
- test counts: passed / failed / skipped / errors, and which markers were deselected
  (`integration`, `slow`, `databricks` are expected to be excluded from the fast run —
  say explicitly if they were skipped rather than passing);
- for each failure, the assertion and the smallest likely cause.

`AGENTS.md` requires accurate reporting: never describe a suite as passing when tests
were skipped, deselected, or never collected. If a step could not run at all, say
that instead of inferring a result.

Do not fix anything in this command. Report only. The caller decides what to repair.

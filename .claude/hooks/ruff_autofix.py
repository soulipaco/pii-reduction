#!/usr/bin/env python3
"""PostToolUse hook: format and auto-fix Python files right after they are edited.

Keeps style drift out of the diff so review effort goes to architecture instead
of formatting. Silent on success; on remaining, non-auto-fixable lint errors it
exits 2, which surfaces stderr back to the agent (the edit has already been
applied, so nothing is lost) and lets it repair the file in the same turn.

Resolves ruff from the project virtualenv first so the repo's pinned version is
used, falling back to whatever is on PATH. Any unexpected failure exits 0: a
formatter must never block work.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def find_ruff() -> str | None:
    for candidate in (
        PROJECT_ROOT / ".venv" / "Scripts" / "ruff.exe",  # Windows
        PROJECT_ROOT / ".venv" / "bin" / "ruff",  # POSIX
    ):
        if candidate.exists():
            return str(candidate)
    return shutil.which("ruff")


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    raw_path = tool_input.get("file_path")
    if not isinstance(raw_path, str) or not raw_path.endswith(".py"):
        return 0

    path = Path(raw_path)
    if not path.exists():
        return 0

    ruff = find_ruff()
    if ruff is None:
        return 0

    try:
        subprocess.run(
            [ruff, "format", str(path)],
            capture_output=True,
            timeout=30,
            check=False,
        )
        result = subprocess.run(
            [ruff, "check", "--fix", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return 0

    if result.returncode != 0 and result.stdout.strip():
        print(
            f"ruff reported issues in {path.name} that need a manual fix:\n"
            f"{result.stdout.strip()}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())

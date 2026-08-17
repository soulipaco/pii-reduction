#!/usr/bin/env python3
"""PreToolUse guard: refuse to write secrets or real-looking PII into the repo.

This enforces AGENTS.md rules 1 (no secrets) and 2 (no private production data)
mechanically instead of relying on the agent to remember them.

Contract (Claude Code hooks):
  stdin  -> JSON with {"tool_name": ..., "tool_input": {...}}
  exit 0 -> allow
  exit 2 -> block, stderr is fed back to the agent as the reason

The guard is deliberately narrow. This is a PII project: synthetic PII is the
whole point, so anything using RFC 2606 / RFC 6761 reserved domains
(example.com/net/org, *.test, *.invalid, *.example, *.localhost) is allowed.
Only patterns that are almost certainly *real* are blocked.

Never crash: an exception here must not stop the user's work, so any unexpected
failure falls through to "allow".
"""

from __future__ import annotations

import json
import re
import sys

# --- Hard blocks: credential material -------------------------------------
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Canonical PATs are dapi + 32 hex, but some carry a "-N" suffix; accept 28+
    # so a truncated or suffixed token is still caught.
    ("Databricks personal access token", re.compile(r"\bdapi[0-9a-fA-F]{28,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Azure/Slack style token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "Hard-coded Databricks workspace host",
        re.compile(r"\bdbc-[0-9a-f]{8}-[0-9a-f]{4}\.cloud\.databricks\.com\b"),
    ),
]

# --- Hard blocks: real personal data --------------------------------------
# Consumer mailbox providers never appear in synthetic fixtures.
REAL_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@(?:gmail|googlemail|hotmail|outlook|live|msn|yahoo|ymail"
    r"|icloud|me\.com|aol|gmx|web\.de|mail\.ru|yandex|protonmail|proton\.me"
    r"|zoho|hey\.com)\.[A-Za-z.]{2,}",
    re.IGNORECASE,
)

# Reserved-for-documentation domains are explicitly fine.
RESERVED_DOMAIN = re.compile(
    r"@(?:[A-Za-z0-9\-]+\.)*(?:example\.(?:com|net|org)|test|invalid|localhost|example)\b",
    re.IGNORECASE,
)

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def extract_payload(tool_input: dict) -> str:
    """Collect every string field that could carry file content."""
    parts: list[str] = []
    for key in ("content", "new_string", "old_string", "new_source"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            value = edit.get("new_string")
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def find_violations(text: str) -> list[str]:
    problems: list[str] = []

    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            problems.append(f"{label} detected (AGENTS.md rule 1: no secrets).")

    for match in REAL_EMAIL.finditer(text):
        if RESERVED_DOMAIN.search(match.group(0)):
            continue
        domain = match.group(0).split("@", 1)[1]
        problems.append(
            f"Email on a real consumer domain '{domain}' detected "
            "(AGENTS.md rule 2: committed PII examples must be obviously synthetic). "
            "Use example.com / example.org / *.test / *.invalid instead."
        )
        break

    return problems


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    if event.get("tool_name") not in WRITE_TOOLS:
        return 0

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    try:
        problems = find_violations(extract_payload(tool_input))
    except Exception:
        return 0

    if not problems:
        return 0

    path = tool_input.get("file_path", "<unknown file>")
    print(f"Blocked write to {path}:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "\nThe matched value is not echoed here on purpose (AGENTS.md rule 8: "
        "privacy-safe observability). Replace it with a clearly synthetic value "
        "or an environment/secret reference, then retry.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

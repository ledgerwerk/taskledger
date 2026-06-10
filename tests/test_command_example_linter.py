"""Command-example linter: validates taskledger command lines found in docs and
skill files against the actual CLI command inventory."""

from __future__ import annotations

import re
from pathlib import Path

from taskledger.command_inventory import COMMAND_METADATA

ROOT = Path(__file__).resolve().parents[1]

DOC_PATHS: list[Path] = sorted(
    p
    for p in (ROOT / "docs").rglob("*")
    if p.suffix == ".rst" and "_build" not in p.parts
) + [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "API.md",
]

SKILL_PATHS: list[Path] = [ROOT / "skills" / "taskledger" / "SKILL.md"]

ALL_PATHS = DOC_PATHS + SKILL_PATHS

# Lines containing these substrings are skipped (incomplete examples, placeholders)
_SKIP_SUBSTRINGS = {
    "...",
    "<",
    ">",
    "QUESTION_ID",
    "TODO_ID",
    "TASK_ID",
    "RUN_ID",
    "CHANGE_ID",
    "HANDOFF_ID",
    "CRITERION_ID",
    "TASK_REF",
    "FILE_PATH",
    "PLAN_VERSION",
    "AC_XXXX",
    "ac-XXXX",
}

_SINGLE_TOKEN_COMMANDS = {
    "init",
    "status",
    "export",
    "import",
    "reindex",
    "context",
    "view",
    "can",
    "next-action",
    "--task",
    "search",
    "grep",
    "symbols",
    "deps",
    "doctor",
    "snapshot",
    "tree",
    "commands",
}

# Commands that are valid top-level or two-token commands from the inventory
_VALID_COMMANDS = set(COMMAND_METADATA.keys()) | _SINGLE_TOKEN_COMMANDS

# Forbidden substrings that indicate removed commands
_FORBIDDEN = [
    "taskledger repo ",
    "taskledger runs ",
    "taskledger context save",
    "taskengine context run",
    "runtildone --harness",
    "todo toggle",
    "taskledger task new",
    "taskledger task clear-active",
    "taskledger implement add-change",
    "taskledger validate add-check",
    "taskledger file unlink",
    "taskledger link link",
    "taskledger link unlink",
    "taskledger actor whoami --json",
]


_COMMAND_STARTERS = {tok.split()[0] for tok in _VALID_COMMANDS} | _SINGLE_TOKEN_COMMANDS


def _extract_command_tokens(line: str) -> str | None:
    """Extract the command token after 'taskledger' from a code-like line."""
    stripped = line.lstrip()
    if stripped.startswith("#") and not stripped.startswith("# "):
        return None
    m = re.search(r"taskledger(?:\s+--\S+)*\s+([a-z][\w-]*)", line)
    if m is None:
        return None
    first = m.group(1)
    # Reject if first token is not a known command starter
    if first not in _COMMAND_STARTERS:
        return None
    # If first token is a known single-token command, return it alone
    if first in _SINGLE_TOKEN_COMMANDS:
        return first
    # Otherwise try to get two tokens for group commands
    m2 = re.search(
        r"taskledger(?:\s+--\S+)*\s+([a-z][\w-]*\s+[a-z][\w-]*)",
        line,
    )
    if m2 is not None:
        return m2.group(1).strip()
    return first


def test_docs_do_not_reference_removed_commands() -> None:
    for path in ALL_PATHS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for needle in _FORBIDDEN:
            assert needle not in text, f"{path}: found forbidden '{needle}'"


def test_command_examples_in_docs_use_valid_commands() -> None:
    failures: list[str] = []
    for path in ALL_PATHS:
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if "taskledger " not in stripped:
                continue
            # Skip lines that are clearly not runnable examples
            if any(s in stripped for s in _SKIP_SUBSTRINGS):
                continue
            # Skip lines that are prose (not code-like)
            # Code lines in markdown are indented or inside ``` blocks
            # Prose lines start with -, *, #, or plain text
            if stripped.startswith("-") or stripped.startswith("*"):
                continue
            if stripped.startswith("# ") or stripped.startswith("## "):
                continue
            # Skip lines with backtick-quoted taskledger (prose references)
            if "`taskledger" in stripped:
                continue
            tokens = _extract_command_tokens(stripped)
            if tokens is None:
                continue
            if tokens in _VALID_COMMANDS:
                continue
            # Also check two-token form with hyphenated subcommand
            parts = tokens.split(None, 1)
            if len(parts) == 2:
                two_token = f"{parts[0]} {parts[1]}"
                if two_token in _VALID_COMMANDS:
                    continue
            failures.append(
                f"{path}:{i}: unknown command '{tokens}' in: {stripped[:120]}"
            )

    assert not failures, "\n".join(failures)


def test_readme_skill_path_matches_repository() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/taskledger/SKILL.md" in readme
    assert "taskledger/skills/taskledger/SKILL.md" not in readme

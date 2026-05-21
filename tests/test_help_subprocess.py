"""Subprocess tests for help command speed and non-logging."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = str(Path(__file__).resolve().parent.parent)


def _run_help(
    tmp_path: Path,
    *argv: str,
    timeout: int = 5,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "taskledger", *argv],
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": ROOT, "TASKLEDGER_NO_LOG": "0"},
        text=True,
        capture_output=True,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["task", "--help"],
        ["plan", "--help"],
        ["question", "--help"],
        ["implement", "--help"],
        ["validate", "--help"],
        ["todo", "--help"],
        ["doctor", "--help"],
        ["repair", "--help"],
        ["handoff", "--help"],
        ["ledger", "--help"],
        ["actor", "--help"],
        ["harness", "--help"],
    ],
)
def test_help_subprocess_exits_quickly(argv: list[str], tmp_path: Path) -> None:
    result = _run_help(tmp_path, *argv)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Usage:" in result.stdout


def test_help_is_not_agent_logged(tmp_path: Path) -> None:
    _run_help(tmp_path, "plan", "--help")
    agent_logs = tmp_path / ".taskledger" / "agent-logs"
    assert not agent_logs.exists(), f"agent-logs dir exists: {agent_logs}"


def test_root_help_shows_completion_options(tmp_path: Path) -> None:
    result = _run_help(tmp_path, "--help")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout


def test_show_completion_exits_quickly_and_does_not_create_agent_logs(
    tmp_path: Path,
) -> None:
    result = _run_help(tmp_path, "--show-completion")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "taskledger" in result.stdout
    agent_logs = tmp_path / ".taskledger" / "agent-logs"
    assert not agent_logs.exists(), f"agent-logs dir exists: {agent_logs}"

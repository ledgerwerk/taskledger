from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app

pytestmark = [
    pytest.mark.cli,
    pytest.mark.integration,
    pytest.mark.git,
    pytest.mark.slow,
]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0


def _prepare_implementation(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "impl-scan",
                "--description",
                "Capture implementation evidence.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "impl-scan"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--task",
                "impl-scan",
                "--criterion",
                "Record the implementation evidence.",
                "--text",
                "## Goal\n\nCapture implementation evidence.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                "impl-scan",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Proceed.",
                "--allow-empty-todos",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "implement", "start", "--task", "impl-scan"],
        ).exit_code
        == 0
    )


# specmason: req=REQ-0025 ac=AC-0313
def test_scan_changes_from_git_records_branch_status_and_diff_stat(
    tmp_path: Path,
) -> None:
    _prepare_implementation(tmp_path)

    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Taskledger Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    readme = tmp_path / "README.md"
    readme.write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    readme.write_text("hello\nworld\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "implement",
            "scan-changes",
            "--task",
            "impl-scan",
            "--from-git",
            "--summary",
            "Captured Git state.",
        ],
    )
    payload = _json(result)
    assert result.exit_code == 0
    assert payload["result"]["kind"] == "scan"
    assert "branch:" in payload["result"]["git_diff_stat"]
    assert "README.md" in payload["result"]["git_diff_stat"]


# specmason: req=REQ-0025 ac=AC-0314
def test_scan_changes_from_git_rejects_non_git_workspace(tmp_path: Path) -> None:
    _prepare_implementation(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "implement",
            "scan-changes",
            "--task",
            "impl-scan",
            "--from-git",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert "Git work tree" in payload["error"]["message"]


# specmason: req=REQ-0025 ac=AC-0312
def test_manual_implement_change_still_works_via_canonical_command(
    tmp_path: Path,
) -> None:
    _prepare_implementation(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "implement",
            "change",
            "--task",
            "impl-scan",
            "--path",
            "taskledger/services/tasks.py",
            "--kind",
            "edit",
            "--summary",
            "Manual evidence entry.",
        ],
    )
    payload = _json(result)
    assert result.exit_code == 0
    assert payload["result"]["path"] == "taskledger/services/tasks.py"


# specmason: req=REQ-0025 ac=AC-0311
def test_implement_finish_warns_when_git_scan_missing(tmp_path: Path) -> None:
    _prepare_implementation(tmp_path)
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    manual = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "implement",
            "change",
            "--task",
            "impl-scan",
            "--path",
            "taskledger/services/tasks.py",
            "--kind",
            "edit",
            "--summary",
            "Manual evidence entry.",
        ],
    )
    assert manual.exit_code == 0, manual.stdout

    finish = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "implement",
            "finish",
            "--task",
            "impl-scan",
            "--summary",
            "Done.",
        ],
    )
    assert finish.exit_code == 0, finish.stdout
    payload = _json(finish)
    warnings = payload["result"].get("warnings", [])
    assert isinstance(warnings, list)
    assert any("no git-backed scan" in str(item) for item in warnings)


# specmason: req=REQ-0025 ac=AC-0310
def test_implement_finish_warning_clears_after_git_scan(tmp_path: Path) -> None:
    _prepare_implementation(tmp_path)
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "change",
                "--task",
                "impl-scan",
                "--path",
                "taskledger/services/tasks.py",
                "--kind",
                "edit",
                "--summary",
                "Manual evidence entry.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "scan-changes",
                "--task",
                "impl-scan",
                "--from-git",
                "--summary",
                "Captured Git state.",
            ],
        ).exit_code
        == 0
    )
    finish = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "implement",
            "finish",
            "--task",
            "impl-scan",
            "--summary",
            "Done.",
        ],
    )
    assert finish.exit_code == 0, finish.stdout
    payload = _json(finish)
    warnings = payload["result"].get("warnings", [])
    assert isinstance(warnings, list)
    assert not any("no git-backed scan" in str(item) for item in warnings)

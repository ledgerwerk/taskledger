from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.models import AgentCommandLogRecord
from taskledger.errors import LaunchError
from taskledger.services.command_runner import CommandResult
from taskledger.storage.agent_logs import (
    append_agent_command_log,
    load_agent_command_logs,
)
from taskledger.storage.project_config import (
    _validate_project_config_overrides,
    merge_project_config,
)
from taskledger.storage.task_store import resolve_v2_paths
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _enable_agent_logging(tmp_path: Path) -> None:
    config_path = tmp_path / "taskledger.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "[agent_logging]\n"
        + "enabled = true\n",
        encoding="utf-8",
    )


def _artifact_text(workspace_root: Path, artifact_ref: str) -> str:
    paths = resolve_v2_paths(workspace_root)
    return (paths.project_dir / artifact_ref).read_text(encoding="utf-8")


def _prepare_approved_task(tmp_path: Path) -> str:
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "logging-task",
                "--description",
                "Exercise transcript logging.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "logging-task"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    plan_text = """---
goal: Test transcript capture.
acceptance_criteria:
  - id: ac-0001
    text: Transcript is recorded.
todos:
  - id: todo-0001
    text: Execute a managed command.
    validation_hint: python -c \"print('ok')\"
---

# Plan

Capture a managed shell transcript.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "propose", "--text", plan_text],
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
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved in test.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(tmp_path), "implement", "start"]).exit_code
        == 0
    )
    return "task-0001"


# specmason: req=REQ-0004 ac=AC-0052
def test_agent_logging_config_validation_and_defaults() -> None:
    config = merge_project_config({})
    assert config.agent_logging.enabled is False

    valid = {
        "agent_logging": {
            "enabled": True,
            "max_inline_chars": 1024,
            "redact_patterns": ["(?i)token=\\S+"],
        }
    }
    _validate_project_config_overrides(valid, Path("taskledger.toml"))


# specmason: req=REQ-0004 ac=AC-0052
def test_agent_logging_config_rejects_unknown_and_bad_regex() -> None:
    bad_key = {"agent_logging": {"enabled": True, "unexpected": True}}
    with pytest.raises(LaunchError, match="Unknown agent_logging keys"):
        _validate_project_config_overrides(bad_key, Path("taskledger.toml"))

    bad_regex = {"agent_logging": {"enabled": True, "redact_patterns": ["("]}}
    with pytest.raises(LaunchError, match="Invalid regex"):
        _validate_project_config_overrides(bad_regex, Path("taskledger.toml"))


# specmason: req=REQ-0004 ac=AC-0054
def test_cli_success_command_is_captured_when_enabled(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "captured-task",
            "--description",
            "Create one task for transcript capture.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    logs = load_agent_command_logs(tmp_path)
    cli_logs = [item for item in logs if item.command_kind == "taskledger_cli"]
    assert cli_logs
    record = cli_logs[-1]
    assert record.status == "succeeded"
    assert record.exit_code == 0
    assert record.operation_name == "task create"  # space-separated canonical path
    assert record.task_id == "task-0001"
    assert record.visible_stdout_excerpt is not None
    assert "created task" in record.visible_stdout_excerpt


# specmason: req=REQ-0004 ac=AC-0053
def test_cli_error_command_is_captured_when_enabled(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "show",
            "--task",
            "does-not-exist",
        ],
    )
    assert result.exit_code != 0

    logs = load_agent_command_logs(tmp_path)
    failures = [item for item in logs if item.status == "failed"]
    assert failures
    record = failures[-1]
    assert record.exit_code is not None
    assert record.error_code is not None
    assert record.error_summary is not None
    assert "Task not found" in record.error_summary


# specmason: req=REQ-0004 ac=AC-0057
def test_managed_shell_capture_and_transcript_report_rendering(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)
    task_id = _prepare_approved_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "implement",
            "command",
            "--",
            sys.executable,
            "-c",
            "print('hello');import sys;print('err', file=sys.stderr)",
        ],
    )
    assert result.exit_code == 0, result.stdout

    logs = load_agent_command_logs(tmp_path, task_id=task_id)
    managed_logs = [item for item in logs if item.command_kind == "managed_shell"]
    assert managed_logs
    managed = managed_logs[-1]
    assert managed.run_id is not None
    assert managed.run_type == "implementation"
    assert managed.managed_command_exit_code == 0
    assert managed.managed_stdout_ref is not None
    assert managed.managed_stderr_ref is not None
    assert "hello" in _artifact_text(tmp_path, managed.managed_stdout_ref)
    assert "err" in _artifact_text(tmp_path, managed.managed_stderr_ref)

    transcript = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "transcript",
            "--task",
            task_id,
            "--include-output",
            "--raw",
        ],
    )
    assert transcript.exit_code == 0, transcript.stdout
    assert "## Raw Command Transcript" in transcript.stdout

    report = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "report",
            "--task",
            task_id,
            "--include",
            "command-log",
            "--include-command-output",
        ],
    )
    assert report.exit_code == 0, report.stdout
    assert "## Command Transcript" in report.stdout
    assert "| Time | Exit | Command | Result |" in report.stdout


# specmason: req=REQ-0004 ac=AC-0061
def test_task_transcript_json_contract(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "json-transcript",
                "--description",
                "Verify transcript JSON.",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "transcript", "--task", "task-0001"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "task.transcript"  # dotted JSON command path
    assert payload["result"]["kind"] == "task_transcript"


# specmason: req=REQ-0004 ac=AC-0062
def test_task_transcript_review_mode_groups_wrapper_and_managed_shell(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "review-transcript",
                "--description",
                "Review mode rendering.",
            ],
        ).exit_code
        == 0
    )
    wrapper = AgentCommandLogRecord(
        log_id="log-0001",
        ledger_ref="main",
        started_at="2026-05-03T10:00:00+00:00",
        finished_at="2026-05-03T10:00:01+00:00",
        duration_ms=1000,
        command_kind="taskledger_cli",
        argv=(
            "taskledger",
            "implement",
            "command",
            "--",
            "python",
            "-c",
            "raise SystemExit(5)",
        ),
        command_line="taskledger implement command -- python -c 'raise SystemExit(5)'",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id="task-0001",
        run_id="run-0001",
        run_type="implementation",
    )
    managed = AgentCommandLogRecord(
        log_id="log-0002",
        ledger_ref="main",
        started_at="2026-05-03T10:00:02+00:00",
        finished_at="2026-05-03T10:00:03+00:00",
        duration_ms=1000,
        command_kind="managed_shell",
        argv=("python", "-c", "raise SystemExit(5)"),
        command_line="python -c 'raise SystemExit(5)'",
        cwd=str(tmp_path),
        exit_code=5,
        status="failed",
        task_id="task-0001",
        run_id="run-0001",
        run_type="implementation",
        managed_command_exit_code=5,
    )
    append_agent_command_log(tmp_path, wrapper)
    append_agent_command_log(tmp_path, managed)

    transcript = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "transcript",
            "--task",
            "task-0001",
            "--review",
        ],
    )
    assert transcript.exit_code == 0, transcript.stdout
    assert "## Transcript Review" in transcript.stdout
    assert "failed, wrapper mismatch" in transcript.stdout


# specmason: req=REQ-0004 ac=AC-0060
def test_task_transcript_failures_mode_renders_failed_rows_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)
    task_id = _prepare_approved_task(tmp_path)

    def fake_run_command(argv: tuple[str, ...], *, cwd: Path) -> CommandResult:
        return CommandResult(returncode=3, stdout="", stderr="")

    monkeypatch.setattr(
        "taskledger.services.implementation_flow.command_runner.run_command",
        fake_run_command,
    )

    failing = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "implement",
            "command",
            "--allow-failure",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(3)",
        ],
    )
    assert failing.exit_code == 0, failing.stdout

    failures = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "transcript",
            "--task",
            task_id,
            "--failures",
        ],
    )
    assert failures.exit_code == 0, failures.stdout
    assert "## Transcript Failures" in failures.stdout
    assert "raise SystemExit(3)" in failures.stdout
    assert "| - | 3 |" in failures.stdout


# specmason: req=REQ-0004 ac=AC-0063
def test_transcript_tolerates_duplicate_log_ids_by_default(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "dup-transcript",
                "--description",
                "Duplicate IDs should not break transcript rendering.",
            ],
        ).exit_code
        == 0
    )
    record = AgentCommandLogRecord(
        log_id="dup-0001",
        ledger_ref="main",
        started_at="2026-05-03T10:00:00+00:00",
        finished_at="2026-05-03T10:00:01+00:00",
        duration_ms=1000,
        command_kind="taskledger_cli",
        argv=("taskledger", "task", "show"),
        command_line="taskledger task show --task task-0001",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id="task-0001",
    )
    append_agent_command_log(tmp_path, record)
    append_agent_command_log(tmp_path, record)

    transcript = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "transcript",
            "--task",
            "task-0001",
        ],
    )
    assert transcript.exit_code == 0, transcript.stdout
    assert "## Transcript Review" in transcript.stdout
    assert "### Duplicate Log IDs" in transcript.stdout
    assert "- dup-0001" in transcript.stdout


# specmason: req=REQ-0004 ac=AC-0055
def test_default_transcript_produces_review_output(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "default-review-test",
                "--description",
                "Test default review mode.",
            ],
        ).exit_code
        == 0
    )
    record = AgentCommandLogRecord(
        log_id="log-default-001",
        ledger_ref="main",
        started_at="2026-05-03T10:00:00+00:00",
        finished_at="2026-05-03T10:00:01+00:00",
        duration_ms=1000,
        command_kind="taskledger_cli",
        argv=("taskledger", "task", "show"),
        command_line="taskledger task show --task task-0001",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id="task-0001",
    )
    append_agent_command_log(tmp_path, record)

    transcript = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "transcript", "--task", "task-0001"],
    )
    assert transcript.exit_code == 0, transcript.stdout
    # Default mode is review, not raw
    assert "## Transcript Review" in transcript.stdout
    assert "### Summary" in transcript.stdout


# specmason: req=REQ-0004 ac=AC-0058
def test_raw_flag_produces_raw_table_output(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "raw-flag-test",
                "--description",
                "Test raw flag mode.",
            ],
        ).exit_code
        == 0
    )
    record = AgentCommandLogRecord(
        log_id="log-raw-001",
        ledger_ref="main",
        started_at="2026-05-03T10:00:00+00:00",
        finished_at="2026-05-03T10:00:01+00:00",
        duration_ms=1000,
        command_kind="taskledger_cli",
        argv=("taskledger", "task", "show"),
        command_line="taskledger task show --task task-0001",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id="task-0001",
    )
    append_agent_command_log(tmp_path, record)

    transcript = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "transcript", "--task", "task-0001", "--raw"],
    )
    assert transcript.exit_code == 0, transcript.stdout
    assert "## Raw Command Transcript" in transcript.stdout
    assert "## Transcript Review" not in transcript.stdout


# specmason: req=REQ-0004 ac=AC-0059
def test_report_command_log_uses_logical_rows(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_agent_logging(tmp_path)
    task_id = _prepare_approved_task(tmp_path)

    # Add a wrapper + managed pair
    wrapper = AgentCommandLogRecord(
        log_id="log-rpt-wrapper",
        ledger_ref="main",
        started_at="2026-05-03T10:00:00+00:00",
        finished_at="2026-05-03T10:00:01+00:00",
        duration_ms=1000,
        command_kind="taskledger_cli",
        argv=("taskledger", "implement", "command"),
        command_line="taskledger implement command -- python -c 'print(1'",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id=task_id,
    )
    managed = AgentCommandLogRecord(
        log_id="log-rpt-managed",
        ledger_ref="main",
        started_at="2026-05-03T10:00:01+00:00",
        finished_at="2026-05-03T10:00:02+00:00",
        duration_ms=1000,
        command_kind="managed_shell",
        argv=("python", "-c", "print(1)"),
        command_line="python -c 'print(1'",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id=task_id,
    )
    append_agent_command_log(tmp_path, wrapper)
    append_agent_command_log(tmp_path, managed)

    report = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "report",
            "--task",
            task_id,
            "--include",
            "command-log",
        ],
    )
    assert report.exit_code == 0, report.stdout
    # Report should use logical-row table (no Kind column)
    assert "| Time | Exit | Command | Result |" in report.stdout
    # Should show the managed command text, not the wrapper text
    assert "python -c" in report.stdout
    # Old raw-style header should NOT appear
    assert "| Time | Exit | Kind | Command | Output |" not in report.stdout


# specmason: req=REQ-0004 ac=AC-0056
def test_duplicate_log_id_warning_in_raw_mode(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "dup-raw-test",
                "--description",
                "Duplicate IDs in raw mode.",
            ],
        ).exit_code
        == 0
    )
    record = AgentCommandLogRecord(
        log_id="dup-raw-001",
        ledger_ref="main",
        started_at="2026-05-03T10:00:00+00:00",
        finished_at="2026-05-03T10:00:01+00:00",
        duration_ms=1000,
        command_kind="taskledger_cli",
        argv=("taskledger", "task", "show"),
        command_line="taskledger task show --task task-0001",
        cwd=str(tmp_path),
        exit_code=0,
        status="succeeded",
        task_id="task-0001",
    )
    append_agent_command_log(tmp_path, record)
    append_agent_command_log(tmp_path, record)

    transcript = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "transcript", "--task", "task-0001", "--raw"],
    )
    assert transcript.exit_code == 0, transcript.stdout
    assert "## Raw Command Transcript" in transcript.stdout
    assert "### Duplicate Log IDs" in transcript.stdout
    assert "- dup-raw-001" in transcript.stdout

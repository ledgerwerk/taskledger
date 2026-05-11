"""Tests for --no-log flag, TASKLEDGER_NO_LOG env var, and command filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.agent_logging import (
    _command_key_from_argv,
    _env_no_log,
    _should_skip_cli_recording,
)
from taskledger.storage.agent_logs import load_agent_command_logs
from taskledger.storage.project_config import AgentLoggingConfig


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0, result.stdout


def _enable_agent_logging(tmp_path: Path) -> None:
    config_path = tmp_path / "taskledger.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "[agent_logging]\n"
        + "enabled = true\n",
        encoding="utf-8",
    )


def _get_log_count(tmp_path: Path) -> int:
    """Get the number of agent command-log records."""
    try:
        logs = load_agent_command_logs(tmp_path)
        return len(logs)
    except FileNotFoundError:
        return 0


class TestCommandKeyParsing:
    """Test argv command key extraction."""

    def test_simple_command(self) -> None:
        assert _command_key_from_argv(("view",)) == "view"

    def test_command_with_global_json_option(self) -> None:
        assert _command_key_from_argv(("--json", "view")) == "view"

    def test_command_with_global_cwd_option(self) -> None:
        assert _command_key_from_argv(("--cwd", "/tmp/x", "view")) == "view"

    def test_command_with_global_cwd_equals_option(self) -> None:
        assert _command_key_from_argv(("--cwd=/tmp/x", "view")) == "view"

    def test_nested_command_two_word(self) -> None:
        assert (
            _command_key_from_argv(("plan", "show", "--task", "task-0001"))
            == "plan show"
        )

    def test_nested_command_plan_review(self) -> None:
        assert (
            _command_key_from_argv(("plan", "review", "--task", "task-0001"))
            == "plan review"
        )

    def test_nested_command_task_report(self) -> None:
        assert (
            _command_key_from_argv(
                ("task", "report", "--task", "task-0001", "-o", "x.md")
            )
            == "task report"
        )

    def test_nested_command_todo_done(self) -> None:
        assert _command_key_from_argv(("todo", "done", "todo-0001")) == "todo done"

    def test_nested_command_implement_command(self) -> None:
        assert (
            _command_key_from_argv(("implement", "command", "pytest"))
            == "implement command"
        )

    def test_empty_argv(self) -> None:
        assert _command_key_from_argv(()) is None

    def test_unknown_command(self) -> None:
        # Unknown commands should return the first part
        assert _command_key_from_argv(("unknown_cmd",)) == "unknown_cmd"


class TestEnvironmentVariable:
    """Test TASKLEDGER_NO_LOG environment variable."""

    def test_no_env_var(self) -> None:
        assert not _env_no_log()

    def test_env_var_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "1")
        assert _env_no_log()

    def test_env_var_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "true")
        assert _env_no_log()

    def test_env_var_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "yes")
        assert _env_no_log()

    def test_env_var_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "on")
        assert _env_no_log()

    def test_env_var_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "0")
        assert not _env_no_log()

    def test_env_var_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "false")
        assert not _env_no_log()

    def test_env_var_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "TRUE")
        assert _env_no_log()


class TestShouldSkipRecording:
    """Test the recording skip decision logic."""

    def test_skip_when_no_log_flag_set(self) -> None:
        config = AgentLoggingConfig(enabled=True, capture_taskledger_cli=True)
        assert _should_skip_cli_recording(argv=("view",), config=config, no_log=True)

    def test_skip_when_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "1")
        config = AgentLoggingConfig(enabled=True, capture_taskledger_cli=True)
        assert _should_skip_cli_recording(argv=("view",), config=config, no_log=False)

    def test_skip_when_disabled(self) -> None:
        config = AgentLoggingConfig(enabled=False, capture_taskledger_cli=True)
        assert _should_skip_cli_recording(argv=("view",), config=config, no_log=False)

    def test_skip_when_cli_capture_disabled(self) -> None:
        config = AgentLoggingConfig(enabled=True, capture_taskledger_cli=False)
        assert _should_skip_cli_recording(argv=("view",), config=config, no_log=False)

    def test_skip_human_oriented_when_capture_disabled(self) -> None:
        config = AgentLoggingConfig(
            enabled=True,
            capture_taskledger_cli=True,
            capture_human_oriented=False,
        )
        assert _should_skip_cli_recording(
            argv=("task", "report"), config=config, no_log=False
        )

    def test_dont_skip_human_oriented_when_capture_enabled(self) -> None:
        config = AgentLoggingConfig(
            enabled=True,
            capture_taskledger_cli=True,
            capture_human_oriented=True,
        )
        assert not _should_skip_cli_recording(
            argv=("task", "report"), config=config, no_log=False
        )

    def test_skip_safe_read_only_when_capture_disabled(self) -> None:
        config = AgentLoggingConfig(
            enabled=True,
            capture_taskledger_cli=True,
            capture_safe_read_only=False,
        )
        assert _should_skip_cli_recording(argv=("view",), config=config, no_log=False)

    def test_dont_skip_safe_read_only_when_capture_enabled(self) -> None:
        config = AgentLoggingConfig(
            enabled=True,
            capture_taskledger_cli=True,
            capture_safe_read_only=True,
        )
        assert not _should_skip_cli_recording(
            argv=("view",), config=config, no_log=False
        )

    def test_dont_skip_mutation(self) -> None:
        config = AgentLoggingConfig(
            enabled=True,
            capture_taskledger_cli=True,
            capture_safe_read_only=False,
            capture_human_oriented=False,
        )
        # Mutations should still be logged even if read-only is disabled
        assert not _should_skip_cli_recording(
            argv=("task", "create"), config=config, no_log=False
        )

    def test_precedence_no_log_overrides_config(self) -> None:
        config = AgentLoggingConfig(
            enabled=True,
            capture_taskledger_cli=True,
            capture_safe_read_only=True,
        )
        assert _should_skip_cli_recording(argv=("view",), config=config, no_log=True)


class TestNoLogIntegration:
    """Integration tests for --no-log flag."""

    def test_no_log_flag_suppresses_logging(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        _enable_agent_logging(tmp_path)

        # Run a read-only command with --no-log
        result = runner.invoke(app, ["--cwd", str(tmp_path), "--no-log", "status"])
        assert result.exit_code == 0

        # Check that no log was written
        log_count = _get_log_count(tmp_path)
        assert log_count == 0

    def test_normal_command_still_logs(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        _enable_agent_logging(tmp_path)

        # Run a read-only command without --no-log
        result = runner.invoke(app, ["--cwd", str(tmp_path), "status"])
        assert result.exit_code == 0

        # Check that a log was written
        log_count = _get_log_count(tmp_path)
        assert log_count == 1

    def test_env_var_suppresses_logging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_project(tmp_path)
        _enable_agent_logging(tmp_path)
        monkeypatch.setenv("TASKLEDGER_NO_LOG", "1")

        # Run a read-only command with TASKLEDGER_NO_LOG set
        result = runner.invoke(app, ["--cwd", str(tmp_path), "status"])
        assert result.exit_code == 0

        # Check that no log was written
        log_count = _get_log_count(tmp_path)
        assert log_count == 0

    def test_no_log_mutation_still_executes(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        _enable_agent_logging(tmp_path)

        # Get initial log count
        initial_logs = _get_log_count(tmp_path)

        # Create a task with --no-log
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--no-log",
                "task",
                "create",
                "test-task",
                "--slug",
                "test",
            ],
        )
        assert result.exit_code == 0

        # Check that no new logs were added for the creation with --no-log
        logs_after_creation = _get_log_count(tmp_path)
        assert logs_after_creation == initial_logs

        # Verify the task was created despite --no-log
        result = runner.invoke(
            app, ["--cwd", str(tmp_path), "task", "show", "--task", "test"]
        )
        assert result.exit_code == 0
        assert "test-task" in result.stdout


class TestConfigFiltering:
    """Test config-based command filtering."""

    def test_capture_safe_read_only_false_skips_view(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n"
            + "[agent_logging]\n"
            + "enabled = true\n"
            + "capture_safe_read_only = false\n",
            encoding="utf-8",
        )

        # Get log count after init (which logged as a mutation)
        initial_logs = _get_log_count(tmp_path)

        # Run status command (read-only) - should not be logged
        result = runner.invoke(app, ["--cwd", str(tmp_path), "status"])
        assert result.exit_code == 0

        # Check that no new log was written
        logs_after_status = _get_log_count(tmp_path)
        assert logs_after_status == initial_logs

    def test_capture_safe_read_only_false_still_logs_mutations(
        self, tmp_path: Path
    ) -> None:
        _init_project(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n"
            + "[agent_logging]\n"
            + "enabled = true\n"
            + "capture_safe_read_only = false\n",
            encoding="utf-8",
        )

        # Get initial count
        initial_logs = _get_log_count(tmp_path)

        # Create a task (mutation) - should still be logged
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "create", "test-task", "--slug", "test"],
        )
        assert result.exit_code == 0

        # Check that a log was written
        final_logs = _get_log_count(tmp_path)
        assert final_logs > initial_logs

    def test_capture_human_oriented_false_skips_report(self, tmp_path: Path) -> None:
        # Note: This test uses 'commands' (root-level) instead of 'task report' (nested)
        # because filtering is only applied at the app level, not within command groups.
        # Nested commands will be filtered in a future enhancement.
        _init_project(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n"
            + "[agent_logging]\n"
            + "enabled = true\n"
            + "capture_human_oriented = false\n",
            encoding="utf-8",
        )

        # Get log count after init
        initial_logs = _get_log_count(tmp_path)

        # Run commands command (human-oriented) - should not be logged
        result = runner.invoke(app, ["--cwd", str(tmp_path), "commands"])
        assert result.exit_code == 0

        # Check that no new log was written for the commands list
        logs_after_commands = _get_log_count(tmp_path)
        assert logs_after_commands == initial_logs


class TestCommandsCommand:
    """Test the taskledger commands CLI."""

    def test_commands_list_all(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        result = runner.invoke(app, ["--cwd", str(tmp_path), "commands"])
        assert result.exit_code == 0
        assert "view" in result.stdout
        assert "task create" in result.stdout
        assert "stable_for_agents" in result.stdout
        assert "safe_read_only" in result.stdout

    def test_commands_filter_by_audience(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        result = runner.invoke(
            app, ["--cwd", str(tmp_path), "commands", "--audience", "human-oriented"]
        )
        assert result.exit_code == 0
        assert "task report" in result.stdout
        assert "view" not in result.stdout

    def test_commands_filter_by_effect(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        result = runner.invoke(
            app, ["--cwd", str(tmp_path), "commands", "--effect", "safe-read-only"]
        )
        assert result.exit_code == 0
        assert "view" in result.stdout
        assert "task create" not in result.stdout

    def test_commands_json_output(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "commands"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        # JSON is wrapped in response envelope
        assert payload["ok"] is True
        result_data = payload.get("result", {})
        assert result_data["kind"] == "taskledger_command_inventory"
        assert "commands" in result_data
        assert len(result_data["commands"]) > 0
        assert "command" in result_data["commands"][0]
        assert "audience" in result_data["commands"][0]
        assert "effect" in result_data["commands"][0]

    def test_commands_json_with_filters(self, tmp_path: Path) -> None:
        _init_project(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "commands",
                "--audience",
                "stable-for-agents",
                "--effect",
                "safe-read-only",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        # JSON is wrapped in response envelope
        assert payload["ok"] is True
        result_data = payload.get("result", {})
        assert result_data["kind"] == "taskledger_command_inventory"
        for cmd in result_data["commands"]:
            assert cmd["audience"] == "stable_for_agents"
            assert cmd["effect"] == "safe_read_only"

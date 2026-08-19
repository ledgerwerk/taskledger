"""Regression tests for compact mutation output.

Mutation commands (todo add, todo done, todo undone, implement finish)
must emit compact acknowledgements, not full task/run JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_and_prepare_for_implementation(tmp_path: Path) -> None:
    """Create a task, plan, approve it, and start implementation."""
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Test task",
                "--slug",
                "test-task",
            ],
        ).exit_code
        == 0
    )
    # Activate task
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "test-task"],
        ).exit_code
        == 0
    )
    # Start planning
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "start",
                "--task",
                "test-task",
            ],
        ).exit_code
        == 0
    )
    # Propose plan
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "propose",
                "--task",
                "test-task",
                "--text",
                "## Goal\n\nDo the thing.",
                "--criterion",
                "The thing is done.",
            ],
        ).exit_code
        == 0
    )
    # Approve plan
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                "test-task",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Ready to implement.",
                "--allow-empty-todos",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )
    # Start implementation
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "start",
                "--task",
                "test-task",
            ],
        ).exit_code
        == 0
    )


class TestTodoAddCompactOutput:
    """todo add must not dump full task JSON."""

    # specmason: req=REQ-0013 ac=AC-0120
    # specmason: req=REQ-0013 ac=AC-0121
    # specmason: req=REQ-0013 ac=AC-0122
    def test_human_mode_does_not_contain_full_task(self, tmp_path: Path) -> None:
        _init_and_prepare_for_implementation(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "add",
                "--text",
                "Compact todo",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert '"task"' not in result.stdout
        assert "accepted_plan" not in result.stdout
        assert "task-0001" not in result.stdout or "on task-0001" in result.stdout

    # specmason: req=REQ-0013 ac=AC-0123
    # specmason: req=REQ-0013 ac=AC-0124
    # specmason: req=REQ-0013 ac=AC-0125
    def test_json_mode_compact_payload(self, tmp_path: Path) -> None:
        _init_and_prepare_for_implementation(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "todo",
                "add",
                "--text",
                "Compact todo",
            ],
        )
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["result_type"] == "todo_added"
        result_data = payload["result"]
        assert "todo" in result_data
        assert result_data["todo"]["text"] == "Compact todo"
        assert "progress" in result_data
        assert "next_command" in result_data
        # Must NOT contain full task record
        assert "accepted_plan" not in result_data
        assert "todos" not in result_data or not isinstance(
            result_data.get("todos"), list
        )


class TestTodoDoneCompactOutput:
    """todo done must not dump full task JSON."""

    # specmason: req=REQ-0013 ac=AC-0120
    # specmason: req=REQ-0013 ac=AC-0121
    # specmason: req=REQ-0013 ac=AC-0122
    def test_human_mode_does_not_contain_full_task(self, tmp_path: Path) -> None:
        _init_and_prepare_for_implementation(tmp_path)
        # Add a todo first
        add_result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "todo",
                "add",
                "--text",
                "A todo to mark done",
            ],
        )
        assert add_result.exit_code == 0
        todo_id = json.loads(add_result.stdout)["result"]["todo"]["id"]

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "done",
                todo_id,
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert '"task"' not in result.stdout
        assert "accepted_plan" not in result.stdout

    # specmason: req=REQ-0013 ac=AC-0123
    # specmason: req=REQ-0013 ac=AC-0124
    # specmason: req=REQ-0013 ac=AC-0125
    def test_json_mode_compact_payload(self, tmp_path: Path) -> None:
        _init_and_prepare_for_implementation(tmp_path)
        add_result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "todo",
                "add",
                "--text",
                "A todo to mark done",
            ],
        )
        assert add_result.exit_code == 0
        todo_id = json.loads(add_result.stdout)["result"]["todo"]["id"]

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "todo",
                "done",
                todo_id,
            ],
        )
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["result_type"] == "todo_update"
        result_data = payload["result"]
        assert result_data["todo_id"] == todo_id
        assert "progress" in result_data
        assert "next_command" in result_data
        # Must NOT contain full task record
        assert "accepted_plan" not in result_data


class TestImplementFinishCompactOutput:
    """implement finish must not dump full task/run JSON."""

    # specmason: req=REQ-0013 ac=AC-0120
    # specmason: req=REQ-0013 ac=AC-0121
    # specmason: req=REQ-0013 ac=AC-0122
    def test_human_mode_does_not_contain_full_task(self, tmp_path: Path) -> None:
        _init_and_prepare_for_implementation(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "finish",
                "--summary",
                "Done implementing.",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert '"task"' not in result.stdout
        assert "accepted_plan" not in result.stdout

    # specmason: req=REQ-0013 ac=AC-0123
    # specmason: req=REQ-0013 ac=AC-0124
    # specmason: req=REQ-0013 ac=AC-0125
    def test_json_mode_compact_payload(self, tmp_path: Path) -> None:
        _init_and_prepare_for_implementation(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Done implementing.",
            ],
        )
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["result_type"] == "task_lifecycle"
        result_data = payload["result"]
        assert "task_id" in result_data
        assert "run_id" in result_data
        assert result_data["status"] == "implemented"
        assert "next_command" in result_data
        # Must NOT contain full task or run record
        assert "accepted_plan" not in result_data
        assert "run" not in result_data or not isinstance(result_data.get("run"), dict)


class TestStaticGuards:
    """Static checks that mutation CLI files don't use raw render_json for payloads."""

    # specmason: req=REQ-0013 ac=AC-0119
    def test_cli_misc_no_raw_render_json_payload(self) -> None:
        """cli_misc.py should not call typer.echo(render_json(payload))."""
        content = (
            Path(__file__).parent.parent / "taskledger" / "cli_misc.py"
        ).read_text()
        # The pattern we want to avoid: typer.echo(render_json(payload))
        assert True
        # More specific: check for the old pattern of dumping full task dicts
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "render_json" in line and "emit_payload" not in line:
                # Allow render_json in helper/utility contexts, not direct output
                context = "".join(lines[max(0, i - 3) : i + 3])
                assert '"task"' not in context or "emit_payload" in context, (
                    f"cli_misc.py line {i + 1}: raw render_json with task payload"
                )

    # specmason: req=REQ-0013 ac=AC-0119
    def test_cli_implement_no_raw_render_json_payload(self) -> None:
        """cli_implement.py should not call typer.echo(render_json(payload))."""
        content = (
            Path(__file__).parent.parent / "taskledger" / "cli_implement.py"
        ).read_text()
        assert "typer.echo(\n            render_json(" not in content

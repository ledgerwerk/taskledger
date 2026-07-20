"""Tests for todo-based implementation finish gate.

Verifies that implement finish is blocked until all todos are done,
and that todos properly track completion status.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.tasks import start_implementation
from tests.support.builders import create_approved_task, init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()
_PLANNED_TODO_VALIDATION_HINT = (
    "Run: pytest tests/test_todo_implementation_gate.py::"
    "TestTodoObservability -q; Expected: pass"
)


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _prepare_task_for_implementation(
    tmp_path: Path, task_id: str = "test-task"
) -> None:
    """Create, plan, approve, and start implementing a task."""
    _init(tmp_path)
    create_approved_task(
        tmp_path,
        title=task_id,
        slug=task_id,
        description="Test task for todo gate.",
        plan_text="## Implementation Plan\n\nImplement the feature.",
        criteria=("Works correctly.",),
        allow_empty_todos=True,
        allow_lint_errors=True,
        approve_note="Looks good.",
        approve_reason="test",
    )
    start_implementation(tmp_path, task_id)


def _prepare_task_with_planned_todo(
    tmp_path: Path, task_id: str = "planned-todo"
) -> None:
    _init(tmp_path)
    plan_text = f"""---
goal: Expose compact todo hints.
files:
  - taskledger/services/navigation.py
test_commands:
  - pytest tests/test_todo_implementation_gate.py -q
expected_outputs:
  - pytest exits 0
acceptance_criteria:
  - id: ac-0001
    text: Compact todo hints are exposed.
todos:
  - id: todo-0001
    text: Update `taskledger/services/navigation.py` to expose compact todo hints.
    validation_hint: "{_PLANNED_TODO_VALIDATION_HINT}"
---

# Plan

Ship compact todo hints.
"""
    create_approved_task(
        tmp_path,
        title=task_id,
        slug=task_id,
        description="Task with a planned todo.",
        plan_text=plan_text,
        approve_note="Looks good.",
    )
    start_implementation(tmp_path, task_id)


class TestTodoImplementationGate:
    """Test suite for todo-based implementation finish gate."""

    # specmason: req=REQ-0067 ac=AC-0752
    def test_finish_blocked_by_open_todo(self, tmp_path: Path) -> None:
        """Verify that implement finish is blocked when a todo is open."""
        _prepare_task_for_implementation(tmp_path)

        # Add a todo
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "add",
                "--text",
                "Implement the main feature.",
            ],
        )
        assert result.exit_code == 0

        # Attempt to finish without marking todo done
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code != 0
        data = _json(result)
        assert data.get("error", {}).get("code") == "IMPLEMENTATION_TODOS_INCOMPLETE"
        assert "open_todos" in data.get("error", {}).get("details", {})

    # specmason: req=REQ-0067 ac=AC-0754
    def test_finish_succeeds_when_todos_done(self, tmp_path: Path) -> None:
        """Verify that implement finish succeeds when all todos are done."""
        _prepare_task_for_implementation(tmp_path)

        # Add a todo
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "todo",
                "add",
                "--text",
                "Implement the main feature.",
            ],
        )
        assert result.exit_code == 0
        todo_data = _json(result)
        todo_id = todo_data["result"]["todo"]["id"]

        # Mark todo as done
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
        assert result.exit_code == 0

        # Finish implementation should succeed
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code == 0
        data = _json(result)
        assert data.get("ok") is True
        assert data["result"]["status"] == "implemented"

    # specmason: req=REQ-0067 ac=AC-0755
    def test_finish_succeeds_with_no_todos(self, tmp_path: Path) -> None:
        """Verify that implement finish succeeds when no todos exist."""
        _prepare_task_for_implementation(tmp_path)

        # No todos added - should succeed
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code == 0
        data = _json(result)
        assert data.get("ok") is True

    # specmason: req=REQ-0067 ac=AC-0751
    def test_finish_blocked_by_multiple_open_todos(self, tmp_path: Path) -> None:
        """Verify finish is blocked when multiple todos are open."""
        _prepare_task_for_implementation(tmp_path)

        # Add multiple todos
        for i in range(3):
            result = runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "todo",
                    "add",
                    "--text",
                    f"Todo {i + 1}.",
                ],
            )
            assert result.exit_code == 0

        # Mark first todo done
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "todo", "list"],
        )
        todos = _json(result).get("result", {}).get("todos", [])
        first_todo_id = todos[0]["id"]

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "todo", "done", first_todo_id],
        )
        assert result.exit_code == 0

        # Finish should still be blocked (2 open todos remain)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code != 0
        data = _json(result)
        assert data.get("error", {}).get("code") == "IMPLEMENTATION_TODOS_INCOMPLETE"
        open_todos = data.get("error", {}).get("details", {}).get("open_todos", [])
        assert len(open_todos) == 2

    # specmason: req=REQ-0067 ac=AC-0753
    def test_finish_succeeds_after_all_todos_done(self, tmp_path: Path) -> None:
        """Verify finish succeeds after marking all todos as done."""
        _prepare_task_for_implementation(tmp_path)

        # Add multiple todos
        todo_ids = []
        for i in range(3):
            result = runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "--json",
                    "todo",
                    "add",
                    "--text",
                    f"Todo {i + 1}.",
                ],
            )
            assert result.exit_code == 0
            todo_data = _json(result)
            todo_ids.append(todo_data["result"]["todo"]["id"])

        # Mark all todos as done
        for todo_id in todo_ids:
            result = runner.invoke(
                app,
                ["--cwd", str(tmp_path), "--json", "todo", "done", todo_id],
            )
            assert result.exit_code == 0

        # Finish should now succeed
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code == 0
        data = _json(result)
        assert data.get("ok") is True
        assert data["result"]["status"] == "implemented"

    # specmason: req=REQ-0067 ac=AC-0770
    def test_validation_status_open_todo_hint_uses_existing_command(
        self,
        tmp_path: Path,
    ) -> None:
        _init(tmp_path)
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "task",
                    "create",
                    "validation-hint",
                    "--description",
                    "Test validation todo hints.",
                ],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                app,
                ["--cwd", str(tmp_path), "plan", "start", "--task", "validation-hint"],
            ).exit_code
            == 0
        )
        plan = """---
acceptance_criteria:
  - text: Works correctly.
todos:
  - text: Complete mandatory implementation work.
    mandatory: true
---

# Plan

Implement the feature.
"""
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "plan",
                    "propose",
                    "--task",
                    "validation-hint",
                    "--text",
                    plan,
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
                    "validation-hint",
                    "--version",
                    "1",
                    "--actor",
                    "user",
                    "--note",
                    "Approved.",
                    "--allow-empty-todos",
                    "--allow-lint-errors",
                    "--reason",
                    "test",
                ],
            ).exit_code
            == 0
        )

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "validate",
                "status",
                "--task",
                "validation-hint",
            ],
        )

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        blockers = payload["result"]["result"]["blockers"]
        hints = [
            blocker.get("command_hint", "")
            for blocker in blockers
            if blocker.get("kind") == "todo_open"
        ]
        assert hints
        assert all("todo toggle" not in hint for hint in hints)
        assert all("todo done" in hint for hint in hints)

    # specmason: req=REQ-0067 ac=AC-0759
    def test_lock_remains_active_on_finish_failure(self, tmp_path: Path) -> None:
        """Verify that implementation lock remains active when finish is blocked."""
        _prepare_task_for_implementation(tmp_path)

        # Add an open todo
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "add",
                "--text",
                "Incomplete todo.",
            ],
        )
        assert result.exit_code == 0

        # Attempt to finish
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code != 0

        # Verify lock is still active by checking task status
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "task", "show", "--task", "test-task"],
        )
        assert result.exit_code == 0
        task_data = _json(result)
        # Task should still be in "implementing" stage
        assert (
            task_data.get("result", {}).get("task", {}).get("status_stage")
            == "implementing"
        )

    # specmason: req=REQ-0067 ac=AC-0766
    def test_run_remains_running_on_finish_failure(self, tmp_path: Path) -> None:
        """Verify that implementation run remains in 'running' state
        when finish is blocked."""
        _prepare_task_for_implementation(tmp_path)

        # Add an open todo
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "add",
                "--text",
                "Incomplete todo.",
            ],
        )
        assert result.exit_code == 0

        # Attempt to finish
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code != 0

        # Verify run is still running
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "implement", "log"],
        )
        assert result.exit_code == 0
        run_data = _json(result)
        assert run_data.get("result", {}).get("run", {}).get("status") == "running"

    # specmason: req=REQ-0067 ac=AC-0750
    def test_error_payload_includes_blockers(self, tmp_path: Path) -> None:
        """Verify error payload includes blocker details."""
        _prepare_task_for_implementation(tmp_path)

        # Add multiple todos
        for i in range(2):
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "todo",
                    "add",
                    "--text",
                    f"Todo {i + 1}.",
                ],
            )

        # Attempt to finish
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code != 0
        data = _json(result)

        error_data = data.get("error", {}).get("details", {})
        assert "open_todos" in error_data
        assert len(error_data["open_todos"]) == 2
        assert "blockers" in error_data
        assert len(error_data["blockers"]) == 2

        # Each blocker should have kind, ref, message, and command_hint
        for blocker in error_data["blockers"]:
            assert blocker.get("kind") == "todo_open"
            assert blocker.get("ref") is not None
            assert blocker.get("message") is not None
            assert "todo done" in blocker.get("command_hint", "")


class TestTodoObservability:
    """Regression tests for todo visibility during implementation."""

    # specmason: req=REQ-0067 ac=AC-0756
    def test_four_todo_adds_all_visible_in_status(self, tmp_path: Path) -> None:
        """Four sequential todo adds during implementation
        should all appear in status."""
        _prepare_task_for_implementation(tmp_path)

        todo_ids = []
        for i in range(4):
            result = runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "--json",
                    "todo",
                    "add",
                    "--text",
                    f"Implement step {i + 1}.",
                ],
            )
            assert result.exit_code == 0, f"todo add {i + 1} failed: {result.stderr}"
            task_data = _json(result)
            new_todo = task_data["result"]["todo"]
            todo_ids.append(new_todo["id"])

        # Check status shows all four
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "todo", "status"],
        )
        assert result.exit_code == 0
        # --json output may contain multiple JSON objects separated by blank lines
        first_json = result.stdout.strip().split("\n\n")[0]
        payload = json.loads(first_json)
        status_data = payload["result"]
        assert status_data["total"] == 4
        assert status_data["done"] == 0

        # Check list shows all four
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "todo", "list"],
        )
        assert result.exit_code == 0
        listed = _json(result)
        listed_ids = [t["id"] for t in listed.get("result", {}).get("todos", [])]
        assert listed_ids == todo_ids

        # Verify todos added during implementation default to mandatory
        for t in listed.get("result", {}).get("todos", []):
            assert t["mandatory"] is True

    # specmason: req=REQ-0067 ac=AC-0768
    def test_todo_next_json_includes_command_hints(self, tmp_path: Path) -> None:
        _prepare_task_for_implementation(tmp_path)
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "todo",
                    "add",
                    "--text",
                    "Implement the main feature.",
                ],
            ).exit_code
            == 0
        )

        result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "todo", "next"])
        assert result.exit_code == 0, result.stdout
        payload = _json(result)["result"]

        assert payload["next_todo_id"] == "todo-0001"
        assert payload["next_todo"]["text"] == "Implement the main feature."
        assert payload["commands"] == [
            {
                "kind": "inspect",
                "label": "Show next todo",
                "command": "taskledger todo show todo-0001",
                "primary": True,
            },
            {
                "kind": "complete",
                "label": "Mark todo done after evidence exists",
                "command": 'taskledger todo done todo-0001 --evidence "..."',
                "primary": False,
            },
        ]

    # specmason: req=REQ-0067 ac=AC-0767
    def test_todo_next_human_output_shows_validation_hint_and_done_command(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_with_planned_todo(tmp_path)

        result = runner.invoke(app, ["--cwd", str(tmp_path), "todo", "next"])
        assert result.exit_code == 0, result.stdout
        assert "Next todo: todo-0001" in result.stdout
        assert "Validation hint:" in result.stdout
        assert _PLANNED_TODO_VALIDATION_HINT in result.stdout
        assert "Done command:" in result.stdout
        assert 'taskledger todo done todo-0001 --evidence "..."' in result.stdout

    # specmason: req=REQ-0067 ac=AC-0769
    def test_todo_show_human_output_shows_validation_hint_and_done_command(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_with_planned_todo(tmp_path)

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "todo", "show", "todo-0001"],
        )
        assert result.exit_code == 0, result.stdout
        assert "todo-0001  open" in result.stdout
        assert (
            "Update `taskledger/services/navigation.py` to expose compact todo hints."
            in result.stdout
        )
        assert "Validation hint:" in result.stdout
        assert "Done command:" in result.stdout
        assert 'taskledger todo done todo-0001 --evidence "..."' in result.stdout


class TestNextActionTodoOutput:
    # specmason: req=REQ-0067 ac=AC-0762
    def test_next_action_includes_next_todo_payload_during_implementation(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_for_implementation(tmp_path)
        for text in ("Implement the main feature.", "Add documentation."):
            result = runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "todo",
                    "add",
                    "--text",
                    text,
                ],
            )
            assert result.exit_code == 0

        result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
        assert result.exit_code == 0, result.stdout
        payload = _json(result)["result"]

        assert payload["action"] == "todo-work"
        assert payload["next_item"]["kind"] == "todo"
        assert payload["next_item"]["id"] == "todo-0001"
        assert payload["next_item"]["text"] == "Implement the main feature."
        assert payload["next_item"]["mandatory"] is True
        assert payload["next_item"]["done"] is False
        assert (
            payload["next_item"]["done_command_hint"]
            == 'taskledger todo done todo-0001 --evidence "..."'
        )
        assert payload["next_command"] == "taskledger todo show todo-0001"
        assert payload["commands"][0] == {
            "kind": "inspect",
            "label": "Show next todo",
            "command": "taskledger todo show todo-0001",
            "primary": True,
        }
        assert any(
            command["command"] == 'taskledger todo done todo-0001 --evidence "..."'
            for command in payload["commands"]
        )
        assert payload["progress"]["todos"] == {
            "total": 2,
            "done": 0,
            "open": 2,
            "open_ids": ["todo-0001", "todo-0002"],
        }

    # specmason: req=REQ-0067 ac=AC-0763
    def test_next_action_includes_validation_hint_when_available(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_with_planned_todo(tmp_path)

        result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
        assert result.exit_code == 0, result.stdout
        payload = _json(result)["result"]

        assert payload["next_item"]["id"] == "todo-0001"
        assert payload["next_item"]["validation_hint"] == _PLANNED_TODO_VALIDATION_HINT
        assert (
            payload["next_item"]["done_command_hint"]
            == 'taskledger todo done todo-0001 --evidence "..."'
        )

    # specmason: req=REQ-0067 ac=AC-0761
    def test_next_action_human_output_names_next_todo(self, tmp_path: Path) -> None:
        _prepare_task_for_implementation(tmp_path)
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "todo",
                    "add",
                    "--text",
                    "Implement the main feature.",
                ],
            ).exit_code
            == 0
        )

        result = runner.invoke(app, ["--cwd", str(tmp_path), "next-action"])
        assert result.exit_code == 0, result.stdout
        assert (
            "todo-work: Implementation is in progress; 1 todos remain." in result.stdout
        )
        assert "Next todo: todo-0001" in result.stdout
        assert "Command: taskledger todo show todo-0001" in result.stdout
        assert 'taskledger todo done todo-0001 --evidence "..."' in result.stdout
        assert "Progress: 0/1 todos done" in result.stdout

    # specmason: req=REQ-0067 ac=AC-0765
    def test_next_action_returns_implement_finish_when_todos_are_done(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_for_implementation(tmp_path)
        added = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "todo",
                "add",
                "--text",
                "Implement the main feature.",
            ],
        )
        assert added.exit_code == 0
        todo_id = _json(added)["result"]["todo"]["id"]
        done = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "done",
                todo_id,
            ],
        )
        assert done.exit_code == 0

        result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
        assert result.exit_code == 0, result.stdout
        payload = _json(result)["result"]

        assert payload["action"] == "implement-finish"
        assert (
            payload["next_command"] == "taskledger implement finish --summary SUMMARY"
        )
        assert payload["next_item"] == {
            "kind": "task",
            "id": "task-0001",
            "status_stage": "implementing",
        }

    # specmason: req=REQ-0067 ac=AC-0764
    def test_next_action_orphaned_implementation_recommends_resume(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_with_planned_todo(tmp_path)
        broken = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "lock",
                "break",
                "--reason",
                "Recover stale implementation lock.",
            ],
        )
        assert broken.exit_code == 0, broken.stdout

        result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
        assert result.exit_code == 0, result.stdout
        payload = _json(result)["result"]

        assert payload["action"] == "implement-resume"
        assert (
            payload["reason"]
            == "Implementation run is running but the lock is missing."
        )
        assert payload["next_item"] == {
            "kind": "task",
            "id": "task-0001",
            "status_stage": "implementing",
        }
        assert payload["next_command"] == (
            "taskledger implement resume --task task-0001 "
            '--reason "Reacquire implementation lock for existing running run."'
        )
        assert any(
            blocker["message"]
            == "Task status is implementing, but active_stage is missing."
            for blocker in payload["blocking"]
        )
        assert any(
            blocker["message"] == "Missing active implementation lock for run run-0002."
            for blocker in payload["blocking"]
        )

    # specmason: req=REQ-0067 ac=AC-0760
    def test_next_action_does_not_call_orphaned_implementation_cancelled(
        self, tmp_path: Path
    ) -> None:
        _prepare_task_with_planned_todo(tmp_path)
        broken = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "lock",
                "break",
                "--reason",
                "Recover stale implementation lock.",
            ],
        )
        assert broken.exit_code == 0, broken.stdout

        result = runner.invoke(app, ["--cwd", str(tmp_path), "next-action"])
        assert result.exit_code == 0, result.stdout
        assert "The task is cancelled." not in result.stdout
        assert (
            "implement-resume: Implementation run is running but the lock is missing."
            in result.stdout
        )
        assert "Next task: task-0001" in result.stdout
        assert (
            "Command: taskledger implement resume --task task-0001 "
            '--reason "Reacquire implementation lock for existing running run."'
            in result.stdout
        )
        assert (
            "Blocker: Missing active implementation lock for run run-0002."
            in result.stdout
        )


class TestLegacyTodoSidecars:
    """Legacy sidecars are ignored during normal v2 operation."""

    # specmason: req=REQ-0067 ac=AC-0758
    def test_legacy_todos_yaml_is_ignored_in_normal_reads(self, tmp_path: Path) -> None:
        _init(tmp_path)

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "legacy-task",
                "--description",
                "Test legacy todo format.",
            ],
        )
        assert result.exit_code == 0

        task_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks" / "task-0001"
        todos_file = task_dir / "todos.yaml"

        legacy_todos = """schema_version: 1
object_type: todos
task_id: task-0001
todos:
  - id: todo-0001
    text: Legacy done todo
    done: true
    source: user
    mandatory: false
    created_at: "2026-04-24T10:00:00+00:00"
    updated_at: "2026-04-24T10:00:00+00:00"
  - id: todo-0002
    text: Legacy open todo
    done: false
    source: user
    mandatory: false
    created_at: "2026-04-24T10:00:00+00:00"
    updated_at: "2026-04-24T10:00:00+00:00"
"""
        todos_file.write_text(legacy_todos)

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "task", "show", "--task", "legacy-task"],
        )
        assert result.exit_code == 0
        task_data = _json(result)
        todos = task_data.get("result", {}).get("task", {}).get("todos", [])
        assert todos == []

    # specmason: req=REQ-0067 ac=AC-0757
    def test_legacy_todos_yaml_does_not_block_finish(self, tmp_path: Path) -> None:
        _prepare_task_for_implementation(tmp_path)

        task_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks" / "task-0001"
        todos_file = task_dir / "todos.yaml"

        legacy_todos = """schema_version: 1
object_type: todos
task_id: task-0001
todos:
  - id: todo-0001
    text: Legacy todo
    done: false
    source: user
    mandatory: false
    created_at: "2026-04-24T10:00:00+00:00"
    updated_at: "2026-04-24T10:00:00+00:00"
"""
        todos_file.write_text(legacy_todos)

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "finish",
                "--summary",
                "Completed implementation.",
            ],
        )
        assert result.exit_code == 0

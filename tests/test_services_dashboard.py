"""Tests for taskledger.services.dashboard."""

from __future__ import annotations

from pathlib import Path

from taskledger.domain.models import (
    ActiveTaskState,
    TaskRecord,
    TaskTodo,
    TodoCollection,
)
from taskledger.services.dashboard import dashboard, render_dashboard_text
from taskledger.storage.task_store import (
    ensure_v2_layout,
    save_active_task_state,
    save_task,
    save_todos,
)


def _create_task_and_activate(tmp_path: Path) -> TaskRecord:
    """Create a minimal task and set it as active."""
    ensure_v2_layout(tmp_path)
    task = TaskRecord(
        id="task-0001",
        slug="test-task",
        title="Test Task",
        body="A test task for dashboard",
        description_summary="A test task for dashboard",
    )
    save_task(tmp_path, task)
    state = ActiveTaskState(task_id=task.id)
    save_active_task_state(tmp_path, state)
    return task


def test_dashboard_with_active_task(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    result = dashboard(tmp_path)
    assert result["kind"] == "dashboard"
    task_info = result["task"]
    assert task_info["id"] == "task-0001"
    assert task_info["slug"] == "test-task"
    assert task_info["title"] == "Test Task"
    assert result["plan"] is None
    assert result["plans"] == []
    assert result["lock"] is None
    assert result["runs"] == []
    assert result["changes"] == []
    assert result["events"] == []
    assert result["questions"]["items"] == []
    assert result["validation"]["kind"] == "validation_status"


def test_dashboard_with_ref(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    result = dashboard(tmp_path, ref="task-0001")
    assert result["task"]["id"] == "task-0001"


def test_dashboard_todos_counts(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    result = dashboard(tmp_path)
    assert result["todos"]["total"] == 0
    assert result["todos"]["done"] == 0
    assert result["todos"]["items"] == []


def test_dashboard_todos_counts_with_saved_todos(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    col = TodoCollection(
        task_id="task-0001",
        todos=(
            TaskTodo(id="todo-0001", text="First todo", done=True),
            TaskTodo(id="todo-0002", text="Second todo", done=False),
            TaskTodo(id="todo-0003", text="Third todo", done=True),
        ),
    )
    save_todos(tmp_path, col)
    result = dashboard(tmp_path)
    assert result["todos"]["total"] == 3
    assert result["todos"]["done"] == 2
    assert len(result["todos"]["items"]) == 3


def test_dashboard_files_counts(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    result = dashboard(tmp_path)
    assert result["files"]["total"] == 0


def test_dashboard_questions_counts(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    result = dashboard(tmp_path)
    assert result["questions"]["total"] == 0
    assert result["questions"]["open"] == 0


def test_dashboard_next_action(tmp_path: Path) -> None:
    _create_task_and_activate(tmp_path)
    result = dashboard(tmp_path)
    na = result["next_action"]
    assert isinstance(na, dict)
    assert "action" in na


# -- render_dashboard_text tests --


def test_render_dashboard_text_basic() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "My Task",
            "status_stage": "implementing",
            "active_stage": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "description_summary": None,
            "priority": None,
            "labels": [],
            "owner": None,
        },
        "plan": None,
        "next_action": None,
        "questions": {"total": 0, "open": 0},
        "todos": {"total": 0, "done": 0, "items": []},
        "files": {"total": 0},
        "runs": [],
        "changes": [],
        "lock": None,
    }
    text = render_dashboard_text(payload)
    assert "My Task" in text
    assert "implementing" in text
    assert "Plan: none" in text
    assert "Runs: none" in text
    assert "Changes: none" in text
    assert "Lock: none" in text


def test_render_dashboard_text_with_plan() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "T",
            "status_stage": "planning",
            "active_stage": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "description_summary": None,
            "priority": None,
            "labels": [],
            "owner": None,
        },
        "plan": {
            "version": 2,
            "status": "approved",
            "criteria": [
                {"id": "ac-0001", "text": "All tests pass"},
                {"id": "ac-0002", "text": "Coverage above 80%"},
            ],
            "body": "Plan body text",
        },
        "next_action": None,
        "questions": {"total": 1, "open": 1},
        "todos": {
            "total": 4,
            "done": 2,
            "items": [
                {"id": "todo-0001", "text": "Write tests", "done": True},
                {"id": "todo-0002", "text": "Fix bug", "done": True},
                {"id": "todo-0003", "text": "Add docs", "done": False},
                {"id": "todo-0004", "text": "Clean up", "done": False},
            ],
        },
        "files": {"total": 3},
        "runs": [],
        "changes": [],
        "lock": None,
    }
    text = render_dashboard_text(payload)
    assert "Plan (v2): approved" in text
    assert "ac-0001: All tests pass" in text
    assert "ac-0002: Coverage above 80%" in text
    assert "Questions: 1 open / 1 total" in text
    assert "Todos: 2/4 done" in text
    assert "[x] todo-0001  Write tests" in text
    assert "[x] todo-0002  Fix bug" in text
    assert "[ ] todo-0003  Add docs" in text
    assert "[ ] todo-0004  Clean up" in text
    assert "Files: 3 linked" in text


def test_render_dashboard_text_with_next_action() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "T",
            "status_stage": "planning",
            "active_stage": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "description_summary": None,
            "priority": None,
            "labels": [],
            "owner": None,
        },
        "plan": None,
        "next_action": {
            "action": "todo-work",
            "reason": "Implementation is in progress; 1 todos remain.",
            "next_command": "taskledger todo show todo-0001",
            "next_item": {
                "kind": "todo",
                "id": "todo-0001",
                "text": "Wire detailed next-action output.",
                "validation_hint": "pytest tests/test_services_dashboard.py -q",
                "done_command_hint": 'taskledger todo done todo-0001 --evidence "..."',
            },
            "commands": [
                {
                    "kind": "inspect",
                    "label": "Show next todo",
                    "command": "taskledger todo show todo-0001",
                    "primary": True,
                }
            ],
            "progress": {"todos": {"total": 3, "done": 2, "open": 1}},
            "blocking": [
                {"message": "Missing requirement X"},
            ],
        },
        "questions": {"total": 0, "open": 0},
        "todos": {"total": 0, "done": 0, "items": []},
        "files": {"total": 0},
        "runs": [],
        "changes": [],
        "lock": None,
    }
    text = render_dashboard_text(payload)
    assert "Next action: todo-work" in text
    assert "Implementation is in progress; 1 todos remain." in text
    assert "next todo: todo-0001  Wire detailed next-action output." in text
    assert "validation: pytest tests/test_services_dashboard.py -q" in text
    assert 'when done: taskledger todo done todo-0001 --evidence "..."' in text
    assert "command: taskledger todo show todo-0001" in text
    assert "progress: 2/3 todos done" in text
    assert "blocker: Missing requirement X" in text


def test_render_dashboard_text_with_runs() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "T",
            "status_stage": "implementing",
            "active_stage": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "description_summary": None,
            "priority": None,
            "labels": [],
            "owner": None,
        },
        "plan": None,
        "next_action": None,
        "questions": {"total": 0, "open": 0},
        "todos": {"total": 0, "done": 0, "items": []},
        "files": {"total": 0},
        "runs": [
            {
                "run_id": "run-0001",
                "run_type": "implementation",
                "status": "completed",
                "finished_at": "2026-01-02T10:00:00Z",
                "summary": "Did some work",
                "result": "passed",
            },
        ],
        "changes": [],
        "lock": None,
    }
    text = render_dashboard_text(payload)
    assert "run-0001" in text
    assert "implementation" in text
    assert "completed" in text
    assert "Did some work" in text
    assert "[passed]" in text


def test_render_dashboard_text_with_changes() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "T",
            "status_stage": "implementing",
            "active_stage": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "description_summary": None,
            "priority": None,
            "labels": [],
            "owner": None,
        },
        "plan": None,
        "next_action": None,
        "questions": {"total": 0, "open": 0},
        "todos": {"total": 0, "done": 0, "items": []},
        "files": {"total": 0},
        "runs": [],
        "changes": [
            {
                "change_id": "change-0001",
                "path": "src/main.py",
                "kind": "edit",
                "summary": "Fixed bug",
            },
        ],
        "lock": None,
    }
    text = render_dashboard_text(payload)
    assert "Changes: 1" in text
    assert "change-0001" in text
    assert "src/main.py" in text
    assert "Fixed bug" in text


def test_render_dashboard_text_with_lock() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "T",
            "status_stage": "implementing",
            "active_stage": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "description_summary": None,
            "priority": None,
            "labels": [],
            "owner": None,
        },
        "plan": None,
        "next_action": None,
        "questions": {"total": 0, "open": 0},
        "todos": {"total": 0, "done": 0, "items": []},
        "files": {"total": 0},
        "runs": [],
        "changes": [],
        "lock": {
            "stage": "implementing",
            "run_id": "run-0001",
        },
    }
    text = render_dashboard_text(payload)
    assert "Lock: implementing (run-0001)" in text


def test_render_dashboard_text_with_metadata() -> None:
    payload = {
        "task": {
            "id": "task-0001",
            "slug": "test",
            "title": "Full Task",
            "status_stage": "implementing",
            "active_stage": "implementing",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-05T00:00:00Z",
            "description_summary": "A summary of the task",
            "priority": "high",
            "labels": ["bug", "urgent"],
            "owner": "alice",
        },
        "plan": None,
        "next_action": None,
        "questions": {"total": 0, "open": 0},
        "todos": {"total": 0, "done": 0, "items": []},
        "files": {"total": 0},
        "runs": [],
        "changes": [],
        "lock": None,
    }
    text = render_dashboard_text(payload)
    assert "Full Task" in text
    assert "Description: A summary of the task" in text
    assert "Priority: high" in text
    assert "Labels: bug, urgent" in text
    assert "Owner: alice" in text
    assert "implementing" in text

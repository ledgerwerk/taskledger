from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.actor import ActorRef
from taskledger.domain.event import TaskEvent
from taskledger.services.monitor import monitor_snapshot, render_monitor_text
from taskledger.services.tasks import create_task, start_implementation
from taskledger.storage.events import append_event
from taskledger.storage.task_store import resolve_v2_paths, save_task
from tests.support.builders import (
    create_approved_task,
    create_failed_validation_task,
    init_workspace,
)


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


# specmason: req=REQ-0033 ac=AC-0369
def test_monitor_snapshot_works_in_empty_initialized_project(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    payload = monitor_snapshot(ws)
    assert payload["kind"] == "monitor_snapshot"
    assert payload["active"] is None
    assert payload["in_progress"] == []
    assert payload["ready"] == []


# specmason: req=REQ-0033 ac=AC-0369
def test_monitor_snapshot_includes_active_task_and_progress(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_approved_task(
        ws, title="Active impl task", slug="active-impl-task"
    )
    start_implementation(ws, task_id)
    payload = monitor_snapshot(ws)
    active = payload["active"]
    assert isinstance(active, dict)
    assert active["task_id"] == task_id
    assert active["todo_progress"] == {"done": 0, "total": 1}
    assert isinstance(active["next_action"], dict)


# specmason: req=REQ-0033 ac=AC-0368
def test_monitor_snapshot_groups_in_progress_and_ready_tasks(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    planning = create_task(
        ws, title="Planning task", slug="planning-task", description="x"
    )
    implementing = create_task(
        ws, title="Implementing task", slug="implementing-task", description="x"
    )
    validating = create_task(
        ws, title="Validating task", slug="validating-task", description="x"
    )
    save_task(ws, replace(planning, status_stage="planning"))
    save_task(ws, replace(implementing, status_stage="implementing"))
    save_task(ws, replace(validating, status_stage="validating"))

    ready = create_approved_task(ws, title="Ready task", slug="ready-task")
    failed = create_failed_validation_task(
        ws, title="Failed validation task", slug="failed-validation-task"
    )

    payload = monitor_snapshot(ws)
    in_progress_ids = {item["task_id"] for item in payload["in_progress"]}
    ready_ids = {item["task_id"] for item in payload["ready"]}
    assert planning.id in in_progress_ids
    assert implementing.id in in_progress_ids
    assert validating.id in in_progress_ids
    assert ready in ready_ids
    assert failed in ready_ids


# specmason: req=REQ-0033 ac=AC-0370
def test_monitor_snapshot_lists_newest_activity_first(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Activity task", slug="activity-task", description="x")
    paths = resolve_v2_paths(ws)
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-01-01T12:38:00+00:00",
            event="task.created",
            task_id=task.id,
            actor=ActorRef(actor_type="agent", actor_name="test"),
        ),
    )
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-01-01T12:39:00+00:00",
            event="plan.started",
            task_id=task.id,
            actor=ActorRef(actor_type="agent", actor_name="test"),
        ),
    )
    payload = monitor_snapshot(ws, max_events=5)
    activity = payload["activity"]
    assert isinstance(activity, list)
    assert activity
    # plan.started was manually appended at 12:39, should appear in results
    assert any(item["event"] == "plan.started" for item in activity)


# specmason: req=REQ-0033 ac=AC-0372
def test_render_monitor_text_truncates_without_throwing() -> None:
    payload = {
        "kind": "monitor_snapshot",
        "active": {
            "task_id": "task-0001",
            "priority": "P1",
            "title": (
                "This is a very long task title that should be shortened "
                "for small terminals"
            ),
            "next_action": {
                "action": "todo-work",
                "reason": "Keep going",
                "next_command": "taskledger todo show todo-0001",
            },
        },
        "in_progress": [
            {
                "task_id": "task-0001",
                "priority": "P1",
                "title": (
                    "This is a very long task title that should be shortened "
                    "for small terminals"
                ),
            }
        ],
        "activity": [
            {
                "time": "12:39",
                "session_id": "ses_123",
                "task_id": "task-0001",
                "message": "Started work on the long-running implementation item",
            }
        ],
        "ready": [],
        "counts": {"ready": 0, "in_progress": 1},
        "warnings": [],
    }
    rendered = render_monitor_text(payload, width=60, height=20)
    assert "CURRENT WORK" in rendered
    assert "..." in rendered


# specmason: req=REQ-0033 ac=AC-0367
def test_monitor_cli_once_exits_zero(empty_workspace: Path) -> None:
    result = runner.invoke(
        app,
        ["--cwd", str(empty_workspace), "--no-log", "monitor", "--once"],
    )
    assert result.exit_code == 0, result.stdout
    assert "CURRENT WORK" in result.stdout


# specmason: req=REQ-0033 ac=AC-0366
def test_monitor_cli_json_once_emits_monitor_snapshot(empty_workspace: Path) -> None:
    result = runner.invoke(
        app,
        ["--cwd", str(empty_workspace), "--no-log", "--json", "monitor", "--once"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["kind"] == "monitor_snapshot"


# specmason: req=REQ-0033 ac=AC-0369
def test_monitor_snapshot_includes_plan_review_in_ready(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    from taskledger.services.tasks import start_planning
    from tests.support.builders import propose_plan

    pr = create_task(ws, title="PR task", slug="pr-task", description="x")
    start_planning(ws, pr.id)
    propose_plan(ws, pr.id, body="Plan body")

    payload = monitor_snapshot(ws)
    ready_ids = {item["task_id"] for item in payload["ready"]}
    assert pr.id in ready_ids


# specmason: req=REQ-0033 ac=AC-0373
def test_monitor_activity_scope_task_filters_to_selected_task(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    task_a = create_task(ws, title="Task A", slug="task-a", description="x")
    task_b = create_task(ws, title="Task B", slug="task-b", description="x")
    paths = resolve_v2_paths(ws)
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-01-01T12:38:00+00:00",
            event="task.created",
            task_id=task_a.id,
            actor=ActorRef(actor_type="agent", actor_name="test"),
        ),
    )
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-01-01T12:39:00+00:00",
            event="task.created",
            task_id=task_b.id,
            actor=ActorRef(actor_type="agent", actor_name="test"),
        ),
    )
    payload = monitor_snapshot(
        ws, task_ref=task_a.id, activity_scope="task", max_events=10
    )
    activity_task_ids = {item["task_id"] for item in payload["activity"]}
    assert activity_task_ids == {task_a.id}
    assert payload["activity_scope"] == "task"


# specmason: req=REQ-0033 ac=AC-0363
# specmason: req=REQ-0033 ac=AC-0364
# specmason: req=REQ-0033 ac=AC-0365
# specmason: req=REQ-0033 ac=AC-0371
def test_monitor_activity_scope_ledger_shows_all(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_a = create_task(ws, title="Task A", slug="task-a", description="x")
    task_b = create_task(ws, title="Task B", slug="task-b", description="x")
    paths = resolve_v2_paths(ws)
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-01-01T12:38:00+00:00",
            event="task.created",
            task_id=task_a.id,
            actor=ActorRef(actor_type="agent", actor_name="test"),
        ),
    )
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-01-01T12:39:00+00:00",
            event="task.created",
            task_id=task_b.id,
            actor=ActorRef(actor_type="agent", actor_name="test"),
        ),
    )
    payload = monitor_snapshot(
        ws, task_ref=task_a.id, activity_scope="ledger", max_events=10
    )
    activity_task_ids = {item["task_id"] for item in payload["activity"]}
    assert task_a.id in activity_task_ids
    assert task_b.id in activity_task_ids
    assert payload["activity_scope"] == "ledger"


# specmason: req=REQ-0033 ac=AC-0372
def test_render_monitor_text_shows_recent_ledger_activity_heading() -> None:
    payload = {
        "kind": "monitor_snapshot",
        "active": None,
        "in_progress": [],
        "activity": [],
        "ready": [],
        "counts": {"ready": 0, "in_progress": 0},
        "activity_scope": "ledger",
        "warnings": [],
    }
    rendered = render_monitor_text(payload, width=100)
    assert "RECENT LEDGER ACTIVITY" in rendered


# specmason: req=REQ-0033 ac=AC-0372
def test_render_monitor_text_shows_task_activity_heading() -> None:
    payload = {
        "kind": "monitor_snapshot",
        "active": {
            "task_id": "task-0042",
            "status_stage": "implementing",
            "title": "Test",
        },
        "in_progress": [],
        "activity": [],
        "ready": [],
        "counts": {"ready": 0, "in_progress": 0},
        "activity_scope": "task",
        "warnings": [],
    }
    rendered = render_monitor_text(payload, width=100)
    assert "TASK ACTIVITY: task-0042" in rendered


# specmason: req=REQ-0033 ac=AC-0372
def test_render_monitor_text_includes_status_stage_in_focused() -> None:
    payload = {
        "kind": "monitor_snapshot",
        "active": {
            "task_id": "task-0042",
            "status_stage": "implementing",
            "title": "Test task",
        },
        "in_progress": [],
        "activity": [],
        "ready": [],
        "counts": {"ready": 0, "in_progress": 0},
        "warnings": [],
    }
    rendered = render_monitor_text(payload, width=100)
    assert "[implementing]" in rendered


# specmason: req=REQ-0033 ac=AC-0364
def test_monitor_cli_activity_scope_task(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws),
            "--no-log",
            "--json",
            "monitor",
            "--once",
            "--activity-scope",
            "task",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["activity_scope"] == "task"


# specmason: req=REQ-0033 ac=AC-0364
def test_monitor_cli_activity_scope_invalid(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws),
            "--no-log",
            "monitor",
            "--once",
            "--activity-scope",
            "invalid",
        ],
    )
    assert result.exit_code != 0

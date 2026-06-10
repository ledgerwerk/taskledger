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


def test_monitor_snapshot_works_in_empty_initialized_project(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    payload = monitor_snapshot(ws)
    assert payload["kind"] == "monitor_snapshot"
    assert payload["active"] is None
    assert payload["in_progress"] == []
    assert payload["ready"] == []


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
    assert activity[0]["event"] == "plan.started"


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


def test_monitor_cli_once_exits_zero(empty_workspace: Path) -> None:
    result = runner.invoke(
        app,
        ["--cwd", str(empty_workspace), "--no-log", "monitor", "--once"],
    )
    assert result.exit_code == 0, result.stdout
    assert "CURRENT WORK" in result.stdout


def test_monitor_cli_json_once_emits_monitor_snapshot(empty_workspace: Path) -> None:
    result = runner.invoke(
        app,
        ["--cwd", str(empty_workspace), "--no-log", "--json", "monitor", "--once"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["kind"] == "monitor_snapshot"

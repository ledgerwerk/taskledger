from __future__ import annotations

from datetime import datetime
from pathlib import Path
from textwrap import shorten
from typing import cast

from taskledger.domain.event import TaskEvent
from taskledger.domain.policies import derive_active_stage
from taskledger.domain.task import TaskRecord
from taskledger.storage.events import load_recent_events
from taskledger.storage.locks import read_lock
from taskledger.storage.task_store import (
    list_runs,
    list_tasks_by_visibility,
    load_active_task_state,
    load_todos,
    resolve_task,
    resolve_v2_paths,
    task_lock_path,
)


def _status_to_active_stage(status_stage: str) -> str | None:
    return {
        "planning": "planning",
        "implementing": "implementation",
        "validating": "validation",
    }.get(status_stage)


def _priority_rank(priority: str | None) -> tuple[int, str]:
    if isinstance(priority, str):
        normalized = priority.strip().upper()
        if normalized.startswith("P") and normalized[1:].isdigit():
            return (int(normalized[1:]), normalized)
        return (50, normalized)
    return (99, "")


def _task_summary(
    workspace_root: Path,
    task: TaskRecord,
    *,
    include_next_action: bool = False,
) -> dict[str, object]:
    lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task.id))
    runs = list_runs(workspace_root, task.id)
    active_stage = derive_active_stage(lock, runs) or _status_to_active_stage(
        task.status_stage
    )
    payload: dict[str, object] = {
        "task_id": task.id,
        "slug": task.slug,
        "title": task.title,
        "priority": task.priority,
        "status_stage": task.status_stage,
        "active_stage": active_stage,
    }
    if include_next_action:
        from taskledger.services.navigation import next_action

        todos = load_todos(workspace_root, task.id).todos
        payload["next_action"] = next_action(workspace_root, task.id)
        payload["todo_progress"] = {
            "done": sum(1 for todo in todos if todo.done),
            "total": len(todos),
        }
    return payload


def _event_time(value: str) -> tuple[str, str]:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return (value, value)
    return (parsed.strftime("%H:%M"), parsed.strftime("%H:%M:%S"))


def _event_message(event: TaskEvent) -> str:
    data = event.data
    for key in ("summary", "message", "reason", "note", "text", "path"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return event.event


def monitor_snapshot(
    workspace_root: Path,
    *,
    task_ref: str | None = None,
    max_events: int = 10,
    max_ready: int = 10,
) -> dict[str, object]:
    tasks = list_tasks_by_visibility(workspace_root, visibility="visible")
    task_by_id = {task.id: task for task in tasks}
    selected = None
    if task_ref is not None:
        selected = resolve_task(workspace_root, task_ref)
    else:
        active_state = load_active_task_state(workspace_root)
        if active_state is not None:
            selected = task_by_id.get(active_state.task_id) or resolve_task(
                workspace_root, active_state.task_id
            )

    in_progress = sorted(
        [
            _task_summary(workspace_root, task)
            for task in tasks
            if task.status_stage in {"planning", "implementing", "validating"}
        ],
        key=lambda item: (
            _priority_rank(cast(str | None, item.get("priority"))),
            str(item["task_id"]),
        ),
    )
    ready = sorted(
        [
            _task_summary(workspace_root, task)
            for task in tasks
            if task.status_stage in {"approved", "failed_validation"}
        ],
        key=lambda item: (
            _priority_rank(cast(str | None, item.get("priority"))),
            str(item["task_id"]),
        ),
    )[:max_ready]

    paths = resolve_v2_paths(workspace_root)
    recent_events = list(
        reversed(load_recent_events(paths.events_dir, limit=max_events))
    )
    activity: list[dict[str, object]] = []
    for event in recent_events:
        task = task_by_id.get(event.task_id)
        time_short, _ = _event_time(event.ts)
        activity.append(
            {
                "time": time_short,
                "session_id": event.actor.session_id
                or (event.harness.session_id if event.harness is not None else None),
                "event": event.event,
                "task_id": event.task_id,
                "slug": task.slug if task is not None else None,
                "message": _event_message(event),
            }
        )

    return {
        "kind": "monitor_snapshot",
        "active": _task_summary(workspace_root, selected, include_next_action=True)
        if selected is not None
        else None,
        "in_progress": in_progress,
        "activity": activity,
        "ready": ready,
        "counts": {"ready": len(ready), "in_progress": len(in_progress)},
        "warnings": [],
    }


def render_monitor_text(
    payload: dict[str, object],
    *,
    width: int | None = None,
    height: int | None = None,
    plain: bool = False,
) -> str:
    del height
    del plain
    max_width = max(40, width or 100)

    def _fit(text: str, *, reserve: int = 0) -> str:
        return shorten(text, width=max(12, max_width - reserve), placeholder="...")

    lines: list[str] = ["CURRENT WORK"]
    active = payload.get("active")
    if isinstance(active, dict):
        header = (
            f"FOCUSED: {active['task_id']} "
            f"{(active.get('priority') or '').strip()} "
            f"{_fit(str(active.get('title') or ''), reserve=20)}"
        ).rstrip()
        lines.append(header)
        next_action = active.get("next_action")
        if isinstance(next_action, dict):
            action = next_action.get("action")
            reason = next_action.get("reason")
            if isinstance(action, str):
                line = f"NEXT: {action}"
                if isinstance(reason, str) and reason:
                    line += f" - {_fit(reason, reserve=10)}"
                lines.append(line)
            command = next_action.get("next_command")
            if isinstance(command, str) and command:
                lines.append(f"COMMAND: {_fit(command, reserve=10)}")
    else:
        lines.append("FOCUSED: none")

    lines.append("")
    lines.append("IN PROGRESS:")
    in_progress = payload.get("in_progress")
    if isinstance(in_progress, list) and in_progress:
        for item in in_progress:
            if not isinstance(item, dict):
                continue
            lines.append(
                "  "
                + _fit(
                    f"{item.get('task_id')} {item.get('priority') or ''} "
                    f"{item.get('title') or ''}",
                    reserve=2,
                )
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("ACTIVITY LOG")
    activity = payload.get("activity")
    if isinstance(activity, list) and activity:
        for item in activity:
            if not isinstance(item, dict):
                continue
            lines.append(
                _fit(
                    f"{item.get('time') or '--:--'} "
                    f"{item.get('session_id') or '-'} "
                    f"{item.get('task_id') or '-'} "
                    f"{item.get('message') or item.get('event') or ''}"
                )
            )
    else:
        lines.append("(empty)")

    lines.append("")
    lines.append("TASK LIST")
    ready = payload.get("ready")
    if isinstance(ready, list):
        lines.append(f"READY ({len(ready)}):")
        if ready:
            for item in ready:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    "  "
                    + _fit(
                        f"{item.get('task_id')} {item.get('priority') or ''} "
                        f"{item.get('title') or ''}",
                        reserve=2,
                    )
                )
        else:
            lines.append("  (none)")

    footer_time = "--:--:--"
    if isinstance(activity, list) and activity:
        first = activity[0]
        if isinstance(first, dict):
            _, footer_time = _event_time(str(first.get("time") or footer_time))
    lines.append("")
    lines.append(f"Last: {footer_time}    Ctrl-C: quit")
    return "\n".join(lines)

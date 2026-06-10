from __future__ import annotations

from pathlib import Path
from typing import cast

from taskledger.domain.actor import ActorRef
from taskledger.domain.policies import derive_active_stage
from taskledger.domain.task import TaskRecord
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_actor, resolve_harness
from taskledger.services.lock_diagnostics import (
    CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
    CLASSIFICATION_ACTIVE_NO_PID,
    CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS,
    CLASSIFICATION_EXPIRED,
    diagnose_lock,
)
from taskledger.services.navigation import next_action
from taskledger.services.task_collections import next_todo
from taskledger.storage.locks import read_lock
from taskledger.storage.task_store import (
    list_code_reviews,
    list_handoffs,
    list_questions,
    list_runs,
    list_tasks_by_visibility,
    load_active_locks,
    load_active_task_state,
    resolve_task,
    resolve_v2_paths,
    task_lock_path,
)


def _priority_rank(priority: str | None) -> tuple[int, str]:
    if isinstance(priority, str):
        normalized = priority.strip().upper()
        if normalized.startswith("P") and normalized[1:].isdigit():
            return (int(normalized[1:]), normalized)
        return (50, normalized)
    return (99, "")


def _ready_entry(task: TaskRecord) -> dict[str, object]:
    return {
        "task_id": task.id,
        "slug": task.slug,
        "title": task.title,
        "priority": task.priority,
        "status_stage": task.status_stage,
    }


def _next_action_label(next_action: object) -> str:
    if isinstance(next_action, dict):
        value = next_action.get("action")
        if isinstance(value, str):
            return value
    return "none"


def _lock_payload(
    workspace_root: Path,
    task_id: str,
    actor: ActorRef,
) -> dict[str, object]:
    lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task_id))
    diagnostics = diagnose_lock(lock, task_id=task_id, current_actor=actor)
    run_id = lock.run_id if lock is not None else None
    stage = lock.stage if lock is not None else None
    classification = diagnostics.classification
    if classification == CLASSIFICATION_EXPIRED:
        status = "expired"
    elif classification == "none":
        status = "none"
    elif classification in {
        CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
        CLASSIFICATION_ACTIVE_NO_PID,
        CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS,
    }:
        status = "stale"
    else:
        status = "active"
    payload: dict[str, object] = {
        "status": status,
        "run_id": run_id,
        "stage": stage,
        "diagnostics": diagnostics.to_dict(),
    }
    if diagnostics.remediation:
        payload["remediation"] = diagnostics.remediation[0]
    return payload


def _active_payload(
    workspace_root: Path,
    task: TaskRecord,
    actor: ActorRef,
    *,
    focused: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": task.id,
        "slug": task.slug,
        "title": task.title,
        "stage": task.status_stage,
        "focused": focused,
        "lock": _lock_payload(workspace_root, task.id, actor),
    }
    active_warnings: list[str] = []
    try:
        payload["next_action"] = next_action_payload = next_action(
            workspace_root,
            task.id,
        )
    except LaunchError as exc:
        payload["next_action"] = None
        active_warnings.append(str(exc))
    else:
        try:
            payload["next_todo"] = next_todo(workspace_root, task.id)
        except LaunchError as exc:
            active_warnings.append(str(exc))
            payload["next_todo"] = None
        if isinstance(next_action_payload, dict) and "active_stage" not in payload:
            payload["active_stage"] = next_action_payload.get("active_stage")
    if "active_stage" not in payload:
        lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task.id))
        payload["active_stage"] = derive_active_stage(
            lock,
            list_runs(workspace_root, task.id),
        )
    if active_warnings:
        payload["warnings"] = active_warnings
    return payload


def usage_payload(
    workspace_root: Path,
    *,
    task_ref: str | None = None,
    quiet: bool = False,
    include_closed: bool = False,
) -> dict[str, object]:
    del quiet
    actor = resolve_actor(workspace_root=workspace_root)
    harness = resolve_harness(cwd=workspace_root, workspace_root=workspace_root)
    warnings: list[str] = []

    all_tasks = list_tasks_by_visibility(workspace_root, visibility="visible")
    visible_tasks = (
        all_tasks
        if include_closed
        else [
            task for task in all_tasks if task.status_stage not in {"done", "cancelled"}
        ]
    )

    active_task: TaskRecord | None = None
    focused = False
    if task_ref is not None:
        active_task = resolve_task(workspace_root, task_ref)
        focused = True
    else:
        active_state = load_active_task_state(workspace_root)
        if active_state is not None:
            try:
                active_task = resolve_task(workspace_root, active_state.task_id)
            except LaunchError as exc:
                warnings.append(str(exc))

    claimable_handoffs: list[dict[str, object]] = []
    review_ready: list[dict[str, object]] = []
    open_questions: list[dict[str, object]] = []

    for task in visible_tasks:
        for handoff in list_handoffs(workspace_root, task.id):
            if handoff.status != "open":
                continue
            claimable_handoffs.append(
                {
                    "task_id": task.id,
                    "handoff_id": handoff.handoff_id,
                    "mode": handoff.mode,
                    "context_for": handoff.context_for,
                    "summary": handoff.summary,
                    "next_action": handoff.next_action,
                    "created_at": handoff.created_at,
                }
            )

        if (
            task.status_stage
            in {"implemented", "validating", "failed_validation", "implementing"}
            and task.latest_implementation_run is not None
        ):
            reviews = list_code_reviews(workspace_root, task.id)
            has_latest_review = any(
                review.implementation_run == task.latest_implementation_run
                for review in reviews
            )
            if not has_latest_review:
                review_ready.append(
                    {
                        "task_id": task.id,
                        "title": task.title,
                        "status_stage": task.status_stage,
                        "latest_implementation_run": task.latest_implementation_run,
                        "command": (
                            f"taskledger review record --task {task.id} "
                            '--result pass --summary "..."'
                        ),
                    }
                )

        for question in list_questions(workspace_root, task.id):
            if question.status != "open":
                continue
            open_questions.append(
                {
                    "task_id": task.id,
                    "question_id": question.id,
                    "question": question.question,
                    "command": (
                        f'taskledger question answer {question.id} --text "..."'
                    ),
                }
            )

    stale_locks: list[dict[str, object]] = []
    for lock in load_active_locks(workspace_root):
        diagnostics = diagnose_lock(lock, task_id=lock.task_id, current_actor=actor)
        if diagnostics.classification not in {
            CLASSIFICATION_EXPIRED,
            CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
            CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS,
            CLASSIFICATION_ACTIVE_NO_PID,
        }:
            continue
        stale_locks.append(
            {
                "task_id": lock.task_id,
                "run_id": lock.run_id,
                "stage": lock.stage,
                "classification": diagnostics.classification,
                "summary": diagnostics.summary,
                "command": (
                    diagnostics.remediation[0] if diagnostics.remediation else None
                ),
            }
        )

    ready: dict[str, list[dict[str, object]]] = {
        "approved": sorted(
            [
                _ready_entry(task)
                for task in visible_tasks
                if task.status_stage == "approved"
            ],
            key=lambda item: (
                _priority_rank(cast(str | None, item.get("priority"))),
                str(item["task_id"]),
            ),
        ),
        "failed_validation": sorted(
            [
                _ready_entry(task)
                for task in visible_tasks
                if task.status_stage == "failed_validation"
            ],
            key=lambda item: (
                _priority_rank(cast(str | None, item.get("priority"))),
                str(item["task_id"]),
            ),
        ),
        "plan_review": sorted(
            [
                _ready_entry(task)
                for task in visible_tasks
                if task.status_stage == "plan_review"
            ],
            key=lambda item: (
                _priority_rank(cast(str | None, item.get("priority"))),
                str(item["task_id"]),
            ),
        ),
    }

    payload: dict[str, object] = {
        "kind": "usage",
        "actor": actor.to_dict(),
        "harness": harness.to_dict(),
        "active": _active_payload(
            workspace_root,
            active_task,
            actor,
            focused=focused,
        )
        if active_task is not None
        else None,
        "inbox": {
            "claimable_handoffs": claimable_handoffs,
            "review_ready": review_ready,
            "stale_locks": stale_locks,
            "open_questions": open_questions[:10],
        },
        "ready": ready,
        "warnings": warnings,
    }
    active_section = payload.get("active")
    active_warnings = (
        active_section.get("warnings") if isinstance(active_section, dict) else None
    )
    if isinstance(active_warnings, list):
        warnings.extend(str(item) for item in active_warnings)
    return payload


def render_usage_text(payload: dict[str, object], *, quiet: bool = False) -> str:
    active = payload.get("active")
    inbox = payload.get("inbox")
    ready = payload.get("ready")

    if quiet:
        active_line = "ACTIVE none"
        if isinstance(active, dict):
            next_action = active.get("next_action")
            command = (
                next_action.get("next_command")
                if isinstance(next_action, dict)
                else None
            )
            active_line = (
                f"ACTIVE {active.get('task_id')} [{active.get('stage')}] "
                "next="
                f"{_next_action_label(next_action)} "
                f'command="{command or ""}"'
            )
        inbox_line = "INBOX handoffs=0 review_ready=0 stale_locks=0 questions=0"
        if isinstance(inbox, dict):
            inbox_line = (
                "INBOX "
                f"handoffs={len(inbox.get('claimable_handoffs', []))} "
                f"review_ready={len(inbox.get('review_ready', []))} "
                f"stale_locks={len(inbox.get('stale_locks', []))} "
                f"questions={len(inbox.get('open_questions', []))}"
            )
        ready_line = "READY approved=0 failed_validation=0 plan_review=0"
        if isinstance(ready, dict):
            ready_line = (
                "READY "
                f"approved={len(ready.get('approved', []))} "
                f"failed_validation={len(ready.get('failed_validation', []))} "
                f"plan_review={len(ready.get('plan_review', []))}"
            )
        return "\n".join([active_line, inbox_line, ready_line])

    lines = ["SESSION"]
    actor = payload.get("actor")
    harness = payload.get("harness")
    if isinstance(actor, dict):
        lines.append(
            "  actor: "
            f"{actor.get('actor_type')}:{actor.get('actor_name')} "
            f"role={actor.get('role')} session={actor.get('session_id')}"
        )
    if isinstance(harness, dict):
        lines.append(
            f"  harness: {harness.get('name')} session={harness.get('session_id')}"
        )

    lines.append("")
    lines.append("ACTIVE")
    if isinstance(active, dict):
        lines.append(
            f"  {active.get('task_id')} {active.get('title')} [{active.get('stage')}]"
        )
        lock = active.get("lock")
        if isinstance(lock, dict):
            lines.append(
                f"  lock: {lock.get('status')} {lock.get('run_id') or ''}".rstrip()
            )
        next_action = active.get("next_action")
        if isinstance(next_action, dict):
            lines.append(
                f"  next: {next_action.get('action')} - {next_action.get('reason')}"
            )
            if next_action.get("next_command"):
                lines.append(f"  command: {next_action.get('next_command')}")
    else:
        lines.append("  none")

    lines.append("")
    lines.append("INBOX")
    if isinstance(inbox, dict):
        lines.append(
            f"  handoffs claimable: {len(inbox.get('claimable_handoffs', []))}"
        )
        lines.append(f"  review ready: {len(inbox.get('review_ready', []))}")
        lines.append(f"  stale locks: {len(inbox.get('stale_locks', []))}")
        lines.append(f"  open questions: {len(inbox.get('open_questions', []))}")

    lines.append("")
    lines.append("READY WORK")
    if isinstance(ready, dict):
        found_ready = False
        for section in ("approved", "failed_validation", "plan_review"):
            items = ready.get(section, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                found_ready = True
                lines.append(
                    f"  {item.get('task_id')} [{item.get('status_stage')}] "
                    f"{item.get('title')}"
                )
        if not found_ready:
            lines.append("  none")

    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("")
        lines.append("WARNINGS")
        for warning in warnings:
            lines.append(f"  - {warning}")
    return "\n".join(lines)

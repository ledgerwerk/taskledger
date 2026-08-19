"""Repair helpers for task records, runs, and planning command changes.

These functions were extracted from services/tasks.py to shrink the monolith.
tasks.py re-exports them for backward compatibility.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from taskledger.domain.states import (
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_INVALID_TRANSITION,
    EXIT_CODE_LOCK_CONFLICT,
)
from taskledger.services import tasks as _tasks
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    list_changes,
    resolve_task,
    resolve_v2_paths,
    save_run,
    save_task,
    task_dir,
)
from taskledger.timeutils import utc_now_iso


def repair_task_record(
    workspace_root: Path,
    task_ref: str,
    *,
    reason: str,
) -> dict[str, object]:
    if not reason.strip():
        raise _tasks._cli_error("Task repair requires --reason.", EXIT_CODE_BAD_INPUT)
    task = resolve_task(workspace_root, task_ref)
    warnings = [("Recorded a repair inspection event only; no task state was changed.")]
    recovery_commands: list[str] = []
    implementation_run = _tasks._optional_run(
        workspace_root,
        task,
        task.latest_implementation_run,
    )
    if (
        task.status_stage == "implementing"
        and implementation_run is not None
        and implementation_run.run_type == "implementation"
        and implementation_run.status == "running"
        and _tasks._current_lock(workspace_root, task.id) is None
    ):
        recovery_commands.append(
            "taskledger implement resume "
            '--reason "Reacquire implementation lock for existing running run."'
        )
    elif task.status_stage == "cancelled":
        recovery_commands.append(
            "taskledger task uncancel "
            '--reason "Restore the task to a safe durable stage."'
        )
    _tasks._append_event(
        workspace_root,
        task.id,
        "repair.task",
        {"reason": reason.strip()},
    )
    return {
        "kind": "task_repair",
        "task_id": task.id,
        "changed": False,
        "reason": reason.strip(),
        "warnings": warnings,
        "recovery_commands": recovery_commands,
    }


def repair_orphaned_planning_run(
    workspace_root: Path,
    task_ref: str,
    *,
    run_id: str | None = None,
    reason: str,
) -> dict[str, object]:
    repair_reason = reason.strip()
    if not repair_reason:
        raise _tasks._cli_error("Run repair requires --reason.", EXIT_CODE_BAD_INPUT)
    task = resolve_task(workspace_root, task_ref)
    selected_run_id = run_id or task.latest_planning_run
    run = _tasks._require_run(workspace_root, task, selected_run_id)
    if run.run_type != "planning":
        raise _tasks._cli_error(
            "Run repair only supports planning runs.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    if run.status != "running":
        raise _tasks._cli_error(
            "Run repair requires a running planning run.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    active_lock = _tasks._current_lock(workspace_root, task.id)
    if _tasks._lock_matches_run(active_lock, run):
        raise _tasks._cli_error(
            (
                "Run repair refuses to finish a planning run "
                "with a matching active lock."
            ),
            EXIT_CODE_LOCK_CONFLICT,
        )
    if active_lock is not None:
        raise _tasks._running_run_conflict_error(
            task,
            run,
            active_lock,
            message=(
                "Run repair requires no active lock for the selected "
                "planning run. Run `taskledger doctor`."
            ),
        )
    now = utc_now_iso()
    save_run(
        workspace_root,
        replace(
            run,
            status="finished",
            finished_at=now,
            summary=(f"Repaired orphaned planning run: {repair_reason}"),
        ),
    )
    _tasks._append_event(
        workspace_root,
        task.id,
        "repair.run",
        {
            "action": "finished_orphan_run",
            "run_id": run.run_id,
            "run_type": run.run_type,
            "previous_status": run.status,
            "new_status": "finished",
            "reason": repair_reason,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return {
        "kind": "run_repair",
        "action": "finished_orphan_run",
        "task_id": task.id,
        "run_id": run.run_id,
        "run_type": run.run_type,
        "previous_status": run.status,
        "new_status": "finished",
        "next_command": "taskledger implement start",
    }


def repair_planning_command_changes(
    workspace_root: Path,
    task_ref: str,
    *,
    reason: str,
    dry_run: bool = False,
) -> dict[str, object]:
    repair_reason = reason.strip()
    if not repair_reason:
        raise _tasks._cli_error(
            "Planning command changes repair requires --reason.",
            EXIT_CODE_BAD_INPUT,
        )
    task = resolve_task(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    changes = list_changes(workspace_root, task.id)
    repaired_changes: list[str] = []
    dry_run_summary: list[str] = []

    for change in changes:
        if change.kind != "command":
            continue
        run = _tasks._optional_run(workspace_root, task, change.implementation_run)
        if run is None or run.run_type != "planning":
            continue

        repaired_changes.append(change.change_id)
        change_path = task_dir(paths, task.id) / "changes" / f"{change.change_id}.yaml"

        if not dry_run:
            updated_run = replace(
                run,
                worklog=(*run.worklog, change.summary),
                artifact_refs=(
                    *run.artifact_refs,
                    *(
                        (change.change_id,)
                        if not change.change_id.startswith("artifact_")
                        else ()
                    ),
                ),
            )
            save_run(workspace_root, updated_run)

            if change_path.exists():
                change_path.unlink()

            save_task(
                workspace_root,
                replace(
                    task,
                    code_change_log_refs=tuple(
                        ref
                        for ref in task.code_change_log_refs
                        if ref != change.change_id
                    ),
                    updated_at=utc_now_iso(),
                ),
            )

            _tasks._append_event(
                workspace_root,
                task.id,
                "repair.change",
                {
                    "action": "moved_planning_command_to_worklog",
                    "change_id": change.change_id,
                    "run_id": run.run_id,
                    "reason": repair_reason,
                },
            )
        else:
            dry_run_summary.append(
                f"Would move change {change.change_id} summary to "
                f"planning run {run.run_id} worklog"
            )

    if not dry_run:
        rebuild_v2_indexes(paths)

    return {
        "kind": "planning_command_changes_repair",
        "task_id": task.id,
        "dry_run": dry_run,
        "repaired_changes": repaired_changes,
        "reason": repair_reason,
        "summary": dry_run_summary if dry_run else None,
    }

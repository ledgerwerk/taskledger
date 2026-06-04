from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from taskledger.domain.actor import ActorRef
from taskledger.domain.states import EXIT_CODE_MISSING
from taskledger.errors import LaunchError
from taskledger.services.task_events import (
    append_task_event,
    default_actor,
    write_broken_lock_audit,
)
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.locks import lock_status, read_lock, remove_lock
from taskledger.storage.task_store import (
    load_active_locks,
    resolve_task,
    resolve_v2_paths,
    task_lock_path,
)
from taskledger.timeutils import utc_now_iso


def show_lock(
    workspace_root: Path,
    task_ref: str,
    *,
    current_actor: ActorRef | None = None,
) -> dict[str, object]:
    from taskledger.services.lock_diagnostics import diagnose_lock
    from taskledger.services.storage_locations import _is_within

    task = resolve_task(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task.id)
    lock = read_lock(lock_path)
    diagnostics = diagnose_lock(
        lock,
        task_id=task.id,
        current_actor=current_actor,
    )
    lock_file_rel = lock_path.relative_to(paths.project_dir).as_posix()
    return {
        "kind": "task_lock",
        "task_id": task.id,
        "lock": lock.to_dict() if lock is not None else None,
        "status": lock_status(lock),
        "diagnostics": diagnostics.to_dict(),
        "storage_root": paths.project_dir.as_posix(),
        "inside_workspace": _is_within(paths.project_dir, workspace_root),
        "lock_file": lock_file_rel,
    }


def break_lock(
    workspace_root: Path,
    task_ref: str,
    *,
    reason: str,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task.id)
    lock = read_lock(lock_path)
    if lock is None:
        raise LaunchError(
            "No active lock exists for the task. "
            "This is normal after plan propose, implement finish, or validate finish. "
            "Run `taskledger next-action` to see what to do next.",
            exit_code=EXIT_CODE_MISSING,
        )
    broken_lock = replace(
        lock,
        broken_at=utc_now_iso(),
        broken_by=default_actor(),
        broken_reason=reason.strip(),
    )
    audit_path = write_broken_lock_audit(paths, task.id, broken_lock)
    rel_path = audit_path.relative_to(paths.project_dir).as_posix()
    append_task_event(
        workspace_root,
        task.id,
        "lock.broken",
        {"lock_id": lock.lock_id, "reason": reason, "audit_path": rel_path},
    )
    append_task_event(
        workspace_root,
        task.id,
        "repair.lock_broken",
        {"lock_id": lock.lock_id, "reason": reason, "audit_path": rel_path},
    )
    remove_lock(lock_path)
    rebuild_v2_indexes(paths)
    return {
        "ok": True,
        "command": "lock break",
        "task_id": task.id,
        "status_stage": task.status_stage,
        "changed": True,
        "warnings": [],
        "lock": broken_lock.to_dict(),
        "reason": reason,
        "audit_path": rel_path,
    }


def list_locks(workspace_root: Path) -> dict[str, object]:
    from taskledger.services.lock_diagnostics import diagnose_lock

    locks = load_active_locks(workspace_root)
    entries: list[dict[str, object]] = []
    for lock in locks:
        entries.append(
            {
                **lock.to_dict(),
                "status": lock_status(lock),
                "diagnostics": diagnose_lock(lock, task_id=lock.task_id).to_dict(),
            }
        )
    return {
        "kind": "task_lock_list",
        "locks": entries,
    }

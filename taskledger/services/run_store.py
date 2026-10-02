from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.states import EXIT_CODE_MISSING
from taskledger.errors import LaunchError
from taskledger.ids import TASK_ID_FORMAT
from taskledger.services.task_events import (
    append_task_event,
    default_actor,
    write_broken_lock_audit,
)
from taskledger.storage.locks import lock_status, read_lock
from taskledger.storage.task_store import (
    remove_lock_from_paths,
    resolve_task,
    resolve_v2_paths,
    task_lock_path,
    task_markdown_path,
)
from taskledger.storage.yaml_store import write_yaml_object
from taskledger.timeutils import utc_now_iso


def show_lock(
    workspace_root: Path,
    task_ref: str,
    *,
    current_actor: ActorRef | None = None,
    current_harness: HarnessRef | None = None,
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
        current_harness=current_harness,
    )
    try:
        lock_file_rel = lock_path.relative_to(paths.project_dir).as_posix()
    except ValueError:
        lock_file_rel = (
            f"runtime/{lock_path.relative_to(paths.runtime_root).as_posix()}"
        )
    return {
        "kind": "task_lock",
        "task_id": task.id,
        "lock": lock.to_dict() if lock is not None else None,
        "status": lock_status(lock),
        "diagnostics": diagnostics.to_dict(),
        "storage_root": paths.runtime_root.as_posix(),
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
    matching_run = next(
        (
            run
            for run in list_runs(workspace_root, task.id)
            if run.status == "running"
            and lock.run_id == run.run_id
            and lock.stage
            == {
                "planning": "planning",
                "implementation": "implementing",
                "validation": "validating",
            }.get(run.run_type)
        ),
        None,
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
    remove_lock_from_paths(paths, task.id)
    return {
        "ok": True,
        "command": "lock break",
        "task_id": task.id,
        "status_stage": task.status_stage,
        "changed": True,
        "warnings": [],
        **recovery_details,
        "lock": broken_lock.to_dict(),
        "reason": reason,
        "audit_path": rel_path,
    }


def break_orphan_lock(
    workspace_root: Path,
    task_id: str,
    *,
    reason: str,
) -> dict[str, object]:
    try:
        task_id_parts = TASK_ID_FORMAT.parse_parts(task_id)
    except ValueError as exc:
        raise LaunchError(f"Invalid task ID for orphan lock: {task_id!r}.") from exc
    if TASK_ID_FORMAT.format(task_id_parts.number) != task_id:
        raise LaunchError(f"Non-canonical task ID for orphan lock: {task_id!r}.")
    if not reason.strip():
        raise LaunchError("Orphan lock repair requires a non-empty reason.")

    paths = resolve_v2_paths(workspace_root)
    if task_markdown_path(paths, task_id).is_file():
        raise LaunchError(f"Task {task_id} exists; its lock is not orphaned.")
    lock_path = task_lock_path(paths, task_id)
    lock = read_lock(lock_path)
    if lock is None:
        raise LaunchError(f"No active lock exists for missing task {task_id}.")
    if lock.task_id != task_id:
        raise LaunchError(
            f"Lock {lock_path} identifies task {lock.task_id}, not {task_id}."
        )

    broken_at = utc_now_iso()
    broken_lock = replace(
        lock,
        broken_at=broken_at,
        broken_by=default_actor(),
        broken_reason=reason.strip(),
    )
    timestamp = broken_at.replace(":", "").replace("-", "")
    audit_path = (
        paths.ledger_dir
        / "recovery"
        / "orphan-locks"
        / task_id
        / f"broken-lock-{timestamp}.yaml"
    )
    write_yaml_object(audit_path, broken_lock.to_dict())
    relative_audit_path = audit_path.relative_to(paths.ledger_dir).as_posix()
    append_task_event(
        workspace_root,
        "*",
        "repair.orphan_lock_broken",
        {
            "task_id": task_id,
            "lock_id": lock.lock_id,
            "reason": reason.strip(),
            "audit_path": relative_audit_path,
        },
    )
    remove_lock_from_paths(paths, task_id)
    return {
        "kind": "orphan_lock_repair",
        "task_id": task_id,
        "changed": True,
        "lock": broken_lock.to_dict(),
        "reason": reason.strip(),
        "audit_path": relative_audit_path,
    }


def list_locks(workspace_root: Path) -> dict[str, object]:
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    inventory = build_lock_inventory(paths)
    entries: list[dict[str, object]] = []
    for entry in inventory.entries:
        entry_dict: dict[str, object] = {
            "task_id": entry.task_id,
            "path": str(entry.path),
            "classification": entry.classification,
        }
        if entry.lock is not None:
            entry_dict.update(entry.lock.to_dict())
            from taskledger.storage.locks import lock_status

            entry_dict["status"] = lock_status(entry.lock)
        if entry.diagnostics is not None:
            entry_dict["diagnostics"] = entry.diagnostics.to_dict()
        if entry.parse_error is not None:
            entry_dict["parse_error"] = entry.parse_error
        entries.append(entry_dict)
    return {
        "kind": "task_lock_list",
        "locks": entries,
        "summary": inventory.to_dict(),
    }

from __future__ import annotations

import getpass
import os
import socket
from dataclasses import replace
from pathlib import Path

import yaml

from taskledger.domain.models import ActorRef, HarnessRef, TaskEvent, TaskLock
from taskledger.domain.states import EXIT_CODE_MISSING
from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.events import append_event, next_event_id
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.locks import lock_status, read_lock, remove_lock
from taskledger.storage.task_store import (
    V2Paths,
    load_active_locks,
    resolve_task,
    resolve_v2_paths,
    task_audit_dir,
    task_lock_path,
)
from taskledger.timeutils import utc_now_iso


def show_lock(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    lock = read_lock(task_lock_path(paths, task.id))
    return {
        "kind": "task_lock",
        "task_id": task.id,
        "lock": lock.to_dict() if lock is not None else None,
        "status": lock_status(lock),
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
        broken_by=_default_actor(),
        broken_reason=reason.strip(),
    )
    audit_path = _write_broken_lock_audit(paths, task.id, broken_lock)
    rel_path = audit_path.relative_to(paths.project_dir).as_posix()
    _append_event(
        paths.project_dir,
        task.id,
        "lock.broken",
        {"lock_id": lock.lock_id, "reason": reason, "audit_path": rel_path},
    )
    _append_event(
        paths.project_dir,
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
    locks = load_active_locks(workspace_root)
    return {
        "kind": "task_lock_list",
        "locks": [{**lock.to_dict(), "status": lock_status(lock)} for lock in locks],
    }


def _default_actor() -> ActorRef:
    return ActorRef(
        actor_type="agent",
        actor_name=getpass.getuser() or "taskledger",
        host=socket.gethostname(),
        pid=os.getpid(),
    )


def _default_harness() -> HarnessRef:
    return HarnessRef(
        harness_id="harness-unknown",
        name=os.getenv("TASKLEDGER_HARNESS") or "unknown",
        kind="unknown",
        session_id=os.getenv("TASKLEDGER_SESSION_ID"),
        working_directory=os.getcwd(),
    )


def _append_event(
    project_dir: Path,
    task_id: str,
    event_name: str,
    data: dict[str, object],
) -> None:
    timestamp = utc_now_iso()
    append_event(
        project_dir / "events",
        TaskEvent(
            ts=timestamp,
            event=event_name,
            task_id=task_id,
            actor=_default_actor(),
            harness=_default_harness(),
            event_id=next_event_id(project_dir / "events", timestamp),
            data=data,
        ),
    )


def _write_broken_lock_audit(paths: V2Paths, task_id: str, lock: TaskLock) -> Path:
    timestamp = lock.broken_at or utc_now_iso()
    filename = timestamp.replace(":", "").replace("-", "").replace("+00:00", "Z")
    path = task_audit_dir(paths, task_id) / f"broken-lock-{filename}.yaml"
    atomic_write_text(
        path,
        yaml.safe_dump(lock.to_dict(), sort_keys=False, allow_unicode=True),
    )
    return path

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from taskledger.domain.models import TaskLock
from taskledger.errors import LaunchError
from taskledger.storage.locks import lock_is_expired, read_lock


class LockPathSet(Protocol):
    @property
    def runtime_root(self) -> Path: ...

    @property
    def ledger_ref(self) -> str: ...

    @property
    def tasks_dir(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class LockRecordRead:
    path: Path
    lock: TaskLock | None
    parse_error: str | None


def read_lock_records(paths: LockPathSet) -> tuple[LockRecordRead, ...]:
    lock_paths = list(
        (paths.runtime_root / "checkouts" / paths.ledger_ref / "locks").glob("*.yaml")
    )
    lock_paths.extend(paths.tasks_dir.glob("*/lock.yaml"))
    records: list[LockRecordRead] = []
    for lock_path in sorted(lock_paths):
        try:
            lock = read_lock(lock_path)
        except Exception as exc:  # noqa: BLE001
            records.append(
                LockRecordRead(
                    path=lock_path,
                    lock=None,
                    parse_error=f"Failed to read lock {lock_path}: {exc}",
                )
            )
        else:
            records.append(LockRecordRead(lock_path, lock, None))
    return tuple(records)


def require_migration_safe_locks(paths: LockPathSet, *, project_root: Path) -> None:
    records = read_lock_records(paths)
    active_locks: list[str] = []
    malformed_locks: list[str] = []
    blocker_task_ids: list[str] = []
    blocker_classifications: list[str] = []
    expired_count = 0

    for record in records:
        task_id = (
            record.lock.task_id
            if record.lock is not None
            else record.path.stem
            if record.path.parent.name == "locks"
            else record.path.parent.name
        )
        if record.parse_error is not None:
            malformed_locks.append(record.parse_error)
            blocker_classifications.append("malformed")
            if task_id.startswith("task-"):
                blocker_task_ids.append(task_id)
        elif record.lock is not None:
            try:
                expired = lock_is_expired(record.lock)
            except LaunchError as exc:
                malformed_locks.append(f"{record.path}: {exc}")
                blocker_classifications.append("malformed")
                if task_id.startswith("task-"):
                    blocker_task_ids.append(task_id)
            else:
                if expired:
                    expired_count += 1
                else:
                    active_locks.append(
                        f"{record.lock.task_id} ({record.lock.lock_id})"
                    )
                    blocker_classifications.append("active")
                    if task_id.startswith("task-"):
                        blocker_task_ids.append(task_id)

    if not active_locks and not malformed_locks:
        return

    details: dict[str, object] = {
        "lock_file_count": len(records),
        "active_count": len(active_locks),
        "expired_count": expired_count,
        "malformed_count": len(malformed_locks),
        "identity_unresolved_count": 0,
        "stale_count": expired_count,
        "blocker_task_ids": blocker_task_ids,
        "blocker_classifications": blocker_classifications,
        "project_root": str(project_root),
    }
    if malformed_locks:
        raise LaunchError(
            f"Taskledger storage migration is blocked by {len(malformed_locks)} "
            f"malformed lock file(s) and {len(active_locks)} active lock(s).",
            code="TASKLEDGER_STORAGE_MIGRATION_LOCK_STATE_INVALID",
            details=details,
            remediation=[
                "Inspect malformed locks and repair them explicitly before migration."
            ],
        )
    raise LaunchError(
        f"Taskledger storage migration is blocked by "
        f"{len(active_locks)} active lock(s).",
        code="TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS",
        details=details,
        remediation=[
            "Wait for active operations to complete.",
            "Or break stale locks with `taskledger repair lock`.",
        ],
    )

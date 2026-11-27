from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.domain.actor import ActorRef
from taskledger.domain.lock import TaskLock
from taskledger.errors import LaunchError
from taskledger.migrations.legacy_init import init_legacy_project_state
from taskledger.migrations.legacy_project_context import (
    legacy_v2_paths,
    load_legacy_project_context,
)
from taskledger.storage.locks import write_lock
from taskledger.storage.taskledger_migration import require_no_active_taskledger_locks


def _active_lock(task_id: str) -> TaskLock:
    return TaskLock(
        lock_id=f"lock-{task_id}",
        task_id=task_id,
        stage="implementing",
        run_id=f"run-{task_id}",
        created_at="2026-06-04T20:35:58+00:00",
        expires_at="2099-12-31T23:59:59+00:00",
        reason="test",
        holder=ActorRef.from_dict(
            {
                "actor_type": "user",
                "actor_name": "testuser",
                "host": "localhost",
                "pid": 999999,
            }
        ),
    )


def test_migration_quiescence_allows_empty_lock_set(tmp_path: Path) -> None:
    init_legacy_project_state(tmp_path)
    require_no_active_taskledger_locks(tmp_path)


def test_migration_quiescence_reports_active_locks(tmp_path: Path) -> None:
    init_legacy_project_state(tmp_path)
    context = load_legacy_project_context(tmp_path)
    paths = legacy_v2_paths(context)
    for task_id in ("task-001", "task-002"):
        task_dir = paths.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        write_lock(task_dir / "lock.yaml", _active_lock(task_id))

    with pytest.raises(LaunchError, match="migration is blocked") as exc_info:
        require_no_active_taskledger_locks(tmp_path)

    assert exc_info.value.code == "TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS"
    assert exc_info.value.details["active_count"] == 2

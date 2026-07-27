"""Tests for taskledger.services.lock_inventory."""

from __future__ import annotations

from pathlib import Path

from taskledger.domain.actor import ActorRef
from taskledger.domain.lock import TaskLock
from taskledger.services.lock_inventory import (
    LockInventoryEntry,
    build_lock_inventory,
)
from taskledger.storage.locks import write_lock
from taskledger.storage.task_store import (
    V2Paths,
)

FAR_FUTURE = "2099-12-31T23:59:59+00:00"
FAR_PAST = "2020-01-01T00:00:00+00:00"


def _holder(**overrides: object) -> ActorRef:
    base: dict[str, object] = {
        "actor_type": "user",
        "actor_name": "testuser",
        "host": "localhost",
        "pid": 999999,
    }
    base.update(overrides)
    return ActorRef.from_dict(base)


def _lock(
    task_id: str = "task-0001",
    stage: str = "implementing",
    expires_at: str | None = FAR_FUTURE,
    holder: ActorRef | None = None,
) -> TaskLock:
    return TaskLock(
        lock_id=f"lock-{task_id}",
        task_id=task_id,
        stage=stage,  # type: ignore[arg-type]
        run_id="run-0002",
        created_at="2026-06-04T20:35:58+00:00",
        expires_at=expires_at,
        reason="test",
        holder=holder or _holder(),
    )


def _make_v2_paths(workspace: Path) -> V2Paths:
    """Build V2Paths pointing to a fresh workspace without walking parents."""
    ledger_dir = workspace / ".taskledger" / "ledgers" / "main"
    indexes_dir = ledger_dir / "indexes"
    for d in (
        ledger_dir,
        ledger_dir / "tasks",
        ledger_dir / "events",
        indexes_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return V2Paths(
        workspace_root=workspace,
        taskledger_root=workspace / ".taskledger",
        ledger_ref="main",
        ledger_dir=ledger_dir,
        project_dir=ledger_dir,
        introductions_dir=ledger_dir / "intros",
        releases_dir=ledger_dir / "releases",
        tasks_dir=ledger_dir / "tasks",
        plans_dir=ledger_dir / "plans",
        questions_dir=ledger_dir / "questions",
        runs_dir=ledger_dir / "runs",
        changes_dir=ledger_dir / "changes",
        events_dir=ledger_dir / "events",
        indexes_dir=indexes_dir,
        active_task_path=ledger_dir / "active-task.yaml",
        actor_path=workspace / ".taskledger" / "actor.yaml",
        harness_path=workspace / ".taskledger" / "harness.yaml",
        active_locks_index_path=indexes_dir / "active_locks.json",
        dependencies_index_path=indexes_dir / "dependencies.json",
        introductions_index_path=indexes_dir / "introductions.json",
    )


def _setup_project(tmp_path: Path) -> V2Paths:
    """Create a minimal project structure with task directories."""
    paths = _make_v2_paths(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"
    task_dir.mkdir(parents=True, exist_ok=True)
    return paths


def test_lock_inventory_entry_is_malformed() -> None:
    entry = LockInventoryEntry(
        task_id="task-0001",
        path=Path("/tmp/lock.yaml"),
        lock=None,
        diagnostics=None,
        parse_error="parse failed",
    )
    assert entry.is_malformed
    assert not entry.is_active
    assert entry.classification == "malformed"


def test_lock_inventory_entry_is_expired() -> None:
    expired_lock = _lock(expires_at=FAR_PAST)
    entry = LockInventoryEntry(
        task_id="task-0001",
        path=Path("/tmp/lock.yaml"),
        lock=expired_lock,
        diagnostics=None,
        parse_error=None,
    )
    assert entry.is_expired
    assert not entry.is_active
    assert not entry.is_malformed


def test_lock_inventory_entry_is_active() -> None:
    active_lock = _lock(expires_at=FAR_FUTURE)
    entry = LockInventoryEntry(
        task_id="task-0001",
        path=Path("/tmp/lock.yaml"),
        lock=active_lock,
        diagnostics=None,
        parse_error=None,
    )
    assert entry.is_active
    assert not entry.is_expired


def test_lock_inventory_counts(tmp_path: Path) -> None:
    paths = _setup_project(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"
    lock_path = task_dir / "lock.yaml"

    # Write an expired lock.
    expired_lock = _lock(expires_at=FAR_PAST)
    write_lock(lock_path, expired_lock)

    inventory = build_lock_inventory(paths)
    assert inventory.lock_file_count == 1
    assert inventory.active_count == 0  # expired, not active
    assert inventory.expired_count == 1


def test_lock_inventory_malformed_file(tmp_path: Path) -> None:
    paths = _setup_project(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"
    lock_path = task_dir / "lock.yaml"
    lock_path.write_text("invalid: yaml: [", encoding="utf-8")

    inventory = build_lock_inventory(paths)
    assert inventory.lock_file_count == 1
    assert inventory.malformed_count == 1
    assert inventory.active_count == 0
    assert inventory.entries[0].parse_error is not None


def test_lock_inventory_no_errors_silenced(tmp_path: Path) -> None:
    """Malformed lock files are preserved in inventory, not hidden as zero."""
    paths = _setup_project(tmp_path)

    # Create two tasks: one valid, one malformed.
    for task_id in ("task-0001", "task-0002"):
        task_dir = paths.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

    valid_lock = _lock(
        task_id="task-0001",
        expires_at=FAR_FUTURE,
    )
    write_lock(paths.tasks_dir / "task-0001" / "lock.yaml", valid_lock)
    (paths.tasks_dir / "task-0002" / "lock.yaml").write_text("broken", encoding="utf-8")

    inventory = build_lock_inventory(paths)
    assert inventory.lock_file_count == 2
    assert inventory.active_count == 1
    assert inventory.malformed_count == 1


def test_lock_inventory_empty(tmp_path: Path) -> None:
    paths = _setup_project(tmp_path)
    inventory = build_lock_inventory(paths)
    assert inventory.lock_file_count == 0
    assert inventory.active_count == 0
    assert inventory.expired_count == 0
    assert inventory.malformed_count == 0
    assert inventory.safe_repairable == ()
    assert inventory.migration_blockers == ()


def test_lock_inventory_safe_repairable(tmp_path: Path) -> None:
    paths = _setup_project(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"
    lock_path = task_dir / "lock.yaml"
    expired_lock = _lock(expires_at=FAR_PAST)
    write_lock(lock_path, expired_lock)

    inventory = build_lock_inventory(paths)
    assert len(inventory.safe_repairable) == 1
    assert inventory.safe_repairable[0].task_id == "task-0001"


def test_lock_inventory_to_dict(tmp_path: Path) -> None:
    paths = _setup_project(tmp_path)
    inventory = build_lock_inventory(paths)
    result = inventory.to_dict()
    assert "lock_file_count" in result
    assert "active_count" in result
    assert "expired_count" in result
    assert "entries" in result

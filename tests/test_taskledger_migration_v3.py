from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_project_state
from taskledger.storage.taskledger_migration import require_no_active_taskledger_locks


@dataclass
class _FakeLockEntry:
    task_id: str | None
    classification: str = "active_same_actor"
    is_malformed: bool = False
    path: Path = Path("/fake")


class _FakeInventory:
    def __init__(self, entries: list[_FakeLockEntry]) -> None:
        self.active_locks = entries
        self.stale_locks: list[Any] = []
        self.classification = "has_active"
        self.lock_file_count = len(entries)
        self.active_count = len(entries)
        self.expired_count = 0
        self.malformed_count = 0
        self.stale_count = 0
        self.migration_blockers = entries


def test_migration_quiescence_allows_empty_lock_set(tmp_path: Path) -> None:
    init_project_state(tmp_path)
    require_no_active_taskledger_locks(tmp_path)


def test_migration_quiescence_reports_active_locks(tmp_path: Path, monkeypatch) -> None:
    init_project_state(tmp_path)
    from taskledger.services import lock_inventory

    fake_entries = [
        _FakeLockEntry(task_id="task-001"),
        _FakeLockEntry(task_id="task-002"),
    ]
    monkeypatch.setattr(
        lock_inventory,
        "build_lock_inventory",
        lambda _paths: _FakeInventory(fake_entries),
    )
    with pytest.raises(LaunchError, match="active lock") as exc_info:
        require_no_active_taskledger_locks(tmp_path)
    assert exc_info.value.code == "TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS"
    assert exc_info.value.details["active_count"] == 2

from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.taskledger_migration import require_no_active_taskledger_locks


def test_migration_quiescence_allows_empty_lock_set(tmp_path: Path) -> None:
    require_no_active_taskledger_locks(tmp_path)


def test_migration_quiescence_reports_active_locks(tmp_path: Path, monkeypatch) -> None:
    from taskledger.storage import taskledger_migration

    monkeypatch.setattr(
        taskledger_migration,
        "load_active_locks",
        lambda _root: [{"lock_id": "lock-1"}, {"lock_id": "lock-2"}],
    )
    with pytest.raises(LaunchError, match="active lock") as exc_info:
        require_no_active_taskledger_locks(tmp_path)
    assert exc_info.value.code == "TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS"
    assert exc_info.value.details["active_lock_count"] == 2

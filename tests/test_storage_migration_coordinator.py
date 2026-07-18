from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from taskledger.api.storage import (
    storage_migration_apply,
    storage_migration_inspect,
)
from taskledger.errors import LaunchError
from taskledger.services.storage_migration import (
    apply_migration,
    inspect_migration,
)
from taskledger.storage.layout_migration import (
    _backup,
    _copy_items,
    apply_layout_migration,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def _legacy_project(root: Path) -> None:
    (root / ".taskledger" / "ledgers" / "main" / "tasks").mkdir(parents=True)
    (root / ".taskledger" / "storage.yaml").write_text(
        "storage_layout_version: 3\nrecord_schema_version: 1\n"
        "created_with_taskledger: test\ncreated_at: now\n",
        encoding="utf-8",
    )
    (root / "taskledger.toml").write_text(
        f'config_version = 2\nproject_uuid = "{UUID}"\n'
        'ledger_ref = "main"\nledger_next_task_number = 4\n',
        encoding="utf-8",
    )


def test_api_and_service_use_the_same_inspection_coordinator(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    sibling = tmp_path / "sibling"

    service = inspect_migration(tmp_path, sibling_ledger_root=sibling).to_dict()
    api = storage_migration_inspect(tmp_path, sibling_ledger_root=sibling)

    assert api == service


def test_api_and_service_use_the_same_apply_coordinator(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    sibling = tmp_path / "sibling"

    service = apply_migration(tmp_path, dry_run=True, sibling_ledger_root=sibling)
    api = storage_migration_apply(tmp_path, dry_run=True, sibling_ledger_root=sibling)

    assert api == service
    assert service["status"] == "dry_run"


def test_migration_post_steps_are_idempotent(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    sibling = tmp_path / "sibling"

    first = apply_layout_migration(
        tmp_path,
        sibling_ledger_root=sibling,
        create_sibling_store=True,
    )
    second = apply_layout_migration(
        tmp_path,
        sibling_ledger_root=sibling,
    )

    assert first["status"] == "applied"
    assert second["status"] == "applied"
    assert Path(str(second["receipt"])).is_file()


def test_migration_rejects_symlinked_source_files(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    source = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks" / "link"
    source.symlink_to(tmp_path / "taskledger.toml")

    with pytest.raises(LaunchError):
        apply_layout_migration(
            tmp_path,
            sibling_ledger_root=tmp_path / "sibling",
            create_sibling_store=True,
        )


def test_migration_collision_tracking_uses_destination_paths(tmp_path: Path) -> None:
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    target = tmp_path / "target"
    data.mkdir()
    logs.mkdir()
    (data / "same.txt").write_text("data\n", encoding="utf-8")
    (logs / "same.txt").write_text("logs\n", encoding="utf-8")

    items = _copy_items(data, logs, target)

    assert len(items) == 2
    assert {item.action for item in items} == {"copy", "conflict"}
    assert len({item.destination for item in items}) == 1


def test_migration_backup_contains_distinct_data_and_log_roots(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    sibling = tmp_path / "sibling"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "event.log").write_text("event\n", encoding="utf-8")
    inspection = inspect_migration(tmp_path, sibling_ledger_root=sibling)
    inspection = replace(inspection, source_logs_root=logs)

    backup = _backup(inspection, tmp_path / "backup")

    assert (backup / "source-data" / "storage.yaml").is_file()
    assert (backup / "source-logs" / "event.log").is_file()

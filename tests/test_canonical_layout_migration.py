from __future__ import annotations

from pathlib import Path

from taskledger.storage.layout_migration import (
    apply_layout_migration,
    build_layout_migration_plan,
    migration_status,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def _legacy_project(root: Path) -> None:
    (root / ".taskledger" / "ledgers" / "main" / "tasks").mkdir(parents=True)
    (root / ".taskledger" / "storage.yaml").write_text(
        (
            "storage_layout_version: 3\nrecord_schema_version: 1\n"
            "created_with_taskledger: test\ncreated_at: now\n"
        ),
        encoding="utf-8",
    )
    (root / ".taskledger" / "ledgers" / "main" / "tasks" / "marker.txt").write_text(
        "data", encoding="utf-8"
    )
    (root / "taskledger.toml").write_text(
        (
            f'config_version = 2\nproject_uuid = "{UUID}"\n'
            'ledger_ref = "main"\nledger_next_task_number = 2\n'
        ),
        encoding="utf-8",
    )


def test_migration_plan_is_read_only(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    before = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    plan = build_layout_migration_plan(tmp_path)
    after = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    assert before == after
    assert plan.project_uuid == UUID
    assert plan.items


def test_migration_creates_backup_and_preserves_legacy(tmp_path: Path) -> None:
    _legacy_project(tmp_path)
    result = apply_layout_migration(tmp_path, backup=True)
    assert result["status"] == "applied"
    assert Path(str(result["backup"])).exists()
    assert (tmp_path / "taskledger.toml").exists()
    assert (tmp_path / ".taskledger").exists()
    status = migration_status(tmp_path)
    assert status["project_mode"] == "canonical"

from __future__ import annotations

from pathlib import Path

from taskledger.storage.layout_migration import (
    apply_layout_migration,
    build_layout_migration_plan,
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


def test_migration_plan_is_read_only_and_targets_fixed_sibling(tmp_path: Path) -> None:
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
    assert plan.target_data_root == tmp_path.parent / "ledger" / "task" / "taskledger"
    assert plan.legacy_next_task_number == 4
    assert plan.tombstones_required == ("task-0001", "task-0002", "task-0003")


def test_migration_creates_automatic_backup_and_preserves_legacy(
    tmp_path: Path,
) -> None:
    _legacy_project(tmp_path)
    result = apply_layout_migration(
        tmp_path,
        backup=True,
        create_sibling_store=True,
    )
    assert result["status"] == "applied"
    assert Path(str(result["backup"])).exists()
    target = tmp_path.parent / "ledger" / "task" / "taskledger"
    assert (target / ".ledger-project.toml").is_file()
    assert (target / "state.toml").is_file()
    assert (target / "ledgers" / "main" / "tombstones" / "task-0003.toml").is_file()
    assert (tmp_path / "taskledger.toml").exists()
    assert (tmp_path / ".taskledger").exists()
    assert list((target / "migrations").glob("*.json"))


def test_migration_does_not_compare_against_foreign_bound_target(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _legacy_project(project)
    sibling = tmp_path / "ledger"
    target = sibling / "task" / "taskledger"
    target.mkdir(parents=True)
    (sibling / ".ledger-store").write_text("", encoding="utf-8")
    (target / ".ledger-project.toml").write_text(
        "schema_version = 1\n"
        'project_uuid = "11111111-1111-4111-8111-111111111111"\n'
        'ledger = "taskledger"\n'
        'mount = "data"\n',
        encoding="utf-8",
    )
    (target / "storage.yaml").write_text(
        "storage_layout_version: 5\n", encoding="utf-8"
    )
    (target / "existing.txt").write_text("foreign\n", encoding="utf-8")

    plan = build_layout_migration_plan(project)

    codes = [issue.code for issue in plan.issues]
    assert "BINDING_UUID_MISMATCH" in codes
    assert "DESTINATION_CONFLICT" not in codes
    assert plan.copy_items == ()

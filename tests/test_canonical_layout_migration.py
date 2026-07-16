from __future__ import annotations

from pathlib import Path

from taskledger.storage.layout_migration import (
    apply_layout_migration,
    build_layout_migration_plan,
)
from taskledger.storage.project_context import load_project_context

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
    assert plan.target_data_root == tmp_path.parent / "ledger" / "taskledger" / UUID
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
    target = tmp_path.parent / "ledger" / "taskledger" / UUID
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
    target = sibling / "taskledger" / UUID
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


def test_migration_override_copies_without_canonical_activation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _legacy_project(project)
    destination = tmp_path / "archledger-sibling"
    result = apply_layout_migration(
        project,
        sibling_ledger_root=destination,
        create_sibling_store=True,
    )
    assert result["status"] == "applied"
    assert result["canonical_activation"] is False
    assert result["inspection"]["target"]["data"] == str(
        destination / "taskledger" / UUID
    )
    assert (destination / ".ledger-store").is_file()
    assert not (project / ".ledger" / "task" / "config.toml").exists()


def test_migration_rehomes_existing_direct_sibling_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sibling = tmp_path / "ledger"
    sibling.mkdir()
    (sibling / ".ledger-store").write_text("store\n", encoding="utf-8")
    (project / ".ledger").mkdir()
    (project / ".ledger" / "ledger.toml").write_text(
        "schema_version = 2\n"
        "[project]\n"
        f'uuid = "{UUID}"\n'
        "[storage.workspace]\n"
        'default_provider = "user-data"\n'
        'namespace = "ledgerwerk"\n'
        "[storage.cache]\n"
        'default_provider = "user-cache"\n'
        'namespace = "ledgerwerk"\n'
        "[ledgers.taskledger.config]\n"
        'location = "project"\npath = "task/config.toml"\n'
        "[ledgers.taskledger.mounts.data]\n"
        'storage = "workspace"\nscope = "project"\npath = "task/taskledger"\n'
        "[ledgers.taskledger.mounts.indexes]\n"
        'storage = "cache"\nscope = "checkout"\npath = "task/taskledger-indexes"\n',
        encoding="utf-8",
    )
    (project / ".ledger" / "ledger.local.toml").write_text(
        'schema_version = 1\n[storage.workspace]\nprovider = "sibling-ledger"\n',
        encoding="utf-8",
    )
    (project / ".ledger" / "task").mkdir()
    (project / ".ledger" / "task" / "config.toml").write_text(
        "config_version = 3\n[ledger]\ncode = 'tl'\nname = 'taskledger'\n",
        encoding="utf-8",
    )
    direct = sibling / "task" / "taskledger"
    (direct / "ledgers" / "main" / "tasks").mkdir(parents=True)
    for name in ("intros", "releases", "events", "agent-logs", "tombstones"):
        (direct / "ledgers" / "main" / name).mkdir()
    (direct / ".ledger-project.toml").write_text(
        "schema_version = 1\n"
        f'project_uuid = "{UUID}"\n'
        'ledger = "taskledger"\nmount = "data"\n',
        encoding="utf-8",
    )
    (direct / "storage.yaml").write_text(
        "storage_layout_version: 5\nrecord_schema_version: 1\n",
        encoding="utf-8",
    )
    (direct / "state.toml").write_text(
        'schema_version = 2\nledger_ref = "main"\n',
        encoding="utf-8",
    )

    plan = build_layout_migration_plan(project)
    assert plan.source_kind == "direct-sibling-old-schema"
    assert plan.target_data_root == sibling / "taskledger" / UUID

    result = apply_layout_migration(project)
    target = sibling / "taskledger" / UUID
    assert result["status"] == "applied"
    assert (target / ".ledger-project.toml").is_file()
    assert direct.is_dir()
    context = load_project_context(project)
    assert context.paths.data_root == target
    assert f"taskledger/{UUID}" in (project / ".ledger" / "ledger.toml").read_text(
        encoding="utf-8"
    )


def test_foreign_binding_at_shared_base_does_not_block_uuid_target(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _legacy_project(project)
    sibling = tmp_path / "ledger"
    base = sibling / "taskledger"
    base.mkdir(parents=True)
    (sibling / ".ledger-store").write_text("store\n", encoding="utf-8")
    (base / ".ledger-project.toml").write_text(
        "schema_version = 1\n"
        'project_uuid = "11111111-1111-4111-8111-111111111111"\n'
        'ledger = "taskledger"\nmount = "data"\n',
        encoding="utf-8",
    )
    plan = build_layout_migration_plan(project)
    assert "BINDING_UUID_MISMATCH" not in {issue.code for issue in plan.issues}
    assert plan.target_data_root == base / UUID


def test_repository_local_registration_uses_legacy_external_source(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sibling = tmp_path / "ledger"
    sibling.mkdir()
    (sibling / ".ledger-store").write_text("store\n", encoding="utf-8")
    source = tmp_path / "legacy"
    (source / "ledgers" / "main" / "tasks").mkdir(parents=True)
    (source / "storage.yaml").write_text(
        "storage_layout_version: 3\nrecord_schema_version: 1\n",
        encoding="utf-8",
    )
    (project / ".ledger").mkdir()
    (project / ".ledger" / "ledger.toml").write_text(
        "schema_version = 2\n[project]\n"
        f'uuid = "{UUID}"\n'
        "[storage.workspace]\ndefault_provider = 'user-data'\n"
        "namespace = 'ledgerwerk'\n"
        "[storage.cache]\ndefault_provider = 'user-cache'\n"
        "namespace = 'ledgerwerk'\n"
        "[ledgers.taskledger.config]\nlocation = 'project'\n"
        "path = 'task/config.toml'\n"
        "[ledgers.taskledger.mounts.data]\nstorage = 'repository'\n"
        "path = 'task/taskledger'\n"
        "[ledgers.taskledger.mounts.indexes]\nstorage = 'cache'\n"
        "scope = 'checkout'\npath = 'task/taskledger-indexes'\n",
        encoding="utf-8",
    )
    (project / ".taskledger.toml").write_text(
        "config_version = 2\n"
        "taskledger_dir = '../legacy'\n"
        f'project_uuid = "{UUID}"\n'
        "project_name = 'project'\n"
        "ledger_ref = 'main'\n"
        "ledger_next_task_number = 4\n",
        encoding="utf-8",
    )

    plan = build_layout_migration_plan(project)
    assert plan.source_kind == "legacy-arbitrary-external"
    assert plan.source_data_root == source
    assert plan.copy_items

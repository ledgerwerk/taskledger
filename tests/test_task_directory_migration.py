from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.domain.actor import ActorRef
from taskledger.domain.lock import TaskLock
from taskledger.domain.models import TaskRecord
from taskledger.errors import LaunchError
from taskledger.services.task_lifecycle import create_task
from taskledger.storage.frontmatter import write_markdown_front_matter
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.locks import write_lock
from taskledger.storage.meta import StorageMeta, read_storage_meta, write_storage_meta
from taskledger.storage.migrations import apply_layout_migrations
from taskledger.storage.task_identity import (
    deterministic_legacy_task_uuid,
    scan_task_identity_inventory,
)
from taskledger.storage.task_store import V2Paths, resolve_v2_paths

PROJECT_UUID = "d1fb158a-6755-4b26-8fbe-aef47f5a6d3a"


def _legacy_project(root: Path) -> tuple[Path, V2Paths]:
    root.mkdir(parents=True, exist_ok=True)
    init_canonical_project_state(
        root,
        project_uuid=PROJECT_UUID,
        external_root=f"../{root.parent.name}-{root.name}-ledger",
    )
    paths = resolve_v2_paths(root)
    write_storage_meta(root, StorageMeta(storage_layout_version=5))
    return root, paths


def _add_task(paths: V2Paths, task_id: str, created_at: str) -> bytes:
    task = TaskRecord(
        id=task_id,
        slug=f"slug-{task_id}",
        title=f"Title {task_id}",
        body=f"Body {task_id}",
        status_stage="draft",
        created_at=created_at,
    )
    metadata = task.to_dict()
    body = metadata.pop("body", "")
    assert isinstance(body, str)
    task_dir = paths.tasks_dir / task_id
    task_dir.mkdir(parents=True)
    task_path = task_dir / "task.md"
    write_markdown_front_matter(task_path, metadata, body)
    sidecar = task_dir / "plans" / "legacy.md"
    sidecar.parent.mkdir()
    sidecar.write_text("preserved sidecar\n", encoding="utf-8")
    return task_path.read_bytes()


def _migrate(root: Path) -> list[str]:
    return apply_layout_migrations(root, 5, dry_run=False)


def _storage_version(root: Path) -> int:
    metadata = read_storage_meta(root)
    assert metadata is not None
    return metadata.storage_layout_version


def test_layout5_migration_renames_bundles_and_preserves_order_and_contents(
    tmp_path: Path,
) -> None:
    root, paths = _legacy_project(tmp_path / "project")
    created_at_1 = "2024-01-01T10:00:00+00:00"
    created_at_2 = "2024-02-01T10:00:00+00:00"
    first_bytes = _add_task(paths, "task-0002", created_at_1)
    second_bytes = _add_task(paths, "task-0007", created_at_2)

    assert _migrate(root) == ["uuidv7-task-directories"]

    inventory = scan_task_identity_inventory(resolve_v2_paths(root))
    assert [entry.task_id for entry in inventory.entries] == [
        f"task-{number:04d}" for number in range(1, 8)
    ]
    expected_first = deterministic_legacy_task_uuid(
        project_uuid=PROJECT_UUID,
        ledger_ref="main",
        legacy_task_id="task-0002",
        created_at=created_at_1,
    )
    expected_second = deterministic_legacy_task_uuid(
        project_uuid=PROJECT_UUID,
        ledger_ref="main",
        legacy_task_id="task-0007",
        created_at=created_at_2,
    )
    first_identity = inventory.by_uuid[expected_first]
    second_identity = inventory.by_uuid[expected_second]
    assert first_identity.task_id == "task-0002"
    assert second_identity.task_id == "task-0007"
    assert (first_identity.path / "task.md").read_bytes() == first_bytes
    assert (second_identity.path / "task.md").read_bytes() == second_bytes
    assert (first_identity.path / "plans" / "legacy.md").read_text() == (
        "preserved sidecar\n"
    )
    assert all(entry.path.stem == str(entry.task_uuid) for entry in inventory.entries)
    assert not (paths.tasks_dir / "task-0002").exists()
    assert not (paths.tasks_dir / "task-0007").exists()
    assert _storage_version(root) == 6


def test_layout5_migration_converts_tombstones_and_incomplete_allocations(
    tmp_path: Path,
) -> None:
    root, paths = _legacy_project(tmp_path / "project")
    _add_task(paths, "task-0001", "2024-01-01T10:00:00+00:00")
    incomplete_dir = paths.tasks_dir / "task-0003"
    incomplete_dir.mkdir()
    (incomplete_dir / "allocation.marker").write_text("reserved", encoding="utf-8")
    tombstones_dir = paths.ledger_dir / "tombstones"
    tombstones_dir.mkdir(exist_ok=True)
    (tombstones_dir / "task-0002.toml").write_text(
        'schema_version = 1\nobject_type = "task_id_tombstone"\n'
        'id = "task-0002"\nreason = "deleted"\n'
        'created_at = "2024-01-02T10:00:00+00:00"\n',
        encoding="utf-8",
    )

    _migrate(root)

    inventory = scan_task_identity_inventory(resolve_v2_paths(root))
    assert [entry.task_id for entry in inventory.entries] == [
        "task-0001",
        "task-0002",
        "task-0003",
    ]
    assert [entry.state for entry in inventory.entries] == [
        "live",
        "tombstone",
        "incomplete",
    ]
    tombstone_path = (
        paths.ledger_dir / "tombstones" / f"{inventory.entries[1].task_uuid}.toml"
    )
    tombstone = tombstone_path.read_text(encoding="utf-8")
    assert "schema_version = 2" in tombstone
    assert f'task_uuid = "{inventory.entries[1].task_uuid}"' in tombstone
    assert 'legacy_task_id = "task-0002"' in tombstone
    assert (inventory.entries[2].path / "allocation.marker").read_text() == "reserved"
    assert not (paths.tasks_dir / "task-0003").exists()
    assert not (tombstones_dir / "task-0002.toml").exists()


def test_layout5_mapping_is_deterministic_across_copies_and_diverges_safely(
    tmp_path: Path,
) -> None:
    first_root, first_paths = _legacy_project(tmp_path / "branch-a" / "project")
    second_root, second_paths = _legacy_project(tmp_path / "branch-b" / "project")
    common_time = "2024-03-01T10:00:00+00:00"
    divergent_time = "2024-03-03T10:00:00+00:00"
    _add_task(first_paths, "task-0001", common_time)
    _add_task(second_paths, "task-0001", common_time)
    _add_task(first_paths, "task-0002", "2024-03-02T10:00:00+00:00")
    _add_task(second_paths, "task-0002", divergent_time)

    _migrate(first_root)
    _migrate(second_root)

    first_inventory = scan_task_identity_inventory(resolve_v2_paths(first_root))
    second_inventory = scan_task_identity_inventory(resolve_v2_paths(second_root))
    assert first_inventory.entries[0].task_uuid == second_inventory.entries[0].task_uuid
    assert first_inventory.entries[1].task_uuid != second_inventory.entries[1].task_uuid
    assert first_inventory.entries[0].task_uuid != first_inventory.entries[1].task_uuid


def test_layout5_migration_rolls_back_renames_when_index_rebuild_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, paths = _legacy_project(tmp_path / "project")
    original = _add_task(paths, "task-0002", "2024-04-01T10:00:00+00:00")

    def fail_rebuild(_paths: V2Paths) -> None:
        raise RuntimeError("injected rebuild failure")

    monkeypatch.setattr(
        "taskledger.storage.task_directory_migration._mark_and_rebuild_indexes",
        fail_rebuild,
    )
    with pytest.raises(LaunchError, match="migration failed"):
        _migrate(root)

    assert (paths.tasks_dir / "task-0002" / "task.md").read_bytes() == original
    assert [path.name for path in paths.tasks_dir.iterdir()] == ["task-0002"]
    assert not list((paths.ledger_dir / "tombstones").glob("*.toml"))
    assert _storage_version(root) == 5
    journal = paths.ledger_dir / "task-directory-migration-v5-to-v6.json"
    assert '"status": "rolled_back"' in journal.read_text(encoding="utf-8")


def test_read_only_access_does_not_migrate_but_mutation_does(tmp_path: Path) -> None:
    root, paths = _legacy_project(tmp_path / "project")
    _add_task(paths, "task-0004", "2024-05-01T10:00:00+00:00")

    from taskledger.storage.task_store import list_tasks_from_paths

    assert [task.id for task in list_tasks_from_paths(paths)] == ["task-0004"]
    assert (paths.tasks_dir / "task-0004").is_dir()
    assert not (paths.ledger_dir / "task-directory-migration-v5-to-v6.json").exists()

    create_task(root, title="new", description="", slug="new")

    assert not (paths.tasks_dir / "task-0004").exists()
    assert _storage_version(root) == 6
    inventory = scan_task_identity_inventory(resolve_v2_paths(root))
    assert [entry.task_id for entry in inventory.entries] == [
        f"task-{number:04d}" for number in range(1, 6)
    ]


def test_layout5_migration_refuses_mixed_layout_and_existing_locks(
    tmp_path: Path,
) -> None:
    root, paths = _legacy_project(tmp_path / "mixed")
    _add_task(paths, "task-0001", "2024-06-01T10:00:00+00:00")
    (paths.tasks_dir / "0190a5e0-0000-7000-8000-000000000001").mkdir()
    with pytest.raises(LaunchError, match="Mixed numeric and UUID"):
        _migrate(root)

    lock_root = tmp_path / "locked"
    locked_root, locked_paths = _legacy_project(lock_root)
    _add_task(locked_paths, "task-0001", "2024-06-02T10:00:00+00:00")
    (locked_paths.tasks_dir / "task-0001" / "lock.yaml").write_text(
        "active: true\n", encoding="utf-8"
    )
    with pytest.raises(LaunchError, match="migration is blocked"):
        _migrate(locked_root)


def test_layout5_migration_allows_and_preserves_expired_lock(
    tmp_path: Path,
) -> None:
    root, paths = _legacy_project(tmp_path / "expired-lock")
    _add_task(paths, "task-0001", "2024-06-02T10:00:00+00:00")
    lock_path = paths.tasks_dir / "task-0001" / "lock.yaml"
    write_lock(
        lock_path,
        TaskLock(
            lock_id="lock-expired",
            task_id="task-0001",
            stage="implementing",
            run_id="run-0001",
            created_at="2020-01-01T00:00:00+00:00",
            expires_at="2020-01-01T02:00:00+00:00",
            reason="expired legacy lock",
            holder=ActorRef.from_dict(
                {
                    "actor_type": "agent",
                    "actor_name": "former-agent",
                    "host": "old-host",
                    "pid": 123,
                }
            ),
        ),
    )
    original_lock = lock_path.read_bytes()

    _migrate(root)

    migrated = scan_task_identity_inventory(resolve_v2_paths(root)).entries[0]
    assert (migrated.path / "lock.yaml").read_bytes() == original_lock
    assert _storage_version(root) == 6


def test_layout5_migration_recovers_a_prepared_partial_rename(
    tmp_path: Path,
) -> None:
    from taskledger.storage.task_directory_migration import (
        _JOURNAL_NAME,
        _build_rename_plan,
        _write_journal,
    )

    root, paths = _legacy_project(tmp_path / "project")
    _add_task(paths, "task-0001", "2024-07-01T10:00:00+00:00")
    _add_task(paths, "task-0003", "2024-07-03T10:00:00+00:00")
    plan = _build_rename_plan(paths)
    journal: dict[str, object] = {
        "schema_version": 1,
        "object_type": "task_directory_migration",
        "from_layout": 5,
        "to_layout": 6,
        "status": "prepared",
        **plan,
    }
    journal_path = paths.ledger_dir / _JOURNAL_NAME
    _write_journal(journal_path, journal)

    first_rename = plan["task_renames"][0]
    source = paths.ledger_dir / str(first_rename["old"])
    destination = paths.ledger_dir / str(first_rename["new"])
    source.rename(destination)

    _migrate(root)

    inventory = scan_task_identity_inventory(resolve_v2_paths(root))
    assert [entry.task_id for entry in inventory.entries] == [
        f"task-{number:04d}" for number in range(1, 4)
    ]
    assert not (paths.tasks_dir / "task-0001").exists()
    assert not (paths.tasks_dir / "task-0003").exists()
    assert '"status": "complete"' in journal_path.read_text(encoding="utf-8")


def test_layout5_migration_blocks_unresolved_git_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from subprocess import CompletedProcess

    root, paths = _legacy_project(tmp_path / "project")
    _add_task(paths, "task-0001", "2024-08-01T10:00:00+00:00")

    def fake_run(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        if args[1] == "rev-parse":
            return CompletedProcess(args, 0, stdout="true\n", stderr="")
        return CompletedProcess(args, 0, stdout="unmerged-file.md\n", stderr="")

    monkeypatch.setattr(
        "taskledger.storage.task_directory_migration.subprocess.run", fake_run
    )
    with pytest.raises(LaunchError, match="unresolved Git merge conflicts"):
        _migrate(root)

    assert (paths.tasks_dir / "task-0001").is_dir()
    assert not (paths.ledger_dir / "task-directory-migration-v5-to-v6.json").exists()

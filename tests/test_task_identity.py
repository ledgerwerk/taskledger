from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
from ledgercore import parse_uuid7

from taskledger.errors import LaunchError
from taskledger.services.task_lifecycle import create_task
from taskledger.storage.frontmatter import (
    read_markdown_front_matter,
    write_markdown_front_matter,
)
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.task_identity import (
    LEGACY_UUID7_EPOCH_MS,
    allocate_task_identity,
    deterministic_legacy_task_uuid,
    legacy_task_identity_for_ref,
    scan_task_identity_inventory,
)
from taskledger.storage.task_ids import write_task_id_tombstone
from taskledger.storage.task_store import resolve_v2_paths


def _init(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project, create_sibling_store=True)
    return project


def _migrated_task_37_fixture(tmp_path: Path):
    project = _init(tmp_path)
    created = create_task(
        project, title="Migrated task 37", description="", slug="migrated-37"
    )
    paths = resolve_v2_paths(project)
    task_dir = paths.tasks_dir / str(created.task_uuid)
    task_path = task_dir / "task.md"
    metadata, body = read_markdown_front_matter(task_path)
    metadata["id"] = "task-0037"
    write_markdown_front_matter(task_path, metadata, body)

    live_uuid = UUID("00dc6acf-ac25-76b7-9c95-3e6e51ff322d")
    task_dir.rename(paths.tasks_dir / str(live_uuid))
    # A physical reservation beyond task 37 causes legacy-gap synthesis to
    # represent earlier missing ordinals in the pre-fix inventory.
    (paths.tasks_dir / "task-0038").mkdir()
    return project, paths, live_uuid


def test_deterministic_legacy_uuid7_is_stable_valid_and_ordered() -> None:
    args = {
        "project_uuid": "d1fb158a-6755-4b26-8fbe-aef47f5a6d3a",
        "ledger_ref": "main",
        "created_at": "2026-06-01T10:00:00+00:00",
    }
    first = deterministic_legacy_task_uuid(legacy_task_id="task-0001", **args)
    same = deterministic_legacy_task_uuid(legacy_task_id="task-0001", **args)
    second = deterministic_legacy_task_uuid(legacy_task_id="task-0002", **args)

    assert first == same
    assert parse_uuid7(first) == first
    assert first.version == 7
    assert first.variant == UUID("00000000-0000-0000-8000-000000000000").variant
    assert first.int >> 80 == LEGACY_UUID7_EPOCH_MS + 1
    assert first < second


def test_deterministic_legacy_uuid7_distinguishes_divergent_creation_times() -> None:
    common = {
        "project_uuid": "d1fb158a-6755-4b26-8fbe-aef47f5a6d3a",
        "ledger_ref": "main",
        "legacy_task_id": "task-0034",
    }
    first = deterministic_legacy_task_uuid(
        created_at="2026-06-01T10:00:00+00:00", **common
    )
    second = deterministic_legacy_task_uuid(
        created_at="2026-06-01T10:00:01+00:00", **common
    )
    assert first != second
    assert first.int >> 80 == second.int >> 80


def test_deterministic_legacy_uuid7_rejects_noncanonical_task_ids() -> None:
    with pytest.raises(LaunchError, match="Non-canonical"):
        deterministic_legacy_task_uuid(
            project_uuid="d1fb158a-6755-4b26-8fbe-aef47f5a6d3a",
            ledger_ref="main",
            legacy_task_id="task-34",
            created_at="2026-06-01T10:00:00+00:00",
        )


def test_identity_inventory_derives_aliases_for_new_tasks(
    tmp_path: Path,
) -> None:
    project = _init(tmp_path)
    create_task(project, title="one", description="", slug="one")
    create_task(project, title="two", description="", slug="two")
    paths = resolve_v2_paths(project)

    inventory = scan_task_identity_inventory(paths)

    assert [entry.task_id for entry in inventory.entries] == ["task-0001", "task-0002"]
    assert [entry.state for entry in inventory.entries] == ["live", "live"]
    assert all(UUID(entry.path.name).version == 7 for entry in inventory.entries)
    assert inventory.next_task_id == "task-0003"


def test_migrated_uuid_task_id_prevents_duplicate_legacy_gap(
    tmp_path: Path,
) -> None:
    _project, paths, live_uuid = _migrated_task_37_fixture(tmp_path)

    inventory = scan_task_identity_inventory(paths)
    legacy_timestamp = LEGACY_UUID7_EPOCH_MS + 37
    matching = tuple(
        entry
        for entry in inventory.entries
        if entry.task_uuid.int >> 80 == legacy_timestamp
    )

    assert [(entry.task_uuid, entry.state) for entry in matching] == [
        (live_uuid, "live")
    ]
    assert legacy_task_identity_for_ref(paths, "task-0037").task_uuid == live_uuid


def test_live_migrated_task_and_legacy_tombstone_report_identity_conflict(
    tmp_path: Path,
) -> None:
    _project, paths, live_uuid = _migrated_task_37_fixture(tmp_path)
    write_task_id_tombstone(
        paths,
        "task-0037",
        reason="Conflicting identity fixture.",
        quarantined_path=paths.tasks_dir / "quarantined-task-0037",
    )

    with pytest.raises(LaunchError) as caught:
        legacy_task_identity_for_ref(paths, "task-0037")

    assert caught.value.code == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    assert caught.value.details["legacy_task_id"] == "task-0037"
    sources = caught.value.details["sources"]
    assert isinstance(sources, list)
    assert any(
        isinstance(source, dict)
        and source.get("kind") == "uuid_task"
        and source.get("task_uuid") == str(live_uuid)
        for source in sources
    )
    assert any(
        isinstance(source, dict) and source.get("kind") == "tombstone"
        for source in sources
    )


def test_loading_uuid_bundle_ignores_stale_numeric_display_id(tmp_path: Path) -> None:
    from taskledger.storage.frontmatter import (
        read_markdown_front_matter,
        write_markdown_front_matter,
    )
    from taskledger.storage.task_store import resolve_task

    project = _init(tmp_path)
    created = create_task(project, title="merged", description="", slug="merged")
    paths = resolve_v2_paths(project)
    task_path = paths.tasks_dir / str(created.task_uuid) / "task.md"
    metadata, body = read_markdown_front_matter(task_path)
    metadata["id"] = "task-0099"
    write_markdown_front_matter(task_path, metadata, body)

    resolved = resolve_task(project, "task-0001")

    assert resolved.id == "task-0001"
    assert resolved.task_uuid == created.task_uuid
    assert task_path.is_file()


def test_uuid_identity_allocation_is_unique_and_inventory_backed(
    tmp_path: Path,
) -> None:
    project = _init(tmp_path)
    paths = resolve_v2_paths(project)

    with ThreadPoolExecutor(max_workers=4) as executor:
        allocations = list(
            executor.map(lambda _: allocate_task_identity(paths), range(4))
        )

    assert len({allocation.task_uuid for allocation in allocations}) == 4
    assert len({allocation.path for allocation in allocations}) == 4
    assert all(
        allocation.path.name == str(allocation.task_uuid) for allocation in allocations
    )
    assert all(
        parse_uuid7(allocation.path.name) == allocation.task_uuid
        for allocation in allocations
    )
    inventory = scan_task_identity_inventory(paths)
    assert len(inventory.entries) == 4
    assert len({entry.task_id for entry in inventory.entries}) == 4
    assert all(entry.state == "reserved" for entry in inventory.entries)

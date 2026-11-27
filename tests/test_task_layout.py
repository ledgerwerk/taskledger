from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import paths_for_ledger_ref
from taskledger.storage.task_layout import inspect_task_directory_layout
from taskledger.storage.task_store import v2_paths_for_ledger_ref

PROJECT_UUID = "d1fb158a-6755-4b26-8fbe-aef47f5a6d3a"
UUID_TASK_DIR = "0190a5e0-0000-7000-8000-000000000001"


def _canonical_project(root: Path):
    context, _created = init_canonical_project_state(
        root,
        project_uuid=PROJECT_UUID,
        external_root=f"../{root.parent.name}-{root.name}-ledger",
    )
    return context


def test_arbitrary_ledger_paths_cover_all_canonical_mounts(tmp_path: Path) -> None:
    context = _canonical_project(tmp_path / "project")

    paths = paths_for_ledger_ref(context, "feature-a")
    v2_paths = v2_paths_for_ledger_ref(context, "feature-a")

    assert paths.ledger_data_dir == context.paths.data_root / "ledgers" / "feature-a"
    assert paths.ledger_logs_dir == context.paths.logs_root / "ledgers" / "feature-a"
    assert paths.ledger_indexes_dir == (
        context.paths.indexes_root / "ledgers" / "feature-a"
    )
    assert paths.active_task_path == (
        context.paths.runtime_root / "checkouts" / "feature-a" / "active-task.yaml"
    )
    assert v2_paths.ledger_ref == "feature-a"
    assert v2_paths.ledger_dir == paths.ledger_data_dir
    assert v2_paths.tasks_dir == paths.tasks_dir
    assert v2_paths.events_dir == paths.events_dir
    assert v2_paths.indexes_dir == paths.ledger_indexes_dir
    assert v2_paths.active_task_path == paths.active_task_path

    with pytest.raises(LaunchError, match="Invalid ledger reference"):
        paths_for_ledger_ref(context, "../outside")


def test_inspection_discovers_empty_uuid_and_legacy_ledgers(tmp_path: Path) -> None:
    context = _canonical_project(tmp_path / "project")
    main_paths = v2_paths_for_ledger_ref(context, "main")
    uuid_paths = v2_paths_for_ledger_ref(context, "feature-a")
    empty_paths = v2_paths_for_ledger_ref(context, "empty-ledger")
    (uuid_paths.tasks_dir / UUID_TASK_DIR).mkdir(parents=True)
    empty_paths.tasks_dir.mkdir(parents=True)

    current = inspect_task_directory_layout(context.project_root)

    assert [ledger.ledger_ref for ledger in current.ledgers] == [
        "empty-ledger",
        "feature-a",
        "main",
    ]
    assert current.current is True
    assert {ledger.ledger_ref: ledger.kind for ledger in current.ledgers} == {
        "empty-ledger": "empty",
        "feature-a": "uuid",
        "main": "empty",
    }

    (main_paths.tasks_dir / "task-0001").mkdir()
    drift = inspect_task_directory_layout(context.project_root)

    assert drift.current is False
    assert drift.repairable is True
    assert drift.legacy_ledgers == ("main",)
    main_layout = next(
        ledger for ledger in drift.ledgers if ledger.ledger_ref == "main"
    )
    assert main_layout.legacy_dirs == ("task-0001",)


def test_inspection_reports_mixed_layout_as_unrepairable_without_journal(
    tmp_path: Path,
) -> None:
    context = _canonical_project(tmp_path / "project")
    paths = v2_paths_for_ledger_ref(context, "main")
    (paths.tasks_dir / "task-0001").mkdir(parents=True)
    (paths.tasks_dir / UUID_TASK_DIR).mkdir()

    inspection = inspect_task_directory_layout(context.project_root)

    assert inspection.current is False
    assert inspection.repairable is False
    assert inspection.mixed_ledgers == ("main",)
    assert inspection.ledgers[0].kind == "mixed"


@pytest.mark.parametrize("entry_name", ["unexpected", "task-not-a-number"])
def test_inspection_reports_unknown_task_directories(
    tmp_path: Path, entry_name: str
) -> None:
    context = _canonical_project(tmp_path / "project")
    paths = v2_paths_for_ledger_ref(context, "main")
    (paths.tasks_dir / entry_name).mkdir(parents=True)

    inspection = inspect_task_directory_layout(context.project_root)

    assert inspection.current is False
    assert inspection.repairable is False
    assert inspection.invalid_ledgers == ("main",)
    assert inspection.ledgers[0].kind == "invalid"


def test_inspection_reports_symlinked_task_directory(tmp_path: Path) -> None:
    context = _canonical_project(tmp_path / "project")
    paths = v2_paths_for_ledger_ref(context, "main")
    target = tmp_path / "target-task"
    target.mkdir()
    (paths.tasks_dir / "task-0001").symlink_to(target, target_is_directory=True)

    inspection = inspect_task_directory_layout(context.project_root)

    assert inspection.current is False
    assert inspection.repairable is False
    assert inspection.invalid_ledgers == ("main",)
    assert "symlink" in inspection.ledgers[0].invalid_entries[0]


def test_inspection_reports_nested_symlink(tmp_path: Path) -> None:
    context = _canonical_project(tmp_path / "project")
    paths = v2_paths_for_ledger_ref(context, "main")
    task_dir = paths.tasks_dir / UUID_TASK_DIR
    task_dir.mkdir(parents=True)
    target = tmp_path / "sidecar"
    target.write_text("external", encoding="utf-8")
    (task_dir / "linked-sidecar").symlink_to(target)

    inspection = inspect_task_directory_layout(context.project_root)

    assert inspection.current is False
    assert inspection.repairable is False
    assert inspection.invalid_ledgers == ("main",)
    assert any(
        "nested symlink" in entry for entry in inspection.ledgers[0].invalid_entries
    )

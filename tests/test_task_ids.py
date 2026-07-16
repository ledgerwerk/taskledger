from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.services.task_lifecycle import create_task
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.task_ids import scan_task_id_inventory
from taskledger.storage.task_store import resolve_v2_paths


def _init(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project, create_sibling_store=True)
    return project


def test_task_ids_are_derived_without_reusing_gaps(tmp_path: Path) -> None:
    project = _init(tmp_path)
    create_task(project, title="one", description="", slug="one")
    paths = resolve_v2_paths(project)
    (paths.tasks_dir / "task-0003").mkdir()
    inventory = scan_task_id_inventory(paths)
    assert inventory.next_task_id == "task-0004"
    assert inventory.empty_reservations == (paths.tasks_dir / "task-0003",)


def test_tombstones_require_schema_and_reserve_numbers(tmp_path: Path) -> None:
    project = _init(tmp_path)
    paths = resolve_v2_paths(project)
    tombstones = paths.ledger_dir / "tombstones"
    tombstones.mkdir(parents=True, exist_ok=True)
    (tombstones / "task-0005.toml").write_text(
        "schema_version = 1\nobject_type = 'task_id_tombstone'\n"
        "id = 'task-0005'\nreason = 'test'\ncreated_at = 'now'\n",
        encoding="utf-8",
    )
    assert scan_task_id_inventory(paths).next_task_id == "task-0006"
    (tombstones / "task-0006.toml").write_text(
        "id = 'task-0006'\nobject_type = 'task_id_tombstone'\n",
        encoding="utf-8",
    )
    with pytest.raises(LaunchError, match="invalid schema"):
        scan_task_id_inventory(paths)

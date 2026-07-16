from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import load_project_context


def _init(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    return project, init_canonical_project_state(project, create_sibling_store=True)


def test_authoritative_and_cache_mounts_are_separate_and_lazy(tmp_path: Path) -> None:
    _project, (context, _) = _init(tmp_path)
    assert context.paths.data_root == tmp_path / "ledger" / "task" / "taskledger"
    assert context.paths.data_root != context.paths.indexes_root
    assert context.paths.data_root.exists()
    assert not context.paths.indexes_root.exists()


def test_malformed_ledger_reference_cannot_escape_mount(tmp_path: Path) -> None:
    project, (context, _) = _init(tmp_path)
    state = context.paths.state_path
    state.write_text('schema_version = 2\nledger_ref = "../escape"\n', encoding="utf-8")
    with pytest.raises(LaunchError):
        load_project_context(project)


def test_task_records_survive_cache_mount_deletion(tmp_path: Path) -> None:
    from taskledger.services.task_lifecycle import create_task
    from taskledger.storage.task_store import list_tasks

    project, (context, _) = _init(tmp_path)
    task = create_task(project, title="cached", description="cached", slug="cached")
    if context.paths.indexes_root.exists():
        shutil.rmtree(context.paths.indexes_root)
    assert [item.id for item in list_tasks(project)] == [task.id]

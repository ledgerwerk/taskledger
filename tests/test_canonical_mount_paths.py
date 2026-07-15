from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import load_project_context


def test_mount_paths_are_separate_and_lazy(tmp_path: Path) -> None:
    context, _ = init_canonical_project_state(tmp_path)
    assert context.paths.data_root != context.paths.logs_root
    assert context.paths.logs_root != context.paths.indexes_root
    assert context.paths.data_root.exists()
    assert not context.paths.logs_root.exists()
    assert not context.paths.indexes_root.exists()


def test_malformed_ledger_reference_cannot_escape_mount(tmp_path: Path) -> None:
    context, _ = init_canonical_project_state(tmp_path)
    state = context.paths.state_path
    state.write_text('schema_version = 1\nledger_ref = "../escape"\n', encoding="utf-8")
    with pytest.raises(LaunchError):
        load_project_context(tmp_path)


def test_task_records_survive_cache_mount_deletion(tmp_path: Path) -> None:
    from taskledger.services.task_lifecycle import create_task
    from taskledger.storage.project_context import load_project_context
    from taskledger.storage.task_store import list_tasks

    init_canonical_project_state(tmp_path)
    task = create_task(tmp_path, title="cached", description="cached", slug="cached")
    context = load_project_context(tmp_path)
    if context.paths.indexes_root.exists():
        import shutil

        shutil.rmtree(context.paths.indexes_root)
    assert [item.id for item in list_tasks(tmp_path)] == [task.id]

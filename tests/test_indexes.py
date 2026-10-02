from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.sidecars import DependencyRequirement, RequirementCollection
from taskledger.domain.task import IntroductionRecord
from taskledger.storage.indexes import (
    rebuild_v2_indexes,
    remove_introduction_index_entry,
    update_dependency_index_entry,
    update_introduction_index_entry,
)
from taskledger.storage.task_store import (
    resolve_v2_paths,
    save_introduction,
    save_requirements,
)
from tests.support.builders import init_workspace


def _read(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_incremental_index_updates_match_rebuild(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    paths = resolve_v2_paths(tmp_path)
    runner = CliRunner()
    for slug in ("required", "dependent"):
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                slug,
                "--description",
                "Index parity task.",
            ],
        )
        assert result.exit_code == 0, result.output
    rebuild_v2_indexes(paths)
    intro = IntroductionRecord(
        id="intro-0001",
        slug="release",
        title="Release",
        body="Release context",
    )

    save_introduction(tmp_path, intro)
    update_introduction_index_entry(paths, intro)
    update_dependency_index_entry(paths, "task-0001", ["task-0002"])
    save_requirements(
        tmp_path,
        RequirementCollection(
            task_id="task-0001",
            requirements=(DependencyRequirement(task_id="task-0002"),),
        ),
    )

    incremental = {
        "introductions": _read(paths.introductions_index_path),
        "dependencies": _read(paths.dependencies_index_path),
    }
    rebuild_v2_indexes(paths)
    rebuilt = {
        "introductions": _read(paths.introductions_index_path),
        "dependencies": _read(paths.dependencies_index_path),
    }
    assert incremental == rebuilt

    remove_introduction_index_entry(paths, intro.id)
    assert _read(paths.introductions_index_path) == []


def _create_task_for_index_test(workspace: Path, slug: str):
    from taskledger.services.task_lifecycle import create_task

    return create_task(
        workspace,
        title=slug,
        description="Index writer test.",
        slug=slug,
    )


def test_canonical_writers_update_requirement_and_introduction_indexes(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = _create_task_for_index_test(tmp_path, "index-writers")
    paths = resolve_v2_paths(tmp_path)

    save_requirements(
        tmp_path,
        RequirementCollection(
            task_id=task.id,
            requirements=(DependencyRequirement(task_id="task-0099"),),
        ),
    )
    introduction = IntroductionRecord(
        id="intro-0001",
        slug="indexed-introduction",
        title="Indexed introduction",
        body="Context.",
    )
    save_introduction(tmp_path, introduction)

    dependencies = _read(paths.dependencies_index_path)
    dependency = next(item for item in dependencies if item["task_id"] == task.id)
    assert dependency["requirements"] == ["task-0099"]
    assert _read(paths.introductions_index_path) == [
        {
            "id": introduction.id,
            "slug": introduction.slug,
            "title": introduction.title,
        }
    ]


def test_lock_writers_update_active_lock_and_sidecar_indexes(tmp_path: Path) -> None:
    from taskledger.domain.actor import ActorRef
    from taskledger.domain.lock import TaskLock
    from taskledger.storage.sidecar_index import load_sidecar_index
    from taskledger.storage.task_store import (
        remove_lock_from_paths,
        save_lock_from_paths,
    )

    init_workspace(tmp_path)
    task = _create_task_for_index_test(tmp_path, "lock-index")
    paths = resolve_v2_paths(tmp_path)
    lock = TaskLock(
        lock_id="lock-test",
        task_id=task.id,
        stage="planning",
        run_id="run-test",
        created_at="2026-10-02T12:00:00+00:00",
        expires_at="2099-12-31T23:59:59+00:00",
        reason="test",
        holder=ActorRef(actor_name="test", tool="pytest"),
    )

    save_lock_from_paths(paths, task.id, lock, create_only=True)
    assert _read(paths.active_locks_index_path) == [lock.to_dict()]
    assert load_sidecar_index(paths)[task.id]["locks"]["has_lock"] is True

    remove_lock_from_paths(paths, task.id)
    assert _read(paths.active_locks_index_path) == []
    assert load_sidecar_index(paths)[task.id]["locks"]["has_lock"] is False

    from dataclasses import replace

    from taskledger.storage import sidecar_index
    from taskledger.storage.task_store import task_lock_path

    failed_lock = replace(lock, lock_id="lock-failed")
    with patch.object(
        sidecar_index, "write_json", side_effect=OSError("index unavailable")
    ):
        save_lock_from_paths(paths, task.id, failed_lock, create_only=True)

    assert task_lock_path(paths, task.id).is_file()
    assert (paths.indexes_dir / ".sidecar_index.dirty").is_file()
    from taskledger.services.doctor import inspect_v2_indexes

    assert "sidecar_index" in inspect_v2_indexes(tmp_path)["dirty_indexes"]


def test_index_write_failure_marks_dirty_without_rebuilding(
    tmp_path: Path,
) -> None:
    from dataclasses import replace as replace_task

    from taskledger.services.task_lifecycle import create_task
    from taskledger.storage import indexes, task_index
    from taskledger.storage.task_store import resolve_task, save_task

    init_workspace(tmp_path)
    task = create_task(
        tmp_path, title="Before", description="Before.", slug="dirty-index"
    )
    paths = resolve_v2_paths(tmp_path)

    with (
        patch.object(
            task_index, "write_json", side_effect=OSError("index unavailable")
        ),
        patch.object(task_index, "rebuild_task_index") as task_rebuild,
    ):
        save_task(tmp_path, replace_task(task, title="After"))

    task_rebuild.assert_not_called()
    assert resolve_task(tmp_path, task.id).title == "After"
    assert (paths.indexes_dir / ".task_index.dirty").is_file()

    with (
        patch.object(indexes, "write_json", side_effect=OSError("index unavailable")),
        patch.object(indexes, "rebuild_v2_indexes") as full_rebuild,
    ):
        save_requirements(
            tmp_path,
            RequirementCollection(
                task_id=task.id,
                requirements=(DependencyRequirement(task_id="task-0098"),),
            ),
        )

    full_rebuild.assert_not_called()
    assert (paths.indexes_dir / ".dependencies.dirty").is_file()


def test_path_bound_sidecar_readers_do_not_resolve_project_paths(
    tmp_path: Path,
) -> None:
    from taskledger.storage.task_store import (
        list_code_reviews_from_paths,
        list_handoffs_with_errors_from_paths,
        load_requirements_from_paths,
    )

    init_workspace(tmp_path)
    task = _create_task_for_index_test(tmp_path, "bound-readers")
    paths = resolve_v2_paths(tmp_path)

    with patch(
        "taskledger.storage.task_store.resolve_v2_paths", side_effect=AssertionError
    ):
        assert load_requirements_from_paths(paths, task.id).requirements == ()
        assert list_code_reviews_from_paths(paths, task.id) == []
        assert list_handoffs_with_errors_from_paths(paths, task.id) == ([], [])

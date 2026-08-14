from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from filelock import FileLock

from taskledger.domain.task import IntroductionRecord
from taskledger.storage.common import load_json_array, write_json
from taskledger.storage.task_store import (
    V2Paths,
    list_introductions,
    list_tasks,
    load_active_locks,
    load_requirements,
)

T = TypeVar("T")


def _update_index(
    index_path: Path,
    update: Callable[[list[dict[str, object]]], T],
) -> T:
    """Serialize a read-modify-write update for one derived index."""

    with FileLock(f"{index_path}.lock"):
        entries = load_json_array(index_path, label=f"index {index_path.name}")
        result = update(entries)
        write_json(index_path, entries)
        return result


def rebuild_v2_indexes(paths: V2Paths) -> dict[str, int]:
    from taskledger.storage.sidecar_index import rebuild_sidecar_index
    from taskledger.storage.task_index import rebuild_task_index

    tasks = list_tasks(paths.workspace_root)
    introductions = list_introductions(paths.workspace_root)
    locks = load_active_locks(paths.workspace_root)
    dependencies = [
        {
            "task_id": task.id,
            "requirements": [
                item.task_id
                for item in load_requirements(
                    paths.workspace_root, task.id
                ).requirements
            ],
        }
        for task in tasks
    ]
    write_json(
        paths.introductions_index_path,
        [
            {"id": intro.id, "slug": intro.slug, "title": intro.title}
            for intro in introductions
        ],
    )
    write_json(paths.active_locks_index_path, [lock.to_dict() for lock in locks])
    write_json(paths.dependencies_index_path, dependencies)

    task_index_counts = rebuild_task_index(paths)
    sidecar_counts = rebuild_sidecar_index(paths)
    return {
        "introductions": len(introductions),
        "locks": len(locks),
        "dependencies": len(dependencies),
        **task_index_counts,
        **sidecar_counts,
    }


def update_dependency_index_entry(
    paths: V2Paths,
    task_id: str,
    requirement_task_ids: list[str],
) -> None:
    """Update one task entry in the dependency index.

    Reads the existing index, updates or inserts the entry for task_id,
    and atomically rewrites the index file.
    """
    index_path = paths.dependencies_index_path

    def update(entries: list[dict[str, object]]) -> None:
        for entry in entries:
            if entry.get("task_id") == task_id:
                entry["requirements"] = list(requirement_task_ids)
                return
        entries.append({"task_id": task_id, "requirements": list(requirement_task_ids)})

    _update_index(index_path, update)


def update_introduction_index_entry(
    paths: V2Paths,
    introduction: IntroductionRecord,
) -> None:
    """Update one entry in the introductions index.

    Reads the existing index, updates or inserts the entry,
    and atomically rewrites the index file.
    """
    index_path = paths.introductions_index_path
    entry_data: dict[str, object] = {
        "id": introduction.id,
        "slug": introduction.slug,
        "title": introduction.title,
    }

    def update(entries: list[dict[str, object]]) -> None:
        for entry in entries:
            if entry.get("id") == introduction.id:
                entry.update(entry_data)
                return
        entries.append(entry_data)

    _update_index(index_path, update)


def remove_introduction_index_entry(
    paths: V2Paths,
    introduction_id: str,
) -> None:
    """Remove one entry from the introductions index.

    Reads the existing index, removes the entry,
    and atomically rewrites the index file.
    """
    index_path = paths.introductions_index_path

    def update(entries: list[dict[str, object]]) -> None:
        entries[:] = [entry for entry in entries if entry.get("id") != introduction_id]

    _update_index(index_path, update)

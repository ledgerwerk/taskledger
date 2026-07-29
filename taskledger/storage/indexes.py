from __future__ import annotations

from taskledger.storage.common import write_json
from taskledger.storage.task_store import (
    V2Paths,
    list_introductions,
    list_tasks,
    load_active_locks,
    load_requirements,
)


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
    from taskledger.storage.common import read_json

    index_path = paths.dependencies_index_path
    entries: list[dict[str, object]] = read_json(index_path) or []
    updated = False
    for entry in entries:
        if entry.get("task_id") == task_id:
            entry["requirements"] = requirement_task_ids
            updated = True
            break
    if not updated:
        entries.append({"task_id": task_id, "requirements": requirement_task_ids})
    write_json(index_path, entries)


def update_introduction_index_entry(
    paths: V2Paths,
    introduction: object,
) -> None:
    """Update one entry in the introductions index.

    Reads the existing index, updates or inserts the entry,
    and atomically rewrites the index file.
    """
    from taskledger.storage.common import read_json

    index_path = paths.introductions_index_path
    entries: list[dict[str, object]] = read_json(index_path) or []
    entry_data = {
        "id": introduction.id,
        "slug": introduction.slug,
        "title": introduction.title,
    }
    updated = False
    for entry in entries:
        if entry.get("id") == introduction.id:
            entry.update(entry_data)
            updated = True
            break
    if not updated:
        entries.append(entry_data)
    write_json(index_path, entries)


def remove_introduction_index_entry(
    paths: V2Paths,
    introduction_id: str,
) -> None:
    """Remove one entry from the introductions index.

    Reads the existing index, removes the entry,
    and atomically rewrites the index file.
    """
    from taskledger.storage.common import read_json

    index_path = paths.introductions_index_path
    entries: list[dict[str, object]] = read_json(index_path) or []
    entries = [e for e in entries if e.get("id") != introduction_id]
    write_json(index_path, entries)

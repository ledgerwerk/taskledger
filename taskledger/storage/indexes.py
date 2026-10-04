from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from filelock import FileLock

from taskledger.domain.models import TaskLock
from taskledger.domain.task import IntroductionRecord
from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.common import load_json_array, write_json
from taskledger.storage.task_store import V2Paths

logger = logging.getLogger(__name__)

DirtyIndexName = Literal[
    "task_index",
    "sidecar_index",
    "dependencies",
    "introductions",
    "active_locks",
]


_ALL_DIRTY_INDEX_NAMES: tuple[DirtyIndexName, ...] = (
    "task_index",
    "sidecar_index",
    "dependencies",
    "introductions",
    "active_locks",
)


def _dirty_index_path(paths: V2Paths, index_name: DirtyIndexName) -> Path:
    return paths.indexes_dir / f".{index_name}.dirty"


def index_is_dirty(paths: V2Paths, index_name: DirtyIndexName) -> bool:
    return _dirty_index_path(paths, index_name).exists()


def mark_index_dirty(
    paths: V2Paths, index_name: DirtyIndexName, *, task_id: str | None = None
) -> None:
    marker = _dirty_index_path(paths, index_name)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(marker, f"{task_id or '*'}\n")
    except Exception:
        logger.warning("Failed to mark %s dirty", index_name, exc_info=True)


def clear_index_dirty(paths: V2Paths, index_name: DirtyIndexName) -> None:
    _dirty_index_path(paths, index_name).unlink(missing_ok=True)


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
    from taskledger.storage.locks import lock_is_expired
    from taskledger.storage.sidecar_index import rebuild_sidecar_index
    from taskledger.storage.task_index import rebuild_task_index
    from taskledger.storage.task_store import (
        list_introductions_from_paths,
        list_tasks_from_paths,
        load_lock_records_from_paths,
        load_requirements_from_paths,
    )

    tasks = list_tasks_from_paths(paths)
    introductions = list_introductions_from_paths(paths)
    locks = [
        lock
        for lock in load_lock_records_from_paths(paths)
        if not lock_is_expired(lock)
    ]
    dependencies = []
    for task in tasks:
        requirements = load_requirements_from_paths(paths, task.id).requirements
        dependencies.append(
            {
                "task_uuid": task.task_uuid,
                "task_id": task.id,
                "requirements": [
                    {
                        "task_uuid": item.required_task_uuid,
                        "task_id": item.required_task_id or item.task_id,
                    }
                    for item in requirements
                ],
            }
        )
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
    for index_name in _ALL_DIRTY_INDEX_NAMES:
        clear_index_dirty(paths, index_name)
    return {
        "introductions": len(introductions),
        "locks": len(locks),
        "dependencies": len(dependencies),
        **task_index_counts,
        **sidecar_counts,
    }


def load_active_locks_from_index(paths: V2Paths) -> list[TaskLock]:
    from dataclasses import replace

    from taskledger.storage.locks import lock_is_expired
    from taskledger.storage.task_identity import (
        AMBIGUOUS_LEGACY_TASK_REF,
        task_identity_for_stored_ref,
    )
    from taskledger.storage.task_store import load_lock_records_from_paths

    path = paths.active_locks_index_path
    if index_is_dirty(paths, "active_locks") or not path.is_file():
        return _rebuild_active_lock_index(paths, load_lock_records_from_paths)
    try:
        locks = [
            TaskLock.from_dict(entry)
            for entry in load_json_array(path, label="active locks index")
        ]
    except LaunchError:
        return _rebuild_active_lock_index(paths, load_lock_records_from_paths)

    normalized: list[TaskLock] = []
    needs_rebuild = False
    for lock in locks:
        try:
            identity = task_identity_for_stored_ref(
                paths, task_id=lock.task_id, task_uuid=lock.task_uuid
            )
        except LaunchError as exc:
            if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                raise
            normalized.append(lock)
            continue
        updated = replace(
            lock, task_id=identity.task_id, task_uuid=str(identity.task_uuid)
        )
        needs_rebuild = needs_rebuild or updated != lock
        normalized.append(updated)
    if needs_rebuild:
        return _rebuild_active_lock_index(paths, load_lock_records_from_paths)
    return [lock for lock in normalized if not lock_is_expired(lock)]


def _rebuild_active_lock_index(
    paths: V2Paths,
    load_locks: Callable[[V2Paths], list[TaskLock]],
) -> list[TaskLock]:
    from taskledger.storage.locks import lock_is_expired

    locks = [lock for lock in load_locks(paths) if not lock_is_expired(lock)]
    write_json(paths.active_locks_index_path, [lock.to_dict() for lock in locks])
    clear_index_dirty(paths, "active_locks")
    return locks


def _best_effort_update_index(
    paths: V2Paths,
    index_name: DirtyIndexName,
    index_path: Path,
    update: Callable[[list[dict[str, object]]], None],
    *,
    task_id: str | None = None,
) -> None:
    if index_is_dirty(paths, index_name):
        return
    if not index_path.is_file():
        mark_index_dirty(paths, index_name, task_id=task_id)
        return
    try:
        _update_index(index_path, update)
    except Exception:
        mark_index_dirty(paths, index_name, task_id=task_id)
        logger.warning("Failed to update %s index", index_name, exc_info=True)


def update_dependency_index_entry(
    paths: V2Paths,
    task_id: str,
    requirement_task_ids: list[str],
) -> None:
    """Update one dependency entry using UUID identities where resolvable."""
    from taskledger.errors import LaunchError
    from taskledger.storage.task_identity import task_identity_for_ref

    try:
        owner = task_identity_for_ref(paths, task_id)
    except LaunchError:
        mark_index_dirty(paths, "dependencies", task_id=task_id)
        return
    owner_uuid = str(owner.task_uuid)
    requirement_entries: list[dict[str, object]] = []
    for requirement_ref in requirement_task_ids:
        try:
            requirement = task_identity_for_ref(paths, requirement_ref)
        except LaunchError:
            requirement_entries.append({"task_uuid": None, "task_id": requirement_ref})
        else:
            requirement_entries.append(
                {
                    "task_uuid": str(requirement.task_uuid),
                    "task_id": requirement.task_id,
                }
            )
    entry_data: dict[str, object] = {
        "task_uuid": owner_uuid,
        "task_id": owner.task_id,
        "requirements": requirement_entries,
    }

    def update(entries: list[dict[str, object]]) -> None:
        for index, entry in enumerate(entries):
            if entry.get("task_uuid") == owner_uuid:
                entries[index] = entry_data
                return
        entries.append(entry_data)

    _best_effort_update_index(
        paths,
        "dependencies",
        paths.dependencies_index_path,
        update,
        task_id=owner.task_id,
    )


def remove_dependency_index_entry(paths: V2Paths, task_id: str) -> None:
    """Remove one dependency entry by its stable task identity."""
    from taskledger.errors import LaunchError
    from taskledger.storage.task_identity import task_identity_for_ref

    try:
        task_uuid = str(task_identity_for_ref(paths, task_id).task_uuid)
    except LaunchError:
        task_uuid = None

    def update(entries: list[dict[str, object]]) -> None:
        entries[:] = [
            entry
            for entry in entries
            if not (
                entry.get("task_uuid") == task_uuid
                if task_uuid is not None
                else entry.get("task_id") == task_id
            )
        ]

    _best_effort_update_index(
        paths,
        "dependencies",
        paths.dependencies_index_path,
        update,
        task_id=task_id,
    )


def update_introduction_index_entry(
    paths: V2Paths,
    introduction: IntroductionRecord,
) -> None:
    """Update one entry in the introductions index."""
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

    _best_effort_update_index(
        paths,
        "introductions",
        paths.introductions_index_path,
        update,
    )


def remove_introduction_index_entry(paths: V2Paths, introduction_id: str) -> None:
    """Remove one entry from the introductions index."""

    def update(entries: list[dict[str, object]]) -> None:
        entries[:] = [entry for entry in entries if entry.get("id") != introduction_id]

    _best_effort_update_index(
        paths,
        "introductions",
        paths.introductions_index_path,
        update,
    )


def update_active_lock_index_entry(paths: V2Paths, lock: TaskLock) -> None:
    """Insert or replace one active-lock index entry."""
    entry_data = lock.to_dict()

    def update(entries: list[dict[str, object]]) -> None:
        for index, entry in enumerate(entries):
            if entry.get("task_uuid") == lock.task_uuid:
                entries[index] = entry_data
                return
        entries.append(entry_data)

    _best_effort_update_index(
        paths,
        "active_locks",
        paths.active_locks_index_path,
        update,
        task_id=lock.task_id,
    )


def remove_active_lock_index_entry(paths: V2Paths, task_id: str) -> None:
    """Remove an active-lock entry by stable UUID identity."""
    from taskledger.errors import LaunchError
    from taskledger.storage.task_identity import task_identity_for_ref

    try:
        task_uuid = str(task_identity_for_ref(paths, task_id).task_uuid)
    except LaunchError:
        task_uuid = None

    def update(entries: list[dict[str, object]]) -> None:
        entries[:] = [
            entry
            for entry in entries
            if not (
                entry.get("task_uuid") == task_uuid
                if task_uuid is not None
                else entry.get("task_id") == task_id
            )
        ]

    _best_effort_update_index(
        paths,
        "active_locks",
        paths.active_locks_index_path,
        update,
        task_id=task_id,
    )

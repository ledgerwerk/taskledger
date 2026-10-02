from __future__ import annotations

import re
from pathlib import Path

from taskledger.domain.models import (
    ActorRef,
    ReleaseRecord,
    TaskEvent,
    TaskRecord,
)
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_actor, resolve_harness
from taskledger.storage.events import append_event, next_event_id
from taskledger.storage.task_store import (
    list_releases,
    list_tasks,
    resolve_release,
    resolve_task,
    resolve_v2_paths,
    save_release,
)
from taskledger.timeutils import utc_now_iso


def tag_release(
    workspace_root: Path,
    *,
    version: str,
    at_task: str,
    note: str | None = None,
    previous_version: str | None = None,
    actor: ActorRef | None = None,
) -> dict[str, object]:
    boundary_task = resolve_task(workspace_root, at_task)
    if boundary_task.status_stage != "done":
        raise LaunchError(
            f"Release boundaries must point to done tasks: {boundary_task.id} is "
            f"{boundary_task.status_stage}."
        )
    existing = list_releases(workspace_root)
    if any(item.version == version for item in existing):
        raise LaunchError(f"Release version already exists: {version}")

    boundary_number = _task_number(boundary_task.id)
    previous = _resolve_previous_release(
        existing,
        boundary_number,
        explicit=previous_version,
    )
    release_actor = actor or resolve_actor(workspace_root=workspace_root)
    task_count = _count_done_tasks_between(
        workspace_root,
        lower_task_id=previous.boundary_task_id if previous is not None else None,
        upper_task_id=boundary_task.id,
    )
    release = ReleaseRecord(
        version=version,
        boundary_task_id=boundary_task.id,
        created_by=release_actor,
        note=note,
        task_count=task_count if previous is not None else None,
        previous_version=previous.version if previous is not None else None,
    )
    save_release(workspace_root, release)
    event_id = _append_release_event(
        workspace_root,
        task_id=boundary_task.id,
        event_name="release.tagged",
        data={
            "version": release.version,
            "boundary_task_id": release.boundary_task_id,
            "note": release.note,
            "previous_version": release.previous_version,
        },
    )
    paths = resolve_v2_paths(workspace_root)
    return {
        "kind": "release",
        "ledger_ref": paths.ledger_ref,
        "release": release.to_dict(),
        "boundary_task": _task_summary(boundary_task),
        "events": [event_id] if event_id is not None else [],
    }


def list_release_records(workspace_root: Path) -> list[dict[str, object]]:
    return [item.to_dict() for item in list_releases(workspace_root)]


def show_release(workspace_root: Path, version: str) -> dict[str, object]:
    release = resolve_release(workspace_root, version)
    boundary_task = resolve_task(workspace_root, release.boundary_task_id)
    paths = resolve_v2_paths(workspace_root)
    return {
        "kind": "release",
        "ledger_ref": paths.ledger_ref,
        "release": release.to_dict(),
        "boundary_task": _task_summary(boundary_task),
    }


def _resolve_previous_release(
    releases: list[ReleaseRecord],
    boundary_number: int,
    *,
    explicit: str | None,
) -> ReleaseRecord | None:
    if explicit is not None:
        for release in releases:
            if release.version != explicit:
                continue
            if _task_number(release.boundary_task_id) >= boundary_number:
                raise LaunchError(
                    f"Previous release {explicit} must be before the new boundary task."
                )
            return release
        raise LaunchError(f"Release not found: {explicit}")
    candidates = [
        release
        for release in releases
        if _task_number(release.boundary_task_id) < boundary_number
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: _task_number(item.boundary_task_id))


def _append_release_event(
    workspace_root: Path,
    *,
    task_id: str,
    event_name: str,
    data: dict[str, object],
) -> str | None:
    from taskledger.services.event_logging import event_logging_enabled

    if not event_logging_enabled(workspace_root):
        return None

    paths = resolve_v2_paths(workspace_root)
    timestamp = utc_now_iso()
    event_id = next_event_id(paths.events_dir, timestamp)
    append_event(
        paths.events_dir,
        TaskEvent(
            ts=timestamp,
            event=event_name,
            task_id=task_id,
            actor=resolve_actor(workspace_root=workspace_root),
            harness=resolve_harness(
                workspace_root=workspace_root,
                cwd=workspace_root,
            ),
            event_id=event_id,
            data=data,
        ),
    )
    return event_id


def _task_summary(task: TaskRecord) -> dict[str, object]:
    return {
        "task_id": task.id,
        "slug": task.slug,
        "title": task.title,
        "status_stage": task.status_stage,
        "archived": task.archived_at is not None,
    }


def _count_done_tasks_between(
    workspace_root: Path,
    *,
    lower_task_id: str | None,
    upper_task_id: str,
) -> int:
    lower_number = _task_number(lower_task_id) if lower_task_id is not None else 0
    upper_number = _task_number(upper_task_id)
    return sum(
        1
        for task in list_tasks(workspace_root)
        if task.status_stage == "done"
        and lower_number < _task_number(task.id) <= upper_number
    )


def _task_number(task_id: str) -> int:
    match = re.fullmatch(r"task-(\d+)", task_id)
    if match is None:
        raise LaunchError(f"Release ranges require numeric task ids: {task_id}")
    return int(match.group(1))


__all__ = [
    "list_release_records",
    "show_release",
    "tag_release",
]

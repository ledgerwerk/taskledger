"""Durable task summary index (tasks.json).

This is a derived index. If absent, malformed, or stale, it is rebuilt from
canonical Markdown/YAML records. It is never the authoritative source of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from taskledger.domain._model_utils import (
    _optional_int,
    _optional_string,
    _string_tuple,
)
from taskledger.domain.states import TaskStatusStage
from taskledger.domain.task import TaskRecord
from taskledger.storage.common import write_json
from taskledger.storage.task_store import (
    V2Paths,
    _load_task,
    task_markdown_path,
)

logger = logging.getLogger(__name__)

TaskVisibility = Literal["visible", "archived", "all"]

TASK_INDEX_FILENAME = "tasks.json"
TASK_INDEX_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TaskSummaryRecord:
    id: str
    slug: str
    title: str
    status_stage: TaskStatusStage
    priority: str | None
    labels: tuple[str, ...]
    owner: str | None
    created_at: str
    updated_at: str
    description_summary: str | None
    latest_plan_version: int | None
    accepted_plan_version: int | None
    latest_planning_run: str | None
    latest_implementation_run: str | None
    latest_validation_run: str | None
    archived_at: str | None
    closed_at: str | None
    path: str
    size: int
    mtime_ns: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "status_stage": self.status_stage,
            "priority": self.priority,
            "labels": list(self.labels),
            "owner": self.owner,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description_summary": self.description_summary,
            "latest_plan_version": self.latest_plan_version,
            "accepted_plan_version": self.accepted_plan_version,
            "latest_planning_run": self.latest_planning_run,
            "latest_implementation_run": self.latest_implementation_run,
            "latest_validation_run": self.latest_validation_run,
            "archived_at": self.archived_at,
            "closed_at": self.closed_at,
            "path": self.path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TaskSummaryRecord:
        size_raw = data.get("size")
        mtime_raw = data.get("mtime_ns")
        return cls(
            id=str(data.get("id", "")),
            slug=str(data.get("slug", "")),
            title=str(data.get("title", "")),
            status_stage=str(data.get("status_stage", "draft")),  # type: ignore[arg-type]
            priority=_optional_string(data.get("priority")),
            labels=_string_tuple(data.get("labels")),
            owner=_optional_string(data.get("owner")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            description_summary=_optional_string(data.get("description_summary")),
            latest_plan_version=_optional_int(data.get("latest_plan_version")),
            accepted_plan_version=_optional_int(data.get("accepted_plan_version")),
            latest_planning_run=_optional_string(data.get("latest_planning_run")),
            latest_implementation_run=_optional_string(
                data.get("latest_implementation_run")
            ),
            latest_validation_run=_optional_string(data.get("latest_validation_run")),
            archived_at=_optional_string(data.get("archived_at")),
            closed_at=_optional_string(data.get("closed_at")),
            path=str(data.get("path", "")),
            size=int(size_raw) if isinstance(size_raw, int) else 0,
            mtime_ns=int(mtime_raw) if isinstance(mtime_raw, int) else 0,
        )


def _task_index_path(paths: V2Paths) -> Path:
    return paths.indexes_dir / TASK_INDEX_FILENAME


def _task_summary_from_record(
    task: TaskRecord, rel_path: str, stat_size: int, stat_mtime_ns: int
) -> TaskSummaryRecord:
    return TaskSummaryRecord(
        id=task.id,
        slug=task.slug,
        title=task.title,
        status_stage=task.status_stage,
        priority=task.priority,
        labels=task.labels,
        owner=task.owner,
        created_at=task.created_at,
        updated_at=task.updated_at,
        description_summary=task.description_summary,
        latest_plan_version=task.latest_plan_version,
        accepted_plan_version=task.accepted_plan_version,
        latest_planning_run=task.latest_planning_run,
        latest_implementation_run=task.latest_implementation_run,
        latest_validation_run=task.latest_validation_run,
        archived_at=task.archived_at,
        closed_at=task.closed_at,
        path=rel_path,
        size=stat_size,
        mtime_ns=stat_mtime_ns,
    )


def _index_envelope(
    entries: list[dict[str, object]], ledger_ref: str, generated_at: str
) -> dict[str, object]:
    return {
        "schema_version": TASK_INDEX_SCHEMA_VERSION,
        "object_type": "task_index",
        "ledger_ref": ledger_ref,
        "generated_at": generated_at,
        "entries": entries,
    }


def rebuild_task_index(paths: V2Paths) -> dict[str, int]:
    """Rebuild tasks.json from canonical Markdown task files."""
    from taskledger.timeutils import utc_now_iso

    entries: list[dict[str, object]] = []
    task_paths = sorted(paths.tasks_dir.glob("task-*/task.md"))
    for path in task_paths:
        try:
            task = _load_task(path)
            stat = path.stat()
            rel = path.relative_to(paths.ledger_dir).as_posix()
            summary = _task_summary_from_record(
                task, rel, stat.st_size, stat.st_mtime_ns
            )
            entries.append(summary.to_dict())
        except Exception:
            logger.warning("Skipping unparseable task file: %s", path, exc_info=True)

    envelope = _index_envelope(entries, paths.ledger_ref, utc_now_iso())
    write_json(_task_index_path(paths), envelope)
    return {"tasks": len(entries)}


def _read_index(paths: V2Paths) -> dict[str, object] | None:
    """Read the task index file. Returns None if missing or malformed."""
    from taskledger.storage.common import try_load_json_object

    return try_load_json_object(_task_index_path(paths), "task index")


def list_task_summaries(
    paths: V2Paths,
    *,
    visibility: TaskVisibility = "visible",
    statuses: set[str] | None = None,
) -> list[TaskSummaryRecord]:
    """List task summaries from the index, rebuilding if necessary."""
    index = _read_index(paths)
    if index is None:
        rebuild_task_index(paths)
        index = _read_index(paths)
        if index is None:
            return []

    raw_entries = index.get("entries")
    if not isinstance(raw_entries, list):
        rebuild_task_index(paths)
        index = _read_index(paths)
        if index is None:
            return []
        raw_entries = index.get("entries", [])

    results: list[TaskSummaryRecord] = []
    for raw in raw_entries:  # type: ignore[attr-defined]
        if not isinstance(raw, dict):
            continue
        summary = TaskSummaryRecord.from_dict(raw)

        # Visibility filter
        is_archived = summary.archived_at is not None
        if visibility == "visible" and is_archived:
            continue
        if visibility == "archived" and not is_archived:
            continue

        # Status filter
        if statuses is not None and summary.status_stage not in statuses:
            continue

        results.append(summary)

    results.sort(key=lambda s: s.id)
    return results


def resolve_task_summary(
    paths: V2Paths,
    ref: str,
    *,
    include_archived: bool = False,
) -> TaskSummaryRecord:
    """Resolve a task summary by ID or slug from the index."""
    from taskledger.storage.task_store import _normalize_numeric_ref

    normalized_ref = ref.strip().lower()
    normalized_id = _normalize_numeric_ref(normalized_ref, "task")

    summaries = list_task_summaries(paths, visibility="all")

    # ID lookup
    for s in summaries:
        if s.id == ref or s.id == normalized_id:
            if not include_archived and s.archived_at is not None:
                continue
            return s

    # Slug lookup
    visible_matches = [
        s for s in summaries if s.archived_at is None and s.slug == normalized_ref
    ]
    if len(visible_matches) == 1:
        return visible_matches[0]
    if len(visible_matches) > 1:
        raise ValueError(f"Duplicate visible task slug: {ref}")

    if not include_archived:
        raise ValueError(f"Task not found: {ref}")

    archived_matches = [
        s for s in summaries if s.archived_at is not None and s.slug == normalized_ref
    ]
    if len(archived_matches) == 1:
        return archived_matches[0]
    if len(archived_matches) > 1:
        ids = ", ".join(sorted(s.id for s in archived_matches))
        raise ValueError(f"Archived task slug is ambiguous: {ref}. Use one of: {ids}")
    raise ValueError(f"Task not found: {ref}")


def update_task_index_entry(paths: V2Paths, task: TaskRecord) -> None:
    """Write-through update: refresh one task entry in the index."""
    path = task_markdown_path(paths, task.id)
    if not path.exists():
        return
    try:
        stat = path.stat()
    except OSError:
        return
    rel = path.relative_to(paths.ledger_dir).as_posix()
    summary = _task_summary_from_record(task, rel, stat.st_size, stat.st_mtime_ns)
    new_entry = summary.to_dict()

    index = _read_index(paths)
    if index is None:
        rebuild_task_index(paths)
        return

    raw_entries = index.get("entries")
    if not isinstance(raw_entries, list):
        rebuild_task_index(paths)
        return

    found = False
    for i, raw in enumerate(raw_entries):
        if isinstance(raw, dict) and raw.get("id") == task.id:
            raw_entries[i] = new_entry
            found = True
            break
    if not found:
        raw_entries.append(new_entry)

    from taskledger.timeutils import utc_now_iso

    index["entries"] = raw_entries
    index["generated_at"] = utc_now_iso()
    write_json(_task_index_path(paths), index)


def remove_task_index_entry(paths: V2Paths, task_id: str) -> None:
    """Remove a task entry from the index."""
    index = _read_index(paths)
    if index is None:
        return
    raw_entries = index.get("entries")
    if not isinstance(raw_entries, list):
        return
    index["entries"] = [
        e for e in raw_entries if not (isinstance(e, dict) and e.get("id") == task_id)
    ]
    write_json(_task_index_path(paths), index)

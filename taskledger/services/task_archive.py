from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from taskledger.domain.states import (
    ACTIVE_TASK_STAGES,
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_INVALID_TRANSITION,
)
from taskledger.ids import slugify_project_ref
from taskledger.services import tasks as _tasks
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.locks import lock_is_expired, read_lock
from taskledger.storage.task_store import (
    clear_active_task_state,
    list_tasks_by_visibility,
    load_active_task_state,
    resolve_task,
    resolve_v2_paths,
    save_task,
    task_lock_path,
)
from taskledger.timeutils import utc_now_iso


def _archive_allowed_status(task_status: str) -> bool:
    return task_status in {"done", "cancelled"}


def archive_task(
    workspace_root: Path,
    ref: str,
    *,
    reason: str,
    force: bool = False,
) -> dict[str, object]:
    archive_reason = reason.strip()
    if not archive_reason:
        raise _tasks._cli_error("task archive requires --reason.", EXIT_CODE_BAD_INPUT)

    task = resolve_task(workspace_root, ref)
    if task.archived_at is not None:
        return {
            "kind": "task_archived",
            "task_id": task.id,
            "slug": task.slug,
            "archived_at": task.archived_at,
            "changed": False,
        }

    lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task.id))
    if lock is not None and not lock_is_expired(lock):
        raise _tasks._cli_error(
            (
                f"Cannot archive task {task.id}: active {lock.stage} lock "
                f"from {lock.run_id} is still live."
            ),
            EXIT_CODE_INVALID_TRANSITION,
        )

    if task.status_stage in ACTIVE_TASK_STAGES:
        raise _tasks._cli_error(
            f"Cannot archive task {task.id} while status_stage is {task.status_stage}.",
            EXIT_CODE_INVALID_TRANSITION,
        )

    if not _archive_allowed_status(task.status_stage) and not force:
        raise _tasks._cli_error(
            (
                f"task archive only allows done/cancelled by default; "
                f"{task.id} is {task.status_stage}. Use --force with --reason."
            ),
            EXIT_CODE_INVALID_TRANSITION,
        )

    now = utc_now_iso()
    updated = replace(
        task,
        archived_at=now,
        archived_by=_tasks._default_actor(),
        archive_reason=archive_reason,
        updated_at=now,
    )
    save_task(workspace_root, updated)

    active_state = load_active_task_state(workspace_root)
    if (
        active_state is not None
        and active_state.task_id == updated.id
        and updated.status_stage in {"done", "cancelled"}
    ):
        clear_active_task_state(workspace_root)

    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.archived",
        {
            "archived_at": now,
            "reason": archive_reason,
            "force": force,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return {
        "kind": "task_archived",
        "task_id": updated.id,
        "slug": updated.slug,
        "archived_at": updated.archived_at,
        "changed": True,
    }


NONTERMINAL_UNARCHIVE_STALE_STAGES = {"approved", "implemented", "failed_validation"}


def unarchive_task(
    workspace_root: Path,
    ref: str,
    *,
    reason: str,
    slug: str | None = None,
    reopen_for_work: bool = False,
) -> dict[str, object]:
    unarchive_reason = reason.strip()
    if not unarchive_reason:
        raise _tasks._cli_error(
            "task unarchive requires --reason.",
            EXIT_CODE_BAD_INPUT,
        )

    task = resolve_task(workspace_root, ref, include_archived=True)
    if task.archived_at is None:
        return {
            "kind": "task_unarchived",
            "task_id": task.id,
            "slug": task.slug,
            "changed": False,
        }

    if task.status_stage in NONTERMINAL_UNARCHIVE_STALE_STAGES and not reopen_for_work:
        raise _tasks._cli_error(
            (
                f"Cannot unarchive non-terminal archived task {task.id} "
                f"in status {task.status_stage} without selecting recovery mode. "
                "Use --reopen-for-work to restore it as work that must be "
                "re-run; do not validate old implementation evidence directly."
            ),
            EXIT_CODE_INVALID_TRANSITION,
        )

    requested_slug = slugify_project_ref(slug, empty="task") if slug else task.slug
    visible = list_tasks_by_visibility(workspace_root, visibility="visible")
    conflict = next(
        (
            item
            for item in visible
            if item.slug == requested_slug and item.id != task.id
        ),
        None,
    )
    if conflict is not None:
        raise _tasks._cli_error(
            (
                f"Cannot unarchive {task.id}: slug '{requested_slug}' is used by "
                f"{conflict.id}. Retry with --slug NEW_SLUG."
            ),
            EXIT_CODE_INVALID_TRANSITION,
        )

    target_stage = task.status_stage
    stale_validation_blocked = False
    if reopen_for_work and task.status_stage == "implemented":
        target_stage = "failed_validation"
        stale_validation_blocked = True

    now = utc_now_iso()
    extra_notes: tuple[str, ...] = ()
    if stale_validation_blocked:
        extra_notes = (
            (
                "Unarchived from non-terminal state "
                f"{task.status_stage}; "
                "old implementation evidence must not be validated directly."
            ),
        )
    updated = replace(
        task,
        slug=requested_slug,
        status_stage=target_stage,
        archived_at=None,
        archived_by=None,
        archive_reason=None,
        updated_at=now,
        notes=(*task.notes, *extra_notes),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.unarchived",
        {
            "reason": unarchive_reason,
            "slug": requested_slug,
            "reopen_for_work": reopen_for_work,
            "target_stage": target_stage,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    result: dict[str, object] = {
        "kind": "task_unarchived",
        "task_id": updated.id,
        "slug": updated.slug,
        "changed": True,
        "target_stage": target_stage,
        "stale_validation_blocked": stale_validation_blocked,
    }
    return result


def list_archived_task_summaries(
    workspace_root: Path,
    *,
    slug: str | None = None,
) -> list[dict[str, object]]:
    rows = []
    slug_filter = slug.strip().lower() if slug and slug.strip() else None
    for task in list_tasks_by_visibility(workspace_root, visibility="archived"):
        if slug_filter is not None and task.slug != slug_filter:
            continue
        rows.append(
            {
                "id": task.id,
                "slug": task.slug,
                "title": task.title,
                "status_stage": task.status_stage,
                "archived": True,
                "archived_at": task.archived_at,
            }
        )
    return rows

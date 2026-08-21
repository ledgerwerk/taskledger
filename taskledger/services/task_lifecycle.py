"""Task lifecycle operations: create, activate, edit, cancel, close, follow-up, record.

These functions were extracted from services/tasks.py to shrink the monolith.
tasks.py re-exports them for backward compatibility.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from taskledger.domain.models import (
    ActiveTaskState,
    ActorRef,
    CodeChangeRecord,
    FileLink,
    HarnessRef,
    LinkCollection,
    TaskRecord,
    TaskRunRecord,
)
from taskledger.domain.policies import metadata_edit_decision
from taskledger.domain.states import (
    ACTIVE_TASK_STAGES,
    EXIT_CODE_APPROVAL_REQUIRED,
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_INVALID_TRANSITION,
    EXIT_CODE_LOCK_CONFLICT,
    TaskStatusStage,
    normalize_task_status_stage,
    require_transition,
)
from taskledger.errors import LaunchError, LockConflict
from taskledger.ids import next_project_id
from taskledger.services import tasks as _tasks
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.task_store import (
    clear_active_task_state,
    list_runs,
    list_tasks,
    list_tasks_by_visibility,
    load_active_task_state,
    require_v2_layout,
    resolve_task,
    resolve_v2_paths,
    save_active_task_state,
    save_change,
    save_links,
    save_run,
    save_task,
)
from taskledger.timeutils import utc_now_iso

# ---------------------------------------------------------------------------
# Internal helpers exclusive to lifecycle operations
# ---------------------------------------------------------------------------


def _allocate_task_id_and_advance(
    workspace_root: Path, existing_ids: list[str] | None = None
) -> str:
    """Reserve the next task bundle directory using authoritative allocations."""
    from taskledger.storage.task_ids import allocate_task_directory

    task_id, _ = allocate_task_directory(workspace_root)
    return task_id


def _actor_for_active_task(actor_type: str) -> ActorRef:
    if actor_type not in {"agent", "user", "system"}:
        raise _tasks._cli_error(
            f"Unsupported actor type: {actor_type}",
            EXIT_CODE_BAD_INPUT,
        )
    base = _tasks._default_actor()
    return replace(
        base,
        actor_type=cast(Literal["agent", "user", "system"], actor_type),
    )


def _ensure_active_switch_allowed(
    workspace_root: Path,
    task_id: str,
    *,
    force: bool,
    reason: str | None,
) -> None:
    lock = _tasks._current_lock(workspace_root, task_id)
    if lock is None or lock_is_expired(lock):
        return
    if force and reason and reason.strip():
        return
    raise LockConflict(
        f"Active task {task_id} has a live {lock.stage} lock from {lock.run_id}. "
        "Pass --force with --reason to switch or clear the active task.",
        task_id=task_id,
        details={"lock": lock.to_dict()},
        remediation=[
            f"taskledger lock show --task {task_id}",
            (
                'Pass --force --reason "..." only if you intend to leave '
                "the lock in place."
            ),
        ],
    )


def _follow_up_description(
    parent: TaskRecord,
    *,
    description: str | None,
    reason: str | None,
) -> str:
    parts: list[str] = []
    if description is not None and description.strip():
        parts.append(description.strip())
    parts.append(f"Follow-up of {parent.id} ({parent.slug}): {parent.title}.")
    if reason is not None and reason.strip():
        parts.append(f"Reason: {reason.strip()}")
    return "\n\n".join(parts)


def _copy_follow_up_links(
    file_links: Sequence[FileLink],
    *,
    copy_files: bool,
    copy_links: bool,
) -> tuple[FileLink, ...]:
    copied: list[FileLink] = []
    for item in file_links:
        is_external = _is_external_task_link(item)
        if is_external and not copy_links:
            continue
        if not is_external and not copy_files:
            continue
        copied.append(
            FileLink(
                path=item.path,
                kind=item.kind,
                label=item.label,
                required_for_validation=item.required_for_validation,
                target_type=item.target_type,
            )
        )
    return tuple(copied)


def _is_external_task_link(link: FileLink) -> bool:
    return link.kind == "other" or "://" in link.path or link.path.startswith("mailto:")


def _infer_uncancel_target(
    workspace_root: Path,
    task: TaskRecord,
) -> TaskStatusStage:
    validation_run = _tasks._optional_run(
        workspace_root, task, task.latest_validation_run
    )
    if (
        validation_run is not None
        and validation_run.run_type == "validation"
        and validation_run.status in {"failed", "blocked"}
        and validation_run.result in {"failed", "blocked"}
        and _tasks._accepted_plan_record_or_none(workspace_root, task) is not None
    ):
        return "failed_validation"
    implementation_run = _tasks._optional_run(
        workspace_root,
        task,
        task.latest_implementation_run,
    )
    if (
        implementation_run is not None
        and implementation_run.run_type == "implementation"
        and implementation_run.status == "finished"
    ):
        return "implemented"
    if _tasks._accepted_plan_record_or_none(workspace_root, task) is not None:
        return "approved"
    latest_plan = _tasks._latest_plan_or_none(workspace_root, task.id)
    if latest_plan is not None and latest_plan.status == "proposed":
        return "plan_review"
    return "draft"


def _validate_uncancel_target(
    workspace_root: Path,
    task: TaskRecord,
    target: TaskStatusStage,
) -> None:
    if target == "draft":
        return
    if target == "plan_review":
        latest_plan = _tasks._latest_plan_or_none(workspace_root, task.id)
        if latest_plan is None or latest_plan.status != "proposed":
            raise _tasks._cli_error(
                "Uncancel to plan_review requires a proposed plan.",
                EXIT_CODE_INVALID_TRANSITION,
            )
        return
    if target == "approved":
        if _tasks._accepted_plan_record_or_none(workspace_root, task) is None:
            raise _tasks._cli_error(
                "Uncancel to approved requires an accepted plan record.",
                EXIT_CODE_INVALID_TRANSITION,
            )
        return
    if target == "implemented":
        implementation_run = _tasks._optional_run(
            workspace_root,
            task,
            task.latest_implementation_run,
        )
        if (
            implementation_run is None
            or implementation_run.run_type != "implementation"
            or implementation_run.status != "finished"
        ):
            raise _tasks._cli_error(
                ("Uncancel to implemented requires a finished implementation run."),
                EXIT_CODE_INVALID_TRANSITION,
            )
        return
    if target == "failed_validation":
        validation_run = _tasks._optional_run(
            workspace_root, task, task.latest_validation_run
        )
        if _tasks._accepted_plan_record_or_none(workspace_root, task) is None:
            raise _tasks._cli_error(
                "Uncancel to failed_validation requires an accepted plan record.",
                EXIT_CODE_INVALID_TRANSITION,
            )
        if (
            validation_run is None
            or validation_run.run_type != "validation"
            or validation_run.status not in {"failed", "blocked"}
            or validation_run.result not in {"failed", "blocked"}
        ):
            raise _tasks._cli_error(
                (
                    "Uncancel to failed_validation requires a failed or blocked "
                    "validation run."
                ),
                EXIT_CODE_INVALID_TRANSITION,
            )
        return
    raise _tasks._cli_error(f"Invalid uncancel target: {target}", EXIT_CODE_BAD_INPUT)


def _uncancel_resumable_implementation_error(
    task: TaskRecord,
    run: TaskRunRecord,
) -> LaunchError:
    command = (
        f"taskledger implement resume --task {task.id} "
        '--reason "Reacquire implementation lock for existing running run."'
    )
    error = LaunchError(
        (
            f"Task {task.id} is not cancelled; it has a running implementation "
            "run with no active lock."
        ),
        remediation=[command],
        details={"run_id": run.run_id, "status_stage": task.status_stage},
        task_id=task.id,
    )
    error.taskledger_exit_code = EXIT_CODE_INVALID_TRANSITION
    error.taskledger_error_code = "INVALID_TRANSITION"
    return error


# ---------------------------------------------------------------------------
# Public lifecycle operations
# ---------------------------------------------------------------------------


def create_task(
    workspace_root: Path,
    *,
    title: str,
    description: str,
    slug: str | None = None,
    priority: str | None = None,
    labels: tuple[str, ...] = (),
    owner: str | None = None,
) -> TaskRecord:
    from taskledger.storage.project_context import require_mutable_project_context

    require_mutable_project_context(workspace_root)
    paths = require_v2_layout(workspace_root)
    all_tasks = list_tasks(workspace_root)
    visible_tasks = list_tasks_by_visibility(workspace_root, visibility="visible")
    task_slug = _tasks._unique_slug(visible_tasks, slug or title)
    task = TaskRecord(
        id=_allocate_task_id_and_advance(
            workspace_root, [item.id for item in all_tasks]
        ),
        slug=task_slug,
        title=title,
        body=description.strip(),
        description_summary=_tasks._summary_line(description),
        priority=priority,
        labels=tuple(dict.fromkeys(labels)),
        owner=owner,
    )
    save_task(workspace_root, task)
    _tasks._append_event(
        workspace_root,
        task.id,
        "task.created",
        {"slug": task.slug, "title": task.title},
    )
    rebuild_v2_indexes(paths)
    return task


def create_follow_up_task(
    workspace_root: Path,
    parent_ref: str,
    *,
    title: str,
    description: str | None = None,
    slug: str | None = None,
    labels: tuple[str, ...] = (),
    activate: bool = False,
    copy_files: bool = False,
    copy_links: bool = False,
    reason: str | None = None,
) -> dict[str, object]:
    from taskledger.storage.project_context import require_mutable_project_context

    require_mutable_project_context(workspace_root)
    paths = require_v2_layout(workspace_root)
    parent = _tasks._task_with_sidecars(
        workspace_root,
        resolve_task(workspace_root, parent_ref),
    )
    _tasks._ensure_not_archived(parent, operation="create follow-up for")
    if parent.status_stage != "done":
        raise _tasks._cli_error(
            "Follow-up tasks require a done parent task.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    all_tasks = list_tasks(workspace_root)
    visible_tasks = list_tasks_by_visibility(workspace_root, visibility="visible")
    task_slug = _tasks._unique_slug(visible_tasks, slug or title)
    body = _follow_up_description(parent, description=description, reason=reason)
    copied_links = _copy_follow_up_links(
        parent.file_links,
        copy_files=copy_files,
        copy_links=copy_links,
    )
    child = TaskRecord(
        id=_allocate_task_id_and_advance(
            workspace_root, [item.id for item in all_tasks]
        ),
        slug=task_slug,
        title=title,
        body=body,
        description_summary=_tasks._summary_line(body),
        labels=tuple(dict.fromkeys((*labels, "follow-up"))),
        file_links=copied_links,
        parent_task_id=parent.id,
        parent_relation="follow_up",
    )
    save_task(workspace_root, child)
    if copied_links:
        save_links(workspace_root, LinkCollection(task_id=child.id, links=copied_links))
    _tasks._append_event(
        workspace_root,
        parent.id,
        "task.follow_up.created",
        {
            "child_task_id": child.id,
            "child_slug": child.slug,
            "reason": reason,
        },
    )
    _tasks._append_event(
        workspace_root,
        child.id,
        "task.created",
        {
            "slug": child.slug,
            "title": child.title,
            "parent_task_id": parent.id,
            "parent_relation": "follow_up",
        },
    )
    rebuild_v2_indexes(paths)
    if activate:
        activate_task(workspace_root, child.id, reason=reason, actor_type="agent")
    return {
        "kind": "task_follow_up_created",
        "task_id": child.id,
        "slug": child.slug,
        "parent_task_id": parent.id,
        "parent_relation": "follow_up",
        "activated": activate,
        "next_command": (
            "taskledger plan start"
            if activate
            else f'taskledger task activate {child.id} --reason "Start follow-up delta"'
        ),
    }


def list_follow_up_tasks(workspace_root: Path, parent_ref: str) -> list[TaskRecord]:
    parent = resolve_task(workspace_root, parent_ref)
    return [
        task
        for task in list_tasks(workspace_root)
        if task.parent_task_id == parent.id and task.parent_relation == "follow_up"
    ]


def record_completed_task(
    workspace_root: Path,
    *,
    title: str,
    description: str | None = None,
    summary: str,
    slug: str | None = None,
    labels: tuple[str, ...] = (),
    owner: str | None = None,
    changes: tuple[tuple[str, str, str], ...] = (),
    evidence: tuple[str, ...] = (),
    completed_by: ActorRef | None = None,
    recorded_by: ActorRef | None = None,
    harness: HarnessRef | None = None,
    allow_empty_record: bool = False,
    reason: str | None = None,
) -> dict[str, object]:
    """Record a manually completed task directly in done status.

    Creates a task with task_type=recorded, a synthetic finished implementation
    run, code change records, and a finished/passed validation run. Does not
    acquire locks or activate the task.
    """
    if not title.strip():
        raise _tasks._cli_error("Title must not be empty.", EXIT_CODE_BAD_INPUT)
    if not summary.strip():
        raise _tasks._cli_error("Summary must not be empty.", EXIT_CODE_BAD_INPUT)
    if not changes and not evidence and not allow_empty_record:
        raise _tasks._cli_error(
            (
                "At least one --change or --evidence is required. "
                'Use --allow-empty-record --reason "..." to record '
                "changes or evidence."
            ),
            EXIT_CODE_BAD_INPUT,
        )
    if allow_empty_record and not (reason or "").strip():
        raise _tasks._cli_error(
            "--allow-empty-record requires --reason.", EXIT_CODE_BAD_INPUT
        )
    # Validate change inputs
    for raw_path, raw_kind, raw_summary in changes:
        if not raw_path.strip():
            raise _tasks._cli_error(
                "Change path must not be empty.", EXIT_CODE_BAD_INPUT
            )
        if not raw_kind.strip():
            raise _tasks._cli_error(
                "Change kind must not be empty.", EXIT_CODE_BAD_INPUT
            )
        if not raw_summary.strip():
            raise _tasks._cli_error(
                "Change summary must not be empty.", EXIT_CODE_BAD_INPUT
            )

    from taskledger.storage.project_context import require_mutable_project_context

    require_mutable_project_context(workspace_root)
    paths = require_v2_layout(workspace_root)
    all_tasks = list_tasks(workspace_root)
    visible_tasks = list_tasks_by_visibility(workspace_root, visibility="visible")
    task_slug = _tasks._unique_slug(visible_tasks, slug or title)
    now = utc_now_iso()
    resolved_completed_by = completed_by or _tasks._default_actor()
    resolved_recorded_by = recorded_by or _tasks._default_actor()

    task = TaskRecord(
        id=_allocate_task_id_and_advance(
            workspace_root, [item.id for item in all_tasks]
        ),
        slug=task_slug,
        title=title.strip(),
        body=(description or "").strip(),
        description_summary=_tasks._summary_line(description or title),
        labels=tuple(dict.fromkeys(labels)),
        owner=owner,
        status_stage="done",
        task_type="recorded",
        recorded_at=now,
        recorded_by=resolved_recorded_by,
    )
    save_task(workspace_root, task)

    from taskledger.storage.task_store import list_changes as _list_changes

    runs = list_runs(workspace_root, task.id)
    existing_run_ids = [item.run_id for item in runs]

    # Synthetic finished implementation run
    impl_run = TaskRunRecord(
        run_id=next_project_id("run", existing_run_ids),
        task_id=task.id,
        run_type="implementation",
        status="finished",
        started_at=now,
        finished_at=now,
        actor=resolved_completed_by,
        harness=harness,
        summary=summary.strip(),
        worklog=("Recorded completed work after it was performed outside taskledger.",),
    )
    save_run(workspace_root, impl_run)
    existing_run_ids.append(impl_run.run_id)

    # Code change records
    change_ids: list[str] = []
    all_changes = _list_changes(workspace_root, task.id)
    existing_change_ids = [item.change_id for item in all_changes]
    for raw_path, raw_kind, raw_summary in changes:
        change = CodeChangeRecord(
            change_id=next_project_id("change", existing_change_ids),
            task_id=task.id,
            implementation_run=impl_run.run_id,
            timestamp=now,
            kind=raw_kind.strip(),
            path=raw_path.strip(),
            summary=raw_summary.strip(),
        )
        save_change(workspace_root, change)
        change_ids.append(change.change_id)
        existing_change_ids.append(change.change_id)

    # Update implementation run with change refs
    if change_ids:
        impl_run = replace(impl_run, change_refs=tuple(change_ids))
        save_run(workspace_root, impl_run)

    # Synthetic finished/passed validation run if evidence exists
    validation_run: TaskRunRecord | None = None
    if evidence:
        validation_run = TaskRunRecord(
            run_id=next_project_id("run", existing_run_ids),
            task_id=task.id,
            run_type="validation",
            status="finished",
            started_at=now,
            finished_at=now,
            actor=resolved_completed_by,
            harness=harness,
            based_on_implementation_run=impl_run.run_id,
            summary="Recorded validation evidence for manually completed work.",
            evidence=evidence,
            result="passed",
        )
        save_run(workspace_root, validation_run)

    # Update task with run and change refs
    updated = replace(
        task,
        latest_implementation_run=impl_run.run_id,
        latest_validation_run=validation_run.run_id if validation_run else None,
        code_change_log_refs=tuple(change_ids),
    )
    save_task(workspace_root, updated)

    _tasks._append_event(
        workspace_root,
        task.id,
        "task.created",
        {"slug": task.slug, "title": task.title, "task_type": "recorded"},
    )
    _tasks._append_event(
        workspace_root,
        task.id,
        "task.recorded",
        {
            "task_type": "recorded",
            "recorded_at": now,
            "recorded_by": resolved_recorded_by.to_dict(),
        },
    )
    for cid in change_ids:
        _tasks._append_event(
            workspace_root,
            task.id,
            "change.logged",
            {"change_id": cid},
        )
    _tasks._append_event(
        workspace_root,
        task.id,
        "implementation.finished",
        {"run_id": impl_run.run_id, "recorded": True},
    )
    if validation_run is not None:
        _tasks._append_event(
            workspace_root,
            task.id,
            "validation.finished",
            {
                "run_id": validation_run.run_id,
                "result": "passed",
                "recorded": True,
            },
        )

    rebuild_v2_indexes(paths)

    return {
        "kind": "recorded_task",
        "task_id": task.id,
        "slug": task.slug,
        "status_stage": "done",
        "task_type": "recorded",
        "implementation_run_id": impl_run.run_id,
        "validation_run_id": validation_run.run_id if validation_run else None,
        "change_ids": change_ids,
        "evidence": list(evidence),
        "next_command": f"taskledger task show {task.id}",
    }


def activate_task(
    workspace_root: Path,
    ref: str,
    *,
    reason: str | None = None,
    actor_type: str = "user",
    force: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, ref)
    _tasks._ensure_not_archived(task, operation="activate")
    previous = load_active_task_state(workspace_root)
    previous_task_id = previous.task_id if previous is not None else None
    if previous_task_id == task.id and previous is not None:
        return _tasks._active_task_payload(
            workspace_root,
            task,
            state=previous,
            changed=False,
            previous_task_id=previous.previous_task_id,
        )
    if previous_task_id is not None:
        _ensure_active_switch_allowed(
            workspace_root,
            previous_task_id,
            force=force,
            reason=reason,
        )
    state = ActiveTaskState(
        task_id=task.id,
        activated_by=_actor_for_active_task(actor_type),
        reason=reason,
        previous_task_id=previous_task_id,
    )
    save_active_task_state(workspace_root, state)
    if previous_task_id is not None:
        _tasks._append_event(
            workspace_root,
            previous_task_id,
            "task.deactivated",
            {"reason": reason, "next_task_id": task.id, "forced": force},
        )
    _tasks._append_event(
        workspace_root,
        task.id,
        "task.activated",
        {"reason": reason, "previous_task_id": previous_task_id, "forced": force},
    )
    return _tasks._active_task_payload(
        workspace_root,
        task,
        state=state,
        changed=True,
        previous_task_id=previous_task_id,
    )


def deactivate_task(
    workspace_root: Path,
    *,
    reason: str,
    actor_type: str = "user",
    force: bool = False,
) -> dict[str, object]:
    return clear_active_task(
        workspace_root,
        reason=reason,
        actor_type=actor_type,
        force=force,
    )


def clear_active_task(
    workspace_root: Path,
    *,
    reason: str,
    actor_type: str = "user",
    force: bool = False,
) -> dict[str, object]:
    state = load_active_task_state(workspace_root)
    if state is None:
        from taskledger.errors import NoActiveTask

        raise NoActiveTask()
    _ensure_active_switch_allowed(
        workspace_root,
        state.task_id,
        force=force,
        reason=reason,
    )
    from taskledger.storage.task_store import (
        resolve_active_task as storage_resolve_active_task,
    )

    task = storage_resolve_active_task(workspace_root)
    clear_active_task_state(workspace_root)
    _tasks._append_event(
        workspace_root,
        task.id,
        "task.deactivated",
        {"reason": reason, "forced": force, "actor_type": actor_type},
    )
    return _tasks._active_task_payload(
        workspace_root,
        task,
        state=state,
        changed=True,
        previous_task_id=state.previous_task_id,
        active=False,
    )


def edit_task(
    workspace_root: Path,
    ref: str,
    *,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    owner: str | None = None,
    add_labels: tuple[str, ...] = (),
    remove_labels: tuple[str, ...] = (),
    add_notes: tuple[str, ...] = (),
) -> TaskRecord:
    task = resolve_task(workspace_root, ref)
    _tasks._ensure_not_archived(task, operation="edit")
    _tasks._enforce_decision(
        metadata_edit_decision(task, _tasks._current_lock(workspace_root, task.id))
    )
    labels = [item for item in task.labels if item not in set(remove_labels)]
    for label in add_labels:
        if label not in labels:
            labels.append(label)
    notes = (*task.notes, *[note for note in add_notes if note])
    updated = replace(
        task,
        title=title or task.title,
        body=description.strip() if description is not None else task.body,
        description_summary=(
            _tasks._summary_line(description)
            if description is not None
            else task.description_summary
        ),
        priority=priority or task.priority,
        owner=owner or task.owner,
        labels=tuple(labels),
        notes=notes,
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.updated",
        {"title": updated.title},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


def cancel_task(
    workspace_root: Path,
    ref: str,
    *,
    reason: str | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, ref)
    _tasks._ensure_not_archived(task, operation="cancel")
    require_transition(task.status_stage, "cancelled")
    from taskledger.storage.locks import read_lock
    from taskledger.storage.task_store import task_lock_path

    lock_path = task_lock_path(resolve_v2_paths(workspace_root), task.id)
    lock = read_lock(lock_path)
    if lock is not None:
        _tasks._release_lock(
            workspace_root,
            task=task,
            expected_stage=lock.stage,
            run_id=lock.run_id,
            target_stage="cancelled",
            event_name="stage.failed",
            extra_data={"reason": reason or "cancelled"},
        )
        task = resolve_task(workspace_root, ref)
    updated = replace(task, status_stage="cancelled", updated_at=utc_now_iso())
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.cancelled",
        {"reason": reason},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "task cancel",
        updated,
        warnings=[],
        changed=True,
    )


def uncancel_task(
    workspace_root: Path,
    ref: str,
    *,
    target_stage: str | None,
    reason: str,
    actor: ActorRef | None = None,
    allow_agent_uncancel: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, ref)
    _tasks._ensure_not_archived(task, operation="uncancel")
    if task.status_stage != "cancelled":
        resumable_run = _tasks._resumable_implementation_run(
            workspace_root,
            task,
            lock=_tasks._current_lock(workspace_root, task.id),
        )
        if resumable_run is not None and task.status_stage == "implementing":
            raise _uncancel_resumable_implementation_error(task, resumable_run)
        raise _tasks._cli_error(
            "Only cancelled tasks can be uncancelled.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    lock = _tasks._current_lock(workspace_root, task.id)
    if lock is not None:
        if lock_is_expired(lock):
            raise _tasks._stale_lock_error(task.id, lock)
        raise _tasks._cli_error(
            "Cancelled task has an active lock; repair the lock first.",
            EXIT_CODE_LOCK_CONFLICT,
        )
    uncancel_reason = reason.strip()
    if not uncancel_reason:
        raise _tasks._cli_error("Uncancel requires --reason.", EXIT_CODE_BAD_INPUT)
    resolved_actor = actor or _tasks._default_actor()
    if resolved_actor.actor_type == "system":
        raise _tasks._cli_error(
            "System actors cannot uncancel tasks.",
            EXIT_CODE_BAD_INPUT,
        )
    if resolved_actor.actor_type != "user" and not allow_agent_uncancel:
        raise _tasks._cli_error(
            "Agent uncancel requires --allow-agent-uncancel and --reason.",
            EXIT_CODE_APPROVAL_REQUIRED,
        )
    target = (
        _infer_uncancel_target(workspace_root, task)
        if target_stage is None
        else normalize_task_status_stage(target_stage)
    )
    if target in ACTIVE_TASK_STAGES or target in {"done", "cancelled"}:
        raise _tasks._cli_error(
            f"Invalid uncancel target: {target}",
            EXIT_CODE_BAD_INPUT,
        )
    _validate_uncancel_target(workspace_root, task, target)
    updated = replace(task, status_stage=target, updated_at=utc_now_iso())
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.uncancelled",
        {
            "from": "cancelled",
            "to": target,
            "reason": uncancel_reason,
            "actor": resolved_actor.to_dict(),
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "task uncancel", updated, warnings=[], changed=True
    )


def close_task(
    workspace_root: Path,
    ref: str,
    *,
    note: str | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, ref)
    _tasks._ensure_not_archived(task, operation="close")
    if task.status_stage != "done":
        raise _tasks._cli_error(
            "Only done tasks can be closed via task close.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    if task.closed_at is not None:
        return _tasks._lifecycle_payload("task close", task, warnings=[], changed=False)
    closed_at = utc_now_iso()
    updated = replace(
        task,
        closed_at=closed_at,
        closed_by=_tasks._default_actor(),
        closure_note=note,
        updated_at=closed_at,
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.closed",
        {"closed_at": closed_at, "note": note},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload("task close", updated, warnings=[], changed=True)

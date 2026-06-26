from __future__ import annotations

import difflib
import getpass
import os
import shlex
import socket
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml

from taskledger.domain.models import (
    AcceptanceCriterion,
    ActiveTaskState,
    ActorRef,
    DependencyWaiver,
    HarnessRef,
    PlanRecord,
    QuestionRecord,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
    ValidationCheck,
)
from taskledger.domain.policies import (
    Decision,
    derive_active_stage,
    implementation_mutation_decision,  # noqa: F401
    plan_approve_decision,
    plan_revise_decision,
    question_add_decision,
    question_mutation_decision,
)
from taskledger.domain.states import (
    ACTIVE_TASK_STAGES,
    EXIT_CODE_APPROVAL_REQUIRED,
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_DEPENDENCY_BLOCKED,
    EXIT_CODE_GENERIC_FAILURE,
    EXIT_CODE_INVALID_TRANSITION,
    EXIT_CODE_LOCK_CONFLICT,
    EXIT_CODE_MISSING,
    EXIT_CODE_STALE_LOCK_REQUIRES_BREAK,
    EXIT_CODE_VALIDATION_FAILED,
    TaskStatusStage,
    normalize_run_type,
)
from taskledger.domain.task import is_archived_task
from taskledger.errors import LaunchError, NoActiveTask
from taskledger.ids import next_project_id, slugify_project_ref
from taskledger.refs import (
    file_ref_for_local_id,
    global_ref_for_local_id,
    local_id_from_ref,
)
from taskledger.services import next_action_payload as _next_action_payload
from taskledger.services.task_events import (
    append_task_event as _append_event,
)
from taskledger.services.task_events import (
    default_actor as _default_actor,
)
from taskledger.services.task_events import (
    default_harness as _default_harness,
)
from taskledger.services.task_events import (
    write_broken_lock_audit as _write_broken_lock_audit,
)
from taskledger.services.task_queries import (
    accepted_plan_record_or_none as _task_query_accepted_plan_record_or_none,
)
from taskledger.services.task_queries import (
    dependency_blockers as _task_query_dependency_blockers,
)
from taskledger.services.task_queries import (
    optional_run as _task_query_optional_run,
)
from taskledger.services.validation import (
    build_validation_gate_report as _build_validation_gate_report_impl,
)
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.locks import (
    lock_is_expired,
    read_lock,
    remove_lock,
    write_lock,
)
from taskledger.storage.project_config import load_worker_pipeline_config
from taskledger.storage.task_store import (
    TaskVisibility,
    ensure_v2_layout,
    list_changes,
    list_plans,
    list_questions,
    list_runs,
    list_tasks_by_visibility,
    load_active_locks,
    load_active_task_state,
    load_links,
    load_requirements,
    load_todos,
    overwrite_plan,
    resolve_plan,
    resolve_question,
    resolve_run,
    resolve_task,
    resolve_v2_paths,
    save_question,
    save_run,
    save_task,
    task_artifacts_dir,
    task_lock_path,
)
from taskledger.storage.task_store import (
    resolve_active_task as storage_resolve_active_task,
)
from taskledger.storage.worker_pipeline_config import WorkerPipelineConfig
from taskledger.timeutils import utc_now_iso

_REQUIRED_PLAN_FIELDS = ("goal", "acceptance_criteria", "todos")
_RECOMMENDED_PLAN_FIELDS = ("files", "test_commands", "expected_outputs")

# Compatibility aliases for split helper modules.
_answer_snapshot_hash = _next_action_payload._answer_snapshot_hash
_required_open_question_ids = _next_action_payload._required_open_question_ids
_stale_answer_question_ids = _next_action_payload._stale_answer_question_ids
_todo_command_hints = _next_action_payload._todo_command_hints


# ---------------------------------------------------------------------------
# Task lifecycle - delegated to task_lifecycle module
# ---------------------------------------------------------------------------


def create_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import create_task as _impl

    return _impl(*args, **kwargs)


def create_follow_up_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import create_follow_up_task as _impl

    return _impl(*args, **kwargs)


def list_follow_up_tasks(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import list_follow_up_tasks as _impl

    return _impl(*args, **kwargs)


def record_completed_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import record_completed_task as _impl

    return _impl(*args, **kwargs)


def activate_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import activate_task as _impl

    return _impl(*args, **kwargs)


def deactivate_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import deactivate_task as _impl

    return _impl(*args, **kwargs)


def clear_active_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import clear_active_task as _impl

    return _impl(*args, **kwargs)


def edit_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import edit_task as _impl

    return _impl(*args, **kwargs)


def cancel_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import cancel_task as _impl

    return _impl(*args, **kwargs)


def uncancel_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import uncancel_task as _impl

    return _impl(*args, **kwargs)


def close_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_lifecycle import close_task as _impl

    return _impl(*args, **kwargs)


def archive_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_archive import archive_task as _impl

    return _impl(*args, **kwargs)


def unarchive_task(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_archive import unarchive_task as _impl

    return _impl(*args, **kwargs)


def list_archived_task_summaries(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_archive import (
        list_archived_task_summaries as _impl,
    )

    return _impl(*args, **kwargs)


def list_task_summaries(
    workspace_root: Path,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
    slug: str | None = None,
) -> list[dict[str, object]]:
    if include_archived and archived_only:
        raise _cli_error(
            "Use either include_archived or archived_only, not both.",
            EXIT_CODE_BAD_INPUT,
        )
    visibility: TaskVisibility
    if include_archived:
        visibility = "all"
    elif archived_only:
        visibility = "archived"
    else:
        visibility = "visible"
    tasks = list_tasks_by_visibility(workspace_root, visibility=visibility)
    slug_filter = slug.strip().lower() if slug and slug.strip() else None
    active_state = load_active_task_state(workspace_root)
    active_task_id = active_state.task_id if active_state is not None else None
    rows = []
    for task in tasks:
        if slug_filter is not None and task.slug != slug_filter:
            continue
        rows.append(
            {
                "id": task.id,
                "global_ref": global_ref_for_local_id(workspace_root, task.id),
                "file_ref": file_ref_for_local_id(workspace_root, task.id),
                "slug": task.slug,
                "title": task.title,
                "status": task.status_stage,
                "status_stage": task.status_stage,
                "is_active": task.id == active_task_id,
                "active_stage": _task_active_stage(workspace_root, task),
                "accepted_plan_version": task.accepted_plan_version,
                "archived": is_archived_task(task),
                "archived_at": task.archived_at,
            }
        )
    return rows


def resolve_active_task(workspace_root: Path) -> TaskRecord:
    return storage_resolve_active_task(workspace_root)


def show_active_task(workspace_root: Path) -> dict[str, object]:
    state = load_active_task_state(workspace_root)
    if state is None:
        raise NoActiveTask()
    task = storage_resolve_active_task(workspace_root)
    return _active_task_payload(
        workspace_root,
        task,
        state=state,
        changed=False,
        previous_task_id=state.previous_task_id,
    )


def show_task(
    workspace_root: Path,
    ref: str,
    *,
    include_archived: bool = False,
) -> dict[str, object]:
    from taskledger.services.handoff import build_task_relationship_payload

    task = _task_with_sidecars(
        workspace_root,
        resolve_task(workspace_root, ref, include_archived=include_archived),
    )
    lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task.id))
    plans = list_plans(workspace_root, task.id)
    questions = list_questions(workspace_root, task.id)
    runs = list_runs(workspace_root, task.id)
    changes = list_changes(workspace_root, task.id)
    relationships = build_task_relationship_payload(workspace_root, task)
    active_stage = _task_active_stage(
        workspace_root,
        task,
        lock=lock,
        runs=runs,
    )
    return {
        "kind": "task",
        "task": _task_payload(workspace_root, task, active_stage=active_stage),
        "lock": lock.to_dict() if lock is not None else None,
        "plans": [plan.to_dict() for plan in plans],
        "questions": [question.to_dict() for question in questions],
        "runs": [run.to_dict() for run in runs],
        "changes": [change.to_dict() for change in changes],
        "parent_task": relationships["parent_task"],
        "follow_up_tasks": relationships["follow_up_tasks"],
    }


# ---------------------------------------------------------------------------
# Task sidecar collections - delegated to task_collections module
# ---------------------------------------------------------------------------


def create_introduction(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        create_introduction as _impl,
    )

    return _impl(*args, **kwargs)


def link_introduction(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        link_introduction as _impl,
    )

    return _impl(*args, **kwargs)


def add_requirement(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        add_requirement as _impl,
    )

    return _impl(*args, **kwargs)


def remove_requirement(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        remove_requirement as _impl,
    )

    return _impl(*args, **kwargs)


def waive_requirement(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        waive_requirement as _impl,
    )

    return _impl(*args, **kwargs)


def add_file_link(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        add_file_link as _impl,
    )

    return _impl(*args, **kwargs)


def remove_file_link(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        remove_file_link as _impl,
    )

    return _impl(*args, **kwargs)


def list_file_links(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        list_file_links as _impl,
    )

    return _impl(*args, **kwargs)


def file_status(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        file_status as _impl,
    )

    return _impl(*args, **kwargs)


def refresh_file_baseline(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        refresh_file_baseline as _impl,
    )

    return _impl(*args, **kwargs)


def add_todo(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        add_todo as _impl,
    )

    return _impl(*args, **kwargs)


def set_todo_done(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        set_todo_done as _impl,
    )

    return _impl(*args, **kwargs)


def show_todo(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        show_todo as _impl,
    )

    return _impl(*args, **kwargs)


def start_planning(
    workspace_root: Path,
    task_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    from taskledger.services.planning_flow import start_planning as _start_planning

    return _start_planning(
        workspace_root,
        task_ref,
        actor=actor,
        harness=harness,
    )


def propose_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    body: str,
    criteria: tuple[str, ...] = (),
) -> dict[str, object]:
    from taskledger.services.planning_flow import propose_plan as _propose_plan

    return _propose_plan(
        workspace_root,
        task_ref,
        body=body,
        criteria=criteria,
    )


def upsert_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    body: str,
    criteria: tuple[str, ...] = (),
    from_answers: bool = False,
    allow_open_questions: bool = False,
    auto_revise: bool = False,
) -> dict[str, object]:
    from taskledger.services.planning_flow import upsert_plan as _upsert_plan

    return _upsert_plan(
        workspace_root,
        task_ref,
        body=body,
        criteria=criteria,
        from_answers=from_answers,
        allow_open_questions=allow_open_questions,
        auto_revise=auto_revise,
    )


def export_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int | None = None,
) -> dict[str, object]:
    from taskledger.services.planning_flow import export_plan as _export_plan

    return _export_plan(
        workspace_root,
        task_ref,
        version=version,
    )


def amend_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    drop_criteria: tuple[str, ...] = (),
    drop_todos: tuple[str, ...] = (),
    remove_files: tuple[str, ...] = (),
    reason: str,
) -> dict[str, object]:
    from taskledger.services.planning_flow import amend_plan as _amend_plan

    return _amend_plan(
        workspace_root,
        task_ref,
        drop_criteria=drop_criteria,
        drop_todos=drop_todos,
        remove_files=remove_files,
        reason=reason,
    )


def show_plan(
    workspace_root: Path, task_ref: str, *, version: int | None = None
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    plan = resolve_plan(
        workspace_root,
        task.id,
        version=version,
    )
    return {
        "kind": "plan",
        "task_id": task.id,
        "plan": plan.to_dict(),
    }


def list_plan_versions(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    plans = list_plans(workspace_root, task.id)
    return {
        "kind": "plan_list",
        "task_id": task.id,
        "plans": [plan.to_dict() for plan in plans],
    }


def diff_plan(
    workspace_root: Path, task_ref: str, *, from_version: int, to_version: int
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    earlier = resolve_plan(workspace_root, task.id, version=from_version)
    later = resolve_plan(workspace_root, task.id, version=to_version)
    diff = "\n".join(
        difflib.unified_diff(
            earlier.body.splitlines(),
            later.body.splitlines(),
            fromfile=f"plan-v{from_version}",
            tofile=f"plan-v{to_version}",
            lineterm="",
        )
    )
    return {
        "kind": "plan_diff",
        "task_id": task.id,
        "from_version": from_version,
        "to_version": to_version,
        "diff": diff,
    }


def approve_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int,
    actor_type: str = "user",
    actor_name: str | None = None,
    note: str | None = None,
    allow_agent_approval: bool = False,
    reason: str | None = None,
    allow_empty_criteria: bool = False,
    materialize_todos: bool = True,
    allow_open_questions: bool = False,
    allow_empty_todos: bool = False,
    allow_lint_errors: bool = False,
    approval_source: str | None = None,
) -> dict[str, object]:
    from taskledger.services.planning_flow import approve_plan as _approve_plan

    return _approve_plan(
        workspace_root,
        task_ref,
        version=version,
        actor_type=actor_type,
        actor_name=actor_name,
        note=note,
        allow_agent_approval=allow_agent_approval,
        reason=reason,
        allow_empty_criteria=allow_empty_criteria,
        materialize_todos=materialize_todos,
        allow_open_questions=allow_open_questions,
        allow_empty_todos=allow_empty_todos,
        allow_lint_errors=allow_lint_errors,
        approval_source=approval_source,
    )


class PlanTodoMaterializationPayload(TypedDict):
    """Re-exported from plan_materialization for backward compatibility."""

    kind: str
    task_id: str
    plan_id: str
    materialized_todos: int
    todos: list[dict[str, object]]
    dry_run: bool


def materialize_plan_todos(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.plan_materialization import (
        materialize_plan_todos as _impl,
    )

    return _impl(*args, **kwargs)


def regenerate_plan_from_answers(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.plan_materialization import (
        regenerate_plan_from_answers as _impl,
    )

    return _impl(*args, **kwargs)


def reject_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    reason: str | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="reject plan for")
    _enforce_decision(
        plan_approve_decision(task, _current_lock(workspace_root, task.id))
    )
    latest = resolve_plan(workspace_root, task.id)
    overwrite_plan(workspace_root, replace(latest, status="rejected"))
    updated = replace(task, status_stage="plan_review", updated_at=utc_now_iso())
    save_task(workspace_root, updated)
    _append_event(
        workspace_root,
        updated.id,
        "plan.rejected",
        {"plan_version": latest.plan_version, "reason": reason},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _lifecycle_payload(
        "plan reject",
        updated,
        warnings=[],
        changed=True,
        plan_version=latest.plan_version,
    )


def revise_plan(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="revise plan for")
    _enforce_decision(
        plan_revise_decision(task, _current_lock(workspace_root, task.id))
    )
    return start_planning(workspace_root, task_ref)


def add_question(
    workspace_root: Path,
    task_ref: str,
    *,
    text: str,
    required_for_plan: bool = False,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> QuestionRecord:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="add question to")
    _enforce_decision(
        question_add_decision(
            task,
            _lock_for_mutation(workspace_root, task.id),
            actor_role="planner",
        )
    )
    question = QuestionRecord(
        id=next_project_id(
            "q",
            [item.id for item in list_questions(workspace_root, task.id)],
        ),
        task_id=task.id,
        question=text.strip(),
        plan_version=task.latest_plan_version,
        required_for_plan=required_for_plan,
        asked_by_actor=actor or _default_actor(),
        asked_in_harness=harness or _default_harness(),
    )
    save_question(workspace_root, question)
    _append_event(
        workspace_root,
        task.id,
        "question.added",
        {"question_id": question.id, "required_for_plan": required_for_plan},
    )
    return question


def add_questions(
    workspace_root: Path,
    task_ref: str,
    questions: Sequence[tuple[str, bool]],
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    allow_duplicates: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="add questions to")
    _enforce_decision(
        question_add_decision(
            task,
            _lock_for_mutation(workspace_root, task.id),
            actor_role="planner",
        )
    )
    normalized = _normalize_question_batch(
        questions,
        allow_duplicates=allow_duplicates,
    )
    known_ids = [item.id for item in list_questions(workspace_root, task.id)]
    created_questions: list[QuestionRecord] = []
    for text, required_for_plan in normalized:
        question_id = next_project_id(
            "q",
            [*known_ids, *[item.id for item in created_questions]],
        )
        created_questions.append(
            QuestionRecord(
                id=question_id,
                task_id=task.id,
                question=text,
                plan_version=task.latest_plan_version,
                required_for_plan=required_for_plan,
                asked_by_actor=actor or _default_actor(),
                asked_in_harness=harness or _default_harness(),
            )
        )
    for question in created_questions:
        save_question(workspace_root, question)
        _append_event(
            workspace_root,
            task.id,
            "question.added",
            {
                "question_id": question.id,
                "required_for_plan": question.required_for_plan,
            },
        )
    return {
        "kind": "question_add_many",
        "task_id": task.id,
        "added_question_ids": [item.id for item in created_questions],
        "added": [item.to_dict() for item in created_questions],
    }


def answer_question(
    workspace_root: Path,
    task_ref: str,
    question_id: str,
    *,
    text: str,
    actor: ActorRef | None = None,
    answer_source: str = "user",
) -> QuestionRecord:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="answer question on")
    _enforce_decision(
        question_mutation_decision(
            task,
            _lock_for_mutation(workspace_root, task.id),
            actor_role="user",
        )
    )
    stripped = text.strip()
    if not stripped:
        raise _cli_error(
            "Answer text must not be empty.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    question = resolve_question(workspace_root, task.id, question_id)
    resolved_actor = actor or ActorRef(actor_type="user", actor_name="user")
    normalized_source = answer_source.strip().lower() if answer_source else ""
    if question.required_for_plan and normalized_source not in {
        "explicit_user_chat",
        "user_file",
    }:
        raise _cli_error(
            "Required planning question requires explicit user source. "
            "Use --source explicit_user_chat after the user answers in chat.",
            EXIT_CODE_APPROVAL_REQUIRED,
        )
    answered = replace(
        question,
        status="answered",
        answer=stripped,
        answered_at=utc_now_iso(),
        answered_by=resolved_actor.actor_name,
        answered_by_actor=resolved_actor,
        answer_source=normalized_source or None,
    )
    save_question(workspace_root, answered)
    _append_event(
        workspace_root,
        task.id,
        "question.answered",
        {"question_id": answered.id},
    )
    return answered


def answer_questions(
    workspace_root: Path,
    task_ref: str,
    answers: Mapping[str, str],
    *,
    actor: ActorRef | None = None,
    answer_source: str = "harness",
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="answer questions on")
    if not answers:
        raise _cli_error("At least one answer is required.", EXIT_CODE_BAD_INPUT)
    known = {item.id: item for item in list_questions(workspace_root, task.id)}
    unknown = [question_id for question_id in answers if question_id not in known]
    if unknown:
        raise _cli_error(
            "Unknown question ids: " + ", ".join(unknown),
            EXIT_CODE_MISSING,
        )
    empty = [question_id for question_id, text in answers.items() if not text.strip()]
    if empty:
        raise _cli_error(
            "Answer text must not be empty for: " + ", ".join(empty),
            EXIT_CODE_BAD_INPUT,
        )
    answered_ids: list[str] = []
    answered_questions: list[dict[str, object]] = []
    for question_id, text in answers.items():
        question = answer_question(
            workspace_root,
            task.id,
            question_id,
            text=text,
            actor=actor,
            answer_source=answer_source,
        )
        answered_ids.append(question.id)
        answered_questions.append(question.to_dict())
    status = question_status(workspace_root, task.id)
    payload = {
        "kind": "question_answer_many",
        "task_id": task.id,
        "answered_question_ids": answered_ids,
        "answered": answered_questions,
        "required_open": status["required_open"],
        "required_open_questions": status["required_open_questions"],
        "plan_regeneration_needed": status["plan_regeneration_needed"],
        "next_action": status["next_action"],
    }
    for key in (
        "template_command",
        "required_plan_fields",
        "recommended_plan_fields",
    ):
        if key in status:
            payload[key] = status[key]
    return payload


def question_status(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    questions = list_questions(workspace_root, task.id)
    required_open = _required_open_question_ids(questions)
    answered_required = [
        item.id
        for item in questions
        if item.status == "answered" and item.required_for_plan
    ]
    answered = [item for item in questions if item.status == "answered"]
    latest_plan = _latest_plan_or_none(workspace_root, task.id)
    answered_since_latest_plan = (
        _stale_answer_question_ids(questions, latest_plan)
        if latest_plan is not None
        else [item.id for item in answered]
    )
    regeneration_needed = bool(answered_since_latest_plan) and not required_open
    payload = {
        "kind": "question_status",
        "task_id": task.id,
        "required_open": len(required_open),
        "required_open_questions": required_open,
        "answered_required_questions": answered_required,
        "answered": len([item for item in questions if item.status == "answered"]),
        "answered_since_latest_plan": answered_since_latest_plan,
        "plan_regeneration_needed": regeneration_needed,
        "next_action": (
            "taskledger plan upsert --from-answers --file plan.md"
            if regeneration_needed
            else (
                "taskledger question answer-many --file answers.yaml"
                if required_open
                else "taskledger plan propose --file plan.md"
            )
        ),
    }
    if regeneration_needed:
        payload.update(_planning_template_hints(from_answers=True))
    return payload


def plan_template(
    workspace_root: Path,
    task_ref: str,
    *,
    from_answers: bool = False,
    include_guidance: bool = False,
    with_worker_pipeline: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    guidance_text = ""
    if include_guidance:
        from taskledger.services.workflow_guidance import (
            render_planning_guidance,
        )

        guidance_text = render_planning_guidance(workspace_root, task)
    answered_questions = [
        item
        for item in list_questions(workspace_root, task.id)
        if item.status == "answered" and item.required_for_plan
    ]
    worker_pipeline: WorkerPipelineConfig | None = None
    if with_worker_pipeline:
        worker_pipeline = _worker_pipeline_for_plan_template(workspace_root)
    template_text = _render_plan_template(
        answered_questions if from_answers else (),
        worker_pipeline=worker_pipeline,
    )
    if include_guidance and guidance_text:
        template_text = _insert_guidance_into_plan_template(
            template_text,
            guidance_text,
        )
    return {
        "kind": "plan_template",
        "task_id": task.id,
        "from_answers": from_answers,
        "template": template_text,
        "answered_question_ids": [item.id for item in answered_questions]
        if from_answers
        else [],
        "recommended_plan_fields": list(_RECOMMENDED_PLAN_FIELDS),
        "guidance": guidance_text,
        "with_worker_pipeline": with_worker_pipeline,
    }


def dismiss_question(
    workspace_root: Path,
    task_ref: str,
    question_id: str,
) -> QuestionRecord:
    task = resolve_task(workspace_root, task_ref)
    _ensure_not_archived(task, operation="dismiss question on")
    _enforce_decision(
        question_mutation_decision(
            task,
            _lock_for_mutation(workspace_root, task.id),
            actor_role="user",
        )
    )
    question = resolve_question(workspace_root, task.id, question_id)
    dismissed = replace(question, status="dismissed")
    save_question(workspace_root, dismissed)
    _append_event(
        workspace_root,
        task.id,
        "question.dismissed",
        {"question_id": dismissed.id},
    )
    return dismissed


def list_open_questions(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    questions = [
        item.to_dict()
        for item in list_questions(workspace_root, task.id)
        if item.status == "open"
    ]
    return {"kind": "task_questions", "task_id": task.id, "questions": questions}


def _accepted_plan_record_or_none(
    workspace_root: Path,
    task: TaskRecord,
) -> PlanRecord | None:
    return _task_query_accepted_plan_record_or_none(workspace_root, task)


def _require_accepted_plan_record(
    workspace_root: Path,
    task: TaskRecord,
    *,
    action: str,
) -> PlanRecord:
    if task.accepted_plan_version is None:
        raise _cli_error(
            f"{action} requires an accepted plan version.",
            EXIT_CODE_APPROVAL_REQUIRED,
        )
    accepted_plan = _accepted_plan_record_or_none(workspace_root, task)
    if accepted_plan is None:
        try:
            stored_plan = resolve_plan(
                workspace_root,
                task.id,
                version=task.accepted_plan_version,
            )
        except LaunchError as exc:
            raise _cli_error(
                f"{action} requires a stored accepted plan record.",
                EXIT_CODE_APPROVAL_REQUIRED,
            ) from exc
        if stored_plan.status != "accepted":
            raise _cli_error(
                f"{action} requires an accepted plan record.",
                EXIT_CODE_APPROVAL_REQUIRED,
            )
        return stored_plan
    return accepted_plan


def start_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    from taskledger.services.implementation_flow import (
        start_implementation as _start_implementation,
    )

    return _start_implementation(
        workspace_root,
        task_ref,
        actor=actor,
        harness=harness,
    )


def restart_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    summary: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    from taskledger.services.implementation_flow import (
        restart_implementation as _restart_implementation,
    )

    return _restart_implementation(
        workspace_root,
        task_ref,
        summary=summary,
        actor=actor,
        harness=harness,
    )


def resume_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    run_id: str | None = None,
    reason: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    repair_expired_lock: bool = False,
) -> dict[str, object]:
    from taskledger.services.implementation_flow import (
        resume_implementation as _resume_implementation,
    )

    return _resume_implementation(
        workspace_root,
        task_ref,
        run_id=run_id,
        reason=reason,
        actor=actor,
        harness=harness,
        repair_expired_lock=repair_expired_lock,
    )


def log_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    message: str,
) -> TaskRunRecord:
    from taskledger.services.implementation_flow import (
        log_implementation as _log_implementation,
    )

    return _log_implementation(
        workspace_root,
        task_ref,
        message=message,
    )


def add_implementation_deviation(
    workspace_root: Path,
    task_ref: str,
    *,
    message: str,
) -> TaskRunRecord:
    from taskledger.services.implementation_flow import (
        add_implementation_deviation as _add_implementation_deviation,
    )

    return _add_implementation_deviation(
        workspace_root,
        task_ref,
        message=message,
    )


def add_implementation_artifact(
    workspace_root: Path,
    task_ref: str,
    *,
    path: str,
    summary: str,
) -> TaskRunRecord:
    from taskledger.services.implementation_flow import (
        add_implementation_artifact as _add_implementation_artifact,
    )

    return _add_implementation_artifact(
        workspace_root,
        task_ref,
        path=path,
        summary=summary,
    )


def add_change(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.change_tracking import (
        add_change as _impl,
    )

    return _impl(*args, **kwargs)


def scan_changes(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.change_tracking import (
        scan_changes as _impl,
    )

    return _impl(*args, **kwargs)


def run_planning_command(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.change_tracking import (
        run_planning_command as _impl,
    )

    return _impl(*args, **kwargs)


def run_implementation_command(
    workspace_root: Path,
    task_ref: str,
    *,
    argv: tuple[str, ...],
) -> dict[str, object]:
    from taskledger.services.implementation_flow import (
        run_implementation_command as _run_implementation_command,
    )

    return _run_implementation_command(
        workspace_root,
        task_ref,
        argv=argv,
    )


def _build_todo_gate_report(
    workspace_root: Path, task: TaskRecord
) -> dict[str, object]:
    """Build a report of todo completion status for finish gate validation."""
    task = _task_with_sidecars(workspace_root, task)
    todos = task.todos
    open_todos = [
        todo.id
        for todo in todos
        if not todo.done
        and todo.status not in {"done", "skipped"}
        and (
            not todo.mandatory
            or todo.active_at is not None
            or todo.source == "plan"
            or todo.source_plan_id is not None
        )
    ]
    blockers = [
        {
            "kind": "todo_open",
            "ref": todo_id,
            "message": f"Todo {todo_id} is not done.",
            "command_hint": f'taskledger todo done {todo_id} --evidence "..."',
        }
        for todo_id in open_todos
    ]
    return {
        "kind": "todo_gate_report",
        "task_id": task.id,
        "total": len(todos),
        "done": len(todos) - len(open_todos),
        "open_todos": open_todos,
        "blockers": blockers,
        "can_finish_implementation": not open_todos,
    }


def _require_todos_complete_for_implementation_finish(
    workspace_root: Path, task: TaskRecord
) -> None:
    """Enforce that all todos are done before finishing implementation."""
    report = _build_todo_gate_report(workspace_root, task)
    if report["can_finish_implementation"]:
        return
    error = LaunchError("Cannot finish implementation because todos are incomplete.")
    error.taskledger_exit_code = EXIT_CODE_VALIDATION_FAILED
    error.taskledger_error_code = "IMPLEMENTATION_TODOS_INCOMPLETE"
    error.taskledger_data = report
    raise error


# Task sidecar collection helpers - delegated to task_collections module


def todo_status(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        todo_status as _impl,
    )

    return _impl(*args, **kwargs)


def next_todo(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_collections import (
        next_todo as _impl,
    )

    return _impl(*args, **kwargs)


def finish_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    summary: str,
) -> dict[str, object]:
    from taskledger.services.implementation_flow import (
        finish_implementation as _finish_implementation,
    )

    return _finish_implementation(
        workspace_root,
        task_ref,
        summary=summary,
    )


def start_validation(
    workspace_root: Path,
    task_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    refresh_implementation_snapshot_first: bool = False,
    refresh_reason: str | None = None,
) -> dict[str, object]:
    from taskledger.services.validation_flow import (
        start_validation as _start_validation,
    )

    return _start_validation(
        workspace_root,
        task_ref,
        actor=actor,
        harness=harness,
        refresh_implementation_snapshot_first=refresh_implementation_snapshot_first,
        refresh_reason=refresh_reason,
    )


def refresh_implementation_snapshot(
    workspace_root: Path,
    task_ref: str,
    *,
    reason: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    from taskledger.services.workspace_snapshot import (
        refresh_implementation_snapshot as _refresh_implementation_snapshot,
    )

    return _refresh_implementation_snapshot(
        workspace_root,
        task_ref,
        reason=reason,
        actor=actor,
        harness=harness,
    )


def _resolve_criterion_ref(plan: PlanRecord, criterion_ref: str) -> str:
    """Canonicalize criterion reference to the exact ID in the plan.

    Accepts:
    - exact ID: ac-0001
    - different case: AC-0001
    - short AC form: ac-1 (should match ac-0001)
    - numeric form: 1 (should match ac-0001)

    Raises LaunchError if criterion not found in plan.
    """
    if not plan.criteria:
        raise _cli_error(
            "No acceptance criteria defined in plan.",
            EXIT_CODE_BAD_INPUT,
        )

    normalized_ref = criterion_ref.strip().lower()

    for c in plan.criteria:
        c_id_lower = c.id.lower()

        if c_id_lower == normalized_ref:
            return c.id

        parts = c_id_lower.split("-")
        if len(parts) == 2:
            prefix, number = parts

            if normalized_ref == f"{prefix}-{number}":
                return c.id

            ref_parts = normalized_ref.split("-")
            if len(ref_parts) == 2:
                ref_prefix, ref_number = ref_parts
                if ref_prefix == prefix:
                    try:
                        if int(ref_number) == int(number):
                            return c.id
                    except ValueError:
                        pass

            if normalized_ref == number:
                return c.id

            try:
                if int(normalized_ref) == int(number):
                    return c.id
            except ValueError:
                pass

    criterion_ids = ", ".join(sorted(c.id for c in plan.criteria))
    raise _cli_error(
        f"Unknown acceptance criterion: {criterion_ref}.\n"
        f"Known criteria: {criterion_ids}.",
        EXIT_CODE_BAD_INPUT,
    )


def _build_validation_gate_report(
    workspace_root: Path,
    task: TaskRecord,
    run: TaskRunRecord | None = None,
) -> dict[str, object]:
    return _build_validation_gate_report_impl(workspace_root, task, run)


def validation_status(
    workspace_root: Path,
    task_ref: str,
    *,
    run_id: str | None = None,
) -> dict[str, object]:
    from taskledger.services.validation_flow import (
        validation_status as _validation_status,
    )

    return _validation_status(
        workspace_root,
        task_ref,
        run_id=run_id,
    )


def add_validation_check(
    workspace_root: Path,
    task_ref: str,
    *,
    name: str | None = None,
    criterion_id: str | None = None,
    status: str,
    details: str | None = None,
    evidence: tuple[str, ...] = (),
) -> TaskRunRecord:
    from taskledger.services.validation_flow import (
        add_validation_check as _add_validation_check,
    )

    return _add_validation_check(
        workspace_root,
        task_ref,
        name=name,
        criterion_id=criterion_id,
        status=status,
        details=details,
        evidence=evidence,
    )


def waive_criterion(
    workspace_root: Path,
    task_ref: str,
    *,
    criterion_id: str,
    reason: str,
    actor_name: str | None = None,
) -> TaskRunRecord:
    from taskledger.services.validation_flow import waive_criterion as _waive_criterion

    return _waive_criterion(
        workspace_root,
        task_ref,
        criterion_id=criterion_id,
        reason=reason,
        actor_name=actor_name,
    )


def finish_validation(
    workspace_root: Path,
    task_ref: str,
    *,
    result: str,
    summary: str,
    recommendation: str | None = None,
) -> dict[str, object]:
    from taskledger.services.validation_flow import (
        finish_validation as _finish_validation,
    )

    return _finish_validation(
        workspace_root,
        task_ref,
        result=result,
        summary=summary,
        recommendation=recommendation,
    )


def show_task_run(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.change_tracking import (
        show_task_run as _impl,
    )

    return _impl(*args, **kwargs)


def show_lock(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.run_store import show_lock as _impl

    return _impl(*args, **kwargs)


def break_lock(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.run_store import break_lock as _impl

    return _impl(*args, **kwargs)


def list_locks(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.run_store import list_locks as _impl

    return _impl(*args, **kwargs)


def next_action(workspace_root: Path, task_ref: str) -> dict[str, object]:
    from taskledger.services.navigation import next_action as navigation_next_action

    return navigation_next_action(workspace_root, task_ref)


def can_perform(workspace_root: Path, task_ref: str, action: str) -> dict[str, object]:
    from taskledger.services.navigation import can_perform as navigation_can_perform

    return navigation_can_perform(workspace_root, task_ref, action)


def task_dossier(
    workspace_root: Path,
    task_ref: str,
    *,
    format_name: str = "markdown",
) -> str | dict[str, object]:
    from taskledger.services.navigation import task_dossier as navigation_task_dossier

    return navigation_task_dossier(
        workspace_root,
        task_ref,
        format_name=format_name,
    )


def reindex(workspace_root: Path) -> dict[str, object]:
    paths = ensure_v2_layout(workspace_root)
    counts = rebuild_v2_indexes(paths)
    _append_event(
        workspace_root, "*", "repair.index", dict(cast(dict[str, object], counts))
    )
    return {"kind": "taskledger_reindex", "counts": counts}


def repair_task_record(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_repair import (
        repair_task_record as _impl,
    )

    return _impl(*args, **kwargs)


def repair_orphaned_planning_run(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_repair import (
        repair_orphaned_planning_run as _impl,
    )

    return _impl(*args, **kwargs)


def repair_planning_command_changes(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.task_repair import (
        repair_planning_command_changes as _impl,
    )

    return _impl(*args, **kwargs)


def list_events(*args, **kwargs):  # type: ignore[no-untyped-def]
    from taskledger.services.change_tracking import (
        list_events as _impl,
    )

    return _impl(*args, **kwargs)


def _start_run(
    workspace_root: Path,
    task: TaskRecord,
    *,
    run_type: str,
    stage: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> TaskRunRecord:
    existing_lock = _current_lock(workspace_root, task.id)
    if existing_lock is not None:
        if lock_is_expired(existing_lock):
            raise _stale_lock_error(task.id, existing_lock)
        raise _cli_error(
            _lock_conflict_message(task.id, existing_lock),
            EXIT_CODE_LOCK_CONFLICT,
        )
    running_runs = _running_runs(workspace_root, task)
    if running_runs:
        raise _running_run_conflict_error(task, running_runs[0], existing_lock)
    resolved_actor = actor or _default_actor()
    run = TaskRunRecord(
        run_id=next_project_id(
            "run",
            [item.run_id for item in list_runs(workspace_root, task.id)],
        ),
        task_id=task.id,
        run_type=normalize_run_type(run_type),
        actor=resolved_actor,
        harness=harness,
        based_on_plan_version=task.accepted_plan_version or task.latest_plan_version,
    )
    save_run(workspace_root, run)
    _acquire_lock(
        workspace_root,
        task=task,
        stage=stage,
        run=run,
        reason={
            "planning": "plan task",
            "implementation": "implement approved plan",
            "validation": "validate implementation",
        }[run_type],
        actor=resolved_actor,
        harness=harness,
    )
    return run


def _running_runs(workspace_root: Path, task: TaskRecord) -> list[TaskRunRecord]:
    return [
        item for item in list_runs(workspace_root, task.id) if item.status == "running"
    ]


def _lock_matches_run(lock: TaskLock | None, run: TaskRunRecord) -> bool:
    expected_stage = {
        "planning": "planning",
        "implementation": "implementing",
        "validation": "validating",
    }[run.run_type]
    return (
        lock is not None
        and not lock_is_expired(lock)
        and lock.run_id == run.run_id
        and lock.stage == expected_stage
    )


def _running_run_details(
    task: TaskRecord,
    run: TaskRunRecord,
    lock: TaskLock | None,
) -> dict[str, object]:
    return {
        "task_id": task.id,
        "running_run": {
            "run_id": run.run_id,
            "run_type": run.run_type,
            "status": run.status,
            "has_matching_lock": _lock_matches_run(lock, run),
        },
        "suggested_command": "taskledger doctor",
    }


def _running_run_conflict_error(
    task: TaskRecord,
    run: TaskRunRecord,
    lock: TaskLock | None,
    *,
    message: str | None = None,
    error_code: str = "RUNNING_RUN_CONFLICT",
    exit_code: int = EXIT_CODE_LOCK_CONFLICT,
) -> LaunchError:
    lock_phrase = (
        "has a matching active lock"
        if _lock_matches_run(lock, run)
        else "has no matching active lock"
    )
    error = LaunchError(
        message
        or (
            f"Cannot start work for {task.id} because {run.run_type} run "
            f"{run.run_id} is still marked running and {lock_phrase}. "
            "Run `taskledger doctor`."
        ),
        details=_running_run_details(task, run, lock),
        task_id=task.id,
    )
    error.taskledger_exit_code = exit_code
    error.taskledger_error_code = error_code
    error.taskledger_data = error.to_error_payload()
    return error


def _acquire_lock(
    workspace_root: Path,
    *,
    task: TaskRecord,
    stage: str,
    run: TaskRunRecord,
    reason: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> TaskLock:
    if stage not in ACTIVE_TASK_STAGES:
        raise _cli_error("Only active stages can acquire locks.", EXIT_CODE_BAD_INPUT)
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task.id)
    existing = read_lock(lock_path)
    if existing is not None:
        if lock_is_expired(existing):
            raise _stale_lock_error(task.id, existing)
        if existing.run_id == run.run_id:
            return existing
        raise _cli_error(
            _lock_conflict_message(task.id, existing), EXIT_CODE_LOCK_CONFLICT
        )
    now = datetime.now(timezone.utc)
    resolved_actor = actor or _default_actor()
    lock = TaskLock(
        lock_id=_next_lock_id(workspace_root, now),
        task_id=task.id,
        stage=cast(Literal["planning", "implementing", "validating"], stage),
        run_id=run.run_id,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=2)).isoformat(),
        lease_seconds=7200,
        last_heartbeat_at=now.isoformat(),
        reason=reason,
        holder=resolved_actor,
        actor=resolved_actor,
        harness=harness,
    )
    try:
        write_lock(lock_path, lock)
    except LaunchError as exc:
        raise _cli_error(
            _lock_conflict_message(task.id, read_lock(lock_path) or lock),
            EXIT_CODE_LOCK_CONFLICT,
        ) from exc
    _append_event(workspace_root, task.id, "lock.acquired", lock.to_dict())
    _append_event(
        workspace_root,
        task.id,
        "stage.entered",
        {"stage": stage, "run_id": run.run_id},
    )
    return lock


def _release_lock(
    workspace_root: Path,
    *,
    task: TaskRecord,
    expected_stage: str,
    run_id: str,
    target_stage: TaskStatusStage,
    event_name: str,
    extra_data: dict[str, object] | None = None,
    delete_only: bool = False,
) -> None:
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task.id)
    lock = read_lock(lock_path)
    if lock is None:
        raise _cli_error(
            f"Task {task.id} has no active {expected_stage} lock to release.",
            EXIT_CODE_LOCK_CONFLICT,
        )
    if lock.stage != expected_stage or lock.run_id != run_id:
        raise _cli_error(
            "Active lock does not match the expected stage/run.",
            EXIT_CODE_LOCK_CONFLICT,
        )
    data = {"stage": expected_stage, "run_id": run_id, **(extra_data or {})}
    _append_event(workspace_root, task.id, event_name, data)
    remove_lock(lock_path)
    _append_event(
        workspace_root,
        task.id,
        "lock.released",
        {"lock_id": lock.lock_id, "stage": expected_stage},
    )
    if delete_only:
        return
    save_task(
        workspace_root,
        replace(task, status_stage=target_stage, updated_at=utc_now_iso()),
    )


def _release_expired_lock(
    workspace_root: Path,
    task_id: str,
    lock: TaskLock,
    *,
    reason: str,
) -> None:
    """Release an expired lock with audit trail, no stage transition."""
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task_id)
    # Write broken-lock audit record
    broken = replace(
        lock,
        broken_at=utc_now_iso(),
        broken_reason=reason,
    )
    _write_broken_lock_audit(paths, task_id, broken)
    remove_lock(lock_path)
    _append_event(
        workspace_root,
        task_id,
        "lock.expired_released",
        {
            "lock_id": lock.lock_id,
            "stage": lock.stage,
            "run_id": lock.run_id,
            "reason": reason,
        },
    )


def _ensure_dependencies_done(workspace_root: Path, task: TaskRecord) -> None:
    blocked = []
    for requirement in load_requirements(workspace_root, task.id).requirements:
        if _has_user_waiver(requirement.waiver):
            continue
        required = resolve_task(workspace_root, requirement.task_id)
        if required.status_stage != "done":
            blocked.append(required.id)
    if blocked:
        raise _cli_error(
            "Implementation is blocked by incomplete requirements: "
            + ", ".join(blocked),
            EXIT_CODE_DEPENDENCY_BLOCKED,
        )


def _require_lock(workspace_root: Path, task_id: str) -> TaskLock:
    lock = _current_lock(workspace_root, task_id)
    if lock is None:
        raise _cli_error("No active lock found.", EXIT_CODE_LOCK_CONFLICT)
    if lock_is_expired(lock):
        raise _stale_lock_error(task_id, lock)
    return lock


def _require_run(
    workspace_root: Path,
    task: TaskRecord,
    run_id: str | None,
) -> TaskRunRecord:
    if run_id is None:
        raise _cli_error("No active run is recorded for the task.", EXIT_CODE_MISSING)
    return resolve_run(workspace_root, task.id, run_id)


def _optional_run(
    workspace_root: Path,
    task: TaskRecord,
    run_id: str | None,
) -> TaskRunRecord | None:
    return _task_query_optional_run(workspace_root, task, run_id)


def _resumable_implementation_run(
    workspace_root: Path,
    task: TaskRecord,
    *,
    lock: TaskLock | None,
) -> TaskRunRecord | None:
    if lock is not None:
        return None
    run = _optional_run(workspace_root, task, task.latest_implementation_run)
    if (
        run is not None
        and run.run_type == "implementation"
        and run.status == "running"
        and _accepted_plan_record_or_none(workspace_root, task) is not None
    ):
        return run
    return None


def _require_running_run(
    workspace_root: Path,
    task: TaskRecord,
    run_id: str | None,
    *,
    expected_type: str,
) -> TaskRunRecord:
    run = _require_run(workspace_root, task, run_id)
    if run.run_type != expected_type or run.status != "running":
        raise _cli_error(
            f"Task does not have a running {expected_type} run.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    return run


def _current_lock(workspace_root: Path, task_id: str) -> TaskLock | None:
    return read_lock(task_lock_path(resolve_v2_paths(workspace_root), task_id))


def _lock_for_mutation(workspace_root: Path, task_id: str) -> TaskLock | None:
    lock = _current_lock(workspace_root, task_id)
    if lock is not None and lock_is_expired(lock):
        raise _stale_lock_error(task_id, lock)
    return lock


def _normalize_question_batch(
    questions: Sequence[tuple[str, bool]],
    *,
    allow_duplicates: bool,
) -> list[tuple[str, bool]]:
    if not questions:
        raise _cli_error("At least one question is required.", EXIT_CODE_BAD_INPUT)
    normalized: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for index, (text, required_for_plan) in enumerate(questions, start=1):
        stripped = text.strip()
        if not stripped:
            raise _cli_error(
                f"Question text must not be empty for item {index}.",
                EXIT_CODE_BAD_INPUT,
            )
        key = stripped.casefold()
        if not allow_duplicates and key in seen:
            raise _cli_error(
                f"Duplicate question text in batch: {stripped}",
                EXIT_CODE_BAD_INPUT,
            )
        seen.add(key)
        normalized.append((stripped, required_for_plan))
    return normalized


def _planning_template_hints(*, from_answers: bool) -> dict[str, object]:
    return {
        "template_command": _plan_template_command(from_answers=from_answers),
        "required_plan_fields": list(_REQUIRED_PLAN_FIELDS),
        "recommended_plan_fields": list(_RECOMMENDED_PLAN_FIELDS),
    }


def _plan_template_command(*, from_answers: bool) -> str:
    command = "taskledger plan template"
    if from_answers:
        command += " --from-answers"
    return f"{command} --file plan.md"


def _render_plan_template(
    answered_questions: Sequence[QuestionRecord],
    *,
    worker_pipeline: WorkerPipelineConfig | None = None,
) -> str:
    lines = [
        "---",
        "# Taskledger editable plan input.",
        "# Keep this front matter valid YAML.",
        "# Do not invent fields. Run `taskledger plan check --file ./plan.md`",
        "# before upsert.",
        "",
        'goal: "<one sentence describing the desired outcome>"',
        "",
        "# Plan-level files only. Todo-level `files:` is not captured.",
        "files:",
        '  - "@path/to/file.py"',
        "test_commands:",
        '  - "pytest -q path/to/test_file.py"',
        "expected_outputs:",
        '  - "pytest exits 0"',
        "",
        "# Acceptance criteria MUST use `text`, not `description`.",
        "# Supported keys: id, text, mandatory.",
        "acceptance_criteria:",
        "  - id: ac-0001",
        '    text: "<observable acceptance criterion>"',
        "    mandatory: true",
        "",
        "# Todos materialize into the implementation checklist.",
        "# Supported keys: id, text, mandatory, validation_hint, worker_step.",
        "todos:",
        "  - id: plan-todo-0001",
        '    text: "Edit @path/to/file.py to implement <specific behavior>."',
        "    mandatory: true",
        (
            '    validation_hint: "Run pytest -q path/to/test_file.py '
            'and inspect the expected output."'
        ),
        "---",
        "",
        "<!-- Required: keep this body. It is the implementation handoff context.",
        "     Run `taskledger plan check --file ./plan.md` before upsert. -->",
        "",
        "## Goal",
        "",
        "<repeat or expand the goal in human prose>",
        "",
        "## Implementation notes",
        "",
        "<describe the approach, architecture, and key decisions>",
        "",
        "## Validation plan",
        "",
        "## Plan input checklist before upsert",
        "",
        "- [ ] I ran `taskledger plan check --file plan.md`.",
        "- [ ] Every acceptance criterion uses `text`, not `description`.",
        "- [ ] Todo mappings use supported keys only: "
        "`id`, `id_hint`, `text`, `mandatory`, `validation_hint`, "
        "`worker_step`.",
        "- [ ] File references are plan-level `files:` entries "
        "or are mentioned in todo text/body; "
        "todo-level `files:` is not captured.",
        "- [ ] The Markdown body explains enough context for implementation handoff.",
        "",
    ]
    if answered_questions:
        lines.extend(["", "## Notes from answered questions", ""])
        for item in answered_questions:
            lines.append(f"- {item.id}: {item.answer}")
    if worker_pipeline is not None:
        lines.extend(_worker_pipeline_template_hints(worker_pipeline))
    return "\n".join(lines) + "\n"


def _insert_guidance_into_plan_template(template_text: str, guidance_text: str) -> str:
    normalized_guidance = guidance_text.strip()
    if not normalized_guidance:
        return template_text

    lines = template_text.splitlines()
    front_matter_end_index: int | None = None
    delimiter_count = 0
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            delimiter_count += 1
            if delimiter_count == 2:
                front_matter_end_index = idx
                break
    if front_matter_end_index is None:
        return template_text

    insertion = [
        "",
        "<!-- Advisory project planning guidance from taskledger plan guidance. -->",
        "",
        normalized_guidance,
        "",
    ]
    updated_lines = (
        lines[: front_matter_end_index + 1]
        + insertion
        + lines[front_matter_end_index + 1 :]
    )
    return "\n".join(updated_lines).rstrip() + "\n"


def _worker_pipeline_for_plan_template(
    workspace_root: Path,
) -> WorkerPipelineConfig:
    pipeline = load_worker_pipeline_config(workspace_root)
    if pipeline is None or not pipeline.enabled:
        raise _cli_error(
            "taskledger plan template --with-worker-pipeline requires an enabled "
            "worker pipeline.",
            EXIT_CODE_BAD_INPUT,
        )
    if pipeline.mode not in {"template", "guided"}:
        raise _cli_error(
            "Worker pipeline plan template hints require "
            "worker_pipeline.mode = 'template' or 'guided'.",
            EXIT_CODE_BAD_INPUT,
        )
    return pipeline


def _worker_pipeline_template_hints(pipeline: WorkerPipelineConfig) -> list[str]:
    lines = ["", "## Optional worker pipeline todo hints", ""]
    lines.append(
        "This project has a configured worker pipeline. Add `worker_step` to any "
        "plan todo that should map to a specific worker step."
    )
    lines.extend(["", "Configured worker steps:"])
    for step in pipeline.steps:
        lines.append(f"- {step.id}: {step.label} ({step.lifecycle_stage})")
    example_steps = [
        step
        for step in pipeline.steps
        if step.lifecycle_stage not in {"planning", "full"}
    ] or list(pipeline.steps)
    lines.extend(["", "Example:", "", "```yaml", "todos:"])
    if example_steps:
        for index, step in enumerate(example_steps[:2], start=1):
            lines.extend(
                [
                    f"  - id: plan-todo-{index:04d}",
                    f'    text: "<todo for {step.label}>"',
                    f'    worker_step: "{step.id}"',
                ]
            )
    else:
        lines.append("  - id: plan-todo-0001")
        lines.append('    text: "<todo text>"')
    lines.extend(["```", ""])
    return lines


def _dependency_blockers(
    workspace_root: Path, task: TaskRecord
) -> list[dict[str, str]]:
    return _task_query_dependency_blockers(workspace_root, task)


def _lock_conflict_message(task_id: str, lock: TaskLock) -> str:
    if lock_is_expired(lock):
        return (
            f"Task {task_id} has an expired {lock.stage} lock from {lock.run_id}. "
            "Recover it explicitly with: "
            f'taskledger repair lock --task {task_id} --reason "recover stale '
            f'{lock.stage} lock"'
        )
    return f"Task {task_id} is locked by {lock.run_id} for {lock.stage}."


def _enforce_decision(decision: Decision) -> None:
    if decision.ok:
        return
    error = _cli_error(decision.reason, decision.exit_code)
    if decision.details:
        error.taskledger_data = dict(decision.details)
        next_commands = decision.details.get("next_commands")
        if isinstance(next_commands, list) and next_commands:
            error.taskledger_remediation = [
                str(item) for item in next_commands if str(item).strip()
            ]
    raise error


def _summary_line(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = " ".join(text.split())
    return stripped[:117] + "..." if len(stripped) > 120 else stripped


def _git_change_state(workspace_root: Path) -> dict[str, str]:
    inside = _run_command(
        workspace_root,
        ("git", "rev-parse", "--is-inside-work-tree"),
        not_git_message="Git change scan requires a Git work tree.",
    )
    if inside.strip() != "true":
        raise _cli_error(
            "Git change scan requires a Git work tree.", EXIT_CODE_BAD_INPUT
        )
    branch = _run_command(workspace_root, ("git", "branch", "--show-current")).strip()
    status = _run_command(workspace_root, ("git", "status", "--short")).strip()
    diff_stat = _run_command(workspace_root, ("git", "diff", "--stat")).strip()
    return {
        "branch": branch or "(detached)",
        "status": status,
        "diff_stat": diff_stat,
    }


def _run_command(
    workspace_root: Path,
    argv: tuple[str, ...],
    *,
    not_git_message: str | None = None,
) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    if not_git_message and "not a git repository" in completed.stderr.lower():
        raise _cli_error(not_git_message, EXIT_CODE_BAD_INPUT)
    raise _cli_error(
        completed.stderr.strip() or f"Command failed: {' '.join(argv)}",
        EXIT_CODE_GENERIC_FAILURE,
    )


def _command_output(
    argv: tuple[str, ...],
    stdout: str,
    stderr: str,
) -> str:
    return (
        f"$ {shlex.join(argv)}\n\n"
        f"stdout:\n{stdout or '(empty)'}\n\n"
        f"stderr:\n{stderr or '(empty)'}\n"
    )


def _command_summary(
    argv: tuple[str, ...],
    exit_code: int,
    artifact_ref: str | None,
) -> str:
    summary = f"Ran {shlex.join(argv)} (exit {exit_code})"
    if artifact_ref is not None:
        summary += f" output: @{artifact_ref}"
    return summary


def _write_command_artifact(
    workspace_root: Path,
    task_id: str,
    run_id: str,
    output: str,
) -> str:
    paths = resolve_v2_paths(workspace_root)
    artifact_dir = task_artifacts_dir(paths, task_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    index = len(list(artifact_dir.glob(f"{run_id}-command-*.log"))) + 1
    artifact_path = artifact_dir / f"{run_id}-command-{index:04d}.log"
    atomic_write_text(artifact_path, output)
    return str(artifact_path.relative_to(paths.project_dir))


def _parse_plan_front_matter(body: str) -> tuple[dict[str, object], str]:
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, body
    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        front_matter = yaml.safe_load("\n".join(lines[1:index])) or {}
        if not isinstance(front_matter, dict):
            raise _cli_error(
                "Plan front matter must be a YAML mapping.",
                EXIT_CODE_BAD_INPUT,
            )
        return front_matter, "\n".join(lines[index + 1 :])
    raise _cli_error("Unterminated plan front matter.", EXIT_CODE_BAD_INPUT)


def _criteria_from_plan_input(
    front_matter: dict[str, object],
    criteria: tuple[str, ...],
) -> tuple[AcceptanceCriterion, ...]:
    raw_criteria = front_matter.get("acceptance_criteria", front_matter.get("criteria"))
    items: list[AcceptanceCriterion] = []
    if raw_criteria is not None:
        if not isinstance(raw_criteria, list):
            raise _cli_error(
                "Plan criteria front matter must be a list.",
                EXIT_CODE_BAD_INPUT,
            )
        for index, item in enumerate(raw_criteria, start=1):
            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                items.append(AcceptanceCriterion(id=_criterion_id(index), text=text))
                continue
            if not isinstance(item, dict):
                raise _cli_error(
                    "Plan criteria must be strings or mappings.",
                    EXIT_CODE_BAD_INPUT,
                )
            text = str(item.get("text") or "").strip()
            if not text:
                # Accept single-key shorthand: {ac-0001: "some text"}
                if len(item) == 1:
                    criterion_key, text_value = next(iter(item.items()))
                    text = str(text_value).strip()
                    if not text:
                        raise _cli_error(
                            "Plan criteria mappings must include non-empty text.",
                            EXIT_CODE_BAD_INPUT,
                        )
                    items.append(
                        AcceptanceCriterion(
                            id=str(criterion_key).strip(),
                            text=text,
                            mandatory=True,
                        )
                    )
                    continue
                raise _cli_error(
                    "Plan criteria mappings must include text.",
                    EXIT_CODE_BAD_INPUT,
                )
            criterion_id = str(item.get("id") or _criterion_id(index)).strip()
            items.append(
                AcceptanceCriterion(
                    id=criterion_id,
                    text=text,
                    mandatory=bool(item.get("mandatory", True)),
                )
            )
    else:
        for index, item in enumerate(criteria, start=1):
            text = item.strip()
            if text:
                items.append(AcceptanceCriterion(id=_criterion_id(index), text=text))
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise _cli_error("Plan criteria ids must be unique.", EXIT_CODE_BAD_INPUT)
    return tuple(items)


def _todos_from_plan_input(
    workspace_root: Path,
    front_matter: dict[str, object],
) -> tuple[TaskTodo, ...]:
    raw_todos = front_matter.get("todos")
    if raw_todos is None:
        return ()
    pipeline = load_worker_pipeline_config(workspace_root)
    if not isinstance(raw_todos, list):
        raise _cli_error("Plan todos front matter must be a list.", EXIT_CODE_BAD_INPUT)
    items: list[TaskTodo] = []
    for index, item in enumerate(raw_todos, start=1):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            items.append(
                TaskTodo(
                    id=f"plan-todo-{index:04d}",
                    text=text,
                    mandatory=True,
                    source="plan",
                )
            )
            continue
        if not isinstance(item, dict):
            raise _cli_error(
                "Plan todos must be strings or mappings.",
                EXIT_CODE_BAD_INPUT,
            )
        text = str(item.get("text") or "").strip()
        if not text:
            raise _cli_error(
                "Plan todo mappings must include text.",
                EXIT_CODE_BAD_INPUT,
            )
        items.append(
            TaskTodo(
                id=str(
                    item.get("id") or item.get("id_hint") or f"plan-todo-{index:04d}"
                ),
                text=text,
                mandatory=bool(item.get("mandatory", True)),
                source="plan",
                validation_hint=_optional_string_value(item.get("validation_hint")),
                worker_step_id=_plan_todo_worker_step_id(
                    pipeline,
                    item,
                    index=index,
                ),
            )
        )
    return tuple(items)


def _plan_todo_worker_step_id(
    pipeline: WorkerPipelineConfig | None,
    item: dict[str, object],
    *,
    index: int,
) -> str | None:
    raw_worker_step = item.get("worker_step")
    if raw_worker_step is None:
        return None
    if not isinstance(raw_worker_step, str) or not raw_worker_step.strip():
        raise _cli_error(
            f"Plan todo {index} worker_step must be a non-empty string.",
            EXIT_CODE_BAD_INPUT,
        )
    if pipeline is None or not pipeline.enabled:
        raise _cli_error(
            "Plan todo worker_step requires an enabled worker pipeline.",
            EXIT_CODE_BAD_INPUT,
        )
    worker_step_id = raw_worker_step.strip()
    try:
        pipeline.resolve_step(worker_step_id)
    except LaunchError as exc:
        raise _cli_error(str(exc), EXIT_CODE_BAD_INPUT) from exc
    return worker_step_id


def _latest_plan_or_none(workspace_root: Path, task_id: str) -> PlanRecord | None:
    plans = list_plans(workspace_root, task_id)
    return plans[-1] if plans else None


def _normalize_todo_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _optional_front_matter_string(
    front_matter: dict[str, object],
    key: str,
) -> str | None:
    return _optional_string_value(front_matter.get(key))


def _optional_string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _string_tuple_from_front_matter(
    front_matter: dict[str, object], key: str
) -> tuple[str, ...]:
    raw = front_matter.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _cli_error(
            f"Plan front matter '{key}' must be a list.", EXIT_CODE_BAD_INPUT
        )
    items: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise _cli_error(
                f"Plan front matter '{key}' must contain non-empty strings.",
                EXIT_CODE_BAD_INPUT,
            )
        items.append(item.strip())
    return tuple(items)


def _criterion_id(index: int) -> str:
    return f"ac-{index:04d}"


def _normalize_local_id(workspace_root: Path, ref: str, prefix: str) -> str:
    normalized = ref.strip().lower()
    try:
        return local_id_from_ref(workspace_root, normalized, kind=prefix)
    except LaunchError:
        raw_prefix = f"{prefix}-"
        if not normalized.startswith(raw_prefix):
            return normalized
        suffix = normalized.removeprefix(raw_prefix)
        if not suffix.isdigit():
            return normalized
        return f"{prefix}-{int(suffix):04d}"


def _next_lock_id(workspace_root: Path, now: datetime) -> str:
    paths = resolve_v2_paths(workspace_root)
    prefix = now.strftime("lock-%Y%m%dT%H%M%SZ")
    existing = [item.lock_id for item in load_active_locks(workspace_root)]
    existing.extend(
        path.stem.removeprefix("broken-")
        for path in paths.tasks_dir.glob("task-*/audit/broken-lock-*.yaml")
    )
    sequence = sum(1 for item in existing if item.startswith(prefix)) + 1
    return f"{prefix}-{sequence:04d}"


def _has_user_waiver(waiver: DependencyWaiver | None) -> bool:
    return waiver is not None and waiver.actor.actor_type == "user"


def _ensure_validation_can_pass(
    workspace_root: Path,
    task: TaskRecord,
    run: TaskRunRecord,
) -> None:
    report = _build_validation_gate_report(workspace_root, task, run)

    if not cast(bool, report["can_finish_passed"]):
        blockers = cast(list[dict[str, object]], report["blockers"])
        missing_criteria = []
        failing_criteria = []
        open_todos = []
        dependency_blockers = []

        for blocker in blockers:
            kind = blocker.get("kind")
            if kind == "criterion_missing":
                missing_criteria.append(blocker.get("ref"))
            elif kind == "criterion_fail":
                failing_criteria.append(blocker.get("ref"))
            elif kind == "todo_open":
                open_todos.append(blocker.get("ref"))
            elif kind == "dependency_blocker":
                dependency_blockers.append(blocker.get("ref"))

        raise _validation_incomplete(
            "Cannot mark validation passed because "
            "mandatory validation gates are incomplete.",
            {
                "missing_criteria": missing_criteria,
                "failing_criteria": failing_criteria,
                "open_mandatory_todos": open_todos,
                "dependency_blockers": dependency_blockers,
                "blockers": blockers,
            },
        )


def _criterion_has_user_waiver(check: ValidationCheck) -> bool:
    return check.waiver is not None and check.waiver.actor.actor_type == "user"


def _validation_incomplete(message: str, details: dict[str, object]) -> LaunchError:
    error = LaunchError(message)
    error.taskledger_exit_code = EXIT_CODE_VALIDATION_FAILED
    error.taskledger_error_code = "VALIDATION_INCOMPLETE"
    error.taskledger_data = details
    return error


def _render_validation_status(payload: dict[str, object]) -> str:  # noqa: C901
    """Render the validation gate report in human-readable text."""
    lines: list[str] = []

    task_slug = payload.get("task_slug", payload.get("task_id", "unknown"))
    task_id = payload.get("task_id", "")
    lines.append(f"# Validation Status: {task_slug}")
    if task_id:
        lines.append(f"Task ID: {task_id}")
    lines.append("")

    status_stage = payload.get("status_stage", "unknown")
    run_id = payload.get("run_id")
    lines.append(f"**Status Stage:** {status_stage}")
    if run_id:
        lines.append(f"**Run ID:** {run_id}")
    lines.append("")

    active_stage = payload.get("active_stage")
    if active_stage:
        lines.append(f"**Active Stage:** {active_stage}")
        lines.append("")

    accepted_plan = payload.get("accepted_plan", {})
    if isinstance(accepted_plan, dict):
        if accepted_plan:
            plan_version = accepted_plan.get("version")
            plan_status = accepted_plan.get("status", "unknown")
            lines.append(
                f"**Accepted Plan:** Version {plan_version}, Status: {plan_status}"
            )
        else:
            lines.append("**Accepted Plan:** None")
    lines.append("")

    implementation = payload.get("implementation", {})
    if isinstance(implementation, dict):
        if implementation:
            impl_run_id = implementation.get("run_id")
            impl_status = implementation.get("status", "unknown")
            impl_satisfied = implementation.get("satisfied", False)
            lines.append(
                f"**Implementation:** Run {impl_run_id}, Status: {impl_status}"
            )
            lines.append(f"  Satisfied: {'✓' if impl_satisfied else '✗'}")
        else:
            lines.append("**Implementation:** None")
    lines.append("")

    criteria = cast(list[dict[str, object]], payload.get("criteria", []))
    if criteria:
        lines.append("## Acceptance Criteria")
        for criterion in criteria:
            if isinstance(criterion, dict):
                criterion_id = criterion.get("id", "unknown")
                text = str(criterion.get("text", ""))
                mandatory = criterion.get("mandatory", False)
                satisfied = criterion.get("satisfied", False)
                has_waiver = criterion.get("has_waiver", False)
                latest_status = criterion.get("latest_status", "unknown")

                checkbox = "☒" if satisfied else "☐"
                mandatory_marker = " (mandatory)" if mandatory else ""
                lines.append(f"  {checkbox} {criterion_id}{mandatory_marker}")
                if text:
                    lines.append(f"      {text[:80]}...")
                lines.append(f"      Status: {latest_status}")
                if has_waiver:
                    lines.append("      ✓ Waived")
        lines.append("")

    todos_obj = payload.get("todos", {})
    if isinstance(todos_obj, dict):
        open_todos = todos_obj.get("open_mandatory", [])
        if open_todos:
            lines.append("## Open Mandatory Todos")
            for todo_id in open_todos:
                lines.append(f"  - {todo_id}")
            lines.append("")

    dependencies_obj = payload.get("dependencies", {})
    if isinstance(dependencies_obj, dict):
        dep_blockers = dependencies_obj.get("blockers", [])
        if dep_blockers:
            lines.append("## Dependency Blockers")
            for blocker_id in dep_blockers:
                lines.append(f"  - {blocker_id}")
            lines.append("")

    can_finish_passed = payload.get("can_finish_passed", False)
    lines.append("## Result")
    lines.append(f"**Can Finish Passed:** {'✓ Yes' if can_finish_passed else '✗ No'}")

    blockers = cast(list[dict[str, object]], payload.get("blockers", []))
    if blockers and not can_finish_passed:
        lines.append("")
        lines.append("### Blocking Issues")
        for blocker in blockers:
            if isinstance(blocker, dict):
                kind = blocker.get("kind", "unknown")
                message = blocker.get("message", "")
                lines.append(f"  - **{kind}**: {message}")
                hint = blocker.get("command_hint")
                if hint:
                    lines.append(f"    Hint: `{hint}`")

    return "\n".join(lines)


def _approval_actor(
    *,
    actor_type: str,
    actor_name: str | None,
    note: str | None,
    allow_agent_approval: bool,
    reason: str | None,
) -> ActorRef:
    normalized_actor = actor_type.strip()
    if normalized_actor == "user":
        if not (note or "").strip():
            raise _cli_error("Plan approval requires --note.", EXIT_CODE_BAD_INPUT)
        return ActorRef(
            actor_type="user",
            actor_name=(actor_name or getpass.getuser() or "user").strip(),
            tool="manual",
        )
    if normalized_actor == "agent":
        if not allow_agent_approval or not (reason or "").strip():
            raise _cli_error(
                "Agent approval requires --allow-agent-approval and --reason.",
                EXIT_CODE_APPROVAL_REQUIRED,
            )
        return ActorRef(
            actor_type="agent",
            actor_name=(actor_name or getpass.getuser() or "taskledger").strip(),
            tool="taskledger",
            host=socket.gethostname(),
            pid=os.getpid(),
        )
    raise _cli_error(
        f"Unsupported approval actor: {actor_type}",
        EXIT_CODE_BAD_INPUT,
    )


def _unique_slug(existing: list, value: str) -> str:
    base = slugify_project_ref(value, empty="task")
    taken = {item.slug for item in existing}
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def _lifecycle_payload(
    command: str,
    task: TaskRecord,
    *,
    warnings: list[str],
    changed: bool,
    plan_version: int | None = None,
    run: TaskRunRecord | None = None,
    lock: TaskLock | None = None,
    result: str | None = None,
) -> dict[str, object]:
    active_stage = (
        derive_active_stage(lock, (run,))
        if lock is not None and run is not None
        else None
    )
    payload: dict[str, object] = {
        "ok": True,
        "command": command,
        "task_id": task.id,
        "status": task.status_stage,
        "status_stage": task.status_stage,
        "active_stage": active_stage,
        "changed": changed,
        "warnings": warnings,
        "lock": lock.to_dict() if lock is not None else None,
    }
    if plan_version is not None:
        payload["plan_version"] = plan_version
    if run is not None:
        payload["run_id"] = run.run_id
        payload["run"] = run.to_dict()
    if result is not None:
        payload["result"] = result
    return payload


def _cli_error(message: str, exit_code: int) -> LaunchError:
    error = LaunchError(message)
    error.taskledger_exit_code = exit_code
    return error


def _stale_lock_error(task_id: str, lock: TaskLock) -> LaunchError:
    error = LaunchError(
        f"Task {task_id} has an expired {lock.stage} lock from {lock.run_id}. "
        "Break it explicitly before continuing."
    )
    error.taskledger_exit_code = EXIT_CODE_STALE_LOCK_REQUIRES_BREAK
    error.taskledger_error_type = "StaleLockRequiresBreak"
    error.taskledger_remediation = [
        (
            f"taskledger repair lock --task {task_id} "
            f'--reason "recover stale {lock.stage} lock"'
        )
    ]
    error.taskledger_data = {
        "task_id": task_id,
        "lock": lock.to_dict(),
    }
    return error


def _ensure_not_archived(task: TaskRecord, *, operation: str) -> None:
    if not is_archived_task(task):
        return
    raise _cli_error(
        (
            f"Cannot {operation} archived task {task.id}. "
            f"Use taskledger task unarchive {task.id} first."
        ),
        EXIT_CODE_INVALID_TRANSITION,
    )


def _task_with_sidecars(workspace_root: Path, task: TaskRecord) -> TaskRecord:
    return replace(
        task,
        requirements=_task_requirements(workspace_root, task),
        file_links=load_links(workspace_root, task.id).links,
        todos=load_todos(workspace_root, task.id).todos,
    )


def _task_payload(
    workspace_root: Path,
    task: TaskRecord,
    *,
    active_stage: str | None,
) -> dict[str, object]:
    payload = task.to_dict()
    archived = is_archived_task(task)
    payload["archived"] = archived
    payload["visibility"] = "archived" if archived else "visible"
    payload["global_ref"] = global_ref_for_local_id(workspace_root, task.id)
    payload["file_ref"] = file_ref_for_local_id(workspace_root, task.id)
    payload["active_stage"] = active_stage
    return payload


def _active_task_payload(
    workspace_root: Path,
    task: TaskRecord,
    *,
    state: ActiveTaskState,
    changed: bool,
    previous_task_id: str | None,
    active: bool = True,
) -> dict[str, object]:
    return {
        "kind": "active_task",
        "task_id": task.id,
        "task_ref": global_ref_for_local_id(workspace_root, task.id),
        "slug": task.slug,
        "title": task.title,
        "status_stage": task.status_stage,
        "active_stage": _task_active_stage(workspace_root, task) if active else None,
        "active": active,
        "changed": changed,
        "previous_task_id": previous_task_id,
        "state": state.to_dict(),
    }


def _task_active_stage(
    workspace_root: Path,
    task: TaskRecord,
    *,
    lock: TaskLock | None = None,
    runs: list[TaskRunRecord] | None = None,
) -> str | None:
    current_lock = lock or _current_lock(workspace_root, task.id)
    if current_lock is None or lock_is_expired(current_lock):
        return None
    task_runs = runs if runs is not None else list_runs(workspace_root, task.id)
    return derive_active_stage(current_lock, task_runs)


def _task_requirements(workspace_root: Path, task: TaskRecord) -> tuple[str, ...]:
    return tuple(
        item.task_id for item in load_requirements(workspace_root, task.id).requirements
    )

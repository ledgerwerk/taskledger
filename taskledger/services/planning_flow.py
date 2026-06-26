from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from taskledger.domain.models import ActorRef, HarnessRef
from taskledger.domain.policies import plan_propose_decision
from taskledger.domain.states import EXIT_CODE_BAD_INPUT
from taskledger.services import tasks as _tasks
from taskledger.services.plan_editing import render_editable_plan
from taskledger.services.plan_hash import approved_plan_content_hash
from taskledger.services.plan_input import (
    parse_plan_input,
    plan_input_error,
)
from taskledger.services.plan_lint import lint_plan
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    list_plans,
    list_questions,
    load_todos,
    overwrite_plan,
    resolve_plan,
    resolve_task,
    resolve_v2_paths,
    save_plan,
    save_run,
    save_task,
)
from taskledger.timeutils import utc_now_iso


def start_planning(
    workspace_root: Path,
    task_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="start planning for")
    if task.status_stage not in {"draft", "plan_review"}:
        raise _tasks._cli_error(
            "Planning can only start from draft or plan_review.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    run = _tasks._start_run(
        workspace_root,
        task,
        run_type="planning",
        stage="planning",
        actor=actor,
        harness=harness,
    )
    updated = replace(
        resolve_task(workspace_root, task.id),
        latest_planning_run=run.run_id,
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "plan.started",
        {"run_id": run.run_id},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "plan start",
        updated,
        warnings=[],
        changed=True,
        run=run,
        lock=_tasks._require_lock(workspace_root, updated.id),
    )


def propose_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    body: str,
    criteria: tuple[str, ...] = (),
    command_label: str = "plan propose",
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="propose plan for")
    run = _tasks._require_run(workspace_root, task, task.latest_planning_run)
    lock = _tasks._lock_for_mutation(workspace_root, task.id)
    _tasks._enforce_decision(plan_propose_decision(task, lock, run=run))
    plans = list_plans(workspace_root, task.id)
    version = plans[-1].plan_version + 1 if plans else 1
    parsed = parse_plan_input(workspace_root, body, criteria=criteria, strict=False)
    if parsed.has_errors:
        raise plan_input_error(parsed, command=command_label)
    plan_body = parsed.body
    questions = list_questions(workspace_root, task.id)
    plan = _tasks.PlanRecord(
        task_id=task.id,
        plan_version=version,
        body=plan_body.strip(),
        status="proposed",
        created_by=_tasks._default_actor(),
        supersedes=plans[-1].plan_version if plans else None,
        question_refs=tuple(item.id for item in questions if item.status == "open"),
        criteria=parsed.criteria,
        todos=parsed.todos,
        generation_reason=parsed.generation_reason or "initial",
        based_on_question_ids=tuple(
            item.id for item in questions if item.status == "answered"
        ),
        based_on_answer_hash=_tasks._answer_snapshot_hash(questions),
        goal=parsed.goal,
        files=parsed.files,
        test_commands=parsed.test_commands,
        expected_outputs=parsed.expected_outputs,
        todos_waived_reason=parsed.todos_waived_reason,
    )
    save_plan(workspace_root, plan)
    finished_run = replace(
        run,
        status="finished",
        finished_at=utc_now_iso(),
        summary=_tasks._summary_line(plan_body),
    )
    save_run(workspace_root, finished_run)
    updated = replace(
        task,
        latest_plan_version=version,
        status_stage="plan_review",
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._release_lock(
        workspace_root,
        task=updated,
        expected_stage="planning",
        run_id=run.run_id,
        target_stage="plan_review",
        event_name="stage.completed",
        extra_data={"plan_version": version},
        delete_only=True,
    )
    _tasks._append_event(
        workspace_root,
        updated.id,
        "plan.proposed",
        {"plan_version": version},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    warnings: list[str] = []
    if not plan_body.strip():
        warnings.append(
            "Plan body is empty; implementation handoff will not contain a human plan."
        )
    parser_warnings = [
        f"{issue.code} at {issue.location}: {issue.message}"
        for issue in parsed.issues
        if issue.severity == "warning"
    ]
    warnings.extend(parser_warnings)
    payload = _tasks._lifecycle_payload(
        "plan propose",
        updated,
        warnings=warnings,
        changed=True,
        plan_version=version,
    )
    payload["plan_body_chars"] = len(plan_body)
    payload["plan_body_lines"] = len(plan_body.splitlines())
    payload["plan_input_warnings"] = [
        issue.to_dict() for issue in parsed.issues if issue.severity == "warning"
    ]
    payload["next_review_command"] = f"taskledger plan review --version {version}"
    payload["approval_command_hint"] = (
        f'taskledger plan accept --version {version} --note "User approved in harness."'
    )
    return payload


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
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="upsert plan for")
    questions = list_questions(workspace_root, task.id)
    open_required = _tasks._required_open_question_ids(questions)
    if open_required and not allow_open_questions:
        raise _tasks._cli_error(
            "Plan upsert is blocked by required open questions: "
            + ", ".join(open_required),
            _tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
    latest_plan = _tasks._latest_plan_or_none(workspace_root, task.id)
    stale_answers = (
        _tasks._stale_answer_question_ids(questions, latest_plan)
        if latest_plan is not None
        else [
            item.id
            for item in questions
            if item.status == "answered" and item.required_for_plan
        ]
    )
    if from_answers or stale_answers:
        payload = cast(
            dict[str, object],
            _tasks.regenerate_plan_from_answers(
                workspace_root,
                task.id,
                body=body,
                criteria=criteria,
                allow_open_questions=allow_open_questions,
            ),
        )
        payload["operation"] = "regenerated"
        payload["command"] = "plan upsert"
        return payload
    auto_revised = False
    if auto_revise:
        lock = _tasks._current_lock(workspace_root, task.id)
        if task.status_stage == "plan_review" and lock is None:
            revised = start_planning(workspace_root, task.id)
            auto_revised = True
    payload = propose_plan(
        workspace_root,
        task.id,
        body=body,
        criteria=criteria,
        command_label="plan upsert",
    )
    payload["operation"] = "proposed"
    payload["command"] = "plan upsert"
    if auto_revised:
        payload["auto_revise_started"] = True
        if isinstance(revised.get("run_id"), str):
            payload["revision_run_id"] = revised["run_id"]
    return payload


def export_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    plan = resolve_plan(workspace_root, task.id, version=version)
    return {
        "kind": "plan_export",
        "task_id": task.id,
        "plan_version": plan.plan_version,
        "text": render_editable_plan(plan),
    }


def amend_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    drop_criteria: tuple[str, ...] = (),
    drop_todos: tuple[str, ...] = (),
    remove_files: tuple[str, ...] = (),
    reason: str,
) -> dict[str, object]:
    if not reason.strip():
        raise _tasks._cli_error("--reason is required.", EXIT_CODE_BAD_INPUT)

    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="amend plan for")
    _tasks._enforce_decision(
        _tasks.plan_revise_decision(task, _tasks._current_lock(workspace_root, task.id))
    )
    latest = resolve_plan(workspace_root, task.id)
    criterion_ids = {item.id for item in latest.criteria}
    unknown_criteria = sorted(
        {item for item in drop_criteria if item not in criterion_ids}
    )
    if unknown_criteria:
        raise _tasks._cli_error(
            "Unknown criterion id(s): " + ", ".join(unknown_criteria),
            EXIT_CODE_BAD_INPUT,
        )
    todo_ids = {item.id for item in latest.todos}
    unknown_todos = sorted({item for item in drop_todos if item not in todo_ids})
    if unknown_todos:
        raise _tasks._cli_error(
            "Unknown todo id(s): " + ", ".join(unknown_todos),
            EXIT_CODE_BAD_INPUT,
        )

    drop_criteria_set = set(drop_criteria)
    drop_todos_set = set(drop_todos)
    remove_files_set = set(remove_files)
    updated_criteria = tuple(
        item for item in latest.criteria if item.id not in drop_criteria_set
    )
    updated_todos = tuple(
        item for item in latest.todos if item.id not in drop_todos_set
    )
    updated_files = tuple(item for item in latest.files if item not in remove_files_set)

    draft = replace(
        latest,
        criteria=updated_criteria,
        todos=updated_todos,
        files=updated_files,
    )
    revised = start_planning(workspace_root, task.id)
    payload = propose_plan(
        workspace_root,
        task.id,
        body=render_editable_plan(draft),
        command_label="plan amend",
    )
    payload["command"] = "plan amend"
    payload["operation"] = "amended"
    payload["from_plan_version"] = latest.plan_version
    payload["reason"] = reason
    payload["dropped_criteria"] = sorted(drop_criteria_set)
    payload["dropped_todos"] = sorted(drop_todos_set)
    payload["removed_files"] = sorted(remove_files_set)
    if isinstance(revised.get("run_id"), str):
        payload["revision_run_id"] = revised["run_id"]

    warnings = payload.get("warnings")
    payload_warnings: list[str] = list(warnings) if isinstance(warnings, list) else []
    if drop_criteria_set and not drop_todos_set:
        payload_warnings.append(
            "Dropped acceptance criteria did not remove todos; "
            "add --drop-todo if intended."
        )
    if payload_warnings:
        payload["warnings"] = payload_warnings

    _tasks._append_event(
        workspace_root,
        task.id,
        "plan.amended",
        {
            "from_plan_version": latest.plan_version,
            "to_plan_version": payload["plan_version"],
            "reason": reason,
            "dropped_criteria": sorted(drop_criteria_set),
            "dropped_todos": sorted(drop_todos_set),
            "removed_files": sorted(remove_files_set),
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return payload


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
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="approve plan for")
    _tasks._enforce_decision(
        _tasks.plan_approve_decision(
            task, _tasks._current_lock(workspace_root, task.id)
        )
    )
    running_runs = _tasks._running_runs(workspace_root, task)
    if running_runs:
        raise _tasks._running_run_conflict_error(
            task,
            running_runs[0],
            _tasks._current_lock(workspace_root, task.id),
            message=(
                "Plan approval is blocked because this task still has a "
                f"running {running_runs[0].run_type} run {running_runs[0].run_id}. "
                "Run `taskledger doctor`."
            ),
            error_code="APPROVAL_REQUIRED",
            exit_code=_tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
    questions = list_questions(workspace_root, task.id)
    open_questions = _tasks._required_open_question_ids(questions)
    if open_questions and not allow_open_questions:
        raise _tasks._cli_error(
            "Plan approval is blocked by open planning questions: "
            + ", ".join(open_questions),
            _tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
    if allow_open_questions and not (reason or "").strip():
        raise _tasks._cli_error(
            "--allow-open-questions requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    target = resolve_plan(workspace_root, task.id, version=version)
    if target.status != "proposed":
        raise _tasks._cli_error(
            "Only proposed plan versions can be approved. "
            f"v{target.plan_version} is {target.status}.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    stale_answer_ids = _tasks._stale_answer_question_ids(questions, target)
    if stale_answer_ids:
        error = _tasks._cli_error(
            "Plan approval is blocked by answered planning questions that are not "
            "reflected in this plan. Regenerate the plan from answers first: "
            + ", ".join(stale_answer_ids),
            _tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
        error.taskledger_error_code = "APPROVAL_REQUIRED"
        raise error
    if not target.criteria and not allow_empty_criteria:
        raise _tasks._cli_error(
            "Plan approval requires at least one acceptance criterion.",
            _tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
    if allow_empty_criteria and not (reason or "").strip():
        raise _tasks._cli_error(
            "--allow-empty-criteria requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    if not target.todos and not allow_empty_todos:
        raise _tasks._cli_error(
            "Plan approval requires at least one todo. "
            'Use --allow-empty-todos --reason "..." for trivial tasks.',
            _tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
    if allow_empty_todos and not (reason or "").strip():
        raise _tasks._cli_error(
            "--allow-empty-todos requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    if not materialize_todos and not (reason or "").strip():
        raise _tasks._cli_error(
            "--no-materialize-todos requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    approved_by = _tasks._approval_actor(
        actor_type=actor_type,
        actor_name=actor_name,
        note=note,
        allow_agent_approval=allow_agent_approval,
        reason=reason,
    )
    lint_payload = lint_plan(workspace_root, task.id, version=version, strict=False)
    if not lint_payload["passed"] and not allow_lint_errors:
        lint_error = _tasks._cli_error(
            "Plan approval is blocked by plan lint errors. "
            "Run `taskledger plan lint --version ...`.",
            _tasks.EXIT_CODE_APPROVAL_REQUIRED,
        )
        lint_error.taskledger_error_code = "APPROVAL_REQUIRED"
        lint_error.taskledger_data = {
            **lint_error.taskledger_data,
            "details": {"plan_lint": lint_payload},
        }
        raise lint_error
    if allow_lint_errors and not (reason or "").strip():
        raise _tasks._cli_error(
            "--allow-lint-errors requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    normalized_approval_source = _normalize_approval_source(approval_source)
    approval_note = (note or reason or "").strip()
    warnings: list[str] = []
    if normalized_approval_source is None:
        warnings.append(
            "Approval source missing; set --approval-source for stronger provenance."
        )
    approval_source_value = normalized_approval_source or "unknown"
    approved_hash = approved_plan_content_hash(target)
    for plan in list_plans(workspace_root, task.id):
        if plan.plan_version == target.plan_version:
            updated_plan = replace(
                plan,
                status="accepted",
                approved_at=utc_now_iso(),
                approved_by=approved_by,
                approval_note=approval_note,
                approval_source=approval_source_value,
                approved_plan_hash=approved_hash,
            )
        elif plan.status == "rejected":
            updated_plan = plan
        else:
            updated_plan = replace(plan, status="superseded")
        overwrite_plan(workspace_root, updated_plan)
    updated = replace(
        task,
        accepted_plan_version=target.plan_version,
        status_stage="approved",
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    materialized = 0
    if materialize_todos:
        materialized_result = _tasks.materialize_plan_todos(
            workspace_root,
            updated.id,
            version=target.plan_version,
        )
        materialized = materialized_result["materialized_todos"]
        updated = resolve_task(workspace_root, updated.id)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "plan.approved",
        {
            "plan_version": target.plan_version,
            "approved_by": approved_by.to_dict(),
            "approval_note": approval_note,
            "approval_source": approval_source_value,
            "approved_plan_hash": approved_hash,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    payload = _tasks._lifecycle_payload(
        "plan approve",
        updated,
        warnings=warnings,
        changed=True,
        plan_version=target.plan_version,
        result=f"materialized_todos={materialized}",
    )
    payload["materialized_todos"] = materialized
    payload["mandatory_todos"] = len(
        [
            todo
            for todo in load_todos(workspace_root, updated.id).todos
            if todo.mandatory
        ]
    )
    payload["next_action"] = "taskledger implement start"
    payload["approval_source"] = approval_source_value
    payload["approved_plan_hash"] = approved_hash
    return payload


_APPROVAL_SOURCES = {
    "explicit_chat",
    "initial_instruction",
    "harness_preapproved",
    "manual_override",
    "unknown",
}


def _normalize_approval_source(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in _APPROVAL_SOURCES:
        raise _tasks._cli_error(
            "Invalid --approval-source value. Use one of: "
            + ", ".join(sorted(_APPROVAL_SOURCES - {"unknown"})),
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    return normalized


_PLANNING_GUIDANCE_WORKLOG_PREFIX = "Planning guidance viewed:"


def mark_planning_guidance_viewed(
    workspace_root: Path,
    task_ref: str,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="mark planning guidance viewed on")
    run = _tasks._optional_run(workspace_root, task, task.latest_planning_run)
    if run is None or run.run_type != "planning" or run.status != "running":
        return {"recorded": False, "run_id": None}
    if any(line.startswith(_PLANNING_GUIDANCE_WORKLOG_PREFIX) for line in run.worklog):
        return {"recorded": False, "run_id": run.run_id}
    updated = replace(
        run,
        worklog=tuple(
            [*run.worklog, f"{_PLANNING_GUIDANCE_WORKLOG_PREFIX} {utc_now_iso()}"]
        ),
    )
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "plan.guidance.viewed",
        {"run_id": run.run_id},
    )
    return {"recorded": True, "run_id": run.run_id}

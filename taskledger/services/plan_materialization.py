"""Plan todo materialization and plan regeneration from answers.

These functions were extracted from services/tasks.py to shrink the monolith.
tasks.py re-exports them for backward compatibility.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TypedDict

from taskledger.domain.models import (
    PlanRecord,
    TaskRunRecord,
    TaskTodo,
    TodoCollection,
)
from taskledger.domain.states import EXIT_CODE_APPROVAL_REQUIRED
from taskledger.ids import next_project_id
from taskledger.services import tasks as _tasks
from taskledger.services.plan_input import (
    parse_plan_input,
    plan_input_error,
)
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    list_plans,
    list_questions,
    overwrite_plan,
    resolve_plan,
    resolve_task,
    resolve_v2_paths,
    save_plan,
    save_run,
    save_task,
    save_todos,
)
from taskledger.timeutils import utc_now_iso


class PlanTodoMaterializationPayload(TypedDict):
    kind: str
    task_id: str
    plan_id: str
    materialized_todos: int
    todos: list[dict[str, object]]
    dry_run: bool


def materialize_plan_todos(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int,
    dry_run: bool = False,
) -> PlanTodoMaterializationPayload:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    plan = resolve_plan(workspace_root, task.id, version=version)
    existing_keys = {
        (
            todo.source_plan_id,
            _tasks._normalize_todo_text(todo.text),
        )
        for todo in task.todos
    }
    new_todos: list[TaskTodo] = []
    next_ids = [todo.id for todo in task.todos]
    for plan_todo in plan.todos:
        key = (
            plan.plan_id,
            _tasks._normalize_todo_text(plan_todo.text),
        )
        if key in existing_keys:
            continue
        todo_id = next_project_id(
            "todo",
            [*next_ids, *(todo.id for todo in new_todos)],
        )
        new_todos.append(
            replace(
                plan_todo,
                id=todo_id,
                source="plan",
                source_plan_id=plan.plan_id,
                mandatory=plan_todo.mandatory,
                status="open",
                done=False,
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
            )
        )
    if new_todos and not dry_run:
        updated = replace(
            task,
            todos=tuple([*task.todos, *new_todos]),
            updated_at=utc_now_iso(),
        )
        save_todos(
            workspace_root,
            TodoCollection(task_id=updated.id, todos=updated.todos),
        )
        save_task(workspace_root, updated)
        _tasks._append_event(
            workspace_root,
            updated.id,
            "todo.added",
            {
                "source_plan_id": plan.plan_id,
                "todo_ids": [todo.id for todo in new_todos],
            },
        )
    return PlanTodoMaterializationPayload(
        kind="plan_todo_materialization",
        task_id=task.id,
        plan_id=plan.plan_id,
        materialized_todos=len(new_todos),
        todos=[todo.to_dict() for todo in new_todos],
        dry_run=dry_run,
    )


def regenerate_plan_from_answers(
    workspace_root: Path,
    task_ref: str,
    *,
    body: str,
    criteria: tuple[str, ...] = (),
    allow_open_questions: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    questions = list_questions(workspace_root, task.id)
    open_required = [
        item.id
        for item in questions
        if item.status == "open" and item.required_for_plan
    ]
    if open_required and not allow_open_questions:
        raise _tasks._cli_error(
            "Plan regeneration is blocked by required open questions: "
            + ", ".join(open_required),
            EXIT_CODE_APPROVAL_REQUIRED,
        )
    answered = [
        item
        for item in questions
        if item.status == "answered" and item.required_for_plan
    ]
    plans = list_plans(workspace_root, task.id)
    if not answered and not plans:
        raise _tasks._cli_error(
            "Plan regeneration requires answered questions or a previous plan.",
            EXIT_CODE_APPROVAL_REQUIRED,
        )
    running_runs = _tasks._running_runs(workspace_root, task)
    latest_planning_run = _tasks._optional_run(
        workspace_root,
        task,
        task.latest_planning_run,
    )
    lock_to_release = _tasks._current_lock(workspace_root, task.id)
    run_to_finish: TaskRunRecord | None = None
    finish_orphaned_run: TaskRunRecord | None = None
    if running_runs:
        if (
            len(running_runs) == 1
            and latest_planning_run is not None
            and running_runs[0].run_id == latest_planning_run.run_id
            and latest_planning_run.run_type == "planning"
        ):
            if _tasks._lock_matches_run(lock_to_release, latest_planning_run):
                run_to_finish = latest_planning_run
            elif lock_to_release is None:
                finish_orphaned_run = latest_planning_run
            else:
                raise _tasks._running_run_conflict_error(
                    task,
                    latest_planning_run,
                    lock_to_release,
                    message=(
                        "Cannot regenerate plan because the latest planning "
                        "run and active lock disagree. Run `taskledger doctor`."
                    ),
                )
        else:
            raise _tasks._running_run_conflict_error(
                task,
                running_runs[0],
                lock_to_release,
                message=(
                    "Cannot regenerate plan while another run is still "
                    "running. Run `taskledger doctor`."
                ),
            )
    parsed = parse_plan_input(workspace_root, body, criteria=criteria, strict=True)
    if parsed.has_errors:
        raise plan_input_error(parsed, command="plan regenerate")
    plan_body = parsed.body
    version = plans[-1].plan_version + 1 if plans else 1
    plan = PlanRecord(
        task_id=task.id,
        plan_version=version,
        body=plan_body.strip(),
        status="proposed",
        created_by=_tasks._default_actor(),
        supersedes=plans[-1].plan_version if plans else None,
        question_refs=tuple(open_required),
        criteria=parsed.criteria,
        todos=parsed.todos,
        generation_reason="after_questions",
        based_on_question_ids=tuple(item.id for item in answered),
        based_on_answer_hash=_tasks._answer_snapshot_hash(questions),
        goal=parsed.goal,
        files=parsed.files,
        test_commands=parsed.test_commands,
        expected_outputs=parsed.expected_outputs,
        todos_waived_reason=parsed.todos_waived_reason,
    )
    save_plan(workspace_root, plan)
    if plans:
        previous = plans[-1]
        if previous.status == "proposed":
            overwrite_plan(workspace_root, replace(previous, status="superseded"))
    finish_time = utc_now_iso()
    if run_to_finish is not None:
        save_run(
            workspace_root,
            replace(
                run_to_finish,
                status="finished",
                finished_at=finish_time,
                summary=_tasks._summary_line(plan_body),
            ),
        )
    if finish_orphaned_run is not None:
        save_run(
            workspace_root,
            replace(
                finish_orphaned_run,
                status="finished",
                finished_at=finish_time,
                summary=_tasks._summary_line(plan_body),
            ),
        )
    updated = replace(
        task,
        latest_plan_version=version,
        status_stage="plan_review",
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    if run_to_finish is not None:
        _tasks._release_lock(
            workspace_root,
            task=updated,
            expected_stage="planning",
            run_id=run_to_finish.run_id,
            target_stage="plan_review",
            event_name="stage.completed",
            extra_data={"plan_version": version},
            delete_only=True,
        )
    if finish_orphaned_run is not None:
        _tasks._append_event(
            workspace_root,
            updated.id,
            "run.recovered",
            {
                "stage": "planning",
                "run_id": finish_orphaned_run.run_id,
                "recovered_missing_lock": True,
                "reason": (
                    "plan regenerated from answers; planning lock was already missing"
                ),
                "plan_version": version,
            },
        )
    _tasks._append_event(
        workspace_root,
        updated.id,
        "plan.proposed",
        {
            "plan_version": version,
            "generation_reason": "after_questions",
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    regenerate_warnings: list[str] = []
    if not plan_body.strip():
        regenerate_warnings.append(
            "Plan body is empty; implementation handoff will not contain a human plan."
        )
    regenerate_warnings.extend(
        f"{issue.code} at {issue.location}: {issue.message}"
        for issue in parsed.issues
        if issue.severity == "warning"
    )
    payload = _tasks._lifecycle_payload(
        "plan regenerate",
        updated,
        warnings=regenerate_warnings,
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

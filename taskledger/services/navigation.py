from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from taskledger.domain.models import (
    PlanRecord,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
)
from taskledger.domain.states import (
    ACTIVE_TASK_STAGES,
    EXIT_CODE_BAD_INPUT,
    IMPLEMENTABLE_TASK_STAGES,
)
from taskledger.domain.task import is_archived_task
from taskledger.services.next_action_logic import (
    _answered_question_next_item,
    _command,
    _commands_for_next_item,
    _compact_next_action_blockers,
    _criterion_next_item,
    _criterion_report_by_id,
    _first_question_by_ids,
    _implement_resume_command,
    _lock_next_item,
    _plan_next_item,
    _primary_command_for_next_item,
    _question_next_item,
    _required_open_question_ids,
    _stale_answer_question_ids,
    _task_next_item,
    _todo_next_item,
    _validation_progress,
)
from taskledger.services.tasks import (
    _build_todo_gate_report,
    _cli_error,
    _current_lock,
    _dependency_blockers,
    _optional_run,
    _planning_template_hints,
    _resumable_implementation_run,
    _running_run_details,
    _running_runs,
    _task_active_stage,
    _task_with_sidecars,
)
from taskledger.services.validation import build_validation_gate_report
from taskledger.services.worker_pipeline import determine_next_worker_step
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.project_config import load_worker_pipeline_config
from taskledger.storage.task_store import (
    list_plans,
    list_questions,
    list_runs,
    resolve_task,
)


def _archived_next_action_payload(task: TaskRecord) -> dict[str, object]:
    return _finalize_next_action_payload(
        {
            "kind": "task_next_action",
            "task_id": task.id,
            "status_stage": task.status_stage,
            "active_stage": None,
            "action": "archived",
            "reason": "Task is archived and read-only.",
            "blocking": [_archived_blocker(task)],
            "next_command": (
                f'taskledger task unarchive {task.id} --reason "Restore archived task."'
            ),
            "commands": [
                _command(
                    "unarchive",
                    "Unarchive task",
                    (
                        f"taskledger task unarchive {task.id}"
                        ' --reason "Restore archived task."'
                    ),
                )
            ],
            "progress": {},
        }
    )


def next_action_for_task(
    workspace_root: Path,
    task: TaskRecord,
    *,
    lock: TaskLock | None = None,
    runs: list[TaskRunRecord] | None = None,
) -> dict[str, object]:
    if lock is None:
        lock = _current_lock(workspace_root, task.id)
    if runs is None:
        runs = list_runs(workspace_root, task.id)
    active_stage = _task_active_stage(
        workspace_root,
        task,
        lock=lock,
        runs=runs,
    )
    lock_diagnostics_dict = _compute_lock_diagnostics_for_payload(lock, task.id)
    lock_warning = _lock_warning_for_action(lock, lock_diagnostics_dict)
    action: str
    reason: str
    blockers: list[dict[str, object]] = []
    next_item: dict[str, object] | None = None
    progress: dict[str, object] = {}
    if is_archived_task(task):
        return _archived_next_action_payload(task)
    if active_stage == "planning":
        action, reason, next_item, blockers, progress = _planning_next_action(
            workspace_root, task
        )
    elif active_stage == "implementation":
        action, reason, next_item, blockers, progress = _implementation_next_action(
            workspace_root, task
        )
    elif active_stage == "validation":
        action, reason, next_item, blockers, progress = _validation_next_action(
            workspace_root, task
        )
    else:
        (
            action,
            reason,
            next_item,
            status_blockers,
            status_progress,
        ) = _inactive_status_next_action(workspace_root, task, lock)
        blockers.extend(status_blockers)
        progress.update(status_progress)
    if lock is not None and active_stage is None:
        if lock_is_expired(lock):
            from taskledger.services.next_action_model import (
                decide_expired_lock_action,
            )

            (
                action,
                reason,
                next_item,
                lock_blockers,
            ) = decide_expired_lock_action(
                task=task,
                lock=lock,
                runs=runs,
                task_next_item=_lock_next_item(task, lock),
            )
            blockers.extend(lock_blockers)
            if action == "repair-lock":
                next_item = _lock_next_item(task, lock)
        else:
            blockers.append(
                {
                    "kind": "lock",
                    "message": (
                        f"Task has a {lock.stage} lock from {lock.run_id} "
                        "without a matching running run."
                    ),
                }
            )
            action = "repair-lock"
            reason = "A stale or broken lock must be repaired before work can continue."
            next_item = _lock_next_item(task, lock)
    # If diagnostics prove an orphaned local holder, override the chosen
    # action with an explicit repair-lock recommendation. This must run
    # after the main branches so we don't drop blockers/progress they set.
    if (
        lock is not None
        and isinstance(lock_diagnostics_dict, dict)
        and lock_diagnostics_dict.get("classification") == "active_dead_local_process"
    ):
        action = "repair-lock"
        reason = (
            "Implementation lock is active but the recorded holder "
            "process is not running."
        )
        blockers.append(
            {
                "kind": "lock",
                "message": str(lock_diagnostics_dict.get("summary", "")),
                "diagnostics": lock_diagnostics_dict,
            }
        )
        next_item = _lock_next_item(task, lock)
    return _build_next_action_payload(
        workspace_root,
        task,
        action=action,
        reason=reason,
        next_item=next_item,
        blockers=blockers,
        progress=progress,
        active_stage=active_stage,
        runs=runs,
        lock_diagnostics_dict=lock_diagnostics_dict,
        lock_warning=lock_warning,
    )


def _planning_next_action(
    workspace_root: Path,
    task: TaskRecord,
) -> tuple[
    str,
    str,
    dict[str, object] | None,
    list[dict[str, object]],
    dict[str, object],
]:
    blockers: list[dict[str, object]] = []
    progress: dict[str, object] = {}
    next_item: dict[str, object] | None = None
    questions = list_questions(workspace_root, task.id)
    open_questions = _required_open_question_ids(questions)
    answered_questions = [
        item.id
        for item in questions
        if item.status == "answered" and item.required_for_plan
    ]
    latest_plan = _latest_plan_or_none(workspace_root, task.id)
    stale_answers = (
        _stale_answer_question_ids(questions, latest_plan)
        if latest_plan is not None
        else answered_questions
    )
    if open_questions:
        action, reason = (
            "question-answer",
            "Required planning questions are open.",
        )
        question = _first_question_by_ids(questions, open_questions)
        next_item = _question_next_item(question) if question is not None else None
        progress["questions"] = {
            "required_open": len(open_questions),
            "required_open_ids": open_questions,
        }
        blockers.append(
            {
                "kind": "open_questions",
                "question_ids": open_questions,
                "message": "Required planning questions must be answered.",
            }
        )
    elif stale_answers:
        action, reason = (
            "plan-regenerate",
            "Answered planning questions should be reflected in the plan.",
        )
        question = _first_question_by_ids(questions, stale_answers)
        next_item = (
            _answered_question_next_item(question) if question is not None else None
        )
        progress["questions"] = {
            "required_open": 0,
            "required_open_ids": [],
            "answered_since_latest_plan": stale_answers,
        }
    else:
        action, reason = (
            "plan-propose",
            "Planning is active; propose the next plan.",
        )
    return action, reason, next_item, blockers, progress


def _implementation_next_action(
    workspace_root: Path,
    task: TaskRecord,
) -> tuple[
    str,
    str,
    dict[str, object] | None,
    list[dict[str, object]],
    dict[str, object],
]:
    blockers: list[dict[str, object]] = []
    progress: dict[str, object] = {}
    todo_report = _build_todo_gate_report(workspace_root, task)
    open_todo_ids = cast(list[str], todo_report.get("open_todos", []))
    open_todo_count = len(open_todo_ids)
    total_todos = todo_report.get("total", 0)
    done_todos = todo_report.get("done", 0)
    progress["todos"] = {
        "total": total_todos if isinstance(total_todos, int) else 0,
        "done": done_todos if isinstance(done_todos, int) else 0,
        "open": open_todo_count,
        "open_ids": open_todo_ids,
    }
    if open_todo_count > 0:
        todo = _first_open_todo_from_report(workspace_root, task, open_todo_ids)
        next_item = _todo_next_item(todo) if todo is not None else None
        action, reason = (
            "todo-work",
            f"Implementation is in progress; {open_todo_count} todos remain.",
        )
    else:
        action, reason = (
            "implement-finish",
            "All todos done; ready to finish implementation.",
        )
        next_item = _task_next_item(task)
    return action, reason, next_item, blockers, progress


def _validation_next_action(
    workspace_root: Path,
    task: TaskRecord,
) -> tuple[
    str,
    str,
    dict[str, object] | None,
    list[dict[str, object]],
    dict[str, object],
]:
    blockers: list[dict[str, object]] = []
    progress: dict[str, object] = {}
    gate_report = build_validation_gate_report(workspace_root, task)
    report_blockers = cast(list[dict[str, object]], gate_report.get("blockers", []))
    blockers.extend(_compact_next_action_blockers(report_blockers))
    progress["validation"] = _validation_progress(gate_report)
    if report_blockers:
        action, reason = (
            "validate-check",
            "Validation is in progress; required checks remain.",
        )
        next_item = _next_validation_item(
            workspace_root,
            task,
            gate_report,
            report_blockers,
        )
    else:
        action, reason = (
            "validate-finish",
            "Validation is complete enough to finish.",
        )
        next_item = _task_next_item(task)
    return action, reason, next_item, blockers, progress


def _build_next_action_payload(
    workspace_root: Path,
    task: TaskRecord,
    *,
    action: str,
    reason: str,
    next_item: dict[str, object] | None,
    blockers: list[dict[str, object]],
    progress: dict[str, object],
    active_stage: str | None,
    runs: list[TaskRunRecord],
    lock_diagnostics_dict: dict[str, object] | None,
    lock_warning: str | None,
) -> dict[str, object]:
    next_command = _primary_command_for_next_item(action, next_item)
    # Derive next_command from blocker hints when the static mapping has no entry.
    if next_command is None and blockers:
        for blocker in blockers:
            hint = blocker.get("command_hint")
            if isinstance(hint, str) and hint.strip():
                next_command = hint.strip()
                break
    commands = _commands_for_next_item(action, next_item)
    guidance_command = _guidance_command(
        workspace_root=workspace_root,
        task=task,
        action=action,
        active_stage=active_stage,
        runs=runs,
    )
    payload: dict[str, object] = {
        "kind": "task_next_action",
        "task_id": task.id,
        "status_stage": task.status_stage,
        "active_stage": active_stage,
        "action": action,
        "reason": reason,
        "blocking": blockers,
        "next_command": next_command,
        "guidance_command": guidance_command,
        "next_item": next_item,
        "commands": commands,
        "progress": progress,
    }
    if lock_diagnostics_dict is not None:
        payload["lock_status"] = lock_diagnostics_dict
    if lock_warning is not None:
        payload["lock_warning"] = lock_warning
    if guidance_command is not None:
        payload["guidance_command"] = guidance_command
    if action in {"plan-propose", "plan-regenerate"}:
        _apply_planning_check_command(payload, action, commands)
    guided_worker_pipeline = _guided_worker_pipeline_payload(workspace_root, task)
    if guided_worker_pipeline is not None:
        payload["worker_pipeline"] = guided_worker_pipeline
        payload["commands"] = _append_guided_worker_pipeline_commands(
            cast(list[dict[str, object]], payload["commands"]),
            guided_worker_pipeline,
        )
    return _finalize_next_action_payload(payload)


def next_action(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    return next_action_for_task(workspace_root, task)


def _orphaned_active_stage_action(
    workspace_root: Path,
    task: TaskRecord,
    lock: TaskLock | None,
) -> tuple[str, str, dict[str, object] | None, list[dict[str, object]]]:
    from taskledger.services.next_action_model import (
        decide_orphaned_active_stage,
    )

    runs = list_runs(workspace_root, task.id)
    plans = list_plans(workspace_root, task.id)
    return decide_orphaned_active_stage(
        task=task,
        plans=plans,
        runs=runs,
        lock=lock,
        task_next_item=_task_next_item(task),
    )


def _inactive_status_next_action(
    workspace_root: Path,
    task: TaskRecord,
    lock: TaskLock | None,
) -> tuple[
    str,
    str,
    dict[str, object] | None,
    list[dict[str, object]],
    dict[str, object],
]:
    blockers: list[dict[str, object]] = []
    progress: dict[str, object] = {}
    next_item: dict[str, object] | None = None
    if task.status_stage == "draft":
        return (
            "plan",
            "Draft tasks need planning before work starts.",
            None,
            blockers,
            progress,
        )
    if task.status_stage == "plan_review":
        questions = list_questions(workspace_root, task.id)
        open_questions = _required_open_question_ids(questions)
        latest_plan = _latest_plan_or_none(workspace_root, task.id)
        stale_answers = (
            _stale_answer_question_ids(questions, latest_plan)
            if latest_plan is not None
            else []
        )
        if open_questions:
            question = _first_question_by_ids(questions, open_questions)
            next_item = _question_next_item(question) if question is not None else None
            progress["questions"] = {
                "required_open": len(open_questions),
                "required_open_ids": open_questions,
            }
            blockers.append(
                {
                    "kind": "open_questions",
                    "question_ids": open_questions,
                    "message": "Required planning questions must be answered.",
                }
            )
            return (
                "question-answer",
                "Required planning questions are open.",
                next_item,
                blockers,
                progress,
            )
        if stale_answers:
            question = _first_question_by_ids(questions, stale_answers)
            next_item = (
                _answered_question_next_item(question) if question is not None else None
            )
            progress["questions"] = {
                "required_open": 0,
                "required_open_ids": [],
                "answered_since_latest_plan": stale_answers,
            }
            blockers.append(
                {
                    "kind": "stale_answers",
                    "question_ids": stale_answers,
                    "message": "Regenerate the plan from answered questions.",
                }
            )
            return (
                "plan-regenerate",
                "Answered planning questions are not reflected in the latest plan.",
                next_item,
                blockers,
                progress,
            )
        if latest_plan is not None:
            next_item = _plan_next_item(latest_plan)
        return (
            "plan-approve",
            "A proposed plan is waiting for review.",
            next_item,
            blockers,
            progress,
        )
    if task.status_stage == "approved":
        next_item = _task_next_item(task)
        running_runs = _running_runs(workspace_root, task)
        non_resumable_runs = [
            run
            for run in running_runs
            if not (
                run.run_type == "implementation"
                and run.run_id == task.latest_implementation_run
                and lock is None
            )
        ]
        if non_resumable_runs:
            run = non_resumable_runs[0]
            blockers.append(
                {
                    "kind": "running_run",
                    "message": (
                        f"Task has running {run.run_type} run {run.run_id}; "
                        "run `taskledger doctor`."
                    ),
                    **_running_run_details(task, run, lock),
                }
            )
            return (
                "repair-run-state",
                (
                    f"Task is approved, but {run.run_type} run {run.run_id} "
                    "is still marked running."
                ),
                next_item,
                blockers,
                progress,
            )
        resumable_run = _resumable_implementation_run(
            workspace_root,
            task,
            lock=lock,
        )
        if resumable_run is not None:
            blockers.append(
                {
                    "kind": "lock",
                    "message": (
                        "Missing active implementation lock "
                        f"for run {resumable_run.run_id}."
                    ),
                }
            )
            return (
                "implement-resume",
                "Implementation run is running but the lock is missing.",
                next_item,
                blockers,
                progress,
            )
        if task.accepted_plan_version is None:
            blockers.append(
                {"kind": "approval", "message": "No accepted plan version is recorded."}
            )
        blockers.extend(
            cast(list[dict[str, object]], _dependency_blockers(workspace_root, task))
        )
        return (
            "implement",
            "The approved plan is ready for implementation.",
            next_item,
            blockers,
            progress,
        )
    if task.status_stage == "implemented":
        next_item = _task_next_item(task)
        impl_run = _optional_run(workspace_root, task, task.latest_implementation_run)
        if (
            impl_run is None
            or impl_run.run_type != "implementation"
            or impl_run.status != "finished"
        ):
            blockers.append(
                {
                    "kind": "implementation",
                    "message": "Validation requires a finished implementation run.",
                }
            )
            return (
                "validate",
                "Implementation is complete and ready to validate.",
                next_item,
                blockers,
                progress,
            )
        from taskledger.services.workspace_snapshot import (
            compare_implementation_snapshot,
        )

        evaluation = compare_implementation_snapshot(workspace_root, task, impl_run)
        if not evaluation.ok:
            blockers.append(
                {
                    "kind": "implementation_snapshot",
                    "message": evaluation.message,
                    "reason_code": evaluation.reason_code,
                    "command_hint": evaluation.command_hint,
                    "details": evaluation.details,
                }
            )
            return (
                "validate-reconcile",
                "Implementation is finished, but validation is blocked by a "
                "workspace snapshot mismatch.",
                next_item,
                blockers,
                progress,
            )
        return (
            "validate",
            "Implementation is complete and ready to validate.",
            next_item,
            blockers,
            progress,
        )
    if task.status_stage == "failed_validation":
        next_item = _task_next_item(task)
        blockers.extend(
            cast(list[dict[str, object]], _dependency_blockers(workspace_root, task))
        )
        return (
            "implement-restart",
            "Validation failed; restart implementation.",
            next_item,
            blockers,
            progress,
        )
    if task.status_stage in ACTIVE_TASK_STAGES:
        action, reason, next_item, orphaned_blockers = _orphaned_active_stage_action(
            workspace_root,
            task,
            lock,
        )
        blockers.extend(orphaned_blockers)
        return action, reason, next_item, blockers, progress
    if task.status_stage == "done":
        return "none", "The task is complete.", None, blockers, progress
    return "none", "The task is cancelled.", None, blockers, progress


def _finalize_next_action_payload(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("action") == "plan-regenerate":
        payload.update(_planning_template_hints(from_answers=True))
    return payload


def _guidance_command(
    *,
    workspace_root: Path,
    task: TaskRecord,
    action: str,
    active_stage: str | None,
    runs: Sequence[object],
) -> str | None:
    if active_stage != "planning":
        return None
    if action not in {"plan-propose", "question-answer", "plan-regenerate"}:
        return None
    if _planning_guidance_already_viewed(task, runs):
        return None
    return "taskledger plan guidance"


def _planning_guidance_already_viewed(
    task: TaskRecord,
    runs: Sequence[object],
) -> bool:
    from taskledger.domain.models import TaskRunRecord

    planning_run_id = task.latest_planning_run
    if planning_run_id is None:
        return False
    for run in runs:
        if not isinstance(run, TaskRunRecord):
            continue
        if run.run_id != planning_run_id or run.run_type != "planning":
            continue
        return any(line.startswith("Planning guidance viewed:") for line in run.worklog)
    return False


def _apply_planning_check_command(
    payload: dict[str, object],
    action: str,
    fallback_commands: list[dict[str, object]],
) -> None:
    template_cmd = (
        "taskledger plan template --include-guidance --file plan.md"
        if action == "plan-propose"
        else (
            "taskledger plan template --from-answers --include-guidance --file plan.md"
        )
    )
    default_check_cmd = "taskledger plan check --file plan.md"
    payload["template_command"] = template_cmd
    payload["check_command"] = default_check_cmd

    guidance_cmd_value = payload.get("guidance_command")
    existing = cast(list[dict[str, object]], payload.get("commands", fallback_commands))

    prefix: list[dict[str, object]] = []
    if guidance_cmd_value is not None:
        prefix.append(
            _command("guidance", "Review planning guidance", str(guidance_cmd_value))
        )
    prefix.append(_command("template", "Write editable plan template", template_cmd))
    prefix.append(_command("check", "Validate plan input", default_check_cmd))

    lifecycle = _without_kinds(existing, {"guidance", "template", "check"})
    payload["commands"] = [*prefix, *lifecycle]


def _archived_blocker(task: TaskRecord) -> dict[str, object]:
    return {
        "kind": "archived_task",
        "message": (
            f"Task {task.id} is archived and read-only. "
            f'Use taskledger task unarchive {task.id} --reason "..." first, '
            "then re-check next-action."
        ),
        "command_hint": (
            f'taskledger task unarchive {task.id} --reason "Restore archived task."'
        ),
    }


def can_perform(workspace_root: Path, task_ref: str, action: str) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    if is_archived_task(task):
        return {
            "kind": "task_capability",
            "task_id": task.id,
            "action": action,
            "ok": False,
            "reason": "Task is archived and read-only.",
            "active_stage": None,
            "blocking": [_archived_blocker(task)],
        }
    lock = _current_lock(workspace_root, task.id)
    active_stage = _task_active_stage(workspace_root, task, lock=lock)
    ok = False
    reason = ""
    blocking: list[dict[str, object]] = []
    if action == "plan":
        ok = task.status_stage in {"draft", "plan_review"} and lock is None
        reason = (
            "Planning can start from draft or after plan review."
            if ok
            else (
                "Planning is only available from draft or plan_review "
                "without an active lock."
            )
        )
        if lock is not None:
            blocking.append(
                {
                    "kind": "lock",
                    "message": (
                        f"Task has an active {lock.stage} lock from {lock.run_id}."
                    ),
                }
            )
    elif action == "implement":
        running_runs = _running_runs(workspace_root, task)
        ok = (
            task.status_stage in IMPLEMENTABLE_TASK_STAGES
            and task.accepted_plan_version is not None
            and not _dependency_blockers(workspace_root, task)
            and not running_runs
            and lock is None
            and active_stage is None
        )
        reason = (
            "Implementation is ready."
            if ok
            else (
                "Implementation requires an accepted plan, valid stage, "
                "no conflicting lock, and completed dependencies."
            )
        )
        if task.accepted_plan_version is None:
            blocking.append(
                {"kind": "approval", "message": "No accepted plan version."}
            )
        blocking.extend(
            cast(list[dict[str, object]], _dependency_blockers(workspace_root, task))
        )
        if running_runs:
            running_run = running_runs[0]
            can_resume = (
                running_run.run_type == "implementation"
                and running_run.run_id == task.latest_implementation_run
            )
            blocking.append(
                {
                    "kind": "implementation",
                    "message": (
                        f"Task already has running {running_run.run_type} run "
                        f"{running_run.run_id}; "
                        + (
                            "use taskledger implement resume."
                            if can_resume
                            else "run taskledger doctor."
                        )
                    ),
                    "command_hint": (
                        _implement_resume_command(task.id)
                        if can_resume
                        else "taskledger doctor"
                    ),
                    **_running_run_details(task, running_run, lock),
                }
            )
        if lock is not None:
            blocking.append(
                {
                    "kind": "lock",
                    "message": (
                        f"Task has an active {lock.stage} lock from {lock.run_id}."
                    ),
                }
            )
    elif action in ("implement-resume", "expired-lock-resume"):
        ok, reason, resume_blockers = _check_resume_can_perform(
            action=action,
            task=task,
            lock=lock,
            active_stage=active_stage,
            workspace_root=workspace_root,
        )
        blocking.extend(resume_blockers)
    elif action == "implement-restart":
        validation_run = _optional_run(workspace_root, task, task.latest_validation_run)
        implementation_run = _optional_run(
            workspace_root,
            task,
            task.latest_implementation_run,
        )
        ok = (
            task.status_stage == "failed_validation"
            and task.accepted_plan_version is not None
            and validation_run is not None
            and validation_run.run_type == "validation"
            and validation_run.status in {"failed", "blocked"}
            and validation_run.result in {"failed", "blocked"}
            and implementation_run is not None
            and implementation_run.run_type == "implementation"
            and not _dependency_blockers(workspace_root, task)
            and lock is None
            and active_stage is None
        )
        reason = (
            "Implementation restart is ready."
            if ok
            else (
                "Implementation restart requires failed_validation state, "
                "an accepted plan, recorded failed validation, a previous "
                "implementation run, no conflicting lock, and completed dependencies."
            )
        )
        if task.accepted_plan_version is None:
            blocking.append(
                {"kind": "approval", "message": "No accepted plan version."}
            )
        if (
            validation_run is None
            or validation_run.run_type != "validation"
            or validation_run.status not in {"failed", "blocked"}
            or validation_run.result not in {"failed", "blocked"}
        ):
            blocking.append(
                {
                    "kind": "validation",
                    "message": "No failed validation run is available for restart.",
                }
            )
        if (
            implementation_run is None
            or implementation_run.run_type != "implementation"
        ):
            blocking.append(
                {
                    "kind": "implementation",
                    "message": "No previous implementation run is available.",
                }
            )
        blocking.extend(
            cast(list[dict[str, object]], _dependency_blockers(workspace_root, task))
        )
        if lock is not None:
            blocking.append(
                {
                    "kind": "lock",
                    "message": (
                        f"Task has an active {lock.stage} lock from {lock.run_id}."
                    ),
                }
            )
    elif action == "validate":
        impl_run = _optional_run(workspace_root, task, task.latest_implementation_run)
        ok = (
            task.status_stage == "implemented"
            and lock is None
            and active_stage is None
            and impl_run is not None
            and impl_run.run_type == "implementation"
            and impl_run.status == "finished"
        )
        reason = (
            "Validation is ready."
            if ok
            else (
                "Validation requires implemented state, a finished "
                "implementation run, and no conflicting lock."
            )
        )
        if ok and impl_run is not None:
            from taskledger.services.workspace_snapshot import (
                compare_implementation_snapshot,
            )

            evaluation = compare_implementation_snapshot(workspace_root, task, impl_run)
            if not evaluation.ok:
                ok = False
                reason = "Validation is blocked by implementation snapshot mismatch."
                blocking.append(
                    {
                        "kind": "implementation_snapshot",
                        "message": evaluation.message,
                        "reason_code": evaluation.reason_code,
                        "command_hint": evaluation.command_hint,
                        "details": evaluation.details,
                    }
                )
        if (
            impl_run is None
            or impl_run.run_type != "implementation"
            or impl_run.status != "finished"
        ):
            blocking.append(
                {
                    "kind": "implementation",
                    "message": "No finished implementation run is available.",
                }
            )
        if lock is not None:
            blocking.append(
                {
                    "kind": "lock",
                    "message": (
                        f"Task has an active {lock.stage} lock from {lock.run_id}."
                    ),
                }
            )
    else:
        raise _cli_error(f"Unsupported action: {action}", EXIT_CODE_BAD_INPUT)
    return {
        "kind": "task_capability",
        "task_id": task.id,
        "action": action,
        "ok": ok,
        "reason": reason,
        "active_stage": active_stage,
        "blocking": blocking,
    }


def task_dossier(
    workspace_root: Path,
    task_ref: str,
    *,
    format_name: str = "markdown",
) -> str | dict[str, object]:
    from taskledger.services.handoff import render_handoff

    return render_handoff(
        workspace_root,
        task_ref,
        mode="full",
        format_name=format_name,
    )


def _latest_plan_or_none(workspace_root: Path, task_id: str) -> PlanRecord | None:
    plans = list_plans(workspace_root, task_id)
    return plans[-1] if plans else None


def _compute_lock_diagnostics_for_payload(
    lock: TaskLock | None, task_id: str
) -> dict[str, object] | None:
    if lock is None:
        return None
    from taskledger.services.lock_diagnostics import diagnose_lock

    return diagnose_lock(lock, task_id=task_id).to_dict()


def _lock_warning_for_action(
    lock: TaskLock | None,
    diagnostics_dict: dict[str, object] | None,
) -> str | None:
    """One-line human warning for non-dead active locks.

    The dead-PID case is handled by overriding the action to repair-lock;
    we only need a warning for live or unverifiable holders.
    """
    if lock is None or diagnostics_dict is None:
        return None
    classification = diagnostics_dict.get("classification")
    if classification in {
        "active_dead_local_process",
        "expired",
        "active_same_actor",
    }:
        return None
    holder = lock.holder
    pid_part = f" pid={holder.pid}" if holder.pid else ""
    host_part = f" host={holder.host}" if holder.host else ""
    return (
        f"Warning: task has an active lock held by "
        f"{holder.actor_type}:{holder.actor_name}{host_part}{pid_part}. "
        "Do not take over from another live holder; inspect with "
        "taskledger lock show or use a handoff."
    )


def _guided_worker_pipeline_payload(
    workspace_root: Path,
    task: TaskRecord,
) -> dict[str, object] | None:
    pipeline = load_worker_pipeline_config(workspace_root)
    if pipeline is None or not pipeline.enabled or pipeline.mode != "guided":
        return None
    step = determine_next_worker_step(workspace_root, task, pipeline)
    if step is None:
        return None
    payload = {
        "configured": True,
        "enabled": True,
        "mode": pipeline.mode,
        "next_step": step.to_dict(),
        "context_command": f"taskledger pipeline context {step.id}",
        "handoff_command": _guided_worker_handoff_command(step.id, step.base_context),
    }
    review_command = _guided_worker_review_command(step.id, step.lifecycle_stage)
    if review_command is not None:
        payload["review_command"] = review_command
    return payload


def _guided_worker_handoff_command(step_id: str, base_context: str) -> str:
    command = f"taskledger handoff create --worker {step_id}"
    if base_context in {"spec-reviewer", "code-reviewer"}:
        command += " --scope task"
    return command + ' --summary "..."'


def _guided_worker_review_command(step_id: str, lifecycle_stage: str) -> str | None:
    if lifecycle_stage != "review":
        return None
    return (
        "taskledger review record "
        f"--worker {step_id} --from-git --result pass --summary-file REVIEW.md"
    )


def _append_guided_worker_pipeline_commands(
    commands: list[dict[str, object]],
    worker_pipeline: Mapping[str, object],
) -> list[dict[str, object]]:
    context_command = worker_pipeline.get("context_command")
    handoff_command = worker_pipeline.get("handoff_command")
    review_command = worker_pipeline.get("review_command")
    extras: list[dict[str, object]] = []
    if isinstance(context_command, str):
        extras.append(_command("context", "Show worker context", context_command))
    if isinstance(handoff_command, str):
        extras.append(_command("handoff", "Create worker handoff", handoff_command))
    if isinstance(review_command, str):
        extras.append(_command("review", "Record code review", review_command))
    if not extras:
        return commands
    for index, item in enumerate(commands):
        if bool(item.get("primary")):
            return [*commands[: index + 1], *extras, *commands[index + 1 :]]
    return [*commands, *extras]


def _first_open_todo_from_report(
    workspace_root: Path,
    task: TaskRecord,
    open_ids: Sequence[str],
) -> TaskTodo | None:
    task = _task_with_sidecars(workspace_root, task)
    wanted = set(open_ids)
    for todo in task.todos:
        if todo.id in wanted and todo.status == "active" and not todo.done:
            return todo
    for todo in task.todos:
        if todo.id in wanted and not todo.done:
            return todo
    return None


def _check_resume_can_perform(
    *,
    action: str,
    task: TaskRecord,
    lock: TaskLock | None,
    active_stage: str | None,
    workspace_root: Path,
) -> tuple[bool, str, list[dict[str, object]]]:
    blocking: list[dict[str, object]] = []
    implementation_run = _optional_run(
        workspace_root,
        task,
        task.latest_implementation_run,
    )
    dependency_blockers = _dependency_blockers(workspace_root, task)
    if action == "expired-lock-resume":
        ok = (
            task.status_stage in {"approved", "implementing"}
            and task.accepted_plan_version is not None
            and implementation_run is not None
            and implementation_run.run_type == "implementation"
            and implementation_run.status == "running"
            and not dependency_blockers
            and lock is not None
            and lock_is_expired(lock)
            and lock.run_id == implementation_run.run_id
        )
    else:
        ok = (
            task.status_stage in {"approved", "implementing"}
            and task.accepted_plan_version is not None
            and implementation_run is not None
            and implementation_run.run_type == "implementation"
            and implementation_run.status == "running"
            and not dependency_blockers
            and lock is None
            and active_stage is None
        )
    if ok:
        reason = "Implementation resume is ready."
    elif action == "expired-lock-resume":
        reason = (
            "Expired lock resume requires an expired implementation lock "
            "matching the running implementation run."
        )
    else:
        reason = (
            "Implementation resume requires approved or implementing state, "
            "an accepted plan, a running implementation run, no active lock, "
            "and completed dependencies."
        )
    if task.status_stage not in {"approved", "implementing"}:
        blocking.append(
            {
                "kind": "stage",
                "message": (
                    "Implementation resume requires approved or implementing state."
                ),
            }
        )
    if task.accepted_plan_version is None:
        blocking.append(
            {
                "kind": "approval",
                "message": "No accepted plan version.",
            }
        )
    if (
        implementation_run is None
        or implementation_run.run_type != "implementation"
        or implementation_run.status != "running"
    ):
        blocking.append(
            {
                "kind": "implementation",
                "message": ("No running implementation run is available to resume."),
            }
        )
    blocking.extend(cast(list[dict[str, object]], dependency_blockers))
    if lock is not None and not lock_is_expired(lock):
        blocking.append(
            {
                "kind": "lock",
                "message": (
                    f"Task has an active {lock.stage} lock from {lock.run_id}."
                ),
            }
        )
    if action == "expired-lock-resume" and (lock is None or not lock_is_expired(lock)):
        blocking.append(
            {
                "kind": "lock",
                "message": "No expired implementation lock found for resume.",
            }
        )
    return ok, reason, blocking


def _next_validation_item(
    workspace_root: Path,
    task: TaskRecord,
    gate_report: Mapping[str, object],
    blockers: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    priority = (
        "criterion_fail",
        "criterion_missing",
        "criterion_unsatisfied",
        "todo_open",
        "no_finished_implementation",
        "dependency_blocker",
        "no_accepted_plan",
        "plan_not_accepted",
    )
    for kind in priority:
        for blocker in blockers:
            if blocker.get("kind") != kind:
                continue
            ref = blocker.get("ref")
            if kind.startswith("criterion_") and isinstance(ref, str):
                criterion = _criterion_report_by_id(gate_report, ref)
                if criterion is not None:
                    return _criterion_next_item(criterion)
            if kind == "todo_open" and isinstance(ref, str):
                todo = _first_open_todo_from_report(workspace_root, task, (ref,))
                if todo is not None:
                    return _todo_next_item(todo)
            if kind == "dependency_blocker" and isinstance(ref, str):
                return {"kind": "dependency", "id": ref}
            if kind == "no_finished_implementation":
                return _task_next_item(task)
            if kind in {"no_accepted_plan", "plan_not_accepted"}:
                plan = _latest_plan_or_none(workspace_root, task.id)
                if plan is not None:
                    return _plan_next_item(plan)
                return _task_next_item(task)

    for criterion in cast(list[dict[str, object]], gate_report.get("criteria", [])):
        criterion_blockers = criterion.get("blockers")
        if isinstance(criterion_blockers, list) and criterion_blockers:
            return _criterion_next_item(criterion)
    return None


def _without_kinds(
    commands: list[dict[str, object]],
    kinds: set[str],
) -> list[dict[str, object]]:
    return [cmd for cmd in commands if cmd.get("kind") not in kinds]


def _optional_string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = ["can_perform", "next_action", "next_action_for_task", "task_dossier"]

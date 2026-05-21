"""Per-task integrity, plan, and sidecar reference checks for doctor."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from taskledger.domain.handoff import TaskHandoffRecord
from taskledger.domain.models import (
    ActiveTaskState,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
)
from taskledger.domain.sidecars import TaskTodo
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.project_config import load_worker_pipeline_config
from taskledger.storage.task_store import V2Paths


def scan_task_integrity(  # noqa: C901
    *,
    workspace_root: Path,
    paths: V2Paths,
    tasks: list[TaskRecord],
    task_map: dict[str, TaskRecord],
    locks: list[TaskLock],
    task_runs: dict[str, list[TaskRunRecord]],
    run_map: dict[tuple[str, str], TaskRunRecord],
    active_state: ActiveTaskState | None,
    errors: list[str],
    warnings: list[str],
    repair_hints: list[str],
    broken_links: list[dict[str, object]],
    run_lock_mismatches: list[dict[str, object]],
    diagnostics: list[dict[str, object]],
) -> None:
    """Scan per-task integrity: plans, todos, run/lock consistency, change refs."""
    from taskledger.domain.policies import derive_active_stage  # noqa: F811
    from taskledger.storage.task_store import (
        change_markdown_path,
        list_changes,
        list_handoffs_with_errors,
        list_plans,
        load_requirements,
        load_todos,
        resolve_introduction,
        run_markdown_path,
    )

    for task in tasks:
        plans = list_plans(workspace_root, task.id)
        accepted = [plan for plan in plans if plan.status == "accepted"]

        # Broken introduction ref
        if task.introduction_ref:
            try:
                resolve_introduction(workspace_root, task.introduction_ref)
            except Exception:
                broken_links.append(
                    {
                        "task_id": task.id,
                        "kind": "introduction",
                        "ref": task.introduction_ref,
                    }
                )

        # Broken requirement refs
        for requirement in (
            item.task_id
            for item in load_requirements(workspace_root, task.id).requirements
        ):
            if requirement not in task_map:
                broken_links.append(
                    {
                        "task_id": task.id,
                        "kind": "requirement",
                        "ref": requirement,
                    }
                )

        # Handoff errors
        _handoffs, handoff_errors = list_handoffs_with_errors(workspace_root, task.id)
        errors.extend(handoff_errors)

        # Accepted plan consistency
        if task.accepted_plan_version is not None and not any(
            plan.plan_version == task.accepted_plan_version for plan in plans
        ):
            errors.append(
                f"Task {task.id} points to missing accepted plan "
                f"v{task.accepted_plan_version}."
            )
        if len(accepted) > 1:
            errors.append(f"Task {task.id} has multiple accepted plans.")
        if task.accepted_plan_version is not None and len(accepted) != 1:
            errors.append(
                f"Task {task.id} must have exactly one accepted plan "
                "for accepted_plan_version."
            )

        # Duplicate todo ids
        todos = load_todos(workspace_root, task.id).todos
        if len({todo.id for todo in todos}) != len(todos):
            errors.append(f"Task {task.id} contains duplicate todo ids.")
        _warn_stale_worker_step_references(
            workspace_root=workspace_root,
            task=task,
            todos=todos,
            handoffs=_handoffs,
            warnings=warnings,
            diagnostics=diagnostics,
        )

        # Run/lock consistency
        active_lock = next(
            (
                lock
                for lock in locks
                if lock.task_id == task.id and not lock_is_expired(lock)
            ),
            None,
        )
        running_runs = [run for run in task_runs[task.id] if run.status == "running"]

        if task.status_stage in {"planning", "implementing", "validating"}:
            errors.append(
                f"Task {task.id} persists transient stage "
                f"{task.status_stage} as status."
            )
        if len(running_runs) > 1:
            errors.append(f"Task {task.id} has multiple running runs.")

        active_stage = derive_active_stage(active_lock, running_runs)
        if running_runs and active_stage is None:
            errors.append(
                f"Task {task.id} has a running run without a matching active lock."
            )
            for run in running_runs:
                next_command = f"taskledger task show --task {task.id}"
                note = "Inspect task and run state before choosing repair."
                if run.run_type == "planning":
                    next_command = (
                        "taskledger repair run "
                        f"--task {task.id} --run {run.run_id} "
                        '--reason "Finish orphaned planning run."'
                    )
                    note = "Planning run can be explicitly finished with repair run."
                elif run.run_type == "implementation":
                    if (
                        run.run_id == task.latest_implementation_run
                        and task.status_stage
                        in {"approved", "implementing", "failed_validation"}
                    ):
                        next_command = (
                            "taskledger implement resume "
                            f"--task {task.id} --run {run.run_id} "
                            '--reason "Reacquire implementation lock."'
                        )
                        note = (
                            "Reacquire the missing implementation lock for this "
                            "running run."
                        )
                    else:
                        next_command = "taskledger doctor locks"
                        note = (
                            "Historical or non-resumable implementation run. "
                            "Inspect run state before repair."
                        )
                run_lock_mismatches.append(
                    {
                        "kind": "running_run_without_matching_lock",
                        "task_id": task.id,
                        "run_id": run.run_id,
                        "run_type": run.run_type,
                        "status": run.status,
                        "next_command": next_command,
                        "note": note,
                    }
                )

            running_implementation = next(
                (
                    run
                    for run in running_runs
                    if run.run_type == "implementation"
                    and run.run_id == task.latest_implementation_run
                ),
                None,
            )
            if (
                active_lock is None
                and task.status_stage == "implementing"
                and task.accepted_plan_version is not None
                and running_implementation is not None
            ):
                repair_hints.append(
                    "After confirming the previous lock was intentionally "
                    "broken, resume the running implementation with "
                    f"`taskledger implement resume --task {task.id} --reason "
                    '"Reacquire implementation lock for existing running run."`.'
                )
            else:
                repair_hints.append(
                    "Inspect the run/lock pair and repair the orphaned run "
                    f"for task {task.id} explicitly."
                )

        if active_lock is not None and active_stage is None and not running_runs:
            errors.append(
                f"Task {task.id} has a {active_lock.stage} lock without a running run."
            )
            repair_hints.append(
                "Break the stale lock with "
                f'`taskledger repair lock --task {task.id} --reason "..."`.'
            )

        # Change validation
        for change in list_changes(workspace_root, task.id):
            change_run = run_map.get((task.id, change.implementation_run))
            change_path = change_markdown_path(paths, task.id, change.change_id)
            if change_run is None:
                _add_diagnostic(
                    diagnostics,
                    errors,
                    severity="error",
                    code="change.missing_implementation_run",
                    message=(
                        f"Change {change.change_id} in task {task.id} references "
                        f"missing implementation run {change.implementation_run}."
                    ),
                    task_id=task.id,
                    task_slug=task.slug,
                    change_id=change.change_id,
                    run_id=change.implementation_run,
                    expected_run_type="implementation",
                    change_kind=change.kind,
                    change_path=_relative_project_path(workspace_root, change_path),
                    repair_hints=[
                        f"Inspect task: taskledger task show --task {task.id}",
                        (
                            "If the change is invalid, remove or migrate the "
                            "change record; if it is valid, relink it to the "
                            "correct implementation run."
                        ),
                    ],
                )
            elif change_run.run_type != "implementation":
                hints = [
                    f"Inspect task: taskledger task show --task {task.id}",
                    (
                        f"Inspect run: taskledger implement show --task {task.id} "
                        f"--run {change.implementation_run}"
                    ),
                ]
                if change.kind == "command" and change_run.run_type == "planning":
                    hints.insert(
                        0,
                        "This looks like a planning command record "
                        "stored as a code change.",
                    )
                    hints.append(
                        "Run: taskledger repair planning-command-changes "
                        f'--task {task.id} --reason "Move planning command '
                        'logs out of code changes."'
                    )
                _add_diagnostic(
                    diagnostics,
                    errors,
                    severity="error",
                    code="change.non_implementation_run",
                    message=(
                        f"Change {change.change_id} in task {task.id} references "
                        f"non-implementation run {change.implementation_run} "
                        f"({change_run.run_type})."
                    ),
                    task_id=task.id,
                    task_slug=task.slug,
                    change_id=change.change_id,
                    run_id=change.implementation_run,
                    expected_run_type="implementation",
                    actual_run_type=change_run.run_type,
                    actual_run_status=change_run.status,
                    change_kind=change.kind,
                    change_path=_relative_project_path(workspace_root, change_path),
                    run_path=_relative_project_path(
                        workspace_root,
                        run_markdown_path(paths, task.id, change_run.run_id),
                    ),
                    repair_hints=hints,
                )

        # Validation run checks
        for run in task_runs[task.id]:
            if run.run_type == "validation" and run.based_on_implementation_run:
                linked = run_map.get((task.id, run.based_on_implementation_run))
                run_path = run_markdown_path(paths, task.id, run.run_id)
                if linked is None:
                    _add_diagnostic(
                        diagnostics,
                        errors,
                        severity="error",
                        code="validation_run.missing_implementation_run",
                        message=(
                            f"Validation run {run.run_id} in task {task.id} "
                            f"references missing implementation run "
                            f"{run.based_on_implementation_run}."
                        ),
                        task_id=task.id,
                        task_slug=task.slug,
                        run_id=run.run_id,
                        based_on_run_id=run.based_on_implementation_run,
                        expected_run_type="implementation",
                        run_path=_relative_project_path(workspace_root, run_path),
                        repair_hints=[
                            f"Inspect task: taskledger task show --task {task.id}",
                            (
                                "If the based-on run is invalid, relink "
                                "validation run or remove it."
                            ),
                        ],
                    )
                elif linked.run_type != "implementation":
                    linked_path = run_markdown_path(paths, task.id, linked.run_id)
                    _add_diagnostic(
                        diagnostics,
                        errors,
                        severity="error",
                        code="validation_run.non_implementation_run",
                        message=(
                            f"Validation run {run.run_id} in task {task.id} references "
                            f"non-implementation run {run.based_on_implementation_run} "
                            f"({linked.run_type})."
                        ),
                        task_id=task.id,
                        task_slug=task.slug,
                        run_id=run.run_id,
                        based_on_run_id=run.based_on_implementation_run,
                        expected_run_type="implementation",
                        actual_run_type=linked.run_type,
                        run_path=_relative_project_path(workspace_root, run_path),
                        based_on_run_path=_relative_project_path(
                            workspace_root, linked_path
                        ),
                        repair_hints=[
                            f"Inspect task: taskledger task show --task {task.id}",
                            (
                                f"Inspect validation run: taskledger validate "
                                f"show --task {task.id} --run {run.run_id}"
                            ),
                            (
                                "Relink validation run to an implementation run "
                                "or remove it."
                            ),
                        ],
                    )


def _relative_project_path(workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def _add_diagnostic(
    diagnostics: list[dict[str, object]],
    errors: list[str],
    *,
    severity: str,
    code: str,
    message: str,
    task_id: str,
    task_slug: str | None = None,
    change_id: str | None = None,
    run_id: str | None = None,
    based_on_run_id: str | None = None,
    expected_run_type: str | None = None,
    actual_run_type: str | None = None,
    actual_run_status: str | None = None,
    change_kind: str | None = None,
    change_path: str | None = None,
    run_path: str | None = None,
    based_on_run_path: str | None = None,
    repair_hints: list[str] | None = None,
) -> None:
    _append_diagnostic(
        diagnostics,
        errors,
        severity=severity,
        code=code,
        message=message,
        task_id=task_id,
        task_slug=task_slug,
        change_id=change_id,
        run_id=run_id,
        based_on_run_id=based_on_run_id,
        expected_run_type=expected_run_type,
        actual_run_type=actual_run_type,
        actual_run_status=actual_run_status,
        change_kind=change_kind,
        change_path=change_path,
        run_path=run_path,
        based_on_run_path=based_on_run_path,
        repair_hints=repair_hints,
    )


def _append_diagnostic(
    diagnostics: list[dict[str, object]],
    messages: list[str],
    *,
    severity: str,
    code: str,
    message: str,
    task_id: str,
    task_slug: str | None = None,
    change_id: str | None = None,
    run_id: str | None = None,
    based_on_run_id: str | None = None,
    expected_run_type: str | None = None,
    actual_run_type: str | None = None,
    actual_run_status: str | None = None,
    change_kind: str | None = None,
    change_path: str | None = None,
    run_path: str | None = None,
    based_on_run_path: str | None = None,
    todo_id: str | None = None,
    handoff_id: str | None = None,
    worker_step_id: str | None = None,
    repair_hints: list[str] | None = None,
) -> None:
    diagnostic: dict[str, object] = {
        "severity": severity,
        "code": code,
        "message": message,
        "task_id": task_id,
    }
    if task_slug is not None:
        diagnostic["task_slug"] = task_slug
    if change_id is not None:
        diagnostic["change_id"] = change_id
    if run_id is not None:
        diagnostic["run_id"] = run_id
    if based_on_run_id is not None:
        diagnostic["based_on_run_id"] = based_on_run_id
    if expected_run_type is not None:
        diagnostic["expected_run_type"] = expected_run_type
    if actual_run_type is not None:
        diagnostic["actual_run_type"] = actual_run_type
    if actual_run_status is not None:
        diagnostic["actual_run_status"] = actual_run_status
    if change_kind is not None:
        diagnostic["change_kind"] = change_kind
    if change_path is not None:
        diagnostic["change_path"] = change_path
    if run_path is not None:
        diagnostic["run_path"] = run_path
    if based_on_run_path is not None:
        diagnostic["based_on_run_path"] = based_on_run_path
    if todo_id is not None:
        diagnostic["todo_id"] = todo_id
    if handoff_id is not None:
        diagnostic["handoff_id"] = handoff_id
    if worker_step_id is not None:
        diagnostic["worker_step_id"] = worker_step_id
    if repair_hints:
        diagnostic["repair_hints"] = repair_hints
    else:
        diagnostic["repair_hints"] = []
    messages.append(f"[{severity}:{code}] {task_id}: {message}")
    diagnostics.append(diagnostic)


def _warn_stale_worker_step_references(
    *,
    workspace_root: Path,
    task: TaskRecord,
    todos: Sequence[TaskTodo],
    handoffs: Sequence[TaskHandoffRecord],
    warnings: list[str],
    diagnostics: list[dict[str, object]],
) -> None:
    pipeline = load_worker_pipeline_config(workspace_root)
    valid_step_ids = (
        set(pipeline.step_ids()) if pipeline and pipeline.enabled else set()
    )
    for todo in todos:
        worker_step_id = getattr(todo, "worker_step_id", None)
        if (
            not isinstance(worker_step_id, str)
            or not worker_step_id.strip()
            or worker_step_id in valid_step_ids
        ):
            continue
        _append_diagnostic(
            diagnostics,
            warnings,
            severity="warning",
            code="todo.stale_worker_step",
            message=(
                f"Todo {todo.id} references worker step '{worker_step_id}' but "
                "no enabled worker pipeline defines it."
            ),
            task_id=task.id,
            task_slug=task.slug,
            todo_id=todo.id,
            worker_step_id=worker_step_id,
            repair_hints=[
                "Inspect the current overlay with `taskledger pipeline show`.",
                "Update the todo worker_step reference or restore the missing step.",
            ],
        )
    for handoff in handoffs:
        worker_step_id = getattr(handoff, "worker_step_id", None)
        handoff_id = getattr(handoff, "handoff_id", None)
        if (
            not isinstance(worker_step_id, str)
            or not worker_step_id.strip()
            or worker_step_id in valid_step_ids
            or not isinstance(handoff_id, str)
        ):
            continue
        _append_diagnostic(
            diagnostics,
            warnings,
            severity="warning",
            code="handoff.stale_worker_step",
            message=(
                f"Handoff {handoff_id} references worker step '{worker_step_id}' but "
                "no enabled worker pipeline defines it."
            ),
            task_id=task.id,
            task_slug=task.slug,
            handoff_id=handoff_id,
            worker_step_id=worker_step_id,
            repair_hints=[
                "Inspect the current overlay with `taskledger pipeline show`.",
                "Update the handoff worker_step_id or restore the missing step.",
            ],
        )

from __future__ import annotations

import getpass
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from taskledger.domain.models import (
    ActorRef,
    CriterionWaiver,
    HarnessRef,
    PlanRecord,
    TaskRecord,
    TaskRunRecord,
    ValidationCheck,
)
from taskledger.domain.policies import validation_check_decision
from taskledger.domain.states import (
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_INVALID_TRANSITION,
    EXIT_CODE_VALIDATION_FAILED,
    TaskStatusStage,
    normalize_validation_check_status,
    normalize_validation_result,
)
from taskledger.errors import LaunchError
from taskledger.services import tasks as _tasks
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    resolve_plan,
    resolve_task,
    resolve_v2_paths,
    save_run,
    save_task,
)
from taskledger.timeutils import utc_now_iso


def start_validation(
    workspace_root: Path,
    task_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    refresh_implementation_snapshot_first: bool = False,
    refresh_reason: str | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="start validation for")
    if task.status_stage != "implemented":
        raise _tasks._cli_error(
            "Validation requires implemented state.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    impl_run = _tasks._require_run(workspace_root, task, task.latest_implementation_run)
    if impl_run.run_type != "implementation" or impl_run.status != "finished":
        raise _tasks._cli_error(
            "Validation requires a finished implementation run.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    if refresh_implementation_snapshot_first:
        from taskledger.services.workspace_snapshot import (
            refresh_implementation_snapshot,
        )

        if refresh_reason is None or not refresh_reason.strip():
            raise _tasks._cli_error(
                "--reason is required with --refresh-implementation-snapshot.",
                EXIT_CODE_BAD_INPUT,
            )
        refresh_implementation_snapshot(
            workspace_root,
            task.id,
            reason=refresh_reason,
            actor=actor,
            harness=harness,
        )
        task = resolve_task(workspace_root, task.id)
        impl_run = _tasks._require_run(
            workspace_root, task, task.latest_implementation_run
        )
    _ensure_implementation_snapshot_current(workspace_root, task, impl_run)
    run = _tasks._start_run(
        workspace_root,
        task,
        run_type="validation",
        stage="validating",
        actor=actor,
        harness=harness,
    )
    updated_run = replace(run, based_on_implementation_run=impl_run.run_id)
    save_run(workspace_root, updated_run)
    updated = replace(
        resolve_task(workspace_root, task.id),
        latest_validation_run=updated_run.run_id,
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "validation.started",
        {"run_id": updated_run.run_id},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "validate start",
        updated,
        warnings=[],
        changed=True,
        run=updated_run,
        lock=_tasks._require_lock(workspace_root, updated.id),
    )


def validation_status(
    workspace_root: Path,
    task_ref: str,
    *,
    run_id: str | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    run = None
    if run_id:
        from taskledger.storage.task_store import resolve_run

        run = resolve_run(workspace_root, task.id, run_id)

    report = _tasks._build_validation_gate_report(workspace_root, task, run)
    if task.latest_implementation_run is not None:
        impl_run = _tasks._require_run(
            workspace_root, task, task.latest_implementation_run
        )
        if impl_run.run_type == "implementation":
            from taskledger.services.workspace_snapshot import (
                compare_implementation_snapshot,
            )

            evaluation = compare_implementation_snapshot(workspace_root, task, impl_run)
            report["implementation_snapshot"] = evaluation.to_dict()
    return {"kind": "validation_status", "result": report}


def _require_running_validation_with_decision(
    workspace_root: Path,
    task_ref: str,
) -> tuple[TaskRecord, TaskRunRecord]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="record validation checks on")
    run = _tasks._require_running_run(
        workspace_root,
        task,
        task.latest_validation_run,
        expected_type="validation",
    )
    _tasks._enforce_decision(
        validation_check_decision(
            task,
            _tasks._lock_for_mutation(workspace_root, task.id),
            run=run,
        )
    )
    return task, run


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
    task, run = _require_running_validation_with_decision(workspace_root, task_ref)
    normalized_status = normalize_validation_check_status(status)
    check_id = f"check-{len(run.checks) + 1:04d}"
    resolved_criterion = criterion_id.strip() if criterion_id else None
    if normalized_status != "not_run" and resolved_criterion is None:
        raise _tasks._cli_error(
            "Validation checks must reference --criterion unless status is not_run.",
            EXIT_CODE_BAD_INPUT,
        )

    if resolved_criterion is not None:
        if task.accepted_plan_version is None:
            raise _tasks._cli_error(
                "Cannot add criterion check without an accepted plan. "
                "Accept a plan first with: task accept-plan",
                EXIT_CODE_BAD_INPUT,
            )
        accepted_plan = resolve_plan(
            workspace_root,
            task.id,
            version=task.accepted_plan_version,
        )
        resolved_criterion = _resolve_criterion_ref(
            workspace_root,
            accepted_plan,
            resolved_criterion,
        )

    check = ValidationCheck(
        name=(name or resolved_criterion or check_id).strip(),
        id=check_id,
        criterion_id=resolved_criterion,
        status=normalized_status,
        details=details.strip() if details else None,
        evidence=tuple(item.strip() for item in evidence if item.strip()),
    )
    updated = replace(run, checks=tuple([*run.checks, check]))
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "validation.check.logged",
        {
            "run_id": run.run_id,
            "check_id": check.id,
            "criterion_id": check.criterion_id,
            "status": check.status,
            "evidence": " | ".join(check.evidence),
            "details": check.details,
        },
    )
    return updated


def waive_criterion(
    workspace_root: Path,
    task_ref: str,
    *,
    criterion_id: str,
    reason: str,
    actor_name: str | None = None,
) -> TaskRunRecord:
    task, run = _require_running_validation_with_decision(workspace_root, task_ref)

    if task.accepted_plan_version is None:
        raise _tasks._cli_error(
            "Cannot waive criterion without an accepted plan.",
            EXIT_CODE_BAD_INPUT,
        )

    accepted_plan = resolve_plan(
        workspace_root,
        task.id,
        version=task.accepted_plan_version,
    )
    resolved_criterion = _resolve_criterion_ref(
        workspace_root,
        accepted_plan,
        criterion_id,
    )

    if not reason.strip():
        raise _tasks._cli_error("Waiver reason is required.", EXIT_CODE_BAD_INPUT)

    waiver = CriterionWaiver(
        actor=ActorRef(
            actor_type="user",
            actor_name=(actor_name or getpass.getuser() or "user").strip(),
            tool="manual",
        ),
        reason=reason.strip(),
    )

    check_id = f"check-{len(run.checks) + 1:04d}"
    check = ValidationCheck(
        name=resolved_criterion,
        id=check_id,
        criterion_id=resolved_criterion,
        status="pass",
        waiver=waiver,
    )

    updated = replace(run, checks=tuple([*run.checks, check]))
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "validation.criterion.waived",
        {
            "run_id": run.run_id,
            "check_id": check.id,
            "criterion_id": resolved_criterion,
            "reason": reason.strip(),
        },
    )
    return updated


def finish_validation(
    workspace_root: Path,
    task_ref: str,
    *,
    result: str,
    summary: str,
    recommendation: str | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="finish validation for")
    run = _tasks._require_running_run(
        workspace_root,
        task,
        task.latest_validation_run,
        expected_type="validation",
    )
    normalized_result = normalize_validation_result(result)
    if normalized_result == "passed":
        _ensure_validation_can_pass(workspace_root, task, run)
    target_stage: TaskStatusStage = (
        "done" if normalized_result == "passed" else "failed_validation"
    )
    if normalized_result == "passed":
        run_status = "finished"
    elif normalized_result == "blocked":
        run_status = "blocked"
    else:
        run_status = "failed"
    finished = replace(
        run,
        status=cast(
            Literal[
                "running",
                "paused",
                "finished",
                "passed",
                "failed",
                "blocked",
                "aborted",
            ],
            run_status,
        ),
        finished_at=utc_now_iso(),
        summary=summary.strip(),
        recommendation=recommendation,
        result=normalized_result,
    )
    save_run(workspace_root, finished)
    updated = replace(task, status_stage=target_stage, updated_at=utc_now_iso())
    save_task(workspace_root, updated)
    _tasks._release_lock(
        workspace_root,
        task=updated,
        expected_stage="validating",
        run_id=run.run_id,
        target_stage=target_stage,
        event_name="stage.completed"
        if normalized_result == "passed"
        else "stage.failed",
        extra_data={"result": normalized_result},
    )
    _tasks._append_event(
        workspace_root,
        updated.id,
        "validation.finished",
        {"run_id": run.run_id, "result": normalized_result},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "validate finish",
        updated,
        warnings=[],
        changed=True,
        run=finished,
        result=normalized_result,
    )


def _resolve_criterion_ref(
    workspace_root: Path,
    plan: PlanRecord,
    criterion_ref: str,
) -> str:
    if not plan.criteria:
        raise _tasks._cli_error(
            "No acceptance criteria defined in plan.",
            EXIT_CODE_BAD_INPUT,
        )

    normalized_ref = criterion_ref.strip().lower()
    try:
        from taskledger.refs import local_id_from_ref

        normalized_ref = local_id_from_ref(workspace_root, normalized_ref, kind="ac")
    except LaunchError:
        pass

    for criterion in plan.criteria:
        c_id_lower = criterion.id.lower()

        if c_id_lower == normalized_ref:
            return criterion.id

        parts = c_id_lower.split("-")
        if len(parts) == 2:
            prefix, number = parts

            if normalized_ref == f"{prefix}-{number}":
                return criterion.id

            ref_parts = normalized_ref.split("-")
            if len(ref_parts) == 2:
                ref_prefix, ref_number = ref_parts
                if ref_prefix == prefix:
                    try:
                        if int(ref_number) == int(number):
                            return criterion.id
                    except ValueError:
                        pass

            if normalized_ref == number:
                return criterion.id

            try:
                if int(normalized_ref) == int(number):
                    return criterion.id
            except ValueError:
                pass

    criterion_ids = ", ".join(sorted(c.id for c in plan.criteria))
    raise _tasks._cli_error(
        f"Unknown acceptance criterion: {criterion_ref}.\n"
        f"Known criteria: {criterion_ids}.",
        EXIT_CODE_BAD_INPUT,
    )


def _ensure_validation_can_pass(
    workspace_root: Path,
    task: TaskRecord,
    run: TaskRunRecord,
) -> None:
    report = _tasks._build_validation_gate_report(workspace_root, task, run)

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


def _validation_incomplete(message: str, details: dict[str, object]) -> LaunchError:
    error = LaunchError(message)
    error.taskledger_exit_code = EXIT_CODE_VALIDATION_FAILED
    error.taskledger_error_code = "VALIDATION_INCOMPLETE"
    error.taskledger_data = details
    return error


def _ensure_implementation_snapshot_current(
    workspace_root: Path,
    task: TaskRecord,
    impl_run: TaskRunRecord,
) -> None:
    """Block validation if the workspace differs from the implementation snapshot."""
    from taskledger.services.workspace_snapshot import compare_implementation_snapshot

    evaluation = compare_implementation_snapshot(workspace_root, task, impl_run)
    if evaluation.ok:
        return
    error = LaunchError(evaluation.message)
    error.taskledger_exit_code = EXIT_CODE_INVALID_TRANSITION
    error.taskledger_error_code = "IMPLEMENTATION_SNAPSHOT_MISMATCH"
    error.taskledger_data = evaluation.to_dict()
    if evaluation.command_hint:
        error.taskledger_remediation = [evaluation.command_hint]
    raise error

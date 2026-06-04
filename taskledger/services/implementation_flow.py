from __future__ import annotations

import shlex
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from taskledger.domain.models import ActorRef, HarnessRef, TaskRecord, TaskRunRecord

if TYPE_CHECKING:
    from taskledger.domain.lock import TaskLock
from taskledger.domain.states import IMPLEMENTABLE_TASK_STAGES
from taskledger.services import command_runner
from taskledger.services import tasks as _tasks
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    list_changes,
    resolve_task,
    resolve_v2_paths,
    save_run,
    save_task,
)
from taskledger.timeutils import utc_now_iso


def _active_lock_blocks_resume_error(
    task_id: str, lock: TaskLock
) -> _tasks.LaunchError:
    """Build a diagnostics-aware LaunchError for resume vs non-expired active lock."""
    from taskledger.domain.lock import TaskLock
    from taskledger.services.lock_diagnostics import diagnose_lock

    assert isinstance(lock, TaskLock)
    diagnostics = diagnose_lock(lock, task_id=task_id)
    holder = lock.holder
    pid_part = f" pid={holder.pid}" if holder.pid else ""
    message = (
        "Implementation resume requires no active lock. "
        f"Task {task_id} has a non-expired {lock.stage} lock for "
        f"{lock.run_id} held by {holder.actor_type}:{holder.actor_name}"
        f"{pid_part}. "
        "--repair-expired-lock only applies after the lock expires."
    )
    remediation = list(diagnostics.remediation) or [
        f"taskledger lock show --task {task_id}",
    ]
    error = _tasks.LaunchError(message)
    error.taskledger_exit_code = _tasks.EXIT_CODE_LOCK_CONFLICT
    error.taskledger_error_code = "LOCK_CONFLICT"
    error.taskledger_data = {
        "task_id": task_id,
        "lock": lock.to_dict(),
        "diagnostics": diagnostics.to_dict(),
    }
    error.taskledger_remediation = remediation
    return error


def start_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    repair_expired_lock: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="start implementation for")
    return _start_implementation_for_task(
        workspace_root,
        task,
        actor=actor,
        harness=harness,
    )


def _start_implementation_for_task(
    workspace_root: Path,
    task: TaskRecord,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    repair_expired_lock: bool = False,
) -> dict[str, object]:
    if task.status_stage not in IMPLEMENTABLE_TASK_STAGES:
        raise _tasks._cli_error(
            "Implementation requires approved or failed_validation state.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    _tasks._require_accepted_plan_record(workspace_root, task, action="Implementation")
    _tasks._ensure_dependencies_done(workspace_root, task)
    run = _tasks._start_run(
        workspace_root,
        task,
        run_type="implementation",
        stage="implementing",
        actor=actor,
        harness=harness,
    )
    updated = replace(
        resolve_task(workspace_root, task.id),
        latest_implementation_run=run.run_id,
        status_stage="implementing",
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "implementation.started",
        {"run_id": run.run_id},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "implement start",
        replace(updated, status_stage=task.status_stage),
        warnings=[],
        changed=True,
        run=run,
        lock=_tasks._require_lock(workspace_root, updated.id),
    )


def restart_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    summary: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    repair_expired_lock: bool = False,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="restart implementation for")
    if task.status_stage != "failed_validation":
        raise _tasks._cli_error(
            "Implementation restart requires failed_validation state.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    _tasks._require_accepted_plan_record(
        workspace_root,
        task,
        action="Implementation restart",
    )
    if task.latest_validation_run is None:
        raise _tasks._cli_error(
            "Implementation restart requires a failed validation run.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    validation_run = _tasks._require_run(
        workspace_root, task, task.latest_validation_run
    )
    if (
        validation_run.run_type != "validation"
        or validation_run.status not in {"failed", "blocked"}
        or validation_run.result not in {"failed", "blocked"}
    ):
        raise _tasks._cli_error(
            (
                "Implementation restart requires the latest validation run "
                "to be failed or blocked."
            ),
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    if task.latest_implementation_run is None:
        raise _tasks._cli_error(
            "Implementation restart requires a previous implementation run.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    previous_run = _tasks._require_run(
        workspace_root, task, task.latest_implementation_run
    )
    if previous_run.run_type != "implementation":
        raise _tasks._cli_error(
            "Implementation restart requires a previous implementation run.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    restart_summary = summary.strip()
    if not restart_summary:
        raise _tasks._cli_error(
            "Implementation restart requires a non-empty summary.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    _tasks._ensure_dependencies_done(workspace_root, task)
    run = _tasks._start_run(
        workspace_root,
        task,
        run_type="implementation",
        stage="implementing",
        actor=actor,
        harness=harness,
    )
    restarted = replace(
        run,
        resumes_run_id=previous_run.run_id,
        worklog=(
            f"Restart summary: {restart_summary}",
            (
                "Restarted after "
                f"validation run {validation_run.run_id} "
                f"({validation_run.result})."
            ),
            *run.worklog,
        ),
    )
    save_run(workspace_root, restarted)
    updated = replace(
        resolve_task(workspace_root, task.id),
        latest_implementation_run=restarted.run_id,
        status_stage="implementing",
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "implementation.started",
        {
            "run_id": restarted.run_id,
            "restart": True,
            "summary": restart_summary,
            "after_validation_run": validation_run.run_id,
            "resumes_run_id": previous_run.run_id,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "implement restart",
        replace(updated, status_stage=task.status_stage),
        warnings=[],
        changed=True,
        run=restarted,
        lock=_tasks._require_lock(workspace_root, updated.id),
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
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="resume implementation for")
    resume_reason = reason.strip()
    if not resume_reason:
        raise _tasks._cli_error(
            "Implementation resume requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    if task.status_stage not in {"approved", "implementing"}:
        raise _tasks._cli_error(
            "Implementation resume requires approved or implementing state.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    _tasks._require_accepted_plan_record(
        workspace_root,
        task,
        action="Implementation resume",
    )
    selected_run_id = run_id or task.latest_implementation_run
    run = _tasks._require_run(workspace_root, task, selected_run_id)
    if run.run_type != "implementation" or run.status != "running":
        raise _tasks._cli_error(
            "Implementation resume requires a running implementation run.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    existing_lock = _tasks._current_lock(workspace_root, task.id)
    if existing_lock is not None:
        if repair_expired_lock and _tasks.lock_is_expired(existing_lock):
            if (
                existing_lock.run_id != run.run_id
                or existing_lock.stage != "implementing"
            ):
                raise _tasks._cli_error(
                    "Expired lock does not match the implementation run.",
                    _tasks.EXIT_CODE_LOCK_CONFLICT,
                )
            _tasks._release_expired_lock(
                workspace_root,
                task.id,
                existing_lock,
                reason=f"Expired lock released for resume: {resume_reason}",
            )
        elif _tasks.lock_is_expired(existing_lock):
            raise _tasks._stale_lock_error(task.id, existing_lock)
        else:
            raise _active_lock_blocks_resume_error(task.id, existing_lock)
    _tasks._ensure_dependencies_done(workspace_root, task)
    resolved_actor = actor or _tasks._default_actor()
    lock = _tasks._acquire_lock(
        workspace_root,
        task=task,
        stage="implementing",
        run=run,
        reason=resume_reason,
        actor=resolved_actor,
        harness=harness,
    )
    updated = replace(
        task,
        latest_implementation_run=run.run_id,
        status_stage="implementing",
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "run.resumed",
        {
            "run_id": run.run_id,
            "run_type": "implementation",
            "reason": resume_reason,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "implement resume",
        replace(updated, status_stage=task.status_stage),
        warnings=[],
        changed=True,
        run=run,
        lock=lock,
    )


def _require_running_implementation_with_decision(
    workspace_root: Path,
    task_ref: str,
    *,
    action: str,
) -> tuple[TaskRecord, TaskRunRecord]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation=action + " on")
    run = _tasks._require_running_run(
        workspace_root,
        task,
        task.latest_implementation_run,
        expected_type="implementation",
    )
    _tasks._enforce_decision(
        _tasks.implementation_mutation_decision(
            task,
            _tasks._lock_for_mutation(workspace_root, task.id),
            run=run,
            action=action,
        )
    )
    return task, run


def log_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    message: str,
) -> TaskRunRecord:
    task, run = _require_running_implementation_with_decision(
        workspace_root,
        task_ref,
        action="log implementation work",
    )
    updated = replace(run, worklog=tuple([*run.worklog, message.strip()]))
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "implementation.logged",
        {"run_id": run.run_id, "message": message.strip()},
    )
    return updated


def add_implementation_deviation(
    workspace_root: Path,
    task_ref: str,
    *,
    message: str,
) -> TaskRunRecord:
    task, run = _require_running_implementation_with_decision(
        workspace_root,
        task_ref,
        action="record implementation deviations",
    )
    updated = replace(
        run,
        deviations_from_plan=tuple([*run.deviations_from_plan, message.strip()]),
    )
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "implementation.logged",
        {"run_id": run.run_id, "deviation": message.strip()},
    )
    return updated


def add_implementation_artifact(
    workspace_root: Path,
    task_ref: str,
    *,
    path: str,
    summary: str,
) -> TaskRunRecord:
    task, run = _require_running_implementation_with_decision(
        workspace_root,
        task_ref,
        action="record implementation artifacts",
    )
    updated = replace(
        run,
        artifact_refs=tuple(
            [*run.artifact_refs, f"{path}: {summary.strip()}"],
        ),
    )
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "implementation.logged",
        {"run_id": run.run_id, "artifact": path, "summary": summary.strip()},
    )
    return updated


def run_implementation_command(
    workspace_root: Path,
    task_ref: str,
    *,
    argv: tuple[str, ...],
) -> dict[str, object]:
    from taskledger.services.agent_logging import record_managed_shell_command

    if not argv:
        raise _tasks._cli_error(
            "implement command requires a command to run.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    task, run = _require_running_implementation_with_decision(
        workspace_root,
        task_ref,
        action="record implementation commands",
    )
    completed = command_runner.run_command(argv, cwd=workspace_root)
    record_managed_shell_command(
        workspace_root,
        task_id=task.id,
        run_id=run.run_id,
        run_type="implementation",
        argv=argv,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    output = _tasks._command_output(argv, completed.stdout, completed.stderr)
    artifact_ref: str | None = None
    if len(output) > 4000 or output.count("\n") > 50:
        artifact_ref = _tasks._write_command_artifact(
            workspace_root,
            task.id,
            run.run_id,
            output,
        )
    from taskledger.services.check_tracking import (
        add_check,
        classify_check_command,
    )

    check = add_check(
        workspace_root,
        task_ref,
        argv=argv,
        command=shlex.join(argv),
        exit_code=completed.returncode,
        summary=_tasks._command_summary(argv, completed.returncode, artifact_ref),
        category=classify_check_command(argv),
        artifact_refs=((artifact_ref,) if artifact_ref else ()),
    )
    return {
        "kind": "implementation_check",
        "task_id": check.task_id,
        "check": check.to_dict(),
        "change": None,
        "exit_code": completed.returncode,
        "artifact_path": artifact_ref,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def finish_implementation(
    workspace_root: Path,
    task_ref: str,
    *,
    summary: str,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="finish implementation for")
    run = _tasks._require_running_run(
        workspace_root,
        task,
        task.latest_implementation_run,
        expected_type="implementation",
    )
    warnings = _implementation_finish_warnings(workspace_root, task.id, run.run_id)
    _tasks._require_todos_complete_for_implementation_finish(workspace_root, task)
    finished = replace(
        run,
        status="finished",
        finished_at=utc_now_iso(),
        summary=summary.strip(),
    )
    save_run(workspace_root, finished)
    updated = replace(task, status_stage="implemented", updated_at=utc_now_iso())
    save_task(workspace_root, updated)
    _tasks._release_lock(
        workspace_root,
        task=updated,
        expected_stage="implementing",
        run_id=run.run_id,
        target_stage="implemented",
        event_name="stage.completed",
    )
    _tasks._append_event(
        workspace_root,
        updated.id,
        "implementation.finished",
        {"run_id": run.run_id},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return _tasks._lifecycle_payload(
        "implement finish",
        updated,
        warnings=warnings,
        changed=True,
        run=finished,
    )


def _implementation_finish_warnings(
    workspace_root: Path,
    task_id: str,
    run_id: str,
) -> list[str]:
    if not _is_git_workspace(workspace_root):
        return []

    changes = [
        change
        for change in list_changes(workspace_root, task_id)
        if change.implementation_run == run_id
    ]
    if not changes:
        return []

    has_manual_change = any(change.kind != "scan" for change in changes)
    has_git_scan = any(change.kind == "scan" for change in changes)
    if has_manual_change and not has_git_scan:
        return [
            "Warning: implementation has manual change records but no git-backed "
            "scan. Recommended: taskledger implement scan-changes --from-git "
            '--summary "Implementation diff summary."'
        ]
    return []


def _is_git_workspace(workspace_root: Path) -> bool:
    try:
        probe = command_runner.run_command(
            ("git", "rev-parse", "--is-inside-work-tree"),
            cwd=workspace_root,
        )
    except OSError:
        return False
    return probe.returncode == 0

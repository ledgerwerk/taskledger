from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from taskledger.domain.lock import TaskLock
from taskledger.domain.models import ActorRef, HarnessRef, TaskRecord, TaskRunRecord
from taskledger.services import tasks as _tasks


@dataclass(frozen=True)
class ResumeLockResult:
    lock: TaskLock
    already_active: bool = False
    repaired_expired_lock: bool = False
    previous_lock_id: str | None = None


def reacquire_run_lock(
    workspace_root: Path,
    *,
    task: TaskRecord,
    run: TaskRunRecord,
    expected_stage: str,
    reason: str,
    actor: ActorRef,
    harness: HarnessRef | None,
    repair_expired_lock: bool,
) -> ResumeLockResult:
    """Reacquire the matching active-stage lock for an existing running run."""
    existing = _tasks._current_lock(workspace_root, task.id)
    previous_lock_id: str | None = None
    if existing is not None:
        matches = existing.run_id == run.run_id and existing.stage == expected_stage
        if _tasks.lock_is_expired(existing):
            if not repair_expired_lock:
                raise _tasks._stale_lock_error(task.id, existing)
            if not matches:
                raise _tasks._cli_error(
                    "Expired lock does not match the selected running run and stage.",
                    _tasks.EXIT_CODE_LOCK_CONFLICT,
                )
            previous_lock_id = existing.lock_id
            _tasks._release_expired_lock(
                workspace_root,
                task.id,
                existing,
                reason=f"Expired lock released for resume: {reason}",
            )
        else:
            from taskledger.services.lock_diagnostics import (
                lock_owned_by_current_execution,
            )

            if matches and lock_owned_by_current_execution(
                existing, current_actor=actor, current_harness=harness
            ):
                return ResumeLockResult(lock=existing, already_active=True)
            if expected_stage == "implementing":
                from taskledger.services.implementation_flow import (
                    _active_lock_blocks_resume_error,
                )

                raise _active_lock_blocks_resume_error(
                    task.id,
                    existing,
                    current_actor=actor,
                    current_harness=harness,
                )
            try:
                from taskledger.services.lock_diagnostics import diagnose_lock

                diagnostics = diagnose_lock(
                    existing,
                    task_id=task.id,
                    current_actor=actor,
                    current_harness=harness,
                )
                remediation = list(diagnostics.remediation)
                summary = diagnostics.summary
            except (ImportError, AttributeError):
                remediation = []
                summary = ""
            error = _tasks._cli_error(
                f"Cannot resume run {run.run_id}; task {task.id} has a non-expired "
                f"{existing.stage} lock for run {existing.run_id}. {summary}",
                _tasks.EXIT_CODE_LOCK_CONFLICT,
            )
            error.taskledger_remediation = remediation or [
                f"taskledger lock show --task {task.id}"
            ]
            raise error

    if expected_stage == "implementing":
        _tasks._ensure_dependencies_done(workspace_root, task)

    lock = _tasks._acquire_lock(
        workspace_root,
        task=task,
        stage=expected_stage,
        run=run,
        reason=reason,
        actor=actor,
        harness=harness,
    )
    return ResumeLockResult(
        lock=lock,
        repaired_expired_lock=previous_lock_id is not None,
        previous_lock_id=previous_lock_id,
    )

"""Pure next-action decision model.

Both CLI navigation and dashboard read model should produce the same
NextActionDecision for the same task state. The frozen dataclass provides
a typed contract for that shared output shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain.lock import TaskLock
from taskledger.domain.run import TaskRunRecord
from taskledger.domain.task import TaskRecord


@dataclass(frozen=True)
class NextActionDecision:
    """Pure decision result for what to do next on a task.

    Attributes:
        action: The recommended action string (e.g. "todo-work",
            "plan-propose", "implement-finish").
        reason: Human-readable reason for the action.
        next_item: Optional structured item that the action targets.
        blockers: Tuple of blocker dicts preventing progress.
        progress: Dict with stage-specific progress counters.
    """

    action: str
    reason: str
    next_item: dict[str, object] | None = None
    blockers: tuple[dict[str, object], ...] = ()
    progress: dict[str, object] = field(default_factory=dict)


def decide_orphaned_active_stage(
    *,
    task: TaskRecord,
    plans: list,
    runs: list[TaskRunRecord],
    lock: TaskLock | None,
    task_next_item: dict[str, object] | None,
) -> tuple[str, str, dict[str, object] | None, list[dict[str, object]]]:
    """Shared orphaned-active-stage decision used by navigation and dashboard."""
    blockers: list[dict[str, object]] = [
        {
            "kind": "active_stage",
            "message": (
                f"Task status is {task.status_stage}, but active_stage is missing."
            ),
        }
    ]
    action = "repair-active-stage"
    reason = f"Task is {task.status_stage}, but no matching active lock/run exists."
    next_item = task_next_item
    if task.status_stage == "implementing":
        latest_run = _find_run(runs, task.latest_implementation_run)
        has_accepted_plan = any(
            plan.plan_version == task.accepted_plan_version
            and plan.status == "accepted"
            for plan in plans
        )
        if (
            latest_run is not None
            and latest_run.run_type == "implementation"
            and latest_run.status == "running"
            and lock is None
            and has_accepted_plan
        ):
            action = "implement-resume"
            reason = "Implementation run is running but the lock is missing."
            blockers.append(
                {
                    "kind": "lock",
                    "message": (
                        "Missing active implementation lock "
                        f"for run {latest_run.run_id}."
                    ),
                }
            )
    return action, reason, next_item, blockers


def _find_run(runs: list[TaskRunRecord], run_id: str | None) -> TaskRunRecord | None:
    if run_id is None:
        return None
    for run in runs:
        if run.run_id == run_id:
            return run
    return None


def decide_expired_lock_action(
    *,
    task: TaskRecord,
    lock: TaskLock,
    runs: list[TaskRunRecord],
    task_next_item: dict[str, object] | None,
) -> tuple[str, str, dict[str, object] | None, list[dict[str, object]]]:
    """Decide action for an expired lock with no active stage.

    When the lock is expired and there is a resumable implementation run
    whose run_id matches the lock, recommend expired-lock-resume.
    Otherwise fall back to repair-lock.
    """
    impl_run = _find_run(runs, task.latest_implementation_run)
    if (
        impl_run is not None
        and impl_run.run_type == "implementation"
        and impl_run.status == "running"
        and lock.run_id == impl_run.run_id
    ):
        return (
            "expired-lock-resume",
            "Implementation lock expired; resume to continue the run.",
            task_next_item,
            [
                {
                    "kind": "expired_lock",
                    "message": (
                        f"Implementation lock for run {impl_run.run_id} has expired."
                    ),
                }
            ],
        )
    validation_run = _find_run(runs, task.latest_validation_run)
    if (
        validation_run is not None
        and validation_run.run_type == "validation"
        and validation_run.status == "running"
        and lock.run_id == validation_run.run_id
        and lock.stage == "validating"
    ):
        return (
            "expired-validation-lock-resume",
            "Validation lock expired; resume to continue the run.",
            {"kind": "task", "task_id": task.id, "run_id": validation_run.run_id},
            [
                {
                    "kind": "expired_lock",
                    "message": (
                        f"Validation lock for run {validation_run.run_id} "
                        "at stage validating has expired."
                    ),
                }
            ],
        )
    return (
        "repair-lock",
        "A stale or broken lock must be repaired before work can continue.",
        task_next_item,
        [
            {
                "kind": "lock",
                "message": (
                    f"Task has a {lock.stage} lock from {lock.run_id} "
                    "without a matching running run."
                ),
            }
        ],
    )

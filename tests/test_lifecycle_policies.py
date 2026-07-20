from __future__ import annotations

from taskledger.domain.models import ActorRef, TaskLock, TaskRecord, TaskRunRecord
from taskledger.domain.policies import (
    derive_active_stage,
    implementation_mutation_decision,
    plan_propose_decision,
)
from taskledger.domain.states import can_transition


def _actor() -> ActorRef:
    return ActorRef(actor_type="agent", actor_name="taskledger")


# specmason: req=REQ-0029 ac=AC-0337
def test_plan_proposal_uses_durable_status_plus_active_planning() -> None:
    task = TaskRecord(
        id="task-0001",
        slug="task-0001",
        title="Task 1",
        body="desc",
        status_stage="draft",
    )
    run = TaskRunRecord(run_id="run-0001", task_id=task.id, run_type="planning")
    lock = TaskLock(
        lock_id="lock-1",
        task_id=task.id,
        stage="planning",
        run_id=run.run_id,
        created_at="2026-04-24T08:00:00+00:00",
        expires_at="2026-04-24T10:00:00+00:00",
        reason="plan task",
        holder=_actor(),
    )

    decision = plan_propose_decision(task, lock, run=run)

    assert decision.ok is True


def test_active_stage_requires_matching_running_run() -> None:
    run = TaskRunRecord(
        run_id="run-0001",
        task_id="task-0001",
        run_type="implementation",
        status="finished",
    )
    lock = TaskLock(
        lock_id="lock-1",
        task_id="task-0001",
        stage="implementing",
        run_id=run.run_id,
        created_at="2026-04-24T08:00:00+00:00",
        expires_at="2026-04-24T10:00:00+00:00",
        reason="implement approved plan",
        holder=_actor(),
    )

    assert derive_active_stage(lock, (run,)) is None


# specmason: req=REQ-0029 ac=AC-0336
def test_implementation_mutation_allows_active_implementation_without_status_flip() -> (
    None
):
    task = TaskRecord(
        id="task-0001",
        slug="task-0001",
        title="Task 1",
        body="desc",
        status_stage="approved",
    )
    run = TaskRunRecord(
        run_id="run-0001",
        task_id=task.id,
        run_type="implementation",
    )
    lock = TaskLock(
        lock_id="lock-1",
        task_id=task.id,
        stage="implementing",
        run_id=run.run_id,
        created_at="2026-04-24T08:00:00+00:00",
        expires_at="2026-04-24T10:00:00+00:00",
        reason="implement approved plan",
        holder=_actor(),
    )

    decision = implementation_mutation_decision(
        task,
        lock,
        run=run,
        action="record code changes",
    )

    assert decision.ok is True


# specmason: req=REQ-0029 ac=AC-0336
def test_failed_validation_can_transition_back_to_implementing() -> None:
    assert can_transition("failed_validation", "implementing") is True

from __future__ import annotations

import pytest

from taskledger.domain.models import (
    AcceptanceCriterion,
    ActorRef,
    CodeChangeRecord,
    FileLink,
    IntroductionRecord,
    PlanRecord,
    QuestionRecord,
    ReleaseRecord,
    TaskEvent,
    TaskHandoffRecord,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
    ValidationCheck,
)
from taskledger.errors import LaunchError


# specmason: req=REQ-0032 ac=AC-0360
def test_persisted_models_round_trip_with_schema_metadata() -> None:
    actor = ActorRef(
        actor_type="agent",
        actor_name="copilot",
        tool="copilot-cli",
        session_id="session-1",
        host="localhost",
        pid=1234,
    )
    criterion = AcceptanceCriterion(id="ac-0001", text="Locks stay auditable.")
    check = ValidationCheck(
        name="criterion check",
        id="check-0001",
        criterion_id="ac-0001",
        status="pass",
        evidence=("pytest -q",),
    )

    records = [
        TaskRecord(
            id="task-0001",
            slug="rewrite-taskledger",
            title="Rewrite taskledger",
            body="Implement the delta rewrite.",
            status_stage="approved",
            introduction_ref="intro-0001",
            latest_plan_version=1,
            accepted_plan_version=1,
            parent_task_id="task-0000",
            parent_relation="follow_up",
            closed_at="2026-04-24T09:30:00+00:00",
            closed_by=ActorRef(actor_type="user", actor_name="local-user"),
            closure_note="Closed after validation.",
            file_links=(
                FileLink(path="taskledger/storage/task_store.py", kind="code"),
            ),
            todos=(TaskTodo(id="todo-0001", text="Ship the contract layer."),),
        ),
        IntroductionRecord(
            id="intro-0001",
            slug="repo-policy",
            title="Repo policy",
            body="Respect the workflow.",
        ),
        ReleaseRecord(
            version="0.4.1",
            boundary_task_id="task-0001",
            created_by=actor,
            note="0.4.1 released",
            task_count=3,
            previous_version="0.4.0",
        ),
        PlanRecord(
            task_id="task-0001",
            plan_version=1,
            body="## Goal\n\nShip the rewrite.",
            created_by=actor,
            criteria=(criterion,),
            approved_at="2026-04-24T08:00:00+00:00",
            approved_by=ActorRef(actor_type="user", actor_name="local-user"),
            approval_note="Approved.",
        ),
        QuestionRecord(
            id="q-0001",
            task_id="task-0001",
            question="Should we keep aliases?",
            plan_version=1,
            status="answered",
            answer="Yes, for one release.",
        ),
        TaskRunRecord(
            run_id="run-0001",
            task_id="task-0001",
            run_type="validation",
            status="finished",
            actor=actor,
            based_on_plan_version=1,
            checks=(check,),
            result="passed",
        ),
        CodeChangeRecord(
            change_id="change-0001",
            task_id="task-0001",
            implementation_run="run-0001",
            timestamp="2026-04-24T08:30:00+00:00",
            kind="edit",
            path="taskledger/cli_common.py",
            summary="Updated JSON envelope.",
        ),
        TaskLock(
            lock_id="lock-20260424T083000Z-0001",
            task_id="task-0001",
            stage="planning",
            run_id="run-0001",
            created_at="2026-04-24T08:30:00+00:00",
            expires_at=None,
            reason="planning",
            holder=actor,
        ),
        TaskEvent(
            ts="2026-04-24T08:45:00+00:00",
            event="plan.proposed",
            task_id="task-0001",
            actor=actor,
            event_id="evt-20260424T084500Z-000001",
            data={"plan_id": "plan-v1"},
        ),
    ]

    for record in records:
        payload = record.to_dict()
        restored = type(record).from_dict(payload)
        assert restored.to_dict() == payload
        assert payload["schema_version"] == 1
        assert payload["object_type"]


# specmason: req=REQ-0032 ac=AC-0360
def test_task_record_requires_object_type() -> None:
    payload = {
        "schema_version": 1,
        "file_version": "v2",
        "id": "task-0001",
        "slug": "rewrite-taskledger",
        "title": "Rewrite taskledger",
        "status_stage": "draft",
        "body": "",
    }

    with pytest.raises(LaunchError, match="object_type"):
        TaskRecord.from_dict(payload)


def test_task_record_rejects_unknown_schema_version() -> None:
    payload = TaskRecord(
        id="task-0001",
        slug="rewrite-taskledger",
        title="Rewrite taskledger",
        body="",
    ).to_dict()
    payload["schema_version"] = 99

    with pytest.raises(LaunchError, match="schema version"):
        TaskRecord.from_dict(payload)


# specmason: req=REQ-0032 ac=AC-0361
def test_plan_record_round_trips_acceptance_criteria_and_approval_metadata() -> None:
    plan = PlanRecord(
        task_id="task-0001",
        plan_version=7,
        body="## Goal\n\nShip the delta rewrite.",
        criteria=(
            AcceptanceCriterion(id="ac-0001", text="Context output uses @path."),
            AcceptanceCriterion(
                id="ac-0002", text="Validation cannot pass accidentally."
            ),
        ),
        approved_at="2026-04-24T09:00:00+00:00",
        approved_by=ActorRef(actor_type="user", actor_name="local-user"),
        approval_note="Looks good.",
    )

    restored = PlanRecord.from_dict(plan.to_dict())
    assert restored.criteria[0].id == "ac-0001"
    assert restored.approved_by is not None
    assert restored.approval_note == "Looks good."
    assert restored.plan_id == "plan-v7"


def test_release_record_rejects_wrong_object_type_and_schema() -> None:
    release = ReleaseRecord(version="0.4.1", boundary_task_id="task-0001").to_dict()
    release["object_type"] = "task"
    with pytest.raises(LaunchError, match="object_type"):
        ReleaseRecord.from_dict(release)

    too_new = ReleaseRecord(version="0.4.1", boundary_task_id="task-0001").to_dict()
    too_new["schema_version"] = 99
    with pytest.raises(LaunchError, match="schema version"):
        ReleaseRecord.from_dict(too_new)


# specmason: req=REQ-0032 ac=AC-0360
def test_handoff_record_round_trips_focused_context_metadata() -> None:
    handoff = TaskHandoffRecord(
        handoff_id="handoff-0001",
        task_id="task-0001",
        mode="implementation",
        context_for="implementer",
        scope="todo",
        todo_id="todo-0003",
        context_format="markdown",
        context_hash="sha256:abc123",
        generated_at="2026-04-27T12:00:00+00:00",
        context_body="# Context\n",
    )

    restored = TaskHandoffRecord.from_dict(handoff.to_dict())
    assert restored.context_for == "implementer"
    assert restored.scope == "todo"
    assert restored.todo_id == "todo-0003"
    assert restored.focus_run_id is None
    assert restored.context_hash == "sha256:abc123"

    legacy = TaskHandoffRecord.from_dict(
        {
            "schema_version": 1,
            "object_type": "handoff",
            "file_version": "v2",
            "handoff_id": "handoff-0001",
            "task_id": "task-0001",
            "mode": "implementation",
            "status": "open",
            "created_at": "2026-04-27T12:00:00+00:00",
            "created_by": {"actor_type": "agent", "actor_name": "taskledger"},
        }
    )
    assert legacy.context_for is None
    assert legacy.scope == "task"
    assert legacy.todo_id is None
    assert legacy.focus_run_id is None
    assert legacy.context_format == "markdown"
    assert legacy.context_hash is None
    assert legacy.generated_at is None


# specmason: req=REQ-0032 ac=AC-0362
def test_validation_check_requires_criterion_id_unless_not_run() -> None:
    with pytest.raises(LaunchError, match="criterion_id"):
        ValidationCheck.from_dict(
            {
                "name": "pytest",
                "status": "pass",
                "details": "passed",
                "evidence": ["pytest -q"],
            }
        )

    check = ValidationCheck.from_dict(
        {
            "name": "exploratory",
            "status": "not_run",
            "details": "manual exploration",
            "evidence": [],
        }
    )
    assert check.criterion_id is None

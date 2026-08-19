"""Tests for taskledger.domain.policies covering uncovered branches."""

from __future__ import annotations

from dataclasses import dataclass

from taskledger.domain.models import ActorRef, TaskLock, TaskRecord, TaskRunRecord
from taskledger.domain.policies import (
    Decision,
    build_policy_context,
    can_approve_plan,
    can_finish_implementation,
    can_finish_validation,
    can_mark_todo_done,
    can_propose_plan,
    can_start_implementation,
    can_start_planning,
    can_start_validation,
    derive_active_stage,
    implementation_mutation_decision,
    metadata_edit_decision,
    plan_approve_decision,
    plan_propose_decision,
    plan_revise_decision,
    question_add_decision,
    question_mutation_decision,
    require_known_actor_role,
    todo_add_decision,
    todo_toggle_decision,
    validation_check_decision,
)


def _actor() -> ActorRef:
    return ActorRef(actor_type="agent", actor_name="taskledger")


def _task(**overrides) -> TaskRecord:
    defaults = {
        "id": "task-0001",
        "slug": "task-0001",
        "title": "Task",
        "body": "desc",
        "status_stage": "draft",
    }
    defaults.update(overrides)
    return TaskRecord(**defaults)


def _lock(**overrides) -> TaskLock:
    defaults = {
        "lock_id": "lock-1",
        "task_id": "task-0001",
        "stage": "planning",
        "run_id": "run-0001",
        "created_at": "2026-04-24T08:00:00+00:00",
        "expires_at": None,
        "reason": "test",
        "holder": _actor(),
    }
    defaults.update(overrides)
    return TaskLock(**defaults)


def _run(**overrides) -> TaskRunRecord:
    defaults = {
        "run_id": "run-0001",
        "task_id": "task-0001",
        "run_type": "planning",
        "status": "running",
    }
    defaults.update(overrides)
    return TaskRunRecord(**defaults)


@dataclass
class FakeLedger:
    lock: TaskLock | None = None
    accepted_plan: object | None = None


@dataclass
class FakeActor:
    actor_type: str = "user"


# -- derive_active_stage --


# specmason: req=REQ-0018 ac=AC-0258
def test_derive_active_stage_lock_no_runs() -> None:
    lock = _lock()
    assert derive_active_stage(lock, []) is None


# specmason: req=REQ-0018 ac=AC-0205
def test_derive_active_stage_matching_run() -> None:
    lock = _lock(run_id="run-0001", stage="planning")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    assert derive_active_stage(lock, [run]) == "planning"


# specmason: req=REQ-0018 ac=AC-0233
def test_derive_active_stage_run_not_running() -> None:
    lock = _lock(run_id="run-0001", stage="planning")
    run = _run(run_id="run-0001", run_type="planning", status="finished")
    assert derive_active_stage(lock, [run]) is None


# specmason: req=REQ-0018 ac=AC-0270
def test_derive_active_stage_run_id_mismatch() -> None:
    lock = _lock(run_id="run-0001", stage="planning")
    run = _run(run_id="run-9999", run_type="planning", status="running")
    assert derive_active_stage(lock, [run]) is None


# specmason: req=REQ-0018 ac=AC-0229
def test_derive_active_stage_run_type_mismatch() -> None:
    lock = _lock(run_id="run-0001", stage="implementing")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    assert derive_active_stage(lock, [run]) is None


# -- build_policy_context --


# specmason: req=REQ-0018 ac=AC-0207
def test_build_policy_context_no_lock_no_run() -> None:
    task = _task()
    ctx = build_policy_context(task, None)
    assert ctx.active_stage is None
    assert ctx.lock is None
    assert ctx.run is None


# specmason: req=REQ-0018 ac=AC-0208
def test_build_policy_context_with_lock_and_run() -> None:
    task = _task()
    lock = _lock(stage="planning", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    ctx = build_policy_context(task, lock, run=run)
    assert ctx.active_stage == "planning"


# specmason: req=REQ-0018 ac=AC-0206
# specmason: req=REQ-0018 ac=AC-0248
def test_build_policy_context_lock_without_run() -> None:
    task = _task()
    lock = _lock(stage="implementing", run_id="run-0001")
    ctx = build_policy_context(task, lock)
    assert ctx.active_stage == "implementation"


# -- can_start_planning --


# specmason: req=REQ-0018 ac=AC-0223
def test_can_start_planning_draft_no_lock() -> None:
    task = _task(status_stage="draft")
    assert can_start_planning(task, FakeLedger()).ok is True


# specmason: req=REQ-0018 ac=AC-0223
def test_can_start_planning_plan_review_no_lock() -> None:
    task = _task(status_stage="plan_review")
    assert can_start_planning(task, FakeLedger()).ok is True


# specmason: req=REQ-0018 ac=AC-0223
def test_can_start_planning_rejected_if_locked() -> None:
    task = _task(status_stage="draft")
    lock = _lock()
    decision = can_start_planning(task, FakeLedger(lock=lock))
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0224
def test_can_start_planning_rejected_if_wrong_stage() -> None:
    task = _task(status_stage="approved")
    decision = can_start_planning(task, FakeLedger())
    assert decision.ok is False


# -- can_propose_plan --


# specmason: req=REQ-0018 ac=AC-0218
def test_can_propose_plan_ok() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    decision = can_propose_plan(task, run, FakeLedger(lock=lock))
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0217
def test_can_propose_plan_denied_wrong_stage() -> None:
    task = _task(status_stage="approved")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    decision = can_propose_plan(task, run, FakeLedger())
    assert decision.ok is False


# -- can_approve_plan --


# specmason: req=REQ-0018 ac=AC-0210
def test_can_approve_plan_ok() -> None:
    task = _task(status_stage="plan_review")
    decision = can_approve_plan(task, object(), FakeLedger())
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0209
def test_can_approve_plan_denied_wrong_stage() -> None:
    task = _task(status_stage="draft")
    decision = can_approve_plan(task, object(), FakeLedger())
    assert decision.ok is False


# -- can_start_implementation --


# specmason: req=REQ-0018 ac=AC-0222
def test_can_start_implementation_ok() -> None:
    task = _task(status_stage="approved")
    decision = can_start_implementation(task, FakeLedger(accepted_plan=object()))
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0219
def test_can_start_implementation_failed_validation_ok() -> None:
    task = _task(status_stage="failed_validation")
    decision = can_start_implementation(task, FakeLedger(accepted_plan=object()))
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0221
def test_can_start_implementation_no_accepted_plan() -> None:
    task = _task(status_stage="approved")
    decision = can_start_implementation(task, FakeLedger())
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0220
def test_can_start_implementation_locked() -> None:
    task = _task(status_stage="approved")
    lock = _lock()
    decision = can_start_implementation(
        task, FakeLedger(accepted_plan=object(), lock=lock)
    )
    assert decision.ok is False


# -- can_finish_implementation --


# specmason: req=REQ-0018 ac=AC-0211
def test_can_finish_implementation_ok() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="implementing", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="implementation", status="running")
    decision = can_finish_implementation(task, run, FakeLedger(lock=lock))
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0212
def test_can_finish_implementation_wrong_stage() -> None:
    task = _task(status_stage="draft")
    run = _run()
    decision = can_finish_implementation(task, run, FakeLedger())
    assert decision.ok is False


# -- can_start_validation --


# specmason: req=REQ-0018 ac=AC-0226
def test_can_start_validation_ok() -> None:
    task = _task(status_stage="implemented")
    decision = can_start_validation(task, FakeLedger())
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0227
def test_can_start_validation_wrong_stage() -> None:
    task = _task(status_stage="draft")
    decision = can_start_validation(task, FakeLedger())
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0225
def test_can_start_validation_locked() -> None:
    task = _task(status_stage="implemented")
    lock = _lock()
    decision = can_start_validation(task, FakeLedger(lock=lock))
    assert decision.ok is False


# -- can_finish_validation --


# specmason: req=REQ-0018 ac=AC-0214
def test_can_finish_validation_ok() -> None:
    task = _task(status_stage="implemented")
    lock = _lock(stage="validating", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="validation", status="running")
    decision = can_finish_validation(task, run, FakeLedger(lock=lock))
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0213
def test_can_finish_validation_denied() -> None:
    task = _task(status_stage="draft")
    run = _run()
    decision = can_finish_validation(task, run, FakeLedger())
    assert decision.ok is False


# -- can_mark_todo_done --


# specmason: req=REQ-0018 ac=AC-0216
def test_can_mark_todo_done_user() -> None:
    task = _task(status_stage="draft")
    actor = FakeActor(actor_type="user")
    decision = can_mark_todo_done(task, object(), actor, FakeLedger())
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0215
def test_can_mark_todo_done_agent_denied() -> None:
    task = _task(status_stage="draft")
    actor = FakeActor(actor_type="agent")
    decision = can_mark_todo_done(task, object(), actor, FakeLedger())
    assert decision.ok is False


# -- metadata_edit_decision --


# specmason: req=REQ-0018 ac=AC-0235
def test_metadata_edit_decision_ok() -> None:
    task = _task(status_stage="draft")
    assert metadata_edit_decision(task, None).ok is True


# specmason: req=REQ-0018 ac=AC-0235
def test_metadata_edit_decision_approved() -> None:
    task = _task(status_stage="approved")
    assert metadata_edit_decision(task, None).ok is True


# specmason: req=REQ-0018 ac=AC-0236
def test_metadata_edit_decision_wrong_stage() -> None:
    task = _task(status_stage="implemented")
    decision = metadata_edit_decision(task, None)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0235
def test_metadata_edit_decision_locked() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    _run(run_id="run-0001", run_type="planning", status="running")
    decision = metadata_edit_decision(task, lock)
    assert decision.ok is False


# -- todo_add_decision --


# specmason: req=REQ-0018 ac=AC-0260
def test_todo_add_decision_ok() -> None:
    task = _task(status_stage="draft")
    decision = todo_add_decision(task, None, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0259
def test_todo_add_decision_during_planning() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    _run(run_id="run-0001", run_type="planning", status="running")
    decision = todo_add_decision(task, lock, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0261
def test_todo_add_decision_planning_non_user_allowed() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = todo_add_decision(task, lock, actor_role="agent")
    # During planning, _active_stage_lock_decision allows any actor
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0262
def test_todo_add_decision_wrong_stage() -> None:
    task = _task(status_stage="implemented")
    decision = todo_add_decision(task, None, actor_role="user")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0258
def test_todo_add_decision_active_stage_blocks() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="implementing", run_id="run-0001")
    decision = todo_add_decision(task, lock, actor_role="user")
    assert decision.ok is False


# -- todo_toggle_decision --


# specmason: req=REQ-0018 ac=AC-0264
def test_todo_toggle_decision_ok() -> None:
    task = _task(status_stage="draft")
    decision = todo_toggle_decision(task, None, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0266
def test_todo_toggle_during_implementation() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="implementing", run_id="run-0001")
    decision = todo_toggle_decision(task, lock, actor_role="implementer")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0268
def test_todo_toggle_validation_denied() -> None:
    task = _task(status_stage="implemented")
    lock = _lock(stage="validating", run_id="run-0001")
    decision = todo_toggle_decision(task, lock, actor_role="user")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0265
def test_todo_toggle_done_denied() -> None:
    task = _task(status_stage="done")
    decision = todo_toggle_decision(task, None, actor_role="user")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0263
def test_todo_toggle_cancelled_denied() -> None:
    task = _task(status_stage="cancelled")
    decision = todo_toggle_decision(task, None, actor_role="user")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0267
def test_todo_toggle_non_user_denied() -> None:
    task = _task(status_stage="draft")
    decision = todo_toggle_decision(task, None, actor_role="implementer")
    assert decision.ok is False


# -- question_add_decision --


# specmason: req=REQ-0018 ac=AC-0250
def test_question_add_ok() -> None:
    task = _task(status_stage="draft")
    decision = question_add_decision(task, None, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0249
def test_question_add_during_planning_user() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = question_add_decision(task, lock, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0251
def test_question_add_planning_non_user_allowed() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = question_add_decision(task, lock, actor_role="agent")
    # _active_stage_lock_decision allows any actor during planning
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0253
def test_question_add_wrong_stage() -> None:
    task = _task(status_stage="approved")
    decision = question_add_decision(task, None, actor_role="user")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0252
def test_question_add_wrong_active_stage() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="implementing", run_id="run-0001")
    decision = question_add_decision(task, lock, actor_role="user")
    assert decision.ok is False


# -- question_mutation_decision --


# specmason: req=REQ-0018 ac=AC-0254
def test_question_mutation_ok() -> None:
    task = _task(status_stage="plan_review")
    decision = question_mutation_decision(task, None, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0256
def test_question_mutation_planning_user_ok() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = question_mutation_decision(task, lock, actor_role="user")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0255
def test_question_mutation_planning_non_user_allowed() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = question_mutation_decision(task, lock, actor_role="agent")
    # _active_stage_lock_decision allows any actor during planning
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0257
def test_question_mutation_wrong_stage() -> None:
    task = _task(status_stage="approved")
    decision = question_mutation_decision(task, None, actor_role="user")
    assert decision.ok is False


# -- plan_propose_decision --


# specmason: req=REQ-0018 ac=AC-0242
def test_plan_propose_ok() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    decision = plan_propose_decision(task, lock, run=run)
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0240
def test_plan_propose_no_lock() -> None:
    task = _task(status_stage="draft")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    decision = plan_propose_decision(task, None, run=run)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0241
def test_plan_propose_no_run() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = plan_propose_decision(task, lock, run=None)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0243
def test_plan_propose_run_not_running() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="planning", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="planning", status="finished")
    decision = plan_propose_decision(task, lock, run=run)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0244
def test_plan_propose_wrong_stage() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="planning", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="planning", status="running")
    decision = plan_propose_decision(task, lock, run=run)
    assert decision.ok is False


# -- plan_approve_decision --


# specmason: req=REQ-0018 ac=AC-0238
def test_plan_approve_ok() -> None:
    task = _task(status_stage="plan_review")
    decision = plan_approve_decision(task, None)
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0239
def test_plan_approve_wrong_stage() -> None:
    task = _task(status_stage="draft")
    decision = plan_approve_decision(task, None)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0237
def test_plan_approve_locked() -> None:
    task = _task(status_stage="plan_review")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = plan_approve_decision(task, lock)
    assert decision.ok is False


# -- plan_revise_decision --


# specmason: req=REQ-0018 ac=AC-0246
def test_plan_revise_ok() -> None:
    task = _task(status_stage="plan_review")
    decision = plan_revise_decision(task, None)
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0247
def test_plan_revise_wrong_stage() -> None:
    task = _task(status_stage="draft")
    decision = plan_revise_decision(task, None)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0245
def test_plan_revise_locked() -> None:
    task = _task(status_stage="plan_review")
    lock = _lock(stage="planning", run_id="run-0001")
    decision = plan_revise_decision(task, lock)
    assert decision.ok is False


# -- implementation_mutation_decision --


# specmason: req=REQ-0018 ac=AC-0232
def test_implementation_mutation_ok() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="implementing", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="implementation", status="running")
    decision = implementation_mutation_decision(task, lock, run=run, action="log")
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0230
def test_implementation_mutation_no_lock() -> None:
    task = _task(status_stage="approved")
    run = _run(run_id="run-0001", run_type="implementation", status="running")
    decision = implementation_mutation_decision(task, None, run=run, action="log")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0231
def test_implementation_mutation_no_run() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="implementing", run_id="run-0001")
    decision = implementation_mutation_decision(task, lock, run=None, action="log")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0233
def test_implementation_mutation_run_not_running() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="implementing", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="implementation", status="finished")
    decision = implementation_mutation_decision(task, lock, run=run, action="log")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0234
def test_implementation_mutation_wrong_stage() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="implementing", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="implementation", status="running")
    decision = implementation_mutation_decision(task, lock, run=run, action="log")
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0229
def test_implementation_mutation_lock_run_id_mismatch() -> None:
    task = _task(status_stage="approved")
    lock = _lock(stage="implementing", run_id="run-0001")
    run = _run(run_id="run-9999", run_type="implementation", status="running")
    decision = implementation_mutation_decision(task, lock, run=run, action="log")
    assert decision.ok is False


# -- validation_check_decision --


# specmason: req=REQ-0018 ac=AC-0273
def test_validation_check_ok() -> None:
    task = _task(status_stage="implemented")
    lock = _lock(stage="validating", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="validation", status="running")
    decision = validation_check_decision(task, lock, run=run)
    assert decision.ok is True


# specmason: req=REQ-0018 ac=AC-0271
def test_validation_check_no_lock() -> None:
    task = _task(status_stage="implemented")
    run = _run(run_id="run-0001", run_type="validation", status="running")
    decision = validation_check_decision(task, None, run=run)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0272
def test_validation_check_no_run() -> None:
    task = _task(status_stage="implemented")
    lock = _lock(stage="validating", run_id="run-0001")
    decision = validation_check_decision(task, lock, run=None)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0274
def test_validation_check_run_not_running() -> None:
    task = _task(status_stage="implemented")
    lock = _lock(stage="validating", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="validation", status="finished")
    decision = validation_check_decision(task, lock, run=run)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0275
def test_validation_check_wrong_stage() -> None:
    task = _task(status_stage="draft")
    lock = _lock(stage="validating", run_id="run-0001")
    run = _run(run_id="run-0001", run_type="validation", status="running")
    decision = validation_check_decision(task, lock, run=run)
    assert decision.ok is False


# specmason: req=REQ-0018 ac=AC-0270
def test_validation_check_lock_run_id_mismatch() -> None:
    task = _task(status_stage="implemented")
    lock = _lock(stage="validating", run_id="run-0001")
    run = _run(run_id="run-9999", run_type="validation", status="running")
    decision = validation_check_decision(task, lock, run=run)
    assert decision.ok is False


# -- require_known_actor_role --


# specmason: req=REQ-0018 ac=AC-0269
def test_require_known_actor_role_valid() -> None:
    assert require_known_actor_role("planner") == "planner"
    assert require_known_actor_role("implementer") == "implementer"
    assert require_known_actor_role("user") == "user"


# specmason: req=REQ-0018 ac=AC-0269
def test_require_known_actor_role_invalid() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unsupported actor role"):
        require_known_actor_role("admin")


# -- Decision properties --


# specmason: req=REQ-0018 ac=AC-0228
def test_decision_reason_property() -> None:
    d = Decision(allowed=True, code="OK", message="test msg")
    assert d.reason == "test msg"

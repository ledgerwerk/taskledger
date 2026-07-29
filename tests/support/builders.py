from __future__ import annotations

from pathlib import Path

from taskledger.services.tasks import (
    activate_task,
    add_change,
    add_question,
    add_validation_check,
    answer_question,
    approve_plan,
    create_task,
    finish_implementation,
    finish_validation,
    propose_plan,
    set_todo_done,
    start_implementation,
    start_planning,
    start_validation,
)
from taskledger.storage.init import init_project_state

DEFAULT_PLAN_TEXT = """---
goal: Test goal.
acceptance_criteria:
  - id: ac-0001
    text: Criterion passes.
todos:
  - id: todo-0001
    text: Implement it.
    validation_hint: pytest tests
---

# Plan

Test plan.
"""


def init_workspace(workspace: Path) -> Path:
    init_project_state(workspace)
    return workspace


def create_planning_task(
    workspace: Path,
    *,
    title: str = "Planning task",
    slug: str = "planning-task",
    description: str = "planning test",
    plan_text: str | None = None,
) -> str:
    """Create a task in planning stage with a proposed plan.

    Returns the task_id.  Use when the test target is plan lint/approve/etc.
    and the setup does not need to exercise the CLI init/create/start/propose
    contract.
    """
    task = create_task(
        workspace,
        title=title,
        slug=slug,
        description=description,
    )
    activate_task(workspace, task.id, reason="test setup")
    start_planning(workspace, task.id)
    if plan_text is not None:
        propose_plan(workspace, task.id, body=plan_text)
    return task.id


def add_and_answer_question(
    workspace: Path,
    task_id: str,
    *,
    question_text: str = "Which database?",
    answer_text: str = "PostgreSQL.",
    required_for_plan: bool = True,
) -> str:
    """Add a question and answer it via service layer. Returns question_id."""
    q = add_question(
        workspace,
        task_id,
        text=question_text,
        required_for_plan=required_for_plan,
    )
    answer_question(
        workspace,
        task_id,
        q.id,
        text=answer_text,
        answer_source="explicit_user_chat",
    )
    return q.id


def create_approved_task(
    workspace: Path,
    *,
    title: str = "Test task",
    slug: str = "test-task",
    description: str = "",
    labels: tuple[str, ...] = (),
    plan_text: str = DEFAULT_PLAN_TEXT,
    criteria: tuple[str, ...] = (),
    allow_empty_todos: bool = False,
    allow_lint_errors: bool = False,
    approve_note: str = "Approved in test setup.",
    approve_reason: str | None = None,
) -> str:
    task = create_task(
        workspace,
        title=title,
        slug=slug,
        description=description,
        labels=labels,
    )
    activate_task(workspace, task.id, reason="test setup")
    start_planning(workspace, task.id)
    propose_plan(workspace, task.id, body=plan_text, criteria=criteria)
    reason = approve_reason
    if reason is None and (allow_empty_todos or allow_lint_errors):
        reason = "test setup"
    approve_plan(
        workspace,
        task.id,
        version=1,
        actor_type="user",
        note=approve_note,
        allow_empty_todos=allow_empty_todos,
        allow_lint_errors=allow_lint_errors,
        reason=reason,
    )
    return task.id


def create_implemented_task(
    workspace: Path,
    *,
    title: str = "Test task",
    slug: str = "test-task",
    description: str = "",
    labels: tuple[str, ...] = (),
    plan_text: str = DEFAULT_PLAN_TEXT,
    criteria: tuple[str, ...] = (),
    todo_id: str = "todo-0001",
    todo_evidence: str = "test setup",
    change_path: str = "taskledger/example.py",
    change_summary: str = "Implemented in test setup.",
    finish_summary: str = "Implemented.",
    allow_empty_todos: bool = False,
    allow_lint_errors: bool = False,
    approve_note: str = "Approved in test setup.",
    approve_reason: str | None = None,
) -> str:
    task_id = create_approved_task(
        workspace,
        title=title,
        slug=slug,
        description=description,
        labels=labels,
        plan_text=plan_text,
        criteria=criteria,
        allow_empty_todos=allow_empty_todos,
        allow_lint_errors=allow_lint_errors,
        approve_note=approve_note,
        approve_reason=approve_reason,
    )
    start_implementation(workspace, task_id)
    add_change(
        workspace,
        task_id,
        path=change_path,
        kind="edit",
        summary=change_summary,
    )
    if not allow_empty_todos:
        set_todo_done(
            workspace,
            task_id,
            todo_id,
            done=True,
            evidence=todo_evidence,
        )
    finish_implementation(workspace, task_id, summary=finish_summary)
    return task_id


def create_done_task(
    workspace: Path,
    *,
    title: str = "Test task",
    slug: str = "test-task",
    description: str = "",
    labels: tuple[str, ...] = (),
    plan_text: str = DEFAULT_PLAN_TEXT,
    criteria: tuple[str, ...] = (),
    criterion_id: str = "ac-0001",
    validation_evidence: str = "pytest tests",
    validation_summary: str = "Validated.",
    change_path: str = "taskledger/example.py",
    change_summary: str = "Implemented in test setup.",
    implement_summary: str = "Implemented.",
    approve_note: str = "Approved in test setup.",
    allow_lint_errors: bool = False,
) -> str:
    task_id = create_implemented_task(
        workspace,
        title=title,
        slug=slug,
        description=description,
        labels=labels,
        plan_text=plan_text,
        criteria=criteria,
        todo_evidence=validation_evidence,
        change_path=change_path,
        change_summary=change_summary,
        finish_summary=implement_summary,
        approve_note=approve_note,
        allow_lint_errors=allow_lint_errors,
    )
    start_validation(workspace, task_id)
    add_validation_check(
        workspace,
        task_id,
        criterion_id=criterion_id,
        status="pass",
        evidence=(validation_evidence,),
    )
    finish_validation(
        workspace,
        task_id,
        result="passed",
        summary=validation_summary,
    )
    return task_id


def create_failed_validation_task(
    workspace: Path,
    *,
    title: str = "Test task",
    slug: str = "test-task",
    description: str = "",
    labels: tuple[str, ...] = (),
    plan_text: str = DEFAULT_PLAN_TEXT,
    criteria: tuple[str, ...] = (),
    criterion_id: str = "ac-0001",
    todo_evidence: str = "test setup",
    failure_evidence: str = "validation failed",
    validation_summary: str = "Validation failed.",
    change_path: str = "taskledger/example.py",
    change_summary: str = "Implemented in test setup.",
    implement_summary: str = "Implemented.",
    approve_note: str = "Approved in test setup.",
) -> str:
    task_id = create_implemented_task(
        workspace,
        title=title,
        slug=slug,
        description=description,
        labels=labels,
        plan_text=plan_text,
        criteria=criteria,
        todo_evidence=todo_evidence,
        change_path=change_path,
        change_summary=change_summary,
        finish_summary=implement_summary,
        approve_note=approve_note,
    )
    start_validation(workspace, task_id)
    add_validation_check(
        workspace,
        task_id,
        criterion_id=criterion_id,
        status="fail",
        evidence=(failure_evidence,),
    )
    finish_validation(
        workspace,
        task_id,
        result="failed",
        summary=validation_summary,
    )
    return task_id

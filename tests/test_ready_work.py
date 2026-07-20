from __future__ import annotations

from pathlib import Path

from taskledger.services.ready_work import (
    READY_STATUSES,
    STAGE_COMMANDS,
    priority_rank,
    ready_work_items,
)
from taskledger.services.tasks import create_task, start_planning
from tests.support.builders import (
    create_approved_task,
    create_failed_validation_task,
    init_workspace,
    propose_plan,
)


def test_priority_rank_parses_p_style() -> None:
    assert priority_rank("P1") == (1, "P1")
    assert priority_rank("P10") == (10, "P10")


def test_priority_rank_non_p_defaults_to_50() -> None:
    assert priority_rank("high") == (50, "HIGH")


def test_priority_rank_none() -> None:
    assert priority_rank(None) == (99, "")


# specmason: req=REQ-0045 ac=AC-0506
def test_ready_work_items_filters_by_ready_statuses(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_approved = create_approved_task(ws, title="Approved", slug="approved-task")
    task_failed = create_failed_validation_task(ws, title="Failed", slug="failed-task")
    # Create a plan_review task
    pr = create_task(ws, title="PR task", slug="pr-task", description="x")
    start_planning(ws, pr.id)
    propose_plan(ws, pr.id, body="Plan body")

    # Create a draft task that should NOT appear
    draft = create_task(ws, title="Draft", slug="draft-task", description="x")

    # Load actual TaskRecords
    from taskledger.storage.task_store import list_tasks_by_visibility

    visible = list_tasks_by_visibility(ws, visibility="visible")
    items = ready_work_items(ws, visible)
    ready_ids = {item["task_id"] for item in items}

    assert task_approved in ready_ids
    assert task_failed in ready_ids
    assert pr.id in ready_ids
    assert draft not in ready_ids


# specmason: req=REQ-0045 ac=AC-0507
def test_ready_work_items_includes_next_and_command(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_approved = create_approved_task(ws, title="Approved", slug="approved-task")

    from taskledger.storage.task_store import list_tasks_by_visibility

    visible = list_tasks_by_visibility(ws, visibility="visible")
    items = ready_work_items(ws, visible)

    approved_items = [i for i in items if i["task_id"] == task_approved]
    assert len(approved_items) == 1
    item = approved_items[0]
    assert isinstance(item.get("next"), str)
    assert isinstance(item.get("command"), str)
    assert task_approved in item["command"]


# specmason: req=REQ-0045 ac=AC-0507
def test_ready_work_items_stage_commands_are_explicit(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    pr = create_task(ws, title="PR", slug="pr-task", description="x")
    start_planning(ws, pr.id)
    propose_plan(ws, pr.id, body="Plan body")

    from taskledger.storage.task_store import list_tasks_by_visibility

    visible = list_tasks_by_visibility(ws, visibility="visible")
    items = ready_work_items(ws, visible)

    pr_items = [i for i in items if i["task_id"] == pr.id]
    assert len(pr_items) == 1
    command = pr_items[0].get("command")
    assert isinstance(command, str)
    assert "plan review" in command
    assert f"--task {pr.id}" in command


# specmason: req=REQ-0045 ac=AC-0508
def test_ready_work_items_respects_max_items(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    create_approved_task(ws, title="A", slug="task-a")
    create_approved_task(ws, title="B", slug="task-b")

    from taskledger.storage.task_store import list_tasks_by_visibility

    visible = list_tasks_by_visibility(ws, visibility="visible")
    items = ready_work_items(ws, visible, max_items=1)
    assert len(items) == 1


# specmason: req=REQ-0045 ac=AC-0507
def test_ready_work_items_without_next_action(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    create_approved_task(ws, title="A", slug="task-a")

    from taskledger.storage.task_store import list_tasks_by_visibility

    visible = list_tasks_by_visibility(ws, visibility="visible")
    items = ready_work_items(ws, visible, include_next_action=False)
    assert len(items) == 1
    item = items[0]
    assert "next_action" not in item
    assert isinstance(item.get("next"), str)
    assert isinstance(item.get("reason"), str)
    assert isinstance(item.get("command"), str)


# specmason: req=REQ-0045 ac=AC-0506
def test_ready_statuses_includes_plan_review() -> None:
    assert "plan_review" in READY_STATUSES


def test_stage_commands_cover_all_ready_statuses() -> None:
    for status in READY_STATUSES:
        assert status in STAGE_COMMANDS

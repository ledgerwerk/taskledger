from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast

from taskledger.domain.task import TaskRecord
from taskledger.errors import LaunchError
from taskledger.services.navigation import next_action
from taskledger.storage.task_index import TaskSummaryRecord

READY_STATUSES = {"approved", "failed_validation", "plan_review"}

STAGE_COMMANDS: dict[str, str] = {
    "plan_review": "taskledger plan review --task {task_id}",
    "approved": "taskledger implement start --task {task_id}",
    "failed_validation": "taskledger next-action --task {task_id}",
}

READY_NEXT: dict[str, tuple[str, str]] = {
    "plan_review": ("plan-approve", "A proposed plan is waiting for review."),
    "approved": ("implement", "The approved plan is ready for implementation."),
    "failed_validation": (
        "implement-restart",
        "Validation failed; restart implementation.",
    ),
}


def priority_rank(priority: str | None) -> tuple[int, str]:
    if isinstance(priority, str):
        normalized = priority.strip().upper()
        if normalized.startswith("P") and normalized[1:].isdigit():
            return (int(normalized[1:]), normalized)
        return (50, normalized)
    return (99, "")


def ready_work_items(
    workspace_root: Path,
    tasks: Iterable[TaskRecord | TaskSummaryRecord],
    *,
    statuses: set[str] | None = None,
    max_items: int | None = None,
    include_next_action: bool = True,
) -> list[dict[str, object]]:
    wanted = statuses or READY_STATUSES
    items: list[dict[str, object]] = []
    for task in tasks:
        if task.status_stage not in wanted:
            continue
        item: dict[str, object] = {
            "task_id": task.id,
            "slug": task.slug,
            "title": task.title,
            "priority": task.priority,
            "status_stage": task.status_stage,
        }
        stage = task.status_stage
        template = STAGE_COMMANDS.get(stage)
        if template:
            item["command"] = template.format(task_id=task.id)
        if include_next_action:
            try:
                decision = next_action(workspace_root, task.id)
            except LaunchError as exc:
                item["next_action_error"] = str(exc)
            else:
                item["next_action"] = decision
                action = decision.get("action") if isinstance(decision, dict) else None
                reason = decision.get("reason") if isinstance(decision, dict) else None
                if isinstance(action, str):
                    item["next"] = action
                if isinstance(reason, str):
                    item["reason"] = reason
        else:
            # Deterministic stage-level next/reason without full next_action() call.
            stage_next = READY_NEXT.get(stage)
            if stage_next is not None:
                item["next"], item["reason"] = stage_next
        items.append(item)

    items.sort(
        key=lambda item: (
            priority_rank(cast(str | None, item.get("priority"))),
            str(item["task_id"]),
        )
    )
    if max_items is not None:
        return items[:max_items]
    return items

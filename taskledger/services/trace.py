from __future__ import annotations

from pathlib import Path
from typing import Any

from taskledger.services.validation import build_validation_gate_report
from taskledger.storage.task_store import (
    list_changes,
    list_code_reviews,
    list_handoffs,
    list_plans,
    list_runs,
    load_links,
    resolve_task,
)


def build_task_trace(workspace_root: Path, task_ref: str) -> dict[str, Any]:
    """Build a read-only taskledger-native task trace bundle."""
    task = resolve_task(workspace_root, task_ref)
    plans = list_plans(workspace_root, task.id)
    accepted_plan = next(
        (plan for plan in plans if plan.plan_version == task.accepted_plan_version),
        None,
    )
    links = load_links(workspace_root, task.id).links
    runs = list_runs(workspace_root, task.id)
    changes = list_changes(workspace_root, task.id)
    reviews = list_code_reviews(workspace_root, task.id)
    handoffs = list_handoffs(workspace_root, task.id)

    ac_ids = sorted(c.id for c in accepted_plan.criteria) if accepted_plan else []
    source_refs = sorted({change.path for change in changes if change.path})

    validation = build_validation_gate_report(workspace_root, task)
    gaps: list[dict[str, str]] = []

    return {
        "schema": "taskledger.trace.v1",
        "producer": "taskledger",
        "subject": {"type": "task", "id": task.id},
        "task_ids": [task.id],
        "ac_ids": ac_ids,
        "link_refs": [link.to_dict() for link in links],
        "source_refs": source_refs,
        "evidence_refs": [],
        "status": {
            "task": task.status_stage,
            "active_stage": None,
            "plan": accepted_plan.status if accepted_plan else None,
            "validation": validation,
            "runs": {run.run_id: run.status for run in runs},
            "changes": [change.change_id for change in changes],
            "reviews": [review.review_id for review in reviews],
            "handoffs": [handoff.handoff_id for handoff in handoffs],
        },
        "gaps": gaps,
    }

from __future__ import annotations

from pathlib import Path

from taskledger.domain.models import (
    DependencyWaiver,
    PlanRecord,
    TaskRecord,
    TaskRunRecord,
)
from taskledger.errors import LaunchError
from taskledger.storage.task_store import (
    load_requirements,
    resolve_plan,
    resolve_run,
    resolve_task,
)


def optional_run(
    workspace_root: Path,
    task: TaskRecord,
    run_id: str | None,
) -> TaskRunRecord | None:
    if run_id is None:
        return None
    try:
        return resolve_run(workspace_root, task.id, run_id)
    except LaunchError:
        return None


def accepted_plan_record_or_none(
    workspace_root: Path,
    task: TaskRecord,
) -> PlanRecord | None:
    if task.accepted_plan_version is None:
        return None
    try:
        accepted_plan = resolve_plan(
            workspace_root,
            task.id,
            version=task.accepted_plan_version,
        )
    except LaunchError:
        return None
    if accepted_plan.status != "accepted":
        return None
    return accepted_plan


def dependency_blockers(
    workspace_root: Path,
    task: TaskRecord,
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for requirement in load_requirements(workspace_root, task.id).requirements:
        if _has_user_waiver(requirement.waiver):
            continue
        required = resolve_task(
            workspace_root,
            requirement.required_task_uuid or requirement.task_id,
        )
        if required.status_stage != "done":
            blockers.append(
                {
                    "kind": "dependency",
                    "message": (
                        f"Requirement {required.id} is still {required.status_stage}."
                    ),
                }
            )
    return blockers


def _has_user_waiver(waiver: DependencyWaiver | None) -> bool:
    return waiver is not None and waiver.actor.actor_type == "user"


__all__ = [
    "accepted_plan_record_or_none",
    "dependency_blockers",
    "optional_run",
]

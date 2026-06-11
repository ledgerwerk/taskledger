from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from taskledger.domain.models import TaskRecord, TaskRunRecord, ValidationCheck
from taskledger.services.task_queries import dependency_blockers, optional_run
from taskledger.storage.task_store import (
    load_todos,
    resolve_plan,
)


def build_validation_gate_report(
    workspace_root: Path,
    task: TaskRecord,
    run: TaskRunRecord | None = None,
) -> dict[str, object]:
    """Build a comprehensive validation gate report."""
    run = run or optional_run(workspace_root, task, task.latest_validation_run)

    report: dict[str, Any] = {
        "kind": "validation_status",
        "task_id": task.id,
        "task_slug": task.slug,
        "status_stage": task.status_stage,
        "active_stage": None,
        "run_id": run.run_id if run else None,
        "can_finish_passed": False,
    }

    report["accepted_plan"] = {}
    if task.accepted_plan_version is not None:
        accepted_plan = resolve_plan(
            workspace_root,
            task.id,
            version=task.accepted_plan_version,
        )
        report["accepted_plan"] = {
            "version": task.accepted_plan_version,
            "status": accepted_plan.status,
        }

    report["implementation"] = {}
    impl_run = optional_run(workspace_root, task, task.latest_implementation_run)
    if impl_run:
        report["implementation"] = {
            "run_id": impl_run.run_id,
            "status": impl_run.status,
            "satisfied": impl_run.status == "finished",
        }

    report["criteria"] = []
    missing_criteria = []
    failing_criteria = []

    if task.accepted_plan_version is not None:
        accepted_plan = resolve_plan(
            workspace_root,
            task.id,
            version=task.accepted_plan_version,
        )

        checks_by_criterion: dict[str, list[ValidationCheck]] = {}
        if run:
            for check in run.checks:
                if check.criterion_id is not None:
                    checks_by_criterion.setdefault(check.criterion_id, []).append(check)

        for criterion in accepted_plan.criteria:
            checks = checks_by_criterion.get(criterion.id, [])

            latest_check = checks[-1] if checks else None
            latest_status = latest_check.status if latest_check else "not_run"
            satisfied = bool(
                latest_status == "pass"
                or (latest_check and _criterion_has_user_waiver(latest_check))
            )

            has_waiver = latest_check and _criterion_has_user_waiver(latest_check)

            blocker = []
            if criterion.mandatory:
                if latest_status == "fail":
                    blocker = [
                        {"kind": "criterion_fail", "message": "Latest check failed"}
                    ]
                    failing_criteria.append(criterion.id)
                elif latest_status == "not_run":
                    blocker = [
                        {
                            "kind": "criterion_missing",
                            "message": "No passing check recorded",
                        }
                    ]
                    missing_criteria.append(criterion.id)
                elif not satisfied and latest_status != "pass":
                    blocker = [
                        {
                            "kind": "criterion_unsatisfied",
                            "message": f"Latest check status: {latest_status}",
                        }
                    ]
                    missing_criteria.append(criterion.id)

            criterion_report = {
                "id": criterion.id,
                "text": criterion.text,
                "mandatory": criterion.mandatory,
                "latest_check_id": latest_check.id if latest_check else None,
                "latest_status": latest_status,
                "satisfied": satisfied,
                "has_waiver": has_waiver,
                "evidence": list(latest_check.evidence) if latest_check else [],
                "history": [{"check_id": c.id, "status": c.status} for c in checks],
                "blockers": blocker,
            }
            cast(list[dict[str, object]], report["criteria"]).append(criterion_report)

    report["behavior_evidence"] = {}
    report["todos"] = {"open_mandatory": []}
    todos = load_todos(workspace_root, task.id).todos
    open_todos = [todo.id for todo in todos if todo.mandatory and not todo.done]
    cast(dict[str, object], report["todos"])["open_mandatory"] = open_todos

    report["dependencies"] = {"blockers": dependency_blockers(workspace_root, task)}

    blockers: list[dict[str, object]] = []

    if task.accepted_plan_version is None:
        blockers.append(
            {
                "kind": "no_accepted_plan",
                "message": "No accepted plan is recorded.",
                "command_hint": (
                    "taskledger plan propose ... && taskledger plan approve ..."
                ),
            }
        )
    elif task.accepted_plan_version is not None:
        accepted_plan = resolve_plan(
            workspace_root,
            task.id,
            version=task.accepted_plan_version,
        )
        if accepted_plan.status != "accepted":
            blockers.append(
                {
                    "kind": "plan_not_accepted",
                    "message": (
                        "Accepted plan record status is "
                        f"{accepted_plan.status}, not accepted."
                    ),
                }
            )

    if not impl_run or impl_run.status != "finished":
        blockers.append(
            {
                "kind": "no_finished_implementation",
                "message": "No finished implementation run is recorded.",
                "command_hint": (
                    "taskledger implement start ... && taskledger implement finish ..."
                ),
            }
        )

    for missing_id in missing_criteria:
        blockers.append(
            {
                "kind": "criterion_missing",
                "ref": missing_id,
                "message": f"Mandatory criterion {missing_id} has no passing check.",
                "command_hint": (
                    f"taskledger validate check --criterion {missing_id} --status pass "
                    f'--evidence "..."'
                ),
            }
        )

    for failing_id in failing_criteria:
        blockers.append(
            {
                "kind": "criterion_fail",
                "ref": failing_id,
                "message": f"Mandatory criterion {failing_id} has a failing check.",
                "command_hint": (
                    f"taskledger validate check --criterion {failing_id} --status pass "
                    f'--evidence "..."'
                ),
            }
        )

    for todo_id in open_todos:
        blockers.append(
            {
                "kind": "todo_open",
                "ref": todo_id,
                "message": f"Mandatory todo {todo_id} is not done.",
                "command_hint": f'taskledger todo done {todo_id} --evidence "..."',
            }
        )

    dependency_report = cast(dict[str, object], report["dependencies"])
    dependency_blocker_items = cast(list[object], dependency_report["blockers"])
    for dep_blocker in dependency_blocker_items:
        blockers.append(
            {
                "kind": "dependency_blocker",
                "ref": dep_blocker,
                "message": f"Dependency {dep_blocker} blocks this task.",
            }
        )

    report["blockers"] = blockers
    report["can_finish_passed"] = len(blockers) == 0

    return report


def _criterion_has_user_waiver(check: ValidationCheck) -> bool:
    return check.waiver is not None and check.waiver.actor.actor_type == "user"


__all__ = ["build_validation_gate_report"]

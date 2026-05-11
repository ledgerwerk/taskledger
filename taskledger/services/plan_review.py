from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from taskledger.domain.models import PlanRecord
from taskledger.errors import LaunchError
from taskledger.services.plan_lint import lint_plan
from taskledger.services.tasks import (
    _latest_plan_or_none,
    _required_open_question_ids,
    _stale_answer_question_ids,
)
from taskledger.storage.task_store import (
    list_plans,
    list_questions,
    resolve_plan,
    resolve_task,
)


@dataclass(frozen=True)
class PlanReviewOptions:
    include_lint: bool = True
    include_questions: bool = True
    include_next_commands: bool = True
    include_empty: bool = True


def build_plan_review_payload(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int | None = None,
    options: PlanReviewOptions | None = None,
) -> dict[str, object]:
    if options is None:
        options = PlanReviewOptions()

    task = resolve_task(workspace_root, task_ref)
    plan = _resolve_target_plan(workspace_root, task.id, task.status_stage, version)
    questions = list_questions(workspace_root, task.id)

    blockers: list[dict[str, object]] = []
    warnings: list[str] = []

    open_required = _required_open_question_ids(questions)
    stale_answer_ids = _stale_answer_question_ids(questions, plan)

    if task.status_stage != "plan_review":
        blockers.append(
            {
                "kind": "stage",
                "message": "Plan review is only actionable in plan_review stage.",
                "ref": task.status_stage,
            }
        )
    if plan.status != "proposed":
        blockers.append(
            {
                "kind": "plan_status",
                "message": "Only proposed plans are reviewable for approval.",
                "ref": plan.plan_id,
            }
        )
    if open_required:
        blockers.append(
            {
                "kind": "open_questions",
                "message": (
                    "Plan approval is blocked by open required planning questions."
                ),
                "ref": ", ".join(open_required),
            }
        )
    if stale_answer_ids:
        blockers.append(
            {
                "kind": "stale_answers",
                "message": (
                    "Plan approval is blocked by answered planning questions "
                    "not reflected in this plan."
                ),
                "ref": ", ".join(stale_answer_ids),
            }
        )
    if not plan.criteria:
        blockers.append(
            {
                "kind": "missing_criteria",
                "message": "Plan approval requires at least one acceptance criterion.",
                "ref": plan.plan_id,
            }
        )
    if not plan.todos and not (plan.todos_waived_reason or "").strip():
        blockers.append(
            {
                "kind": "missing_todos",
                "message": "Plan approval requires todos or a todo waiver reason.",
                "ref": plan.plan_id,
            }
        )

    lint_payload: object = {}
    lint_passed = True
    if options.include_lint:
        lint_payload = lint_plan(
            workspace_root,
            task.id,
            version=plan.plan_version,
            strict=False,
        )
        lint_passed = bool(cast(dict[str, object], lint_payload).get("passed") is True)
        if not lint_passed:
            blockers.append(
                {
                    "kind": "lint_errors",
                    "message": "Plan approval is blocked by plan lint errors.",
                    "ref": plan.plan_id,
                }
            )
    else:
        warnings.append("Plan lint was not included in this review output.")

    approval_ready = len(blockers) == 0
    commands = (
        _review_commands(plan.plan_version) if options.include_next_commands else []
    )
    summary = _plan_summary(task.description_summary or "", plan.goal, plan.body)

    return {
        "kind": "plan_review",
        "task_id": task.id,
        "task_title": task.title,
        "task_description": task.description_summary,
        "status_stage": task.status_stage,
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "plan_status": plan.status,
        "approval_ready": approval_ready,
        "blockers": blockers,
        "warnings": warnings,
        "lint": lint_payload,
        "open_required_questions": open_required if options.include_questions else [],
        "stale_answer_question_ids": (
            stale_answer_ids if options.include_questions else []
        ),
        "todos_to_materialize": len(plan.todos),
        "commands": commands,
        "summary": summary,
        "plan_body": plan.body,
        "goal": plan.goal,
        "criteria": [item.to_dict() for item in plan.criteria],
        "todos": [item.to_dict() for item in plan.todos],
        "files": list(plan.files),
        "test_commands": list(plan.test_commands),
        "expected_outputs": list(plan.expected_outputs),
        "todos_waived_reason": plan.todos_waived_reason,
    }


def render_plan_review_markdown(payload: dict[str, object]) -> str:
    lines: list[str] = []
    title = str(payload.get("task_title") or payload.get("task_id") or "Task")
    lines.append(f"# Proposed Plan: {title}")
    lines.append("")
    lines.append("## Review Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Task | {payload.get('task_id')} — {title} |")
    lines.append(f"| Plan | {payload.get('plan_id')} — {payload.get('plan_status')} |")
    lines.append(
        "| Approval readiness | "
        + ("Ready" if payload.get("approval_ready") else "Blocked")
        + " |"
    )
    lines.append(f"| Lint | {_lint_summary(payload.get('lint'))} |")
    lines.append(
        "| Open required questions | "
        + _render_count_or_none(payload.get("open_required_questions"))
        + " |"
    )
    lines.append(
        "| Stale answers | "
        + _render_count_or_none(payload.get("stale_answer_question_ids"))
        + " |"
    )
    lines.append(f"| Todos to materialize | {payload.get('todos_to_materialize', 0)} |")
    lines.append("")

    blockers = payload.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.append("### Blockers")
        lines.append("")
        for blocker in blockers:
            if isinstance(blocker, dict):
                lines.append(f"- {blocker.get('kind')}: {blocker.get('message')}")
        lines.append("")

    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("### Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(str(payload.get("summary") or "(no summary available)"))
    lines.append("")

    lines.append("## Proposed Plan")
    lines.append("")
    body = str(payload.get("plan_body") or "").strip()
    lines.append(body if body else "(plan body is empty)")
    lines.append("")

    lines.append("## Machine-Readable Commitments")
    lines.append("")
    lines.append("### Acceptance Criteria")
    lines.append("")
    criteria = payload.get("criteria")
    if isinstance(criteria, list) and criteria:
        for item in criteria:
            if isinstance(item, dict):
                suffix = "" if bool(item.get("mandatory", True)) else " (optional)"
                lines.append(f"- {item.get('id')}: {item.get('text')}{suffix}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Planned Todos")
    lines.append("")
    todos = payload.get("todos")
    if isinstance(todos, list) and todos:
        for item in todos:
            if isinstance(item, dict):
                suffix = "" if bool(item.get("mandatory", True)) else " (optional)"
                lines.append(f"- {item.get('id')}: {item.get('text')}{suffix}")
                hint = item.get("validation_hint")
                if isinstance(hint, str) and hint.strip():
                    lines.append(f"  - Validation hint: {hint}")
    else:
        lines.append("- none")
    lines.append("")

    _append_simple_list(lines, "### Files", payload.get("files"))
    _append_simple_list(lines, "### Test Commands", payload.get("test_commands"))
    _append_simple_list(lines, "### Expected Outputs", payload.get("expected_outputs"))

    lines.append("## Approval Checklist")
    lines.append("")
    lines.append(f"- [{_check_mark(bool(body))}] Plan body is present.")
    lines.append(f"- [{_check_mark(bool(criteria))}] Acceptance criteria are present.")
    lines.append(f"- [{_check_mark(bool(todos))}] Planned todos are present.")
    open_q = payload.get("open_required_questions")
    stale = payload.get("stale_answer_question_ids")
    lines.append(
        f"- [{_check_mark(not (isinstance(open_q, list) and open_q))}] "
        "Required planning questions are answered."
    )
    lines.append(
        f"- [{_check_mark(not (isinstance(stale, list) and stale))}] "
        "Latest answers are reflected in this plan."
    )
    lint_payload = payload.get("lint")
    lint_ok = isinstance(lint_payload, dict) and lint_payload.get("passed") is True
    lines.append(f"- [{_check_mark(lint_ok)}] Plan lint passed.")
    lines.append("")

    commands = payload.get("commands")
    if isinstance(commands, list) and commands:
        lines.append("## Next Commands")
        lines.append("")
        for item in commands:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            command = item.get("command")
            if isinstance(label, str):
                lines.append(f"{label}:")
                lines.append("")
            if isinstance(command, str):
                lines.append("```bash")
                lines.append(command)
                lines.append("```")
                lines.append("")

    result = "\n".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def render_plan_review(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int | None = None,
    options: PlanReviewOptions | None = None,
    format_name: str = "markdown",
) -> dict[str, object]:
    if options is None:
        options = PlanReviewOptions()
    if format_name not in {"markdown", "json"}:
        raise LaunchError("Unsupported plan review format: use 'markdown' or 'json'.")

    payload = build_plan_review_payload(
        workspace_root,
        task_ref,
        version=version,
        options=options,
    )
    if format_name == "markdown":
        content = render_plan_review_markdown(payload)
    else:
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return {
        **payload,
        "format": format_name,
        "content": content,
    }


def _resolve_target_plan(
    workspace_root: Path,
    task_id: str,
    status_stage: str,
    version: int | None,
) -> PlanRecord:
    if version is not None:
        return resolve_plan(workspace_root, task_id, version=version)

    latest = _latest_plan_or_none(workspace_root, task_id)
    if latest is None:
        raise LaunchError(f"Task {task_id} has no plans to review.")
    if status_stage != "plan_review":
        return latest

    for plan in reversed(list_plans(workspace_root, task_id)):
        if plan.status == "proposed":
            return plan
    return latest


def _review_commands(version: int) -> list[dict[str, object]]:
    return [
        {
            "kind": "accept",
            "label": "Approve after explicit user approval",
            "command": (
                f"taskledger plan accept --version {version} "
                '--note "User approved in harness."'
            ),
            "primary": True,
        },
        {
            "kind": "revise",
            "label": "Revise proposed plan",
            "command": "taskledger plan revise",
            "primary": False,
        },
        {
            "kind": "export",
            "label": "Export editable plan",
            "command": f"taskledger plan export --version {version} --file ./plan.md",
            "primary": False,
        },
    ]


def _plan_summary(task_description: str, goal: str | None, body: str) -> str:
    if isinstance(goal, str) and goal.strip():
        return goal.strip()
    first = _first_paragraph(body)
    if first:
        return first
    if task_description.strip():
        return task_description.strip()
    return "(no summary available)"


def _first_paragraph(text: str) -> str:
    blocks = [item.strip() for item in text.split("\n\n") if item.strip()]
    if not blocks:
        return ""
    return blocks[0]


def _lint_summary(lint_payload: object) -> str:
    if not isinstance(lint_payload, dict) or not lint_payload:
        return "not included"
    passed = lint_payload.get("passed") is True
    summary = lint_payload.get("summary")
    errors = 0
    warnings = 0
    if isinstance(summary, dict):
        errors = int(summary.get("errors", 0))
        warnings = int(summary.get("warnings", 0))
    return (
        "passed" if passed else "failed"
    ) + f", {errors} errors, {warnings} warnings"


def _render_count_or_none(value: object) -> str:
    if isinstance(value, list):
        if not value:
            return "none"
        return str(len(value))
    return "none"


def _check_mark(ok: bool) -> str:
    return "x" if ok else " "


def _append_simple_list(lines: list[str], heading: str, value: object) -> None:
    lines.append(heading)
    lines.append("")
    if isinstance(value, list) and value:
        for item in value:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")

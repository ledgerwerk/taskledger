from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from taskledger.domain.models import (
    CodeChangeRecord,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
)
from taskledger.domain.policies import derive_active_stage
from taskledger.domain.states import (
    ContextFor,
    ContextScope,
    HandoffMode,
    normalize_context_for,
    normalize_context_format,
    normalize_context_scope,
    normalize_handoff_mode,
)
from taskledger.errors import LaunchError
from taskledger.services.worker_context import (
    append_worker_contract as _append_worker_contract,
)
from taskledger.services.worker_context import (
    append_worker_role as _append_worker_role,
)
from taskledger.services.worker_context import (
    append_worker_step as _append_worker_step,
)
from taskledger.services.worker_context import (
    guardrails_for_context_for as _guardrails_for_context_for,
)
from taskledger.services.worker_pipeline import (
    resolve_worker_pipeline_step,
    worker_step_context_for,
    worker_step_handoff_mode,
)
from taskledger.services.workflow_guidance import (
    render_planning_guidance as _render_planning_guidance,
)
from taskledger.storage.locks import lock_is_expired, lock_status, read_lock
from taskledger.storage.task_store import (
    list_changes,
    list_checks,
    list_plans,
    list_questions,
    list_runs,
    list_tasks,
    load_links,
    load_requirements,
    load_todos,
    resolve_introduction,
    resolve_plan,
    resolve_run,
    resolve_task,
    resolve_v2_paths,
    task_lock_path,
)
from taskledger.storage.worker_pipeline_config import WorkerStepConfig


@dataclass(frozen=True)
class ContextRequest:
    mode: HandoffMode
    context_for: ContextFor
    scope: ContextScope = "task"
    todo_id: str | None = None
    focus_run_id: str | None = None
    format_name: str = "markdown"


def render_handoff(
    workspace_root: Path,
    task_ref: str,
    *,
    mode: str | None = None,
    context_for: str | None = None,
    worker_step_id: str | None = None,
    scope: str | None = None,
    todo_id: str | None = None,
    focus_run_id: str | None = None,
    format_name: str = "markdown",
) -> str | dict[str, object]:
    worker_step = _resolve_worker_step(
        workspace_root,
        worker_step_id,
        mode=mode,
        context_for=context_for,
    )
    resolved_mode = worker_step_handoff_mode(worker_step) if worker_step else mode
    resolved_context_for = (
        worker_step_context_for(worker_step) if worker_step else context_for
    )
    request = build_context_request(
        mode=resolved_mode,
        context_for=resolved_context_for,
        scope=scope,
        todo_id=todo_id,
        focus_run_id=focus_run_id,
        format_name=format_name,
    )
    payload = build_handoff_payload(
        workspace_root,
        task_ref,
        mode=request.mode,
        context_for=request.context_for,
        worker_step_id=worker_step_id,
        scope=request.scope,
        todo_id=request.todo_id,
        focus_run_id=request.focus_run_id,
        format_name=request.format_name,
    )
    if request.format_name == "json":
        return payload
    return render_markdown_handoff(payload)


def build_context_request(
    *,
    mode: str | None = None,
    context_for: str | None = None,
    scope: str | None = None,
    todo_id: str | None = None,
    focus_run_id: str | None = None,
    format_name: str = "markdown",
) -> ContextRequest:
    resolved_format = normalize_context_format(format_name)
    resolved_mode = normalize_handoff_mode(_canonical_mode(mode)) if mode else None
    resolved_for = normalize_context_for(context_for) if context_for else None

    if resolved_for is None and resolved_mode is None:
        resolved_for = "full"
        resolved_mode = "full"
    elif resolved_for is None:
        assert resolved_mode is not None
        resolved_for = _default_context_for(resolved_mode)
    else:
        inferred_mode = _mode_for_context_for(resolved_for)
        if resolved_mode is None:
            resolved_mode = inferred_mode
        elif resolved_mode != inferred_mode:
            raise LaunchError(
                "Context role "
                f"{resolved_for!r} is incompatible with mode {resolved_mode!r}"
            )

    assert resolved_mode is not None
    explicit_scope = normalize_context_scope(scope) if scope else None
    resolved_scope = explicit_scope or "task"
    if todo_id is not None:
        if explicit_scope is not None and explicit_scope != "todo":
            raise LaunchError("--todo implies --scope todo")
        resolved_scope = "todo"
    if focus_run_id is not None:
        if explicit_scope is not None and explicit_scope != "run":
            raise LaunchError("--run implies --scope run")
        resolved_scope = "run"
    if resolved_scope == "todo" and not todo_id:
        raise LaunchError("--scope todo requires --todo")
    if resolved_scope == "run" and not focus_run_id:
        raise LaunchError("--scope run requires --run")
    if (
        resolved_for in {"spec-reviewer", "code-reviewer"}
        and focus_run_id is None
        and explicit_scope is None
    ):
        raise LaunchError(f"{resolved_for} context requires --run or --scope task")

    return ContextRequest(
        mode=resolved_mode,
        context_for=resolved_for,
        scope=resolved_scope,
        todo_id=todo_id,
        focus_run_id=focus_run_id,
        format_name=resolved_format,
    )


def _resolve_worker_step(
    workspace_root: Path,
    worker_step_id: str | None,
    *,
    mode: str | None,
    context_for: str | None,
) -> WorkerStepConfig | None:
    if worker_step_id is None:
        return None
    _, step = resolve_worker_pipeline_step(workspace_root, worker_step_id)
    step_mode = worker_step_handoff_mode(step)
    step_context = worker_step_context_for(step)
    if mode is not None and normalize_handoff_mode(_canonical_mode(mode)) != step_mode:
        raise LaunchError(
            f"Worker step '{worker_step_id}' requires mode '{step_mode}', not '{mode}'."
        )
    if context_for is not None and normalize_context_for(context_for) != step_context:
        raise LaunchError(
            f"Worker step '{worker_step_id}' requires context '{step_context}', "
            f"not '{context_for}'."
        )
    return step


def build_handoff_payload(
    workspace_root: Path,
    task_ref: str,
    *,
    mode: str | None = None,
    context_for: str | None = None,
    worker_step_id: str | None = None,
    scope: str | None = None,
    todo_id: str | None = None,
    focus_run_id: str | None = None,
    format_name: str = "markdown",
) -> dict[str, object]:
    worker_step = _resolve_worker_step(
        workspace_root,
        worker_step_id,
        mode=mode,
        context_for=context_for,
    )
    resolved_mode = worker_step_handoff_mode(worker_step) if worker_step else mode
    resolved_context_for = (
        worker_step_context_for(worker_step) if worker_step else context_for
    )
    request = build_context_request(
        mode=resolved_mode,
        context_for=resolved_context_for,
        scope=scope,
        todo_id=todo_id,
        focus_run_id=focus_run_id,
        format_name=format_name,
    )
    task = resolve_task(workspace_root, task_ref)
    intro = (
        resolve_introduction(workspace_root, task.introduction_ref)
        if task.introduction_ref
        else None
    )
    plans = list_plans(workspace_root, task.id)
    questions = list_questions(workspace_root, task.id)
    runs = list_runs(workspace_root, task.id)
    todos = list(load_todos(workspace_root, task.id).todos)
    changes = list_changes(workspace_root, task.id)
    checks = list_checks(workspace_root, task.id)
    accepted_plan = (
        resolve_plan(workspace_root, task.id, version=task.accepted_plan_version)
        if task.accepted_plan_version is not None
        else None
    )
    latest_impl = _latest_run(runs, "implementation")
    latest_validation = _latest_run(runs, "validation")
    lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task.id))
    active_stage = (
        None
        if lock is None or lock_is_expired(lock)
        else derive_active_stage(lock, runs)
    )

    dependencies = []
    for requirement in (
        item.task_id for item in load_requirements(workspace_root, task.id).requirements
    ):
        dependency = resolve_task(workspace_root, requirement)
        dependencies.append(
            {
                "task_id": dependency.id,
                "title": dependency.title,
                "status_stage": dependency.status_stage,
            }
        )

    focus = _resolve_focus(workspace_root, task.id, request, todos, runs, changes)
    open_questions = [item.to_dict() for item in questions if item.status == "open"]
    answered_questions = [
        item.to_dict() for item in questions if item.status == "answered"
    ]
    dismissed_questions = [
        item.to_dict() for item in questions if item.status == "dismissed"
    ]
    validation_history = [
        run.to_dict()
        for run in runs
        if run.run_type == "validation" and run.status != "running"
    ]

    validation_status_report = None
    if request.context_for in {"validator", "full"}:
        from taskledger.services.validation import build_validation_gate_report

        validation_status_report = build_validation_gate_report(workspace_root, task)
    relationships = build_task_relationship_payload(workspace_root, task)

    payload = {
        "kind": "task_handoff",
        "mode": request.mode,
        "context_for": request.context_for,
        "scope": request.scope,
        "context_format": request.format_name,
        "focus": focus,
        "task": {**task.to_dict(), "active_stage": active_stage},
        "introduction": intro.to_dict() if intro is not None else None,
        "guardrails": _guardrails_for_context_for(request.context_for),
        "accepted_plan": accepted_plan.to_dict() if accepted_plan is not None else None,
        "plans": [plan.to_dict() for plan in plans],
        "questions": {
            "open": open_questions,
            "answered": answered_questions,
            "dismissed": dismissed_questions,
        },
        "todos": [todo.to_dict() for todo in todos],
        "todo_summary": _todo_summary(todos, request.todo_id),
        "file_links": [
            item.to_dict() for item in load_links(workspace_root, task.id).links
        ],
        "dependencies": dependencies,
        "runs": {
            "latest_planning": _run_to_dict(_latest_run(runs, "planning")),
            "latest_implementation": _run_to_dict(latest_impl),
            "latest_validation": _run_to_dict(latest_validation),
        },
        "lock": lock.to_dict() if lock is not None else None,
        "lock_status": lock_status(lock),
        "changes": [change.to_dict() for change in changes],
        "checks": [check.to_dict() for check in checks],
        "focused_changes": focus["focused_changes"],
        "validation_history": validation_history,
        "validation_status": validation_status_report,
        "parent_task": relationships["parent_task"],
        "follow_up_tasks": relationships["follow_up_tasks"],
        "review_contract": (
            {
                "role": request.context_for,
                "scope": request.scope,
                "guardrails": _guardrails_for_context_for(request.context_for),
            }
            if request.context_for in {"reviewer", "spec-reviewer", "code-reviewer"}
            else None
        ),
        "workflow_guidance": _guidance_for_context(
            workspace_root, task, request.context_for
        ),
    }
    if worker_step is not None:
        payload["worker_step"] = worker_step.to_dict()
    return payload


def render_markdown_handoff(payload: dict[str, object]) -> str:
    mode = str(payload["mode"])
    context_for = str(payload.get("context_for") or mode)
    task = payload["task"]
    assert isinstance(task, dict)
    title_prefix = {
        "planning": "Planning Context",
        "implementation": "Implementation Context",
        "validation": "Validation Context",
        "review": "Review Context",
        "full": "Task Dossier",
    }.get(mode, "Task Context")
    lines = [f"# {title_prefix}: {task['title']}", ""]
    _append_worker_role(lines, payload)
    _append_worker_contract(lines, payload)
    _append_worker_step(lines, payload.get("worker_step"))
    _append_task_section(lines, task)
    _append_relationships(
        lines,
        payload.get("parent_task"),
        payload.get("follow_up_tasks"),
    )
    _append_description(lines, task)
    _append_intro(lines, payload.get("introduction"))
    _append_dependencies(lines, payload["dependencies"])
    _append_file_links(lines, payload["file_links"])
    _append_plans(lines, payload["plans"])
    _append_questions(lines, payload["questions"])
    if context_for in {"planner"}:
        _append_guardrails(lines, payload["guardrails"])
        _append_workflow_guidance(lines, payload.get("workflow_guidance"))
        _append_required_commands(lines, payload.get("accepted_plan"))
        _append_required_output(lines, context_for)
        return "\n".join(lines).rstrip() + "\n"
    if context_for in {
        "implementer",
        "validator",
        "reviewer",
        "spec-reviewer",
        "code-reviewer",
        "full",
    }:
        _append_accepted_plan(lines, payload.get("accepted_plan"))
    if context_for == "implementer":
        _append_acceptance_criteria(lines, payload.get("accepted_plan"))
        if payload.get("scope") == "todo":
            _append_focused_todo(lines, payload.get("focus"))
            _append_other_todo_summary(lines, payload.get("todo_summary"))
        else:
            _append_todos(lines, payload["todos"])
        _append_lock_and_runs(lines, payload)
        _append_required_commands(lines, payload.get("accepted_plan"))
        _append_required_output(lines, context_for)
    elif context_for == "validator":
        _append_todo_completion_summary(lines, payload.get("todo_summary"))
        _append_implementation_summary(lines, payload["runs"])
        _append_change_log(lines, payload["changes"], include_commands=False)
        _append_checks_log(lines, payload.get("checks"), payload["changes"])
        _append_validation_status(lines, payload.get("validation_status"))
        _append_validation_history(lines, payload["validation_history"])
        _append_required_commands(lines, payload.get("accepted_plan"))
        _append_required_output(lines, context_for)
    elif context_for == "spec-reviewer":
        _append_acceptance_criteria(lines, payload.get("accepted_plan"))
        _append_focused_run(lines, payload.get("focus"))
        _append_focused_changes(lines, payload.get("focused_changes"))
        _append_plan_deviations(lines, payload.get("focus"))
        _append_todo_updates(lines, payload.get("focus"))
        _append_spec_review(lines)
        _append_required_output(lines, context_for)
    elif context_for == "code-reviewer":
        _append_focused_run(lines, payload.get("focus"))
        _append_focused_changes(lines, payload.get("focused_changes"))
        _append_commands_already_run(lines, payload.get("focus"))
        _append_code_quality_review(lines)
        _append_required_output(lines, context_for)
    elif context_for == "reviewer":
        _append_focused_run(lines, payload.get("focus"))
        _append_focused_changes(lines, payload.get("focused_changes"))
        _append_required_output(lines, context_for)
    elif context_for == "full":
        _append_acceptance_criteria(lines, payload.get("accepted_plan"))
        _append_todos(lines, payload["todos"])
        _append_lock_and_runs(lines, payload)
        _append_implementation_summary(lines, payload["runs"])
        _append_change_log(lines, payload["changes"], include_commands=False)
        _append_checks_log(lines, payload.get("checks"), payload["changes"])
        _append_validation_status(lines, payload.get("validation_status"))
        _append_validation_history(lines, payload["validation_history"])
        _append_required_commands(lines, payload.get("accepted_plan"))
        _append_required_output(lines, context_for)
    else:
        _append_guardrails(lines, payload["guardrails"])
        _append_required_output(lines, context_for)
    return "\n".join(lines).rstrip() + "\n"


def _append_task_section(lines: list[str], task: dict[str, object]) -> None:
    lines.extend(
        [
            "## Task",
            "",
            f"- id: {task['id']}",
            f"- slug: {task['slug']}",
            f"- status_stage: {task['status_stage']}",
            f"- active_stage: {task.get('active_stage') or 'none'}",
            f"- priority: {task.get('priority') or 'unset'}",
            "- labels: "
            + (", ".join(cast(list[str], task.get("labels") or [])) or "none"),
            f"- owner: {task.get('owner') or 'unassigned'}",
            "",
        ]
    )


def _append_description(lines: list[str], task: dict[str, object]) -> None:
    lines.extend(["## Description", "", str(task.get("body") or ""), ""])


def _append_relationships(
    lines: list[str],
    parent_task: object,
    follow_up_tasks: object,
) -> None:
    if isinstance(parent_task, dict):
        lines.extend(
            [
                "## Parent Task",
                "",
                f"- ID: {parent_task['task_id']}",
                f"- Title: {parent_task['title']}",
                f"- Status: {parent_task['status_stage']}",
                f"- Accepted plan: {parent_task.get('accepted_plan') or 'none'}",
                "- Latest validation: " + _latest_validation_label(parent_task),
                "",
            ]
        )
    if not isinstance(follow_up_tasks, list):
        return
    lines.extend(["## Follow-up Tasks", ""])
    if follow_up_tasks:
        for item in follow_up_tasks:
            if isinstance(item, dict):
                lines.append(
                    f"- {item['task_id']} {item['title']} — {item['status_stage']}"
                )
    else:
        lines.append("- none")
    lines.append("")


def _append_intro(lines: list[str], intro: object) -> None:
    if not isinstance(intro, dict):
        return
    lines.extend(["## Introduction", "", str(intro.get("body") or ""), ""])


def _append_dependencies(lines: list[str], dependencies: object) -> None:
    if not isinstance(dependencies, list):
        return
    lines.extend(["## Requirements", ""])
    for item in dependencies:
        if isinstance(item, dict):
            lines.append(
                f"- {item['task_id']}: {item['title']} — {item['status_stage']}"
            )
    if not dependencies:
        lines.append("- none")
    lines.append("")


def _append_file_links(lines: list[str], file_links: object) -> None:
    if not isinstance(file_links, list):
        return
    lines.extend(["## Linked Files", ""])
    for item in file_links:
        if isinstance(item, dict):
            lines.append(f"- @{item['path']} [{item['kind']}]")
    if not file_links:
        lines.append("- none")
    lines.append("")


def _append_plans(lines: list[str], plans: object) -> None:
    if not isinstance(plans, list):
        return
    lines.extend(["## Existing Plans", ""])
    for item in plans:
        if isinstance(item, dict):
            lines.append(f"- v{item['plan_version']} {item['status']}")
    if not plans:
        lines.append("- none")
    lines.append("")


def _append_questions(lines: list[str], payload: object) -> None:
    if not isinstance(payload, dict):
        return
    lines.extend(["## Questions", "", "### Open", ""])
    open_items = payload.get("open")
    if isinstance(open_items, list) and open_items:
        for item in open_items:
            if isinstance(item, dict):
                lines.append(f"- {item['id']}: {item['question']}")
    else:
        lines.append("- none")
    lines.extend(["", "### Answered", ""])
    answered_items = payload.get("answered")
    if isinstance(answered_items, list) and answered_items:
        for item in answered_items:
            if isinstance(item, dict):
                lines.append(
                    f"- {item['question']} -> {item.get('answer') or '(none)'}"
                )
    else:
        lines.append("- none")
    lines.append("")


def _append_guardrails(lines: list[str], guardrails: object) -> None:
    if not isinstance(guardrails, list):
        return
    lines.extend(["## Guardrails", ""])
    for item in guardrails:
        lines.append(f"- {item}")
    lines.append("")


def _append_accepted_plan(lines: list[str], accepted_plan: object) -> None:
    if not isinstance(accepted_plan, dict):
        return
    lines.extend(["## Accepted Plan", ""])
    body = str(accepted_plan.get("body") or "").strip()
    if body:
        lines.extend([body, ""])
    else:
        lines.extend(
            [
                "WARNING: accepted plan body is empty.",
                "Use acceptance criteria and todos below, but"
                "planning rationale is missing."
                "",
            ]
        )


def _append_acceptance_criteria(lines: list[str], accepted_plan: object) -> None:
    if not isinstance(accepted_plan, dict):
        return
    criteria = accepted_plan.get("criteria")
    lines.extend(["## Acceptance Criteria", ""])
    if isinstance(criteria, list) and criteria:
        for item in criteria:
            if isinstance(item, dict):
                lines.append(f"- {item['id']}: {item['text']}")
    else:
        lines.append("- none")
    lines.append("")


def _append_todos(lines: list[str], todos: object) -> None:
    if not isinstance(todos, list):
        return
    done_count = sum(1 for item in todos if isinstance(item, dict) and item.get("done"))
    total_count = len(todos)
    lines.extend(["## Todo Checklist", ""])
    if total_count == 0:
        lines.append("- none (no todos)")
    else:
        lines.append(f"Progress: {done_count}/{total_count} done")
        lines.append("")
        for item in todos:
            if isinstance(item, dict):
                mark = "x" if item.get("done") else " "
                lines.append(f"- [{mark}] {item['id']}: {item['text']}")
    lines.append("")


def _append_focused_todo(lines: list[str], focus: object) -> None:
    lines.extend(["## Focused Todo", ""])
    if not isinstance(focus, dict) or not isinstance(focus.get("todo"), dict):
        lines.append("- none")
        lines.append("")
        return
    todo = cast(dict[str, object], focus["todo"])
    lines.append(f"- id: {todo['id']}")
    lines.append(f"- text: {todo['text']}")
    lines.append(f"- status: {todo['status']}")
    if todo.get("validation_hint"):
        lines.append(f"- validation_hint: {todo['validation_hint']}")
    lines.append("")


def _append_other_todo_summary(lines: list[str], summary: object) -> None:
    lines.extend(["## Other Todo Summary", ""])
    if not isinstance(summary, dict):
        lines.append("- none")
        lines.append("")
        return
    lines.append(f"- total: {summary.get('total', 0)}")
    lines.append(f"- done: {summary.get('done', 0)}")
    lines.append(f"- open: {summary.get('open', 0)}")
    focused_index = summary.get("focused_index")
    if focused_index is not None:
        lines.append(f"- focused_index: {focused_index}")
    lines.append("")


def _append_todo_completion_summary(lines: list[str], summary: object) -> None:
    lines.extend(["## Todo Completion Summary", ""])
    if not isinstance(summary, dict):
        lines.append("- none")
        lines.append("")
        return
    lines.append(f"- total: {summary.get('total', 0)}")
    lines.append(f"- done: {summary.get('done', 0)}")
    lines.append(f"- open: {summary.get('open', 0)}")
    lines.append("")


def _append_lock_and_runs(lines: list[str], payload: dict[str, object]) -> None:
    lines.extend(["## Current Run / Lock State", ""])
    runs = payload["runs"]
    assert isinstance(runs, dict)
    latest_impl = runs.get("latest_implementation")
    if isinstance(latest_impl, dict):
        lines.append(
            f"- implementation run: {latest_impl['run_id']} ({latest_impl['status']})"
        )
    else:
        lines.append("- implementation run: none")
    status = payload.get("lock_status")
    if isinstance(status, dict) and status.get("active"):
        lines.append(
            f"- lock: {status.get('stage')} / {status.get('run_id')} "
            f"expired={status.get('expired')}"
        )
    else:
        lines.append("- lock: none")
    lines.append("")


def _append_focused_run(lines: list[str], focus: object) -> None:
    lines.extend(["## Focused Run", ""])
    if not isinstance(focus, dict) or not isinstance(focus.get("run"), dict):
        lines.append("- none")
        lines.append("")
        return
    run = cast(dict[str, object], focus["run"])
    lines.append(f"- run_id: {run['run_id']}")
    lines.append(f"- run_type: {run['run_type']}")
    lines.append(f"- status: {run['status']}")
    lines.append(f"- based_on_plan: {run.get('based_on_plan') or 'none'}")
    lines.append(f"- summary: {run.get('summary') or '(no summary)'}")
    lines.append("")


def _append_focused_changes(lines: list[str], changes: object) -> None:
    if not isinstance(changes, list):
        return
    lines.extend(["## Focused Changes", ""])
    for item in changes:
        if isinstance(item, dict):
            lines.append(f"- @{item['path']}: {item['summary']}")
    if not changes:
        lines.append("- none")
    lines.append("")


def _append_plan_deviations(lines: list[str], focus: object) -> None:
    lines.extend(["## Plan Deviations", ""])
    if not isinstance(focus, dict) or not isinstance(focus.get("run"), dict):
        lines.append("- none")
        lines.append("")
        return
    run = cast(dict[str, object], focus["run"])
    deviations = run.get("deviations_from_plan")
    if isinstance(deviations, list) and deviations:
        for item in deviations:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")


def _append_todo_updates(lines: list[str], focus: object) -> None:
    lines.extend(["## Todo Updates from that run", ""])
    if not isinstance(focus, dict) or not isinstance(focus.get("run"), dict):
        lines.append("- none")
        lines.append("")
        return
    run = cast(dict[str, object], focus["run"])
    updates = run.get("todo_updates")
    if isinstance(updates, list) and updates:
        for item in updates:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")


def _append_commands_already_run(lines: list[str], focus: object) -> None:
    lines.extend(["## Commands already run", ""])
    if not isinstance(focus, dict) or not isinstance(focus.get("run"), dict):
        lines.append("- none")
        lines.append("")
        return
    run = cast(dict[str, object], focus["run"])
    evidence = run.get("evidence")
    if isinstance(evidence, list) and evidence:
        for item in evidence:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")


def _append_implementation_summary(lines: list[str], runs: object) -> None:
    if not isinstance(runs, dict):
        return
    latest_impl = runs.get("latest_implementation")
    lines.extend(["## Implementation Summary", ""])
    if isinstance(latest_impl, dict):
        lines.append(str(latest_impl.get("summary") or "(no summary)"))
    else:
        lines.append("(no implementation run)")
    lines.append("")


def _append_change_log(
    lines: list[str], changes: object, *, include_commands: bool = True
) -> None:
    if not isinstance(changes, list):
        return
    filtered = changes
    if not include_commands:
        filtered = [
            c for c in changes if isinstance(c, dict) and c.get("kind") != "command"
        ]
    lines.extend(["## Code Changes", ""])
    for item in filtered:
        if isinstance(item, dict):
            lines.append(f"- @{item['path']}: {item['summary']}")
    if not filtered:
        lines.append("- none")
    lines.append("")


def _append_checks_log(lines: list[str], checks: object, changes: object) -> None:
    all_checks: list[dict] = []
    if isinstance(checks, list):
        for ck in checks:
            if isinstance(ck, dict):
                all_checks.append(ck)
    # Legacy command changes displayed as checks
    if isinstance(changes, list):
        for ch in changes:
            if isinstance(ch, dict) and ch.get("kind") == "command":
                all_checks.append(ch)
    if not all_checks:
        return
    lines.extend(["## Checks", ""])
    for ck in all_checks:
        cid = ck.get("check_id") or ck.get("change_id", "?")
        cmd = ck.get("command", "?")
        exit_code = ck.get("exit_code")
        exit_str = f" (exit {exit_code})" if exit_code is not None else ""
        lines.append(f"- {cid}: `{cmd}`{exit_str}")
    lines.append("")


def _append_validation_history(lines: list[str], history: object) -> None:
    if not isinstance(history, list):
        return
    lines.extend(["## Previous Validation History", ""])
    for item in history:
        if isinstance(item, dict):
            lines.append(
                f"- {item['run_id']}: "
                f"{item.get('result') or item['status']} — "
                f"{item.get('summary') or ''}"
            )
    if not history:
        lines.append("- none")
    lines.append("")


def _append_validation_status(lines: list[str], status_report: object) -> None:
    if not isinstance(status_report, dict):
        return

    lines.extend(["## Validation Status", ""])

    can_finish = status_report.get("can_finish_passed", False)
    lines.append(f"**Can Finish Passed:** {'yes' if can_finish else 'no'}")
    lines.append("")

    criteria = status_report.get("criteria", [])
    if criteria and isinstance(criteria, list):
        lines.append("### Acceptance Criteria")
        for criterion in criteria:
            if isinstance(criterion, dict):
                criterion_id = criterion.get("id", "unknown")
                mandatory = criterion.get("mandatory", False)
                satisfied = criterion.get("satisfied", False)
                latest_status = criterion.get("latest_status", "unknown")
                marker = "pass" if satisfied else "pending"
                mandatory_marker = " (mandatory)" if mandatory else ""
                lines.append(
                    f"- {criterion_id}{mandatory_marker}: {latest_status} [{marker}]"
                )
        lines.append("")

    blockers = status_report.get("blockers", [])
    if blockers and isinstance(blockers, list) and not can_finish:
        lines.append("### Blocking Issues")
        for blocker in blockers:
            if isinstance(blocker, dict):
                kind = blocker.get("kind", "unknown")
                message = blocker.get("message", "")
                lines.append(f"- [{kind}] {message}")
        lines.append("")


def _append_required_commands(lines: list[str], accepted_plan: object) -> None:
    lines.extend(["## Required Commands", ""])
    if not isinstance(accepted_plan, dict):
        lines.append("- none")
        lines.append("")
        return
    commands = accepted_plan.get("test_commands")
    if isinstance(commands, list) and commands:
        for item in commands:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")


def _append_spec_review(lines: list[str]) -> None:
    lines.extend(
        [
            "## Spec Compliance Review",
            "",
            "- Check every acceptance criterion against the focused run evidence.",
            "- Call out deviations_from_plan.",
            "- Mark unclear items when evidence is missing.",
            "",
        ]
    )


def _append_code_quality_review(lines: list[str]) -> None:
    lines.extend(
        [
            "## Code Quality Review",
            "",
            "- Check correctness and maintainability risks.",
            "- Call out unsafe or brittle changes.",
            "- Check test coverage gaps.",
            "",
        ]
    )


def _append_required_output(lines: list[str], context_for: str) -> None:
    section = {
        "planner": [
            "plan body",
            "assumptions",
            "risks",
            "acceptance criteria",
            "open questions",
        ],
        "implementer": [
            "worklog entries",
            "code change records",
            "todo updates",
            "implementation summary",
        ],
        "validator": [
            "structured checks",
            "evidence",
            "summary",
            "recommendation",
        ],
        "reviewer": ["approval decision"],
        "spec-reviewer": [
            "overall_spec_result: pass|fail|blocked",
            "acceptance_criteria_findings",
            "todo_findings",
            "deviations_from_plan",
            "missing_evidence",
            "recommended_next_action",
        ],
        "code-reviewer": [
            "overall_code_quality: pass|fail|blocked",
            "high_risk_issues",
            "maintainability_issues",
            "test_coverage_gaps",
            "unsafe_or_brittle_changes",
            "recommended_next_action",
        ],
        "full": ["next action"],
    }[context_for]
    lines.extend(["## Required Output", ""])
    for item in section:
        lines.append(f"- {item}")
    lines.append("")


def build_task_relationship_payload(
    workspace_root: Path,
    task: TaskRecord,
) -> dict[str, object]:
    parent_task = None
    if task.parent_task_id is not None:
        parent = resolve_task(workspace_root, task.parent_task_id)
        parent_task = _relationship_task_summary(workspace_root, parent)
    follow_up_tasks = [
        _relationship_task_summary(workspace_root, child)
        for child in list_tasks(workspace_root)
        if child.parent_task_id == task.id and child.parent_relation == "follow_up"
    ]
    return {
        "parent_task": parent_task,
        "follow_up_tasks": follow_up_tasks,
    }


def _relationship_task_summary(
    workspace_root: Path,
    task: TaskRecord,
) -> dict[str, object]:
    runs = list_runs(workspace_root, task.id)
    lock = read_lock(task_lock_path(resolve_v2_paths(workspace_root), task.id))
    active_stage = (
        None
        if lock is None or lock_is_expired(lock)
        else derive_active_stage(lock, runs)
    )
    latest_validation = _latest_run(runs, "validation")
    return {
        "task_id": task.id,
        "slug": task.slug,
        "title": task.title,
        "status_stage": task.status_stage,
        "active_stage": active_stage,
        "accepted_plan": (
            f"plan-v{task.accepted_plan_version}"
            if task.accepted_plan_version is not None
            else None
        ),
        "accepted_plan_version": task.accepted_plan_version,
        "latest_validation_run": (
            latest_validation.run_id if latest_validation is not None else None
        ),
        "latest_validation_result": (
            latest_validation.result or latest_validation.status
            if latest_validation is not None
            else None
        ),
    }


def _resolve_focus(
    workspace_root: Path,
    task_id: str,
    request: ContextRequest,
    todos: list[TaskTodo],
    runs: list[TaskRunRecord],
    changes: list[CodeChangeRecord],
) -> dict[str, object]:
    focused_todo = None
    focused_run = None
    focused_changes: list[dict[str, object]] = []

    if request.scope == "todo":
        normalized_todo_id = request.todo_id
        for todo in todos:
            if todo.id == normalized_todo_id:
                focused_todo = todo
                break
        if focused_todo is None:
            raise LaunchError(f"Todo not found: {request.todo_id}")
    elif request.scope == "run":
        assert request.focus_run_id is not None
        focused_run = resolve_run(workspace_root, task_id, request.focus_run_id)
        focused_changes = [
            change.to_dict()
            for change in changes
            if change.implementation_run == focused_run.run_id
        ]

    return {
        "todo_id": request.todo_id,
        "todo": focused_todo.to_dict() if focused_todo is not None else None,
        "focus_run_id": request.focus_run_id,
        "run": focused_run.to_dict() if focused_run is not None else None,
        "focused_changes": focused_changes,
    }


def _todo_summary(
    todos: list[TaskTodo], focused_todo_id: str | None
) -> dict[str, object]:
    focused_index = None
    for index, todo in enumerate(todos, start=1):
        if todo.id == focused_todo_id:
            focused_index = index
            break
    return {
        "total": len(todos),
        "done": sum(1 for todo in todos if todo.done),
        "open": sum(1 for todo in todos if not todo.done and todo.status != "skipped"),
        "focused_index": focused_index,
    }


def _latest_run(runs: list[TaskRunRecord], run_type: str) -> TaskRunRecord | None:
    matches = [item for item in runs if item.run_type == run_type]
    return matches[-1] if matches else None


def _run_to_dict(run: TaskRunRecord | None) -> dict[str, object] | None:
    return run.to_dict() if run is not None else None


def _latest_validation_label(task_summary: dict[str, object]) -> str:
    run_id = task_summary.get("latest_validation_run")
    result = task_summary.get("latest_validation_result")
    if isinstance(run_id, str) and isinstance(result, str):
        return f"{run_id} {result}"
    return "none"


def _default_context_for(mode: HandoffMode) -> ContextFor:
    return cast(
        ContextFor,
        {
            "planning": "planner",
            "implementation": "implementer",
            "validation": "validator",
            "review": "reviewer",
            "full": "full",
        }[mode],
    )


def _mode_for_context_for(context_for: ContextFor) -> HandoffMode:
    return cast(
        HandoffMode,
        {
            "planner": "planning",
            "implementer": "implementation",
            "validator": "validation",
            "reviewer": "review",
            "spec-reviewer": "review",
            "code-reviewer": "review",
            "full": "full",
        }[context_for],
    )


def _canonical_mode(mode: str | None) -> str:
    if mode is None:
        return "full"
    return {
        "plan-context": "planning",
        "implementation-context": "implementation",
        "validation-context": "validation",
        "show": "full",
    }.get(mode, mode)


def _guidance_for_context(
    workspace_root: Path,
    task: TaskRecord,
    context_for: str,
) -> str:
    """Load workflow guidance for the given context role, if applicable."""
    if context_for in {"planner", "planning"}:
        return _render_planning_guidance(workspace_root, task)
    return ""


def _append_workflow_guidance(lines: list[str], guidance: object) -> None:
    """Append workflow guidance section if present."""
    if not isinstance(guidance, str) or not guidance:
        return
    lines.append(guidance)

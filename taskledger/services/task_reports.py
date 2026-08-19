"""Human-readable task report service.

Generates structured Markdown (or JSON) reports for a single task.
Read-only: does not mutate storage or append events.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from taskledger.errors import LaunchError

ReportFormat = Literal["markdown", "json"]
ReportPreset = Literal[
    "summary", "planning", "implementation", "validation", "full", "archive"
]

VALID_SECTIONS = (
    "summary",
    "description",
    "relationships",
    "requirements",
    "files",
    "questions",
    "plans",
    "accepted-plan",
    "acceptance-criteria",
    "todos",
    "implementation",
    "checks",
    "code-reviews",
    "changes",
    "command-log",
    "validation",
    "locks",
    "events",
    "next-action",
)

SUMMARY_SECTIONS = (
    "summary",
    "description",
    "relationships",
    "requirements",
    "files",
    "next-action",
)

PLANNING_SECTIONS = (
    "summary",
    "description",
    "relationships",
    "requirements",
    "files",
    "questions",
    "plans",
    "accepted-plan",
    "acceptance-criteria",
    "todos",
    "next-action",
)

IMPLEMENTATION_SECTIONS = (
    "summary",
    "description",
    "accepted-plan",
    "acceptance-criteria",
    "todos",
    "implementation",
    "checks",
    "code-reviews",
    "changes",
    "locks",
    "next-action",
)

VALIDATION_SECTIONS = (
    "summary",
    "description",
    "accepted-plan",
    "acceptance-criteria",
    "todos",
    "implementation",
    "checks",
    "code-reviews",
    "changes",
    "validation",
    "next-action",
)

FULL_SECTIONS = (
    "summary",
    "description",
    "relationships",
    "requirements",
    "files",
    "questions",
    "plans",
    "accepted-plan",
    "acceptance-criteria",
    "todos",
    "implementation",
    "checks",
    "code-reviews",
    "changes",
    "command-log",
    "validation",
    "locks",
    "next-action",
)

ARCHIVE_SECTIONS = FULL_SECTIONS + ("events",)

PRESET_SECTIONS: dict[str, tuple[str, ...]] = {
    "summary": SUMMARY_SECTIONS,
    "planning": PLANNING_SECTIONS,
    "implementation": IMPLEMENTATION_SECTIONS,
    "validation": VALIDATION_SECTIONS,
    "full": FULL_SECTIONS,
    "archive": ARCHIVE_SECTIONS,
}


def normalize_report_section(name: str) -> str:
    return name.strip().lower()


def resolve_report_sections(
    *,
    preset: str,
    sections: tuple[str, ...],
    include_sections: tuple[str, ...],
    exclude_sections: tuple[str, ...],
) -> tuple[str, ...]:
    if preset not in PRESET_SECTIONS:
        raise LaunchError(f"Unsupported task report preset: {preset}")
    for raw in sections + include_sections + exclude_sections:
        normalized = normalize_report_section(raw)
        if normalized not in VALID_SECTIONS:
            raise LaunchError(f"Unsupported task report section: {raw}")

    if sections:
        base = tuple(normalize_report_section(s) for s in sections)
    else:
        base = PRESET_SECTIONS[preset]

    result: list[str] = []
    for section in [
        *base,
        *(normalize_report_section(s) for s in include_sections),
    ]:
        if section not in result:
            result.append(section)

    excluded = {normalize_report_section(s) for s in exclude_sections}
    return tuple(s for s in result if s not in excluded)


@dataclass(frozen=True)
class TaskReportOptions:
    preset: ReportPreset = "full"
    sections: tuple[str, ...] = ()
    include_sections: tuple[str, ...] = ()
    exclude_sections: tuple[str, ...] = ()
    events_limit: int = 50
    command_log_limit: int = 100
    include_command_output: bool = False
    include_empty: bool = True


def build_task_report_payload(
    workspace_root: Path,
    task_ref: str,
    *,
    options: TaskReportOptions | None = None,
) -> dict[str, object]:
    if options is None:
        options = TaskReportOptions()
    if options.events_limit < 0:
        raise LaunchError("--events-limit must be >= 0.")
    if options.command_log_limit < 0:
        raise LaunchError("--command-log-limit must be >= 0.")

    from taskledger.services.handoff import build_task_relationship_payload
    from taskledger.services.tasks import (
        list_events as _list_events,
    )
    from taskledger.services.tasks import (
        next_action as _next_action,
    )
    from taskledger.services.validation import build_validation_gate_report
    from taskledger.storage.task_store import (
        list_changes,
        list_checks,
        list_code_reviews,
        list_plans,
        list_questions,
        list_runs,
        load_links,
        load_requirements,
        load_todos,
        resolve_lock,
        resolve_plan,
        resolve_task,
    )

    task = resolve_task(workspace_root, task_ref)
    resolved_sections = resolve_report_sections(
        preset=options.preset,
        sections=options.sections,
        include_sections=options.include_sections,
        exclude_sections=options.exclude_sections,
    )

    _data: dict[str, object] = {}

    def _load(key: str) -> object:
        if key in _data:
            return _data[key]
        if key == "plans":
            val: object = list_plans(workspace_root, task.id)
        elif key == "questions":
            val = list_questions(workspace_root, task.id)
        elif key in ("runs", "changes", "checks", "code_reviews"):
            val = (
                list_runs(workspace_root, task.id)
                if key == "runs"
                else (
                    list_changes(workspace_root, task.id)
                    if key == "changes"
                    else (
                        list_checks(workspace_root, task.id)
                        if key == "checks"
                        else (
                            list_code_reviews(workspace_root, task.id)
                            if key == "code_reviews"
                            else []
                        )
                    )
                )
            )
        elif key == "todos":
            val = load_todos(workspace_root, task.id).todos
        elif key == "links":
            val = load_links(workspace_root, task.id).links

        elif key == "requirements":
            val = load_requirements(workspace_root, task.id).requirements
        elif key == "lock":
            val = resolve_lock(workspace_root, task.id)
        elif key == "events":
            all_events = _list_events(workspace_root)
            val = [e for e in all_events if e.get("task_id") == task.id]
        elif key == "command_logs":
            from taskledger.storage.agent_logs import load_agent_command_logs

            val = load_agent_command_logs(
                workspace_root,
                task_id=task.id,
                limit=options.command_log_limit or None,
            )
        elif key == "duplicate_log_ids":
            from taskledger.storage.agent_logs import detect_duplicate_log_ids

            val = detect_duplicate_log_ids(workspace_root, task_id=task.id)
        elif key == "relationships":
            val = build_task_relationship_payload(workspace_root, task)
        elif key == "validation_report":
            val = build_validation_gate_report(workspace_root, task)
        elif key == "next_action":
            val = _next_action(workspace_root, task.id)
        else:
            val = None
        _data[key] = val
        return val

    accepted_plan = None
    if task.accepted_plan_version is not None:
        accepted_plan = resolve_plan(
            workspace_root,
            task.id,
            version=task.accepted_plan_version,
        )

    return {
        "task": task,
        "sections": resolved_sections,
        "options": options,
        "_load": _load,
        "accepted_plan": accepted_plan,
    }


def render_task_report_markdown(payload: dict[str, object]) -> str:
    from taskledger.domain.models import TaskRecord

    task = payload["task"]
    assert isinstance(task, TaskRecord)
    sections = payload["sections"]
    assert isinstance(sections, tuple)
    options = payload["options"]
    assert isinstance(options, TaskReportOptions)
    _load = payload["_load"]
    accepted_plan = payload["accepted_plan"]

    lines: list[str] = []
    _append_title(lines, task)

    section_renderers: dict[str, object] = {
        "summary": _append_summary,
        "description": _append_description,
        "relationships": _append_relationships,
        "requirements": _append_requirements,
        "files": _append_files,
        "questions": _append_questions,
        "plans": _append_plans,
        "accepted-plan": _append_accepted_plan,
        "acceptance-criteria": _append_acceptance_criteria,
        "todos": _append_todos,
        "implementation": _append_implementation,
        "changes": _append_changes,
        "checks": _append_checks,
        "code-reviews": _append_code_reviews,
        "command-log": _append_command_log,
        "validation": _append_validation,
        "locks": _append_locks,
        "events": _append_events,
        "next-action": _append_next_action,
    }

    for section in sections:
        renderer = section_renderers.get(section)
        if renderer is not None:
            renderer(  # type: ignore[operator]
                lines,
                task,
                _load,
                accepted_plan,
                options,
            )
        elif options.include_empty:
            lines.append(f"## {_heading_for(section)}")
            lines.append("")

    result = "\n".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def render_task_report(
    workspace_root: Path,
    task_ref: str,
    *,
    options: TaskReportOptions | None = None,
    format_name: str = "markdown",
) -> dict[str, object]:
    if options is None:
        options = TaskReportOptions()
    if format_name not in ("markdown", "json"):
        raise LaunchError(f"Unsupported task report format: {format_name}")

    from taskledger.domain.models import TaskRecord

    payload = build_task_report_payload(
        workspace_root,
        task_ref,
        options=options,
    )
    task = payload["task"]
    assert isinstance(task, TaskRecord)

    content = render_task_report_markdown(payload)

    result: dict[str, object] = {
        "kind": "task_report",
        "task_id": task.id,
        "title": task.title,
        "format": format_name,
        "preset": options.preset,
        "sections": (
            list(payload["sections"])
            if isinstance(payload["sections"], (list, tuple))
            else []
        ),
        "content": content,
    }
    return result


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _append_title(lines: list[str], task: object) -> None:
    from taskledger.domain.models import TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append(f"# Task {task.id} — {task.title}")
    lines.append("")


def _append_summary(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskLock, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Status | {task.status_stage} |")

    active_stage = "none"
    lock = _load("lock")  # type: ignore[operator]
    if isinstance(lock, TaskLock):
        active_stage = lock.stage
    lines.append(f"| Active stage | {active_stage} |")

    lines.append(f"| Type | {task.task_type} |")
    lines.append(f"| Priority | {task.priority or 'unset'} |")
    lines.append(f"| Owner | {task.owner or 'unassigned'} |")
    labels = ", ".join(task.labels) if task.labels else "none"
    lines.append(f"| Labels | {labels} |")
    lines.append(f"| Created | {task.created_at} |")
    lines.append(f"| Updated | {task.updated_at} |")
    if task.accepted_plan_version is not None:
        lines.append(f"| Accepted plan | plan-v{task.accepted_plan_version} |")
    lines.append("")


def _append_description(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Description")
    lines.append("")
    body = task.body.strip()
    if body:
        lines.append(body)
    elif task.description_summary:
        lines.append(str(task.description_summary))
    else:
        lines.append("(no description)")
    lines.append("")


def _append_relationships(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Relationships")
    lines.append("")
    rels = _load("relationships")  # type: ignore[operator]
    parent = None
    follow_ups: list[object] = []
    if isinstance(rels, dict):
        parent = rels.get("parent_task")
        fu = rels.get("follow_up_tasks")
        if isinstance(fu, list):
            follow_ups = fu
    if isinstance(parent, dict):
        tid = parent.get("task_id", "unknown")
        title = parent.get("title", "")
        lines.append(f"- Parent task: {tid} — {title}")
    else:
        lines.append("- Parent task: none")
    if follow_ups:
        items = []
        for fu in follow_ups:
            if isinstance(fu, dict):
                tid = fu.get("task_id", "unknown")
                title = fu.get("title", "")
                items.append(f"{tid} — {title}")
        if items:
            lines.append(f"- Follow-up tasks: {', '.join(items)}")
        else:
            lines.append("- Follow-up tasks: none")
    else:
        lines.append("- Follow-up tasks: none")
    lines.append("")


def _append_requirements(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import (
        DependencyRequirement,
        TaskRecord,
    )

    assert isinstance(task, TaskRecord)
    lines.append("## Requirements")
    lines.append("")
    reqs = _load("requirements")  # type: ignore[operator]
    if not reqs:
        lines.append("- none")
        lines.append("")
        return
    if isinstance(reqs, (list, tuple)):
        for req in reqs:
            if isinstance(req, DependencyRequirement):
                rid = req.required_task_id or req.task_id
                lines.append(f"- {rid}: status {req.required_status}")
            elif isinstance(req, dict):
                rid = req.get("required_task_id", "unknown")
                rs = req.get("required_status", "?")
                lines.append(f"- {rid}: status {rs}")
    lines.append("")


def _append_files(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import FileLink, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Linked Files")
    lines.append("")
    links = _load("links")  # type: ignore[operator]
    if not links:
        lines.append("- none")
        lines.append("")
        return
    if isinstance(links, (list, tuple)):
        for link in links:
            if isinstance(link, FileLink):
                lines.append(f"- `{link.path}` — {link.kind}")
            elif isinstance(link, dict):
                p = link.get("path", "?")
                k = link.get("kind", "?")
                lines.append(f"- `{p}` — {k}")
    lines.append("")


def _append_questions(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import QuestionRecord, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Questions")
    lines.append("")
    questions = _load("questions")  # type: ignore[operator]
    if not questions:
        lines.append("No questions recorded.")
        lines.append("")
        return

    open_q = [
        q for q in questions if isinstance(q, QuestionRecord) and q.status == "open"
    ]
    answered_q = [
        q for q in questions if isinstance(q, QuestionRecord) and q.status == "answered"
    ]

    lines.append("### Open")
    lines.append("")
    if open_q:
        for q in open_q:
            lines.append(f"- {q.id}: {q.question}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Answered")
    lines.append("")
    if answered_q:
        for q in answered_q:
            lines.append(f"- {q.id}: {q.question}")
            answer = q.answer or "(no answer text)"
            lines.append(f"  - Answer: {answer}")
    else:
        lines.append("- none")
    lines.append("")


def _append_plans(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import PlanRecord, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Plans")
    lines.append("")
    plans = _load("plans")  # type: ignore[operator]
    if not plans:
        lines.append("- none")
        lines.append("")
        return

    plan_records: list[PlanRecord] = []
    for plan in plans:
        if isinstance(plan, PlanRecord):
            plan_records.append(plan)
            lines.append(f"- plan-v{plan.plan_version} — {plan.status}")
        elif isinstance(plan, dict):
            pv = plan.get("plan_version", "?")
            st = plan.get("status", "?")
            lines.append(f"- plan-v{pv} — {st}")
    lines.append("")

    reviewable_plans = [
        plan for plan in plan_records if not _plan_is_accepted_plan(plan, accepted_plan)
    ]
    if not reviewable_plans:
        return

    lines.append("### Reviewable Plan Details")
    lines.append("")
    for plan in reviewable_plans:
        _append_plan_detail(lines, plan)


def _plan_is_accepted_plan(plan: object, accepted_plan: object) -> bool:
    from taskledger.domain.models import PlanRecord

    return (
        isinstance(plan, PlanRecord)
        and isinstance(accepted_plan, PlanRecord)
        and plan.plan_version == accepted_plan.plan_version
    )


def _append_plan_detail(lines: list[str], plan: object) -> None:
    from taskledger.domain.models import PlanRecord

    assert isinstance(plan, PlanRecord)
    lines.append(f"#### plan-v{plan.plan_version} — {plan.status}")
    lines.append("")
    lines.append(f"- Created: {plan.created_at}")
    if plan.created_by.actor_name:
        lines.append(
            f"- Created by: {plan.created_by.actor_name} ({plan.created_by.actor_type})"
        )
    else:
        lines.append(f"- Created by: {plan.created_by.actor_type}")
    if plan.supersedes is not None:
        lines.append(f"- Supersedes: plan-v{plan.supersedes}")
    if plan.generation_reason:
        lines.append(f"- Generation reason: {plan.generation_reason}")
    if plan.question_refs:
        lines.append(f"- Based on questions: {', '.join(plan.question_refs)}")
    if plan.files:
        lines.append(f"- Files: {', '.join(plan.files)}")
    if plan.test_commands:
        lines.append(f"- Test commands: {', '.join(plan.test_commands)}")
    lines.append("")

    body = plan.body.strip()
    if body:
        lines.append(body)
    else:
        lines.append("(plan body is empty)")
    lines.append("")

    if plan.criteria:
        lines.append("Planned acceptance criteria:")
        for criterion in plan.criteria:
            mandatory = "" if criterion.mandatory else " (optional)"
            lines.append(f"- {criterion.id}: {criterion.text}{mandatory}")
        lines.append("")

    if plan.todos:
        lines.append("Planned todos:")
        for todo in plan.todos:
            mandatory = "" if todo.mandatory else " (optional)"
            lines.append(f"- [{todo.status}] {todo.id}: {todo.text}{mandatory}")
            if todo.validation_hint:
                lines.append(f"  - Validation hint: {todo.validation_hint}")
            if todo.worker_step_id:
                lines.append(f"  - Worker step: {todo.worker_step_id}")
        lines.append("")


def _append_accepted_plan(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import PlanRecord, TaskRecord
    from taskledger.services.plan_hash import approved_plan_content_hash

    assert isinstance(task, TaskRecord)
    lines.append("## Accepted Plan")
    lines.append("")
    if isinstance(accepted_plan, PlanRecord):
        lines.append(f"- Version: plan-v{accepted_plan.plan_version}")
        if accepted_plan.approved_at:
            lines.append(f"- Approved at: {accepted_plan.approved_at}")
        if accepted_plan.approved_by is not None:
            lines.append(
                "- Approved by: "
                f"{accepted_plan.approved_by.actor_name} "
                f"({accepted_plan.approved_by.actor_type})"
            )
        if accepted_plan.approval_source:
            lines.append(f"- Approval source: {accepted_plan.approval_source}")
        if accepted_plan.approved_plan_hash:
            lines.append(f"- Approved plan hash: {accepted_plan.approved_plan_hash}")
            current_hash = approved_plan_content_hash(accepted_plan)
            if current_hash != accepted_plan.approved_plan_hash:
                lines.append(
                    "- Warning: approved plan content hash does not match current "
                    "plan content."
                )
        lines.append("")
        body = accepted_plan.body.strip()
        if body:
            lines.append(body)
        else:
            lines.append("(accepted plan body is empty)")
    else:
        lines.append("No accepted plan.")
    lines.append("")


def _append_acceptance_criteria(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import (
        AcceptanceCriterion,
        PlanRecord,
        TaskRecord,
    )

    assert isinstance(task, TaskRecord)
    lines.append("## Acceptance Criteria")
    lines.append("")

    criteria: list[AcceptanceCriterion] = []
    if isinstance(accepted_plan, PlanRecord):
        criteria = list(accepted_plan.criteria)

    if not criteria:
        lines.append("- none")
        lines.append("")
        return

    validation_report = _load(  # type: ignore[operator]
        "validation_report"
    )
    checks_by_id: dict[str, str] = {}
    if isinstance(validation_report, dict):
        criteria_reports = validation_report.get("criteria")
        if isinstance(criteria_reports, list):
            for cr in criteria_reports:
                if isinstance(cr, dict):
                    cid = cr.get("id")
                    latest = cr.get("latest_status")
                    if isinstance(cid, str) and isinstance(latest, str):
                        checks_by_id[cid] = latest

    for c in criteria:
        latest_status = checks_by_id.get(c.id, "not_run")
        mark = "x" if latest_status == "pass" else " "
        lines.append(f"- [{mark}] {c.id}: {c.text}")

    lines.append("")


def _append_todos(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord, TaskTodo

    assert isinstance(task, TaskRecord)
    lines.append("## Todo Checklist")
    lines.append("")

    todos = _load("todos")  # type: ignore[operator]
    if not todos:
        lines.append("- none")
        lines.append("")
        return

    todo_list = list(todos) if isinstance(todos, (list, tuple)) else []
    done_count = sum(1 for t in todo_list if isinstance(t, TaskTodo) and t.done)
    total = len(todo_list)
    lines.append(f"Progress: {done_count}/{total} done")
    lines.append("")

    for t in todo_list:
        if isinstance(t, TaskTodo):
            mark = "x" if t.done else " "
            lines.append(f"- [{mark}] {t.id}: {t.text}")
            if t.done and t.evidence:
                for ev in t.evidence:
                    lines.append(f"  - Evidence: {ev}")
    lines.append("")


def _append_implementation(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord, TaskRunRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Implementation")
    lines.append("")

    runs = _load("runs")  # type: ignore[operator]
    impl_runs = [
        r
        for r in (runs or [])
        if isinstance(r, TaskRunRecord) and r.run_type == "implementation"
    ]
    if not impl_runs:
        lines.append("No implementation runs recorded.")
        lines.append("")
        return

    latest = impl_runs[-1]
    lines.append(f"- Latest implementation run: {latest.run_id} — {latest.status}")
    if latest.summary:
        lines.append(f"- Summary: {latest.summary}")
    lines.append("")

    if latest.worklog:
        lines.append("### Worklog")
        lines.append("")
        for entry in latest.worklog:
            lines.append(f"- {entry}")
        lines.append("")

    if latest.deviations_from_plan:
        lines.append("### Deviations from Plan")
        lines.append("")
        for dev in latest.deviations_from_plan:
            lines.append(f"- {dev}")
    else:
        lines.append("### Deviations from Plan")
        lines.append("")
        lines.append("- none")
        lines.append("")


def _append_checks(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import (
        CodeChangeRecord,
        ImplementationCheckRecord,
        TaskRecord,
    )

    assert isinstance(task, TaskRecord)
    checks = _load("checks")  # type: ignore[operator]
    changes = _load("changes")  # type: ignore[operator]

    # Collect legacy command changes as checks
    legacy_checks: list[dict[str, object]] = []
    for ch in changes or []:
        if isinstance(ch, CodeChangeRecord) and ch.kind == "command":
            legacy_checks.append(ch.to_dict())
        elif isinstance(ch, dict) and ch.get("kind") == "command":
            legacy_checks.append(ch)

    all_items: list[dict[str, object]] = []
    for ck in checks or []:
        if isinstance(ck, ImplementationCheckRecord):
            all_items.append(ck.to_dict())
        elif isinstance(ck, dict):
            all_items.append(ck)
    all_items.extend(legacy_checks)

    lines.append("## Checks")
    lines.append("")

    if not all_items:
        lines.append("- none")
        lines.append("")
        return

    lines.append("| ID | Category | Status | Exit | Command |")
    lines.append("| --- | --- | --- | ---: | --- |")
    for item in all_items:
        cid = item.get("check_id") or item.get("change_id", "?")
        cat = item.get("category", "other")
        status = item.get("status", "unknown")
        exit_code = item.get("exit_code")
        cmd = item.get("command", "?")
        exit_str = str(exit_code) if exit_code is not None else "?"
        lines.append(f"| {cid} | {cat} | {status} | {exit_str} | `{cmd}` |")
    lines.append("")


def _append_changes(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import CodeChangeRecord, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Code Changes")
    lines.append("")

    changes = _load("changes")  # type: ignore[operator]
    if not changes:
        lines.append("- none")
        lines.append("")
        return

    for ch in changes:
        if isinstance(ch, CodeChangeRecord):
            if ch.kind == "command":
                continue  # shown under Checks
            lines.append(f"- {ch.kind} `{ch.path}`: {ch.summary}")
        elif isinstance(ch, dict):
            if ch.get("kind") == "command":
                continue  # shown under Checks
            k = ch.get("kind", "?")
            p = ch.get("path", "?")
            s = ch.get("summary", "?")
            lines.append(f"- {k} `{p}`: {s}")
    lines.append("")


def _append_code_reviews(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import CodeReviewRecord, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Code Reviews")
    lines.append("")

    reviews = _load("code_reviews")  # type: ignore[operator]
    if not isinstance(reviews, list) or not reviews:
        lines.append("- none")
        lines.append("")
        return

    lines.append("| ID | Result | Source | Run | Worker | Summary |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for review in reviews:
        if not isinstance(review, CodeReviewRecord):
            continue
        summary = (review.summary or _first_line(review.body) or "").replace("|", "\\|")
        lines.append(
            f"| {review.review_id} | {review.result} | {review.source} | "
            f"{review.implementation_run or ''} | {review.worker_step_id or ''} | "
            f"{summary} |"
        )
    lines.append("")


def _append_validation(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord, TaskRunRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Validation")
    lines.append("")

    runs = _load("runs")  # type: ignore[operator]
    val_runs = [
        r
        for r in (runs or [])
        if isinstance(r, TaskRunRecord) and r.run_type == "validation"
    ]
    if not val_runs:
        lines.append("No validation runs recorded.")
        lines.append("")
        return

    latest = val_runs[-1]
    result_str = latest.result or latest.status
    lines.append(f"- Latest validation run: {latest.run_id} — {result_str}")
    if latest.summary:
        lines.append(f"- Summary: {latest.summary}")
    lines.append("")

    if latest.checks:
        lines.append("### Checks")
        lines.append("")
        for check in latest.checks:
            criterion = check.criterion_id or "unknown"
            lines.append(f"- {criterion}: {check.status}")
            if check.evidence:
                for ev in check.evidence:
                    lines.append(f"  - Evidence: {ev}")
        lines.append("")


def _append_command_log(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import AgentCommandLogRecord, TaskRecord
    from taskledger.services.agent_transcripts import _logical_rows

    assert isinstance(task, TaskRecord)
    lines.append("## Command Transcript")
    lines.append("")

    logs = _load("command_logs")  # type: ignore[operator]
    if not logs:
        lines.append("- none")
        lines.append("")
        return

    rows = _logical_rows(logs)
    lines.append("| Time | Exit | Command | Result |")
    lines.append("| --- | ---: | --- | --- |")
    for row in rows:
        exit_value = row.get("effective_exit")
        exit_str = str(exit_value) if isinstance(exit_value, int) else "-"
        result = str(row.get("result", ""))
        lines.append(
            f"| {row['started_at']} | {exit_str} | "
            f"{row['display_command']} | {result} |"
        )
    lines.append("")

    duplicate_ids = _load("duplicate_log_ids")  # type: ignore[operator]
    if isinstance(duplicate_ids, list) and duplicate_ids:
        lines.append("### Duplicate Log IDs")
        lines.append("")
        for lid in duplicate_ids:
            lines.append(f"- {lid}")
        lines.append("")

    if not options.include_command_output:
        return

    for row in rows:
        raw_records = row.get("_records", [])
        records = raw_records if isinstance(raw_records, list) else []
        # Use the last record for output (managed for pairs, self for standalone)
        primary = records[-1] if records else None
        if not isinstance(primary, AgentCommandLogRecord):
            continue
        lines.append(f"### {primary.log_id} — {row['display_command']}")
        lines.append("")
        exit_value = row.get("effective_exit")
        lines.append(f"Exit: {exit_value if isinstance(exit_value, int) else '-'}")
        lines.append(f"Kind: {primary.command_kind}")
        if primary.run_id:
            lines.append(f"Run: {primary.run_id}")
        lines.append("")
        lines.append("#### stdout")
        lines.append("")
        lines.append("```text")
        lines.append(primary.visible_stdout_excerpt or "(empty)")
        lines.append("```")
        lines.append("")
        lines.append("#### stderr")
        lines.append("")
        lines.append("```text")
        lines.append(primary.visible_stderr_excerpt or "(empty)")
        lines.append("```")
        lines.append("")


def _append_locks(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskLock, TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Lock State")
    lines.append("")

    lock = _load("lock")  # type: ignore[operator]
    if isinstance(lock, TaskLock):
        lines.append(f"- Active lock: {lock.lock_id} (stage: {lock.stage})")
    else:
        lines.append("- Active lock: none")
    lines.append("")


def _append_events(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Events")
    lines.append("")

    events = _load("events")  # type: ignore[operator]
    if not events:
        lines.append("- none")
        lines.append("")
        return

    event_list = events if isinstance(events, list) else []
    if options.events_limit:
        limited = event_list[-options.events_limit :]
    else:
        limited = event_list

    for evt in limited:
        if isinstance(evt, dict):
            ts = str(evt.get("ts", ""))[:19].replace("T", " ")
            event_type = evt.get("event", "unknown")
            summary = _event_summary(evt)
            lines.append(f"- [{ts}] {event_type}: {summary}")
    lines.append("")


def _append_next_action(
    lines: list[str],
    task: object,
    _load: object,
    accepted_plan: object,
    options: TaskReportOptions,
) -> None:
    from taskledger.domain.models import TaskRecord

    assert isinstance(task, TaskRecord)
    lines.append("## Next Action")
    lines.append("")

    na = _load("next_action")  # type: ignore[operator]
    if isinstance(na, dict):
        action = na.get("action")
        reason = na.get("reason")
        if action:
            lines.append(f"Action: {action}")
        if reason:
            lines.append(f"Reason: {reason}")
        if not action and not reason:
            lines.append("No next action.")
    else:
        lines.append("No next action.")
    lines.append("")


def _heading_for(section: str) -> str:
    return section.replace("-", " ").title()


def _safe(value: object) -> str:
    if value is None:
        return "none"
    return str(value).replace("|", "\\|")


def _first_line(value: str) -> str:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _event_summary(evt: dict[str, object]) -> str:
    data = evt.get("data")
    if isinstance(data, dict):
        for key in ("reason", "todo_id", "lock_id", "status", "slug", "title"):
            val = data.get(key)
            if isinstance(val, str) and val:
                return val
    return ""

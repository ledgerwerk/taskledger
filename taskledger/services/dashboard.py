from __future__ import annotations

from pathlib import Path

from taskledger.domain.models import PlanRecord
from taskledger.domain.policies import derive_active_stage
from taskledger.services.validation import build_validation_gate_report
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.task_store import (
    list_changes,
    list_checks,
    list_plans,
    list_questions,
    list_runs,
    load_todos,
    read_lock,
    resolve_task,
    resolve_task_or_active,
    resolve_v2_paths,
    task_lock_path,
)


def dashboard(
    workspace_root: Path,
    *,
    ref: str | None = None,
) -> dict[str, object]:
    if ref is not None:
        task = resolve_task(workspace_root, ref)
    else:
        task = resolve_task_or_active(workspace_root)

    paths = resolve_v2_paths(workspace_root)
    lock = read_lock(task_lock_path(paths, task.id))
    plans = list_plans(workspace_root, task.id)
    questions = list_questions(workspace_root, task.id)
    runs = list_runs(workspace_root, task.id)
    changes = list_changes(workspace_root, task.id)
    checks = list_checks(workspace_root, task.id)

    active_stage: str | None = None
    if lock is not None and not lock_is_expired(lock):
        active_stage = derive_active_stage(lock, runs)

    # next action
    from taskledger.services.navigation import next_action

    action_info = next_action(workspace_root, task.id)

    # todos
    todo_collection = load_todos(workspace_root, task.id)
    todos_total = len(todo_collection.todos)
    todos_done = sum(1 for t in todo_collection.todos if t.done)

    # files
    files = task.file_links

    # bdd
    from taskledger.storage.task_store import (
        load_bdd_examples,
        load_bdd_feature,
        load_bdd_reports,
        load_bdd_rules,
    )

    bdd_feature = load_bdd_feature(workspace_root, task.id)
    bdd_rules = load_bdd_rules(workspace_root, task.id)
    bdd_examples = load_bdd_examples(workspace_root, task.id)
    bdd_reports_list = load_bdd_reports(workspace_root, task.id)
    bdd_examples_by_status: dict[str, int] = {}
    for ex in bdd_examples:
        status = ex.status
        bdd_examples_by_status[status] = bdd_examples_by_status.get(status, 0) + 1
    bdd_examples_summary = [
        {
            "id": ex.id,
            "title": ex.title,
            "status": ex.status,
            "acceptance_criteria": list(ex.acceptance_criteria),
            "archledger_refs": list(ex.archledger_refs),
            "automation": ex.automation.to_dict() if ex.automation else None,
        }
        for ex in bdd_examples
    ]

    return {
        "kind": "dashboard",
        "task": {
            "id": task.id,
            "slug": task.slug,
            "title": task.title,
            "status_stage": task.status_stage,
            "active_stage": active_stage,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "description_summary": task.description_summary,
            "priority": task.priority,
            "labels": list(task.labels),
            "owner": task.owner,
        },
        "plan": _plan_summary(plans),
        "plans": [plan.to_dict() for plan in plans],
        "next_action": action_info,
        "questions": {
            "total": len(questions),
            "open": sum(1 for q in questions if q.status == "open"),
            "items": [question.to_dict() for question in questions],
        },
        "todos": {
            "total": todos_total,
            "done": todos_done,
            "items": [t.to_dict() for t in todo_collection.todos],
        },
        "files": {
            "total": len(files),
            "links": [fl.to_dict() for fl in files],
        },
        "runs": [r.to_dict() for r in runs],
        "changes": [c.to_dict() for c in changes],
        "checks": [c.to_dict() for c in checks],
        "validation": build_validation_gate_report(workspace_root, task),
        "bdd": {
            "feature": bdd_feature.to_dict() if bdd_feature else None,
            "rules": len(bdd_rules),
            "examples": len(bdd_examples),
            "reports": len(bdd_reports_list),
            "examples_by_status": bdd_examples_by_status,
            "items": bdd_examples_summary,
        },
        "events": _recent_task_events(workspace_root, task.id),
        "lock": lock.to_dict() if lock is not None else None,
    }


def render_dashboard_text(payload: dict[str, object]) -> str:  # noqa: C901
    lines: list[str] = []

    task = payload["task"]
    assert isinstance(task, dict)
    lines.append(
        f"Task: {task['slug']} ({task['id']})\n"
        f"Title: {task['title']}\n"
        f"Stage: {task['status_stage']}  Active: {task.get('active_stage') or 'none'}\n"
        f"Created: {_ts(task.get('created_at'))} "
        f"Updated: {_ts(task.get('updated_at'))}",
    )

    desc = task.get("description_summary")
    if desc:
        lines.append(f"Description: {desc}")

    priority = task.get("priority")
    if priority:
        lines.append(f"Priority: {priority}")

    labels = task.get("labels")
    if labels and isinstance(labels, list | tuple) and len(labels) > 0:
        lines.append(f"Labels: {', '.join(str(x) for x in labels)}")

    owner = task.get("owner")
    if owner:
        lines.append(f"Owner: {owner}")

    lines.append("")

    # plan
    plan = payload.get("plan")
    assert isinstance(plan, dict | type(None))
    if plan is not None:
        version = plan.get("version")
        status = plan.get("status", "none")
        lines.append(f"Plan (v{version}): {status}")
        criteria = plan.get("criteria")
        if isinstance(criteria, list | tuple):
            for ac in criteria:
                assert isinstance(ac, dict)
                lines.append(f"  {ac.get('id', '?')}: {ac.get('text', '')}")
    else:
        lines.append("Plan: none")

    lines.append("")

    # next action
    na = payload.get("next_action")
    assert isinstance(na, dict | type(None))
    if na is not None:
        lines.append(f"Next action: {na.get('action', 'none')}")
        reason = na.get("reason")
        if reason:
            lines.append(f"  {reason}")
        next_item = na.get("next_item")
        if isinstance(next_item, dict):
            kind = next_item.get("kind")
            item_id = next_item.get("id")
            text = next_item.get("text")
            if kind and item_id and text:
                lines.append(f"  next {kind}: {item_id}  {text}")
            elif kind and item_id:
                lines.append(f"  next {kind}: {item_id}")
            validation_hint = next_item.get("validation_hint")
            if isinstance(validation_hint, str) and validation_hint:
                lines.append(f"  validation: {validation_hint}")
            done_command = next_item.get("done_command_hint")
            if isinstance(done_command, str) and done_command:
                lines.append(f"  when done: {done_command}")
        next_command = na.get("next_command")
        if next_command:
            lines.append(f"  command: {next_command}")
        progress = na.get("progress")
        if isinstance(progress, dict):
            todos = progress.get("todos")
            if isinstance(todos, dict):
                lines.append(
                    f"  progress: {todos.get('done', 0)}/"
                    f"{todos.get('total', 0)} todos done"
                )
        blockers = na.get("blocking")
        if isinstance(blockers, list | tuple) and len(blockers) > 0:
            for b in blockers:
                assert isinstance(b, dict)
                lines.append(f"  blocker: {b.get('message', '')}")

    lines.append("")

    # questions
    q = payload.get("questions")
    assert isinstance(q, dict)
    lines.append(f"Questions: {q.get('open', 0)} open / {q.get('total', 0)} total")

    # todos
    t = payload.get("todos")
    assert isinstance(t, dict)
    lines.append(f"Todos: {t.get('done', 0)}/{t.get('total', 0)} done")
    items = t.get("items")
    if isinstance(items, list | tuple):
        for item in items:
            assert isinstance(item, dict)
            mark = "x" if item.get("done") else " "
            lines.append(f"  [{mark}] {item.get('id', '?')}  {item.get('text', '')}")

    # files
    f = payload.get("files")
    assert isinstance(f, dict)
    lines.append(f"Files: {f.get('total', 0)} linked")

    # runs
    runs = payload.get("runs")
    if isinstance(runs, list | tuple) and len(runs) > 0:
        lines.append("Runs:")
        for r in runs:
            assert isinstance(r, dict)
            rid = r.get("run_id", "?")
            rtype = r.get("run_type", "?")
            rstatus = r.get("status", "?")
            finished = r.get("finished_at")
            summary = r.get("summary")
            line = f"  {rid} {rtype} {rstatus}"
            if finished:
                line += f" ({_ts(finished)})"
            if summary:
                line += f"\n    {summary}"
            # validation result
            result = r.get("result")
            if result:
                line += f" [{result}]"
            lines.append(line)
    else:
        lines.append("Runs: none")

    lines.append("")

    changes_raw = payload.get("changes") or []
    checks = payload.get("checks") or []
    legacy_command_changes = [
        c
        for c in (changes_raw if isinstance(changes_raw, list | tuple) else [])
        if isinstance(c, dict) and c.get("kind") == "command"
    ]
    all_checks = (
        list(checks if isinstance(checks, list) else []) + legacy_command_changes
    )
    if isinstance(all_checks, list | tuple) and len(all_checks) > 0:
        lines.append(f"Checks: {len(all_checks)}")
        for ck in all_checks:
            assert isinstance(ck, dict)
            if "check_id" in ck:
                ck_id = ck.get("check_id", "?")
                ck_cmd = ck.get("command", "?")
                ck_exit = ck.get("exit_code")
                ck_cat = ck.get("category", "other")
                exit_str = f" (exit {ck_exit})" if ck_exit is not None else ""
                lines.append(f"  {ck_id} {ck_cat} {ck_cmd}{exit_str}")
            else:
                # Legacy command change displayed as check
                ck_id = ck.get("change_id", "?")
                ck_cmd = ck.get("command", ck.get("summary", "?"))
                ck_exit = ck.get("exit_code")
                exit_str = f" (exit {ck_exit})" if ck_exit is not None else ""
                lines.append(f"  {ck_id} {ck_cmd}{exit_str}")
    else:
        lines.append("Checks: none")
    # changes (exclude legacy command records shown as checks above)
    changes_raw = payload.get("changes") or []
    real_changes = [
        c
        for c in (changes_raw if isinstance(changes_raw, list | tuple) else [])
        if isinstance(c, dict) and c.get("kind") != "command"
    ]
    if isinstance(real_changes, list | tuple) and len(real_changes) > 0:
        lines.append(f"Changes: {len(real_changes)}")
        for c in real_changes:
            assert isinstance(c, dict)
            cid = c.get("change_id", "?")
            cpath = c.get("path", "?")
            ckind = c.get("kind", "?")
            csum = c.get("summary", "")
            lines.append(f"  {cid} {cpath} ({ckind})")
            if csum:
                lines.append(f"    {csum}")
    else:
        lines.append("Changes: none")

    # bdd
    from typing import cast

    bdd_raw = payload.get("bdd")
    if isinstance(bdd_raw, dict):
        bdd_dict = cast(dict[str, object], bdd_raw)
        feature = bdd_dict.get("feature")
        bdd_feat_title = feature.get("title", "?") if isinstance(feature, dict) else "?"
        feature_title = str(bdd_feat_title)
        lines.append(f"BDD: {feature_title}")
        lines.append(f"  Rules: {bdd_dict.get('rules', 0)}")
        lines.append(f"  Examples: {bdd_dict.get('examples', 0)}")
        by_status_raw = bdd_dict.get("examples_by_status", {})
        by_status = (
            cast(dict[str, int], by_status_raw)
            if isinstance(by_status_raw, dict)
            else {}
        )
        if by_status:
            parts = [f"{s}: {c}" for s, c in sorted(by_status.items())]
            lines.append(f"  By status: {', '.join(parts)}")
        items_raw = bdd_dict.get("items", [])
        items_list = items_raw if isinstance(items_raw, list) else []
        for item_raw in items_list:
            if not isinstance(item_raw, dict):
                continue
            item = cast(dict[str, object], item_raw)
            archledger_refs = item.get("archledger_refs", [])
            if isinstance(archledger_refs, list) and archledger_refs:
                ref_parts = ", ".join(str(r) for r in archledger_refs)
                archledger = f" [Archledger: {ref_parts}]"
            else:
                archledger = ""
            ac_list = item.get("acceptance_criteria", [])
            if isinstance(ac_list, list) and ac_list:
                ac_str = f" AC: {', '.join(str(a) for a in ac_list)}"
            else:
                ac_str = ""
            lines.append(
                f"  {item.get('id', '?')} [{item.get('status', '?')}]"
                f" {item.get('title', '?')}{ac_str}{archledger}"
            )
        report_count_raw = bdd_dict.get("reports", 0)
        report_count = report_count_raw if isinstance(report_count_raw, int) else 0
        if report_count:
            lines.append(f"  Reports: {report_count}")
    elif bdd_raw is not None:
        lines.append("BDD: none")

    lines.append("")

    # lock
    lock = payload.get("lock")
    if lock is not None and isinstance(lock, dict):
        lines.append(f"Lock: {lock.get('stage', '?')} ({lock.get('run_id', '?')})")
    else:
        lines.append("Lock: none")

    return "\n".join(lines)


def _plan_summary(plans: list[PlanRecord]) -> dict[str, object] | None:
    if not plans:
        return None
    latest: PlanRecord | None = None
    for p in plans:
        if latest is None or p.plan_version > latest.plan_version:
            latest = p
    if latest is None:
        return None
    return {
        "version": latest.plan_version,
        "status": latest.status,
        "criteria": [ac.to_dict() for ac in latest.criteria],
        "body": latest.body,
    }


def _recent_task_events(
    workspace_root: Path,
    task_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    from taskledger.services.tasks import list_events

    events = [
        event
        for event in list_events(workspace_root)
        if event.get("task_id") == task_id
    ]
    if limit <= 0:
        return []
    return events[-limit:]


def _ts(value: object) -> str:
    if value is None:
        return "-"
    s = str(value)
    # trim to datetime portion (drop seconds timezone noise for compactness)
    if len(s) >= 10:
        return s[:10]
    return s

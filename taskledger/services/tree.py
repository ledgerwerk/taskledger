"""Read-only tree view of taskledger workspace, ledgers, and tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskledger.domain.models import ReleaseRecord, TaskLock, TaskRecord
from taskledger.domain.policies import derive_active_stage
from taskledger.storage.frontmatter import read_markdown_front_matter
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.paths import load_project_locator
from taskledger.storage.task_store import (
    list_changes,
    list_plans,
    list_questions,
    list_releases,
    list_runs,
    list_tasks,
    load_active_locks,
    load_active_task_state,
    load_todos,
    resolve_task,
    resolve_v2_paths,
    task_numeric_sort_key,
)


@dataclass(slots=True, frozen=True)
class TreeOptions:
    include_all_ledgers: bool = False
    task_ref: str | None = None
    details: bool = False
    plain: bool = False
    include_archived: bool = False


# ---------------------------------------------------------------------------
# Build tree payload
# ---------------------------------------------------------------------------


def build_tree(workspace_root: Path, options: TreeOptions) -> dict[str, Any]:
    locator = load_project_locator(workspace_root)
    active_state = load_active_task_state(workspace_root)
    active_task_id = active_state.task_id if active_state else None

    scope = "current_ledger"
    if options.task_ref:
        scope = "task_subtree"
    elif options.include_all_ledgers:
        scope = "all_ledgers"

    ledgers: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "kind": "taskledger_tree",
        "workspace_root": str(locator.workspace_root),
        "config_path": str(locator.config_path),
        "taskledger_dir": str(locator.taskledger_dir),
        "current_ledger_ref": _current_ledger_ref(locator.config_path),
        "scope": scope,
        "include_all_ledgers": options.include_all_ledgers,
        "include_archived": options.include_archived,
        "details": options.details,
        "ledgers": ledgers,
    }

    if options.include_all_ledgers:
        ledgers_dir = locator.taskledger_dir / "ledgers"
        if ledgers_dir.exists():
            current_ref = _current_ledger_ref(locator.config_path)
            for ledger_path in sorted(ledgers_dir.iterdir()):
                if ledger_path.is_dir():
                    ref = ledger_path.name
                    is_current = ref == current_ref
                    tasks, releases = _ledger_records(ledger_path)
                    ledger_data = _build_ledger(
                        workspace_root,
                        ref,
                        is_current=is_current,
                        active_task_id=active_task_id if is_current else None,
                        task_ref=options.task_ref if is_current else None,
                        details=options.details,
                        include_archived=options.include_archived,
                        tasks=tasks,
                        releases=releases,
                    )
                    ledgers.append(ledger_data)
    else:
        v2 = resolve_v2_paths(workspace_root)
        ledger_data = _build_ledger(
            workspace_root,
            v2.ledger_ref,
            is_current=True,
            active_task_id=active_task_id,
            task_ref=options.task_ref,
            details=options.details,
            include_archived=options.include_archived,
        )
        ledgers.append(ledger_data)

    return payload


def _current_ledger_ref(config_path: Path) -> str:
    from taskledger.storage.ledger_config import load_ledger_config

    config = load_ledger_config(config_path)
    return config.ref


def _ledger_records(ledger_dir: Path) -> tuple[list[TaskRecord], list[ReleaseRecord]]:
    tasks_dir = ledger_dir / "tasks"
    releases_dir = ledger_dir / "releases"

    tasks: list[TaskRecord] = []
    if tasks_dir.exists():
        tasks = [_load_task_record(path) for path in tasks_dir.glob("task-*/task.md")]
        tasks = sorted(tasks, key=lambda item: task_numeric_sort_key(item.id))

    releases: list[ReleaseRecord] = []
    if releases_dir.exists():
        releases = [_load_release_record(path) for path in releases_dir.glob("*.md")]
        releases = sorted(
            releases,
            key=lambda item: (
                task_numeric_sort_key(item.boundary_task_id),
                item.version,
            ),
        )

    return tasks, releases


def _load_task_record(path: Path) -> TaskRecord:
    metadata, body = read_markdown_front_matter(path)
    payload = dict(metadata)
    payload["body"] = body.rstrip("\n")
    return TaskRecord.from_dict(payload)


def _load_release_record(path: Path) -> ReleaseRecord:
    metadata, body = read_markdown_front_matter(path)
    payload = dict(metadata)
    payload["body"] = body.rstrip("\n")
    return ReleaseRecord.from_dict(payload)


def _build_ledger(
    workspace_root: Path,
    ledger_ref: str,
    *,
    is_current: bool,
    active_task_id: str | None,
    task_ref: str | None,
    details: bool,
    include_archived: bool,
    tasks: list[TaskRecord] | None = None,
    releases: list[ReleaseRecord] | None = None,
) -> dict[str, Any]:
    if tasks is None:
        all_tasks = list_tasks(workspace_root)
    else:
        all_tasks = list(tasks)
    tasks = (
        all_tasks
        if include_archived
        else [task for task in all_tasks if task.archived_at is None]
    )
    if releases is None:
        releases = list_releases(workspace_root)

    locks = load_active_locks(workspace_root) if is_current else []
    lock_by_task: dict[str, TaskLock] = {}
    for lock in locks:
        if not lock_is_expired(lock):
            lock_by_task[lock.task_id] = lock

    next_task_id = _compute_next_task_id(all_tasks)

    task_nodes, orphans = _build_task_nodes(
        tasks,
        workspace_root=workspace_root,
        active_task_id=active_task_id,
        lock_by_task=lock_by_task,
        is_current=is_current,
        details=details,
        task_ref=task_ref,
    )

    release_nodes = [
        {
            "version": r.version,
            "boundary_task_id": r.boundary_task_id,
            "previous_version": r.previous_version,
        }
        for r in releases
    ]

    return {
        "ref": ledger_ref,
        "is_current": is_current,
        "parent_ref": None,
        "ledger_dir": f".taskledger/ledgers/{ledger_ref}",
        "active_task_id": active_task_id,
        "next_task_id": next_task_id,
        "task_count": len(tasks),
        "release_count": len(releases),
        "releases": release_nodes,
        "tasks": task_nodes,
        "orphaned_children": orphans,
    }


def _compute_next_task_id(tasks: list[TaskRecord]) -> str | None:
    if not tasks:
        return None
    max_num = 0
    for t in tasks:
        m = re.fullmatch(r"task-(\d+)", t.id)
        if m:
            max_num = max(max_num, int(m.group(1)))
    if max_num == 0:
        return None
    return f"task-{max_num + 1:04d}"


def _build_task_nodes(
    tasks: list[TaskRecord],
    *,
    workspace_root: Path,
    active_task_id: str | None,
    lock_by_task: dict[str, TaskLock],
    is_current: bool,
    details: bool,
    task_ref: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks_by_id = {t.id: t for t in tasks}
    children_by_parent: dict[str, list[TaskRecord]] = {t.id: [] for t in tasks}
    roots: list[TaskRecord] = []
    orphans: list[TaskRecord] = []

    for task in tasks:
        parent_id = task.parent_task_id
        if parent_id and parent_id in tasks_by_id:
            children_by_parent[parent_id].append(task)
        elif parent_id:
            orphans.append(task)
        else:
            roots.append(task)

    # If task_ref is specified, filter to that task's subtree
    if task_ref:
        try:
            target = resolve_task(workspace_root, task_ref, include_archived=True)
        except Exception:  # noqa: BLE001
            return [], []
        # Collect all descendants
        subtree_ids = _collect_subtree_ids(target.id, children_by_parent)
        subtree_ids.add(target.id)
        roots = [t for t in roots if t.id in subtree_ids]
        # Also check if the target is a child of some parent
        if target.parent_task_id and target.parent_task_id in tasks_by_id:
            # Target is a child; make it a root in the subtree view
            roots = [target]
        filtered_orphans = [o for o in orphans if o.id in subtree_ids]
        orphans = filtered_orphans
        # Update children_by_parent to only include subtree
        children_by_parent = {
            tid: [c for c in cs if c.id in subtree_ids]
            for tid, cs in children_by_parent.items()
            if tid in subtree_ids
        }

    def _active_stage(task_id: str) -> str | None:
        if not is_current:
            return None
        lock = lock_by_task.get(task_id)
        if lock is None:
            return None
        runs = list_runs(workspace_root, task_id)
        return derive_active_stage(lock, runs)

    def _counts(task_id: str) -> dict[str, Any] | None:
        if not details:
            return None
        todo_col = load_todos(workspace_root, task_id)
        total = len(todo_col.todos)
        done = sum(1 for t in todo_col.todos if t.done)
        plans = list_plans(workspace_root, task_id)
        questions = list_questions(workspace_root, task_id)
        runs_list = list_runs(workspace_root, task_id)
        changes = list_changes(workspace_root, task_id)
        has_lock = task_id in lock_by_task
        return {
            "plans": len(plans),
            "questions": len(questions),
            "runs": len(runs_list),
            "changes": len(changes),
            "todos": {
                "total": total,
                "done": done,
                "open": total - done,
            },
            "has_lock": has_lock,
        }

    visited: set[str] = set()

    def node(task: TaskRecord) -> dict[str, Any]:
        if task.id in visited:
            return {"id": task.id, "_cycle": True}
        visited.add(task.id)
        children = sorted(
            children_by_parent.get(task.id, []),
            key=lambda t: task_numeric_sort_key(t.id),
        )
        return {
            "id": task.id,
            "slug": task.slug,
            "title": task.title,
            "status_stage": task.status_stage,
            "archived": task.archived_at is not None,
            "active_stage": _active_stage(task.id),
            "is_active": task.id == active_task_id,
            "task_type": task.task_type,
            "parent_task_id": task.parent_task_id,
            "parent_relation": task.parent_relation,
            "counts": _counts(task.id),
            "children": [node(c) for c in children],
        }

    root_nodes = [
        node(t) for t in sorted(roots, key=lambda t: task_numeric_sort_key(t.id))
    ]
    orphan_nodes = [
        node(t) for t in sorted(orphans, key=lambda t: task_numeric_sort_key(t.id))
    ]
    return root_nodes, orphan_nodes


def _collect_subtree_ids(
    root_id: str,
    children_by_parent: dict[str, list[TaskRecord]],
) -> set[str]:
    ids: set[str] = set()
    stack = [root_id]
    while stack:
        tid = stack.pop()
        if tid in ids:
            continue
        ids.add(tid)
        for child in children_by_parent.get(tid, []):
            stack.append(child.id)
    return ids


# ---------------------------------------------------------------------------
# Render tree text
# ---------------------------------------------------------------------------

_UNICODE = {"mid": "├─ ", "last": "└─ ", "pipe": "│  ", "space": "   "}
_ASCII = {"mid": "+- ", "last": "`- ", "pipe": "|  ", "space": "   "}


def render_tree_text(payload: dict[str, Any], *, plain: bool = False) -> str:
    glyphs = _ASCII if plain else _UNICODE
    lines: list[str] = ["TASKLEDGER TREE", str(payload["workspace_root"])]

    ledgers = payload["ledgers"]
    if not isinstance(ledgers, list):
        return "\n".join(lines)

    for li, ledger in enumerate(ledgers):
        is_last_ledger = li == len(ledgers) - 1
        branch = glyphs["last"] if is_last_ledger else glyphs["mid"]
        prefix_cont = glyphs["space"] if is_last_ledger else glyphs["pipe"]

        ledger_line = _ledger_header(ledger)
        lines.append(f"{branch}{ledger_line}")

        children_count = _count_ledger_children(ledger)
        ci = 0

        # Releases
        releases = ledger.get("releases", [])
        if isinstance(releases, list) and releases:
            ci += 1
            is_last = ci == children_count
            rb = glyphs["last"] if is_last else glyphs["mid"]
            rp = prefix_cont + (glyphs["space"] if is_last else glyphs["pipe"])
            lines.append(f"{prefix_cont}{rb}releases")
            for ri, rel in enumerate(releases):
                r_is_last = ri == len(releases) - 1
                r_branch = glyphs["last"] if r_is_last else glyphs["mid"]
                lines.append(
                    f"{rp}{r_branch}{rel['version']} -> {rel['boundary_task_id']}"
                )

        # Tasks
        tasks = ledger.get("tasks", [])
        orphaned = ledger.get("orphaned_children", [])
        if isinstance(tasks, list):
            ci += 1
            is_last = ci == children_count and not orphaned
            tb = glyphs["last"] if is_last else glyphs["mid"]
            tp = prefix_cont + (glyphs["space"] if is_last else glyphs["pipe"])
            if not tasks and not orphaned:
                lines.append(f"{prefix_cont}{tb}(no tasks)")
            else:
                lines.append(f"{prefix_cont}{tb}tasks")
                for ti, task in enumerate(tasks):
                    t_is_last = ti == len(tasks) - 1 and not orphaned
                    _render_task_node(lines, task, tp, t_is_last, glyphs)

                # Orphaned children
                if isinstance(orphaned, list) and orphaned:
                    o_branch = glyphs["last"]
                    o_prefix = tp + glyphs["space"]
                    lines.append(f"{tp}{o_branch}orphaned children")
                    for oi, orphan in enumerate(orphaned):
                        o_is_last = oi == len(orphaned) - 1
                        _render_task_node(lines, orphan, o_prefix, o_is_last, glyphs)

    return "\n".join(lines)


def _count_ledger_children(ledger: dict[str, Any]) -> int:
    count = 0
    releases = ledger.get("releases", [])
    if isinstance(releases, list) and releases:
        count += 1
    tasks = ledger.get("tasks", [])
    orphaned = ledger.get("orphaned_children", [])
    if isinstance(tasks, list) and (tasks or (isinstance(orphaned, list) and orphaned)):
        count += 1
    return count


def _ledger_header(ledger: dict[str, Any]) -> str:
    parts = [f"ledger {ledger['ref']}"]
    if ledger.get("is_current"):
        parts.append("(current)")
    task_count = ledger.get("task_count", 0)
    parts.append(f"tasks={task_count}")
    active = ledger.get("active_task_id")
    parts.append(f"active={active or 'none'}")
    nxt = ledger.get("next_task_id")
    if nxt:
        parts.append(f"next={nxt}")
    return " ".join(parts)


def _render_task_node(
    lines: list[str],
    task: dict[str, Any],
    parent_prefix: str,
    is_last: bool,
    glyphs: dict[str, str],
) -> None:
    branch = glyphs["last"] if is_last else glyphs["mid"]
    child_prefix = parent_prefix + (glyphs["space"] if is_last else glyphs["pipe"])

    parts: list[str] = [task["id"]]
    slug = task.get("slug")
    if slug:
        parts.append(slug)
    status = task.get("status_stage", "")
    active_stage = task.get("active_stage")
    if active_stage:
        parts.append(f"[{status}/{active_stage}]")
    else:
        parts.append(f"[{status}]")
    title = task.get("title", "")
    if title:
        parts.append(title)

    # Follow-up marker
    parent_relation = task.get("parent_relation")
    if parent_relation == "follow_up":
        parts.append("(follow-up)")

    # Recorded marker
    if task.get("task_type") == "recorded":
        parts.append("{recorded}")
    if task.get("archived"):
        parts.append("{archived}")

    # Active marker
    if task.get("is_active"):
        parts.append("*")

    # Details counts
    counts = task.get("counts")
    if counts and isinstance(counts, dict):
        todo_info = counts.get("todos", {})
        count_parts: list[str] = []
        if isinstance(todo_info, dict):
            count_parts.append(
                f"todos={todo_info.get('done', 0)}/{todo_info.get('total', 0)}"
            )
        count_parts.append(f"plans={counts.get('plans', 0)}")
        count_parts.append(f"runs={counts.get('runs', 0)}")
        count_parts.append(f"changes={counts.get('changes', 0)}")
        parts.append(" ".join(count_parts))

    lines.append(f"{parent_prefix}{branch}{' '.join(str(p) for p in parts)}")

    # Render children
    children = task.get("children", [])
    if isinstance(children, list):
        for ci, child in enumerate(children):
            c_is_last = ci == len(children) - 1
            if child.get("_cycle"):
                lines.append(f"{child_prefix}{glyphs['last']}(cycle: {child['id']})")
            else:
                _render_task_node(lines, child, child_prefix, c_is_last, glyphs)

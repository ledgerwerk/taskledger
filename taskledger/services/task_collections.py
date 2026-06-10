"""Task sidecar collection operations: todos, file links, requirements, introductions.

These functions were extracted from services/tasks.py to shrink the monolith.
tasks.py re-exports them for backward compatibility.
"""

from __future__ import annotations

import getpass
from dataclasses import replace
from pathlib import Path

from taskledger.domain.models import (
    ActorRef,
    DependencyRequirement,
    DependencyWaiver,
    FileLink,
    HarnessRef,
    IntroductionRecord,
    LinkCollection,
    RequirementCollection,
    TaskRecord,
    TaskTodo,
    TodoCollection,
)
from taskledger.domain.policies import (
    require_known_actor_role,
    todo_add_decision,
    todo_toggle_decision,
)
from taskledger.domain.states import (
    EXIT_CODE_APPROVAL_REQUIRED,
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_MISSING,
    normalize_file_link_kind,
)
from taskledger.ids import next_project_id
from taskledger.services import tasks as _tasks
from taskledger.services.file_links import (
    file_status as build_file_status,
)
from taskledger.services.file_links import (
    refresh_file_baseline as refresh_file_link_baseline,
)
from taskledger.services.file_links import (
    with_baseline,
)
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    list_introductions,
    load_requirements,
    resolve_introduction,
    resolve_task,
    resolve_v2_paths,
    save_introduction,
    save_links,
    save_requirements,
    save_task,
    save_todos,
)
from taskledger.timeutils import utc_now_iso

# ---------------------------------------------------------------------------
# Internal helpers exclusive to collection operations
# ---------------------------------------------------------------------------


def _next_todo_payload(task_id: str, todo: TaskTodo) -> dict[str, object]:
    return {
        "kind": "next_todo",
        "task_id": task_id,
        "next_todo_id": todo.id,
        "next_todo": todo.to_dict(),
        "commands": _tasks._todo_command_hints(todo.id),
        "can_finish_implementation": False,
    }


# ---------------------------------------------------------------------------
# Introductions
# ---------------------------------------------------------------------------


def create_introduction(
    workspace_root: Path,
    *,
    title: str,
    body: str,
    slug: str | None = None,
    labels: tuple[str, ...] = (),
) -> IntroductionRecord:
    intros = list_introductions(workspace_root)
    intro = IntroductionRecord(
        id=next_project_id("intro", [item.id for item in intros]),
        slug=_tasks._unique_slug(intros, slug or title),
        title=title,
        body=body.strip(),
        labels=tuple(dict.fromkeys(labels)),
    )
    save_introduction(workspace_root, intro)
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return intro


def link_introduction(
    workspace_root: Path, task_ref: str, introduction_ref: str
) -> TaskRecord:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="link introduction on")
    intro = resolve_introduction(workspace_root, introduction_ref)
    updated = replace(
        task,
        introduction_ref=intro.id,
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "task.updated",
        {"introduction_ref": intro.id},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


# ---------------------------------------------------------------------------
# Requirements / Dependencies
# ---------------------------------------------------------------------------


def add_requirement(
    workspace_root: Path, task_ref: str, required_task_ref: str
) -> TaskRecord:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="add requirement to")
    required = resolve_task(workspace_root, required_task_ref)
    requirements = list(task.requirements)
    if required.id not in requirements:
        requirements.append(required.id)
    updated = replace(
        task,
        requirements=tuple(requirements),
        updated_at=utc_now_iso(),
    )
    save_requirements(
        workspace_root,
        RequirementCollection(
            task_id=updated.id,
            requirements=tuple(
                DependencyRequirement(task_id=item) for item in requirements
            ),
        ),
    )
    save_task(workspace_root, updated)
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


def remove_requirement(
    workspace_root: Path, task_ref: str, required_task_ref: str
) -> TaskRecord:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="remove requirement from")
    required = resolve_task(workspace_root, required_task_ref)
    remaining = tuple(item for item in task.requirements if item != required.id)
    updated = replace(
        task,
        requirements=remaining,
        updated_at=utc_now_iso(),
    )
    save_requirements(
        workspace_root,
        RequirementCollection(
            task_id=updated.id,
            requirements=tuple(
                DependencyRequirement(task_id=item) for item in remaining
            ),
        ),
    )
    save_task(workspace_root, updated)
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


def waive_requirement(
    workspace_root: Path,
    task_ref: str,
    required_task_ref: str,
    *,
    actor_type: str,
    reason: str,
) -> TaskRecord:
    if actor_type != "user":
        raise _tasks._cli_error(
            "Only user dependency waivers can unblock implementation.",
            EXIT_CODE_APPROVAL_REQUIRED,
        )
    if not reason.strip():
        raise _tasks._cli_error(
            "Dependency waiver requires --reason.", EXIT_CODE_BAD_INPUT
        )
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="waive requirement on")
    required = resolve_task(workspace_root, required_task_ref)
    sidecar = load_requirements(workspace_root, task.id)
    requirements = list(sidecar.requirements)
    for index, item in enumerate(requirements):
        if item.task_id == required.id:
            requirements[index] = replace(
                item,
                waiver=DependencyWaiver(
                    actor=ActorRef(
                        actor_type="user",
                        actor_name=getpass.getuser() or "user",
                        tool="manual",
                    ),
                    reason=reason.strip(),
                ),
            )
            break
    else:
        requirements.append(
            DependencyRequirement(
                task_id=required.id,
                waiver=DependencyWaiver(
                    actor=ActorRef(
                        actor_type="user",
                        actor_name=getpass.getuser() or "user",
                        tool="manual",
                    ),
                    reason=reason.strip(),
                ),
            )
        )
    save_requirements(
        workspace_root,
        RequirementCollection(task_id=task.id, requirements=tuple(requirements)),
    )
    updated = replace(
        task,
        requirements=tuple(item.task_id for item in requirements),
        updated_at=utc_now_iso(),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "requirement.waived",
        {"required_task_id": required.id, "reason": reason.strip()},
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


# ---------------------------------------------------------------------------
# File links
# ---------------------------------------------------------------------------


def add_file_link(
    workspace_root: Path,
    task_ref: str,
    *,
    path: str,
    kind: str,
    label: str | None = None,
    required_for_validation: bool = False,
    snapshot: bool | None = None,
) -> TaskRecord:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="add file link to")
    links = list(task.file_links)
    existing = next((item for item in links if item.path == path), None)
    if existing is None:
        new_link = FileLink(
            path=path,
            kind=normalize_file_link_kind(kind),
            label=label,
            required_for_validation=required_for_validation,
        )
        if snapshot is not False:
            new_link = with_baseline(new_link, workspace_root)
    else:
        new_link = replace(
            existing,
            kind=normalize_file_link_kind(kind),
            label=label,
            required_for_validation=required_for_validation,
            updated_at=utc_now_iso(),
        )
        if snapshot is True:
            new_link = with_baseline(new_link, workspace_root)
    if existing is not None:
        links = [item for item in links if item.path != path]
    links.append(new_link)
    updated = replace(
        task,
        file_links=tuple(links),
        updated_at=utc_now_iso(),
    )
    save_links(
        workspace_root, LinkCollection(task_id=updated.id, links=updated.file_links)
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "file.linked",
        {
            "path": path,
            "kind": kind,
            "snapshot": snapshot,
            "target_type": new_link.target_type,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


def remove_file_link(workspace_root: Path, task_ref: str, *, path: str) -> TaskRecord:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="remove file link from")
    remaining = tuple(item for item in task.file_links if item.path != path)
    updated = replace(
        task,
        file_links=remaining,
        updated_at=utc_now_iso(),
    )
    save_links(workspace_root, LinkCollection(task_id=updated.id, links=remaining))
    save_task(workspace_root, updated)
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return updated


def list_file_links(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    return {
        "kind": "task_file_links",
        "task_id": task.id,
        "file_links": [item.to_dict() for item in task.file_links],
    }


def file_status(workspace_root: Path, task_ref: str) -> dict[str, object]:
    return build_file_status(workspace_root, task_ref)


def refresh_file_baseline(
    workspace_root: Path,
    task_ref: str,
    *,
    path: str,
    reason: str,
) -> dict[str, object]:
    return refresh_file_link_baseline(
        workspace_root,
        task_ref,
        path,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Todos
# ---------------------------------------------------------------------------


def add_todo(
    workspace_root: Path,
    task_ref: str,
    *,
    text: str,
    source: str | None = None,
    mandatory: bool = False,
) -> TaskRecord:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="add todo to")
    lock = _tasks._lock_for_mutation(workspace_root, task.id)
    # Infer source from active lock unless explicitly provided
    if source is not None:
        resolved_source = source
    elif lock is not None and lock.stage == "planning":
        resolved_source = "planner"
    elif lock is not None and lock.stage == "implementing":
        resolved_source = "implementer"
    else:
        resolved_source = "user"
    actor_role = require_known_actor_role(resolved_source)
    _tasks._enforce_decision(
        todo_add_decision(
            task,
            lock,
            actor_role=actor_role,
        )
    )
    todo = TaskTodo(
        id=next_project_id("todo", [item.id for item in task.todos]),
        text=text.strip(),
        source=resolved_source,
        mandatory=mandatory,
        active_at=utc_now_iso()
        if lock is not None and lock.stage == "implementing"
        else None,
    )
    updated = replace(
        task,
        todos=tuple([*task.todos, todo]),
        updated_at=utc_now_iso(),
    )
    save_todos(workspace_root, TodoCollection(task_id=updated.id, todos=updated.todos))
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "todo.added",
        {"todo_id": todo.id, "text": todo.text},
    )
    return updated


def set_todo_done(
    workspace_root: Path,
    task_ref: str,
    todo_id: str,
    *,
    done: bool,
    evidence: str | None = None,
    artifacts: tuple[str, ...] = (),
    changes: tuple[str, ...] = (),
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> TaskRecord:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    _tasks._ensure_not_archived(task, operation="update todo on")
    normalized_todo_id = _tasks._normalize_local_id(todo_id, "todo")
    _tasks._enforce_decision(
        todo_toggle_decision(
            task,
            _tasks._lock_for_mutation(workspace_root, task.id),
            actor_role="user",
        )
    )
    now = utc_now_iso()
    resolved_actor = actor or _tasks._default_actor()
    todos = [
        replace(
            todo,
            done=done,
            status="done" if done else "open",
            updated_at=now,
            done_at=now if done else None,
            completed_by=resolved_actor if done else None,
            completed_in_harness=harness if done else None,
            evidence=(
                tuple([*todo.evidence, evidence.strip()])
                if done and evidence and evidence.strip()
                else todo.evidence
            ),
            artifact_refs=tuple([*todo.artifact_refs, *artifacts])
            if done
            else todo.artifact_refs,
            change_refs=tuple([*todo.change_refs, *changes])
            if done
            else todo.change_refs,
        )
        if todo.id in {todo_id, normalized_todo_id}
        else todo
        for todo in task.todos
    ]
    if not any(todo.id in {todo_id, normalized_todo_id} for todo in task.todos):
        raise _tasks._cli_error(f"Todo not found: {todo_id}", EXIT_CODE_MISSING)
    updated = replace(task, todos=tuple(todos), updated_at=now)
    save_todos(workspace_root, TodoCollection(task_id=updated.id, todos=updated.todos))
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "todo.completed" if done else "todo.toggled",
        {
            "todo_id": todo_id,
            "done": done,
            "evidence": evidence,
            "artifacts": list(artifacts),
            "changes": list(changes),
        },
    )
    return updated


def show_todo(workspace_root: Path, task_ref: str, todo_id: str) -> dict[str, object]:
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    normalized_todo_id = _tasks._normalize_local_id(todo_id, "todo")
    for todo in task.todos:
        if todo.id == todo_id or todo.id == normalized_todo_id:
            return {
                "kind": "task_todo",
                "task_id": task.id,
                "todo": todo.to_dict(),
            }
    raise _tasks._cli_error(f"Todo not found: {todo_id}", EXIT_CODE_MISSING)


def todo_status(workspace_root: Path, task_ref: str) -> dict[str, object]:
    """Get todo status and progress for a task."""
    task = resolve_task(workspace_root, task_ref)
    return _tasks._build_todo_gate_report(workspace_root, task)


def next_todo(workspace_root: Path, task_ref: str) -> dict[str, object]:
    """Get the next unfinished todo for a task."""
    task = _tasks._task_with_sidecars(
        workspace_root, resolve_task(workspace_root, task_ref)
    )
    todos = task.todos

    # Prefer active todos first, then first open todo
    for todo in todos:
        if not todo.done and hasattr(todo, "status") and todo.status == "active":
            return _next_todo_payload(task.id, todo)

    for todo in todos:
        if not todo.done:
            return _next_todo_payload(task.id, todo)

    return {
        "kind": "next_todo",
        "task_id": task.id,
        "next_todo_id": None,
        "next_todo": None,
        "commands": [],
        "can_finish_implementation": True,
    }

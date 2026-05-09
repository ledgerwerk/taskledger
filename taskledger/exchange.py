from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256 as _sha256
from pathlib import Path
from typing import Literal, cast

import yaml

from taskledger.domain.models import (
    ActiveTaskState,
    AgentCommandLogRecord,
    CodeChangeRecord,
    DependencyRequirement,
    FileLink,
    ImplementationCheckRecord,
    IntroductionRecord,
    LinkCollection,
    PlanRecord,
    QuestionRecord,
    ReleaseRecord,
    RequirementCollection,
    TaskEvent,
    TaskHandoffRecord,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
    TodoCollection,
)
from taskledger.errors import LaunchError
from taskledger.ids import allocate_ledger_task_id, slugify_project_ref
from taskledger.storage.agent_logs import (
    append_agent_command_log,
    load_agent_command_logs,
)
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.events import append_event, load_events
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.ledger_config import (
    LedgerConfigPatch,
    load_ledger_config,
    update_ledger_config,
)
from taskledger.storage.locks import write_lock
from taskledger.storage.paths import load_project_locator
from taskledger.storage.project_identity import (
    assert_same_project_uuid,
    ensure_project_uuid,
    normalize_project_uuid,
    project_name_or_default,
    project_slug_or_default,
)
from taskledger.storage.task_store import (
    V2Paths,
    ensure_v2_layout,
    load_active_locks,
    load_active_task_state,
    overwrite_plan,
    plan_markdown_path,
    resolve_task,
    resolve_v2_paths,
    save_active_task_state,
    save_change,
    save_check,
    save_handoff,
    save_introduction,
    save_links,
    save_plan,
    save_question,
    save_release,
    save_requirements,
    save_run,
    save_task,
    save_todos,
    task_audit_dir,
    task_lock_path,
)
from taskledger.storage.task_store import list_changes as list_v2_changes
from taskledger.storage.task_store import list_checks as list_v2_checks
from taskledger.storage.task_store import list_handoffs as list_v2_handoffs
from taskledger.storage.task_store import list_introductions as list_v2_introductions
from taskledger.storage.task_store import list_plans as list_v2_plans
from taskledger.storage.task_store import list_questions as list_v2_questions
from taskledger.storage.task_store import list_releases as list_v2_releases
from taskledger.storage.task_store import list_runs as list_v2_runs
from taskledger.storage.task_store import list_tasks as list_v2_tasks
from taskledger.storage.task_store import load_links as load_v2_links
from taskledger.storage.task_store import load_requirements as load_v2_requirements
from taskledger.storage.task_store import load_todos as load_v2_todos
from taskledger.timeutils import utc_now_iso

ImportLockPolicy = Literal["drop", "keep", "quarantine"]
IMPORT_LOCK_POLICIES: tuple[ImportLockPolicy, ...] = ("drop", "keep", "quarantine")
ImportIdPolicy = Literal["preserve", "renumber-on-conflict", "fail-on-conflict"]
IMPORT_ID_POLICIES: tuple[ImportIdPolicy, ...] = (
    "preserve",
    "renumber-on-conflict",
    "fail-on-conflict",
)
ArchiveScope = Literal["ledger", "tasks"]


@dataclass(frozen=True)
class ExportSelection:
    scope: ArchiveScope
    task_ids: tuple[str, ...] = ()


def export_project_payload(
    workspace_root: Path,
    *,
    include_bodies: bool = False,
    include_run_artifacts: bool = False,
    selected_task_ids: Sequence[str] = (),
) -> dict[str, object]:
    selected_ids = tuple(selected_task_ids)
    v2_payload = _export_v2_payload(
        workspace_root,
        include_bodies=include_bodies,
        selected_task_ids=set(selected_ids) if selected_ids else None,
    )
    archive_scope: ArchiveScope = "tasks" if selected_ids else "ledger"
    return {
        "kind": "taskledger_export",
        "version": 4,
        "schema_version": 2,
        "generated_at": utc_now_iso(),
        "project_dir": str(resolve_v2_paths(workspace_root).project_dir),
        "archive_scope": archive_scope,
        "selected_task_ids": list(selected_ids),
        "options": {
            "include_bodies": include_bodies,
            "include_run_artifacts": include_run_artifacts,
        },
        "counts": {
            key: len(_dict_list(value))
            for key, value in v2_payload.items()
            if isinstance(value, list)
        },
        "v2": v2_payload,
    }


def resolve_export_selection(
    workspace_root: Path, task_refs: Sequence[str]
) -> ExportSelection:
    if not task_refs:
        return ExportSelection(scope="ledger")
    ordered: list[str] = []
    seen: set[str] = set()
    for task_ref in task_refs:
        resolved = resolve_task(workspace_root, task_ref.strip())
        if resolved.id in seen:
            continue
        seen.add(resolved.id)
        ordered.append(resolved.id)
    if not ordered:
        raise LaunchError("No tasks selected for task archive export.")
    return ExportSelection(scope="tasks", task_ids=tuple(ordered))


def parse_project_import_payload(text: str, *, format_name: str) -> dict[str, object]:
    if format_name != "json":
        raise LaunchError(f"Unsupported project import format: {format_name}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LaunchError(f"Invalid project import JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LaunchError("Project import JSON must be an object.")
    result: dict[str, object] = payload
    if payload.get("success") is True and isinstance(payload.get("data"), dict):
        candidate = payload["data"]
        if candidate.get("kind") in {"taskledger_export", "project_export"}:
            result = candidate
    if payload.get("ok") is True and isinstance(payload.get("result"), dict):
        candidate = payload["result"]
        if candidate.get("kind") in {"taskledger_export", "project_export"}:
            result = candidate
    if result.get("kind") not in {None, "taskledger_export", "project_export"}:
        raise LaunchError("Unsupported project import payload kind.")
    return result


def import_project_payload(
    workspace_root: Path,
    *,
    payload: dict[str, object],
    replace: bool,
    dry_run: bool = False,
    lock_policy: ImportLockPolicy | str = "quarantine",
    id_policy: ImportIdPolicy | str = "preserve",
    archive_scope: ArchiveScope = "ledger",
) -> dict[str, object]:
    normalized_lock_policy = normalize_import_lock_policy(lock_policy)
    normalized_id_policy = normalize_import_id_policy(id_policy)
    _assert_payload_project_uuid(workspace_root, payload)
    raw_v2 = payload.get("v2")
    if not isinstance(raw_v2, dict):
        raise LaunchError("Import payload is missing v2 task state.")
    incoming_task_ids = [
        str(item.get("id"))
        for item in _dict_list(raw_v2.get("tasks"))
        if item.get("id")
    ]
    effective_id_policy: ImportIdPolicy = (
        "preserve"
        if replace
        else (
            "renumber-on-conflict"
            if archive_scope == "tasks" and normalized_id_policy == "preserve"
            else normalized_id_policy
        )
    )
    task_id_map = _build_import_task_id_map(
        workspace_root,
        incoming_task_ids,
        id_policy=effective_id_policy,
    )
    rewritten_v2 = _rewrite_task_ids_in_payload(
        raw_v2,
        task_id_map,
        include_active_task=archive_scope != "tasks",
    )
    renumbered = sorted(
        [incoming for incoming, target in task_id_map.items() if incoming != target]
    )
    imported_task_ids = [task_id_map[item] for item in incoming_task_ids]
    counts = _payload_counts(payload)
    if dry_run:
        return {
            "kind": "taskledger_import",
            "replace": replace,
            "dry_run": True,
            "lock_policy": normalized_lock_policy,
            "id_policy": effective_id_policy,
            "archive_scope": archive_scope,
            "project_uuid": payload.get("project_uuid"),
            "project_name": payload.get("project_name"),
            "project_slug": payload.get("project_slug"),
            "ledger_ref": payload.get("ledger_ref"),
            "counts": counts,
            "task_id_map": task_id_map,
            "renumbered": renumbered,
            "imported_task_ids": imported_task_ids,
        }
    paths = ensure_v2_layout(workspace_root)
    if replace:
        _clear_v2_state(paths)
    else:
        _assert_import_will_not_overwrite_tasks(workspace_root, imported_task_ids)
    payload_for_import = dict(payload)
    payload_for_import["v2"] = rewritten_v2
    _import_v2_payload(
        workspace_root,
        payload_for_import,
        replace=replace,
        lock_policy=normalized_lock_policy,
    )
    rebuilt_counts = rebuild_v2_indexes(paths)
    counts = {key: value for key, value in rebuilt_counts.items()}
    next_task_number = repair_ledger_next_task_number(workspace_root)
    return {
        "kind": "taskledger_import",
        "replace": replace,
        "dry_run": False,
        "lock_policy": normalized_lock_policy,
        "id_policy": effective_id_policy,
        "archive_scope": archive_scope,
        "project_uuid": payload.get("project_uuid"),
        "project_name": payload.get("project_name"),
        "project_slug": payload.get("project_slug"),
        "ledger_ref": payload.get("ledger_ref"),
        "counts": counts,
        "task_id_map": task_id_map,
        "renumbered": renumbered,
        "imported_task_ids": imported_task_ids,
        "ledger_next_task_number": next_task_number,
    }


def write_project_snapshot(
    workspace_root: Path,
    *,
    output_dir: Path,
    include_bodies: bool,
    include_run_artifacts: bool,
) -> dict[str, object]:
    payload = export_project_payload(
        workspace_root,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
    )
    timestamp = utc_now_iso().replace(":", "-").replace("+00:00", "Z")
    snapshot_dir = output_dir / f"taskledger-snapshot-{timestamp}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    export_path = snapshot_dir / "taskledger-export.json"
    export_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "kind": "taskledger_snapshot",
        "snapshot_dir": str(snapshot_dir),
        "export_path": str(export_path),
        "include_bodies": include_bodies,
        "include_run_artifacts": include_run_artifacts,
    }


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _export_v2_payload(
    workspace_root: Path,
    *,
    include_bodies: bool = True,
    selected_task_ids: set[str] | None = None,
) -> dict[str, object]:
    tasks = list_v2_tasks(workspace_root)
    if selected_task_ids is not None:
        tasks = [task for task in tasks if task.id in selected_task_ids]
    introductions = list_v2_introductions(workspace_root)
    if selected_task_ids is not None:
        introductions = []
    payload: dict[str, object] = {
        "tasks": [item.to_dict() for item in tasks],
        "active_task": (
            active_state.to_dict()
            if (active_state := load_active_task_state(workspace_root)) is not None
            else None
        ),
        "introductions": [item.to_dict() for item in introductions],
        "releases": (
            []
            if selected_task_ids is not None
            else [item.to_dict() for item in list_v2_releases(workspace_root)]
        ),
        "plans": [
            plan.to_dict()
            for task in tasks
            for plan in list_v2_plans(workspace_root, task.id)
        ],
        "questions": [
            question.to_dict()
            for task in tasks
            for question in list_v2_questions(workspace_root, task.id)
        ],
        "runs": [
            run.to_dict()
            for task in tasks
            for run in list_v2_runs(workspace_root, task.id)
        ],
        "changes": [
            change.to_dict()
            for task in tasks
            for change in list_v2_changes(workspace_root, task.id)
        ],
        "checks": [
            check.to_dict()
            for task in tasks
            for check in list_v2_checks(workspace_root, task.id)
        ],
        "handoffs": [
            handoff.to_dict()
            for task in tasks
            for handoff in list_v2_handoffs(workspace_root, task.id)
        ],
        "todos": [
            todo.to_dict()
            for task in tasks
            for todo in load_v2_todos(workspace_root, task.id).todos
        ],
        "links": [
            link.to_dict()
            for task in tasks
            for link in load_v2_links(workspace_root, task.id).links
        ],
        "requirements": [
            req.to_dict()
            for task in tasks
            for req in load_v2_requirements(workspace_root, task.id).requirements
        ],
        "locks": [item.to_dict() for item in load_active_locks(workspace_root)],
        "events": [
            item.to_dict()
            for item in load_events(resolve_v2_paths(workspace_root).events_dir)
            if selected_task_ids is None or item.task_id in selected_task_ids
        ],
        "agent_command_logs": [
            item.to_dict()
            for item in load_agent_command_logs(workspace_root)
            if selected_task_ids is None
            or (item.task_id is not None and item.task_id in selected_task_ids)
        ],
    }
    if selected_task_ids is not None:
        payload["active_task"] = None
        payload["locks"] = [
            lock
            for lock in _dict_list(payload["locks"])
            if lock.get("task_id") in selected_task_ids
        ]
    if not include_bodies:
        _strip_export_bodies(payload)
    return payload


def _strip_export_bodies(v2_payload: dict[str, object]) -> None:
    body_fields_by_collection = {
        "tasks": ("body",),
        "introductions": ("body",),
        "plans": ("body",),
        "handoffs": ("context_body",),
    }
    for collection_key, body_fields in body_fields_by_collection.items():
        for item in _dict_list(v2_payload.get(collection_key)):
            for field in body_fields:
                if field in item:
                    item.pop(field, None)
                    item[f"{field}_omitted"] = True


def _payload_counts(payload: dict[str, object]) -> dict[str, object]:
    counts = _sanitize_counts(payload.get("counts"))
    if counts:
        return counts
    raw_v2 = payload.get("v2")
    if not isinstance(raw_v2, dict):
        return {}
    return {
        key: len(_dict_list(value))
        for key, value in raw_v2.items()
        if isinstance(value, list)
    }


def _build_import_task_id_map(
    workspace_root: Path,
    incoming_task_ids: Sequence[str],
    *,
    id_policy: ImportIdPolicy,
) -> dict[str, str]:
    existing_ids = {task.id for task in list_v2_tasks(workspace_root)}
    allocated_ids = set(existing_ids)
    locator = load_project_locator(workspace_root)
    ledger = load_ledger_config(locator.config_path)
    next_number = ledger.next_task_number
    id_map: dict[str, str] = {}
    for incoming in incoming_task_ids:
        if incoming in id_map:
            continue
        if incoming not in allocated_ids:
            id_map[incoming] = incoming
            allocated_ids.add(incoming)
            continue
        if id_policy in {"preserve", "fail-on-conflict"}:
            raise LaunchError(f"Task id already exists: {incoming}")
        new_id, next_number = allocate_ledger_task_id(
            sorted(allocated_ids), next_number
        )
        id_map[incoming] = new_id
        allocated_ids.add(new_id)
    return id_map


def _rewrite_task_ids_in_payload(
    raw_v2: dict[str, object],
    id_map: Mapping[str, str],
    *,
    include_active_task: bool,
) -> dict[str, object]:
    if not id_map:
        rewritten = deepcopy(raw_v2)
        if not include_active_task:
            rewritten["active_task"] = None
        return rewritten
    rewritten = deepcopy(raw_v2)

    def rewrite_task_id(value: object) -> object:
        return id_map.get(value, value) if isinstance(value, str) else value

    for item in _dict_list(rewritten.get("tasks")):
        item["id"] = rewrite_task_id(item.get("id"))
        parent_task_id = item.get("parent_task_id")
        if isinstance(parent_task_id, str) and parent_task_id in id_map:
            item["parent_task_id"] = id_map[parent_task_id]
        requirements = item.get("requirements")
        if isinstance(requirements, list):
            item["requirements"] = [rewrite_task_id(req) for req in requirements]

    for key in (
        "plans",
        "questions",
        "runs",
        "changes",
        "checks",
        "handoffs",
        "todos",
        "links",
        "locks",
        "events",
        "agent_command_logs",
    ):
        for item in _dict_list(rewritten.get(key)):
            if "task_id" in item:
                item["task_id"] = rewrite_task_id(item.get("task_id"))

    for item in _dict_list(rewritten.get("requirements")):
        if "task_id" in item:
            item["task_id"] = rewrite_task_id(item.get("task_id"))
        if "parent_task_id" in item:
            item["parent_task_id"] = rewrite_task_id(item.get("parent_task_id"))
        if "required_task_id" in item:
            item["required_task_id"] = rewrite_task_id(item.get("required_task_id"))

    for item in _dict_list(rewritten.get("releases")):
        if "boundary_task_id" in item:
            item["boundary_task_id"] = rewrite_task_id(item.get("boundary_task_id"))

    if include_active_task:
        active_task = rewritten.get("active_task")
        if isinstance(active_task, dict) and "task_id" in active_task:
            active_task["task_id"] = rewrite_task_id(active_task.get("task_id"))
            previous_task_id = active_task.get("previous_task_id")
            if isinstance(previous_task_id, str) and previous_task_id in id_map:
                active_task["previous_task_id"] = id_map[previous_task_id]
    else:
        rewritten["active_task"] = None
    return rewritten


def _assert_import_will_not_overwrite_tasks(
    workspace_root: Path, target_task_ids: Iterable[str]
) -> None:
    existing = {task.id for task in list_v2_tasks(workspace_root)}
    conflicts = sorted(existing & set(target_task_ids))
    if conflicts:
        raise LaunchError(
            "Import would overwrite existing tasks: " + ", ".join(conflicts)
        )


def repair_ledger_next_task_number(workspace_root: Path) -> int | None:
    paths = resolve_v2_paths(workspace_root)
    max_task_number = _max_numeric_task_number(paths.tasks_dir)
    if max_task_number is None:
        return None
    locator = load_project_locator(workspace_root)
    ledger = load_ledger_config(locator.config_path)
    if ledger.next_task_number <= max_task_number:
        updated = update_ledger_config(
            locator.config_path,
            LedgerConfigPatch(next_task_number=max_task_number + 1),
        )
        return updated.next_task_number
    return ledger.next_task_number


def _max_numeric_task_number(tasks_dir: Path) -> int | None:
    max_number: int | None = None
    if not tasks_dir.exists():
        return None
    for child in tasks_dir.glob("task-*"):
        if not child.is_dir():
            continue
        match = re.fullmatch(r"task-(\d+)", child.name)
        if match is None:
            continue
        number = int(match.group(1))
        max_number = number if max_number is None else max(max_number, number)
    return max_number


def _import_standalone_collections(
    raw_v2: dict[str, object], workspace_root: Path
) -> None:
    """Import per-record collections from newer exports."""
    todos_by_task: dict[str, list] = {}
    for item in _dict_list(raw_v2.get("todos")):
        tid = str(item.get("task_id") or "")
        todos_by_task.setdefault(tid, []).append(item)
    for tid, items in todos_by_task.items():
        save_todos(
            workspace_root,
            TodoCollection(
                task_id=tid,
                todos=tuple(TaskTodo.from_dict(i) for i in items),
            ),
        )
    links_by_task: dict[str, list] = {}
    for item in _dict_list(raw_v2.get("links")):
        tid = str(item.get("task_id") or "")
        links_by_task.setdefault(tid, []).append(item)
    for tid, items in links_by_task.items():
        save_links(
            workspace_root,
            LinkCollection(
                task_id=tid,
                links=tuple(FileLink.from_dict(i) for i in items),
            ),
        )
    reqs_by_task: dict[str, list] = {}
    for item in _dict_list(raw_v2.get("requirements")):
        tid = str(item.get("task_id") or item.get("parent_task_id") or "")
        reqs_by_task.setdefault(tid, []).append(item)
    for tid, items in reqs_by_task.items():
        save_requirements(
            workspace_root,
            RequirementCollection(
                task_id=tid,
                requirements=tuple(DependencyRequirement.from_dict(i) for i in items),
            ),
        )


def _import_v2_payload(  # noqa: C901
    workspace_root: Path,
    payload: dict[str, object],
    *,
    replace: bool = False,
    lock_policy: ImportLockPolicy | str = "quarantine",
) -> None:
    normalized_lock_policy = normalize_import_lock_policy(lock_policy)
    raw_v2 = payload.get("v2")
    if not isinstance(raw_v2, dict):
        raise LaunchError("Import payload is missing v2 task state.")
    paths = resolve_v2_paths(workspace_root)
    for item in _dict_list(raw_v2.get("tasks")):
        task = TaskRecord.from_dict(item)
        save_task(workspace_root, task)
        # Import per-record collections from embedded task data
        if task.todos:
            save_todos(
                workspace_root,
                TodoCollection(task_id=task.id, todos=task.todos),
            )
        if task.file_links:
            save_links(
                workspace_root,
                LinkCollection(task_id=task.id, links=task.file_links),
            )
        if task.requirements:
            save_requirements(
                workspace_root,
                RequirementCollection(
                    task_id=task.id,
                    requirements=tuple(
                        DependencyRequirement(task_id=r) for r in task.requirements
                    ),
                ),
            )
    # Import standalone per-record collections (from newer exports)
    _import_standalone_collections(raw_v2, workspace_root)
    active_task = raw_v2.get("active_task")
    if active_task is not None:
        state = ActiveTaskState.from_dict(active_task)
        if not any(task.id == state.task_id for task in list_v2_tasks(workspace_root)):
            raise LaunchError(
                f"Import active task points to missing task: {state.task_id}"
            )
        save_active_task_state(workspace_root, state)
    for item in _dict_list(raw_v2.get("introductions")):
        save_introduction(workspace_root, IntroductionRecord.from_dict(item))
    _import_releases(raw_v2, workspace_root)
    for item in _dict_list(raw_v2.get("plans")):
        plan = PlanRecord.from_dict(item)
        if plan_markdown_path(paths, plan.task_id, plan.plan_version).exists():
            overwrite_plan(workspace_root, plan)
        else:
            save_plan(workspace_root, plan)
    for item in _dict_list(raw_v2.get("questions")):
        save_question(workspace_root, QuestionRecord.from_dict(item))
    for item in _dict_list(raw_v2.get("runs")):
        save_run(workspace_root, TaskRunRecord.from_dict(item))
    for item in _dict_list(raw_v2.get("changes")):
        save_change(workspace_root, CodeChangeRecord.from_dict(item))
    for item in _dict_list(raw_v2.get("checks")):
        save_check(workspace_root, ImplementationCheckRecord.from_dict(item))
    for item in _dict_list(raw_v2.get("handoffs")):
        save_handoff(workspace_root, TaskHandoffRecord.from_dict(item))
    _import_locks(paths, raw_v2, lock_policy=normalized_lock_policy)
    existing_ids: set[str] = set()
    if replace:
        if paths.events_dir.exists():
            for path in paths.events_dir.glob("*.ndjson"):
                path.unlink()
    else:
        existing_ids = {e.event_id for e in load_events(paths.events_dir)}
    for item in _dict_list(raw_v2.get("events")):
        event = TaskEvent.from_dict(item)
        if not replace and event.event_id in existing_ids:
            continue
        append_event(paths.events_dir, event)
    existing_log_ids: set[str] = set()
    if not replace:
        existing_log_ids = {
            item.log_id for item in load_agent_command_logs(workspace_root)
        }
    for item in _dict_list(raw_v2.get("agent_command_logs")):
        log_record = AgentCommandLogRecord.from_dict(item)
        if not replace and log_record.log_id in existing_log_ids:
            continue
        append_agent_command_log(workspace_root, log_record)


def _import_releases(raw_v2: dict[str, object], workspace_root: Path) -> None:
    raw_releases = _dict_list(raw_v2.get("releases"))
    if not raw_releases:
        return
    task_ids_present = {task.id for task in list_v2_tasks(workspace_root)}
    missing = sorted(
        {
            str(item.get("boundary_task_id") or "")
            for item in raw_releases
            if str(item.get("boundary_task_id") or "") not in task_ids_present
        }
    )
    if missing:
        raise LaunchError(
            "Import release records reference missing boundary tasks: "
            + ", ".join(missing)
        )
    for item in raw_releases:
        save_release(workspace_root, ReleaseRecord.from_dict(item))


def _clear_v2_state(paths: V2Paths) -> None:
    for directory in paths.tasks_dir.glob("task-*"):
        if directory.is_dir():
            shutil.rmtree(directory)
    for directory in (
        paths.introductions_dir,
        paths.releases_dir,
        paths.events_dir,
    ):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    if paths.active_task_path.exists():
        paths.active_task_path.unlink()


# ---------------------------------------------------------------------------
# Archive export / import
# ---------------------------------------------------------------------------

ARCHIVE_KIND = "taskledger_archive"
ARCHIVE_VERSION = 1
MANIFEST_MEMBER = "manifest.json"
PAYLOAD_MEMBER = "payload/taskledger-export.json"
ARTIFACTS_PREFIX = "artifacts/"
MAX_ARCHIVE_MEMBERS = 4096
MAX_MANIFEST_BYTES = 256_000
MAX_PAYLOAD_BYTES = 50_000_000
MAX_ARTIFACT_MEMBER_BYTES = 20_000_000
MAX_TOTAL_ARTIFACT_BYTES = 100_000_000


def write_project_archive(
    workspace_root: Path,
    *,
    output_path: Path | None = None,
    include_bodies: bool = True,
    include_run_artifacts: bool = False,
    task_refs: Sequence[str] = (),
    overwrite: bool = False,
) -> dict[str, object]:
    """Export current-ledger state into a gzip-compressed tar archive."""
    paths = ensure_v2_layout(workspace_root)
    locator = load_project_locator(workspace_root)
    project_uuid = ensure_project_uuid(locator.config_path)
    project_name = project_name_or_default(
        locator.config_path, workspace_root=locator.workspace_root
    )
    project_slug = project_slug_or_default(
        locator.config_path, workspace_root=locator.workspace_root
    )
    selection = resolve_export_selection(workspace_root, task_refs)
    selected_task_ids = set(selection.task_ids)

    payload = export_project_payload(
        workspace_root,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
        selected_task_ids=selection.task_ids,
    )
    payload["version"] = 4
    payload["project_uuid"] = project_uuid
    payload["project_name"] = project_name
    payload["project_slug"] = project_slug
    payload["ledger_ref"] = paths.ledger_ref

    payload_bytes = (
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    payload_sha = _sha256(payload_bytes).hexdigest()

    manifest = _build_manifest(
        project_uuid=project_uuid,
        project_name=project_name,
        project_slug=project_slug,
        ledger_ref=paths.ledger_ref,
        payload_sha=payload_sha,
        payload=payload,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
        selection=selection,
    )

    output_path = output_path or (
        _default_task_archive_path(
            project_slug,
            paths.ledger_ref,
            selection.task_ids[0] if selection.task_ids else "task-0000",
        )
        if selection.scope == "tasks"
        else _default_archive_path(project_slug, paths.ledger_ref)
    )
    if output_path.exists():
        if overwrite:
            output_path.unlink()
        else:
            raise LaunchError(
                "Output file already exists: "
                f"{output_path}. Use --overwrite to replace."
            )

    artifact_members = (
        _collect_artifact_members(
            paths,
            selected_task_ids=selected_task_ids if selection.scope == "tasks" else None,
        )
        if include_run_artifacts
        else []
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        _add_json_member(tar, MANIFEST_MEMBER, manifest)
        _add_json_member(tar, PAYLOAD_MEMBER, payload)
        for archive_name, source_path in artifact_members:
            _add_file_member(tar, archive_name, source_path)

    archive_bytes = output_path.read_bytes()
    archive_sha = _sha256(archive_bytes).hexdigest()

    return {
        "kind": "taskledger_archive_export",
        "path": str(output_path),
        "archive_sha256": archive_sha,
        "project_uuid": project_uuid,
        "project_name": project_name,
        "project_slug": project_slug,
        "ledger_ref": paths.ledger_ref,
        "archive_scope": selection.scope,
        "selected_task_ids": list(selection.task_ids),
        "counts": payload["counts"],
        "include_run_artifacts": include_run_artifacts,
        "filename_policy": (
            "project-task-ledger-timestamp-v1"
            if selection.scope == "tasks"
            else "project-ledger-timestamp-v1"
        ),
        "artifact_members": len(artifact_members),
    }


def read_project_archive(source_path: Path) -> dict[str, object]:
    """Read and validate a taskledger archive in-memory.

    Never extracts tar members to disk. Returns dict with keys
    ``manifest`` and ``payload``.
    """
    if not source_path.exists():
        raise LaunchError(f"Archive not found: {source_path}")

    with tarfile.open(source_path, "r:gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        artifact_members = _validate_archive_members(members)

        manifest_member = members[MANIFEST_MEMBER]
        payload_member = members[PAYLOAD_MEMBER]

        manifest_bytes = tar.extractfile(manifest_member).read()  # type: ignore[union-attr]
        payload_bytes = tar.extractfile(payload_member).read()  # type: ignore[union-attr]

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LaunchError(f"Invalid manifest JSON: {exc}") from exc

    if not isinstance(manifest, dict):
        raise LaunchError("Manifest must be a JSON object.")

    if manifest.get("kind") != ARCHIVE_KIND:
        raise LaunchError(f"Unknown archive kind: {manifest.get('kind')!r}")

    archive_version = manifest.get("archive_version")
    if archive_version != ARCHIVE_VERSION:
        raise LaunchError(
            f"Unsupported archive version: {archive_version}."
            f" Expected {ARCHIVE_VERSION}."
        )

    declared_sha = manifest.get("payload", {}).get("sha256")
    if declared_sha:
        actual_sha = _sha256(payload_bytes).hexdigest()
        if declared_sha != actual_sha:
            raise LaunchError(
                f"Payload sha256 mismatch: manifest declares {declared_sha},"
                f" computed {actual_sha}"
            )

    archive_uuid = normalize_project_uuid(manifest.get("project", {}).get("uuid"))

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LaunchError(f"Invalid payload JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise LaunchError("Payload must be a JSON object.")

    payload_uuid = normalize_project_uuid(payload.get("project_uuid"))
    if archive_uuid != payload_uuid:
        raise LaunchError(
            "Archive manifest and payload project UUID differ:"
            f" manifest={archive_uuid}, payload={payload_uuid}"
        )

    return {
        "manifest": manifest,
        "payload": payload,
        "artifact_members": artifact_members,
    }


def import_project_archive(
    workspace_root: Path,
    *,
    source_path: Path,
    replace: bool = False,
    dry_run: bool = False,
    lock_policy: ImportLockPolicy | str = "quarantine",
    id_policy: ImportIdPolicy | str = "preserve",
) -> dict[str, object]:
    """Import a taskledger archive into the current project."""
    normalized_lock_policy = normalize_import_lock_policy(lock_policy)
    archive = read_project_archive(source_path)
    payload = cast(dict[str, object], archive["payload"])
    manifest = cast(dict[str, object], archive["manifest"])
    artifact_members = cast(list[str], archive.get("artifact_members", []))
    scope = manifest.get("scope")
    archive_scope: ArchiveScope = "ledger"
    if isinstance(scope, dict):
        kind = scope.get("kind")
        if kind == "tasks":
            archive_scope = "tasks"
    elif payload.get("archive_scope") == "tasks":
        archive_scope = "tasks"

    project = manifest.get("project")
    if not isinstance(project, dict):
        raise LaunchError("Manifest missing 'project' table.")
    archive_uuid = normalize_project_uuid(project.get("uuid"))
    project_name = project.get("name")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = payload.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = None
    project_slug = project.get("slug")
    if not isinstance(project_slug, str) or not project_slug.strip():
        project_slug = payload.get("project_slug")
    if (not isinstance(project_slug, str) or not project_slug.strip()) and isinstance(
        project_name, str
    ):
        project_slug = slugify_project_ref(project_name, empty="project")
    if not isinstance(project_slug, str) or not project_slug.strip():
        project_slug = None
    manifest_ledger_ref = project.get("ledger_ref")
    if isinstance(manifest_ledger_ref, str) and manifest_ledger_ref.strip():
        ledger_ref = manifest_ledger_ref
    else:
        ledger_ref = (
            str(payload.get("ledger_ref", "")) if isinstance(payload, dict) else ""
        )
    locator = load_project_locator(workspace_root)
    local_uuid = ensure_project_uuid(locator.config_path)
    assert_same_project_uuid(archive_uuid, local_uuid)

    counts: dict[str, object] = {}
    if isinstance(payload.get("counts"), dict):
        counts = cast(dict[str, object], payload.get("counts"))

    if dry_run:
        dry_run_result = import_project_payload(
            workspace_root,
            payload=payload,
            replace=replace,
            dry_run=True,
            lock_policy=normalized_lock_policy,
            id_policy=id_policy,
            archive_scope=archive_scope,
        )
        return {
            "kind": "taskledger_archive_import",
            "source_path": str(source_path),
            "project_uuid": archive_uuid,
            "project_name": project_name,
            "project_slug": project_slug,
            "ledger_ref": ledger_ref,
            "archive_scope": archive_scope,
            "replace": replace,
            "dry_run": True,
            "lock_policy": normalized_lock_policy,
            "counts": dry_run_result.get("counts", counts),
            "imported": dry_run_result.get("counts", counts),
            "id_policy": dry_run_result.get("id_policy"),
            "task_id_map": dry_run_result.get("task_id_map", {}),
            "renumbered": dry_run_result.get("renumbered", []),
            "imported_task_ids": dry_run_result.get("imported_task_ids", []),
            "next_command": _archive_import_next_command(dry_run_result),
        }

    result = import_project_payload(
        workspace_root,
        payload=payload,
        replace=replace,
        dry_run=False,
        lock_policy=normalized_lock_policy,
        id_policy=id_policy,
        archive_scope=archive_scope,
    )
    imported_artifacts = _extract_artifact_members(
        source_path,
        artifact_members=artifact_members,
        workspace_root=workspace_root,
        task_id_map=cast(dict[str, str], result.get("task_id_map", {})),
    )
    return {
        "kind": "taskledger_archive_import",
        "source_path": str(source_path),
        "project_uuid": archive_uuid,
        "project_name": project_name,
        "project_slug": project_slug,
        "ledger_ref": ledger_ref,
        "archive_scope": archive_scope,
        "replace": replace,
        "dry_run": False,
        "lock_policy": normalized_lock_policy,
        "counts": result.get("counts", {}),
        "imported": result.get("counts", {}),
        "id_policy": result.get("id_policy"),
        "task_id_map": result.get("task_id_map", {}),
        "renumbered": result.get("renumbered", []),
        "imported_task_ids": result.get("imported_task_ids", []),
        "ledger_next_task_number": result.get("ledger_next_task_number"),
        "imported_artifacts": imported_artifacts,
        "next_command": _archive_import_next_command(result),
    }


def normalize_import_lock_policy(value: ImportLockPolicy | str) -> ImportLockPolicy:
    if value == "drop":
        return "drop"
    if value == "keep":
        return "keep"
    if value == "quarantine":
        return "quarantine"
    raise LaunchError(
        f"Unknown lock import policy: {value!r}. "
        f"Expected one of: {', '.join(IMPORT_LOCK_POLICIES)}."
    )


def normalize_import_id_policy(value: ImportIdPolicy | str) -> ImportIdPolicy:
    if value == "preserve":
        return "preserve"
    if value == "renumber-on-conflict":
        return "renumber-on-conflict"
    if value == "fail-on-conflict":
        return "fail-on-conflict"
    raise LaunchError(
        f"Unknown import id policy: {value!r}. "
        f"Expected one of: {', '.join(IMPORT_ID_POLICIES)}."
    )


def _archive_import_next_command(result: dict[str, object]) -> str:
    imported = result.get("imported_task_ids")
    if (
        isinstance(imported, list)
        and len(imported) == 1
        and isinstance(imported[0], str)
    ):
        return f"taskledger task show {imported[0]}"
    return "taskledger next-action"


def _assert_payload_project_uuid(
    workspace_root: Path, payload: dict[str, object]
) -> None:
    raw_uuid = payload.get("project_uuid")
    if raw_uuid is None:
        return
    payload_uuid = normalize_project_uuid(raw_uuid)
    locator = load_project_locator(workspace_root)
    local_uuid = ensure_project_uuid(locator.config_path)
    assert_same_project_uuid(payload_uuid, local_uuid)


def _import_locks(
    paths: V2Paths, raw_v2: dict[str, object], *, lock_policy: ImportLockPolicy
) -> None:
    imported_locks = [
        TaskLock.from_dict(item) for item in _dict_list(raw_v2.get("locks"))
    ]
    if lock_policy == "drop":
        return
    if lock_policy == "keep":
        for lock in imported_locks:
            write_lock(task_lock_path(paths, lock.task_id), lock)
        return
    for lock in imported_locks:
        _write_imported_lock_audit(paths, lock)


def _write_imported_lock_audit(paths: V2Paths, lock: TaskLock) -> None:
    path = task_audit_dir(paths, lock.task_id) / f"imported-lock-{lock.lock_id}.yaml"
    payload = lock.to_dict()
    payload["imported_as_active"] = False
    payload["import_note"] = (
        "Lock came from a taskledger archive and was not restored as an active lock."
    )
    atomic_write_text(
        path,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )


def _build_manifest(
    *,
    project_uuid: str,
    project_name: str,
    project_slug: str,
    ledger_ref: str,
    payload_sha: str,
    payload: dict[str, object],
    include_bodies: bool,
    include_run_artifacts: bool,
    selection: ExportSelection,
) -> dict[str, object]:
    return {
        "kind": ARCHIVE_KIND,
        "archive_version": ARCHIVE_VERSION,
        "created_at": utc_now_iso(),
        "producer": {
            "name": "taskledger",
            "version": _taskledger_version(),
        },
        "project": {
            "uuid": project_uuid,
            "name": project_name,
            "slug": project_slug,
            "ledger_ref": ledger_ref,
        },
        "payload": {
            "path": PAYLOAD_MEMBER,
            "sha256": payload_sha,
            "encoding": "utf-8",
        },
        "options": {
            "include_bodies": include_bodies,
            "include_run_artifacts": include_run_artifacts,
        },
        "scope": {
            "kind": selection.scope,
            "task_ids": list(selection.task_ids),
            "default_import_id_policy": (
                "renumber-on-conflict" if selection.scope == "tasks" else "preserve"
            ),
        },
        "counts": _sanitize_counts(payload.get("counts")),
    }


def _add_json_member(
    tar: tarfile.TarFile, name: str, payload: dict[str, object]
) -> bytes:
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))
    return data


def _add_file_member(tar: tarfile.TarFile, name: str, source_path: Path) -> None:
    data = source_path.read_bytes()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def _default_archive_path(project_slug: str, ledger_ref: str) -> Path:
    ts = utc_now_iso()
    safe_ts = ts.replace(":", "").replace("-", "").replace("+00:00", "Z").split(".")[0]
    safe_ledger = slugify_project_ref(ledger_ref, empty="main")
    filename = f"taskledger-export-{project_slug}-{safe_ledger}-{safe_ts}.tar.gz"
    return Path(filename)


def _default_task_archive_path(
    project_slug: str, ledger_ref: str, task_id: str
) -> Path:
    ts = utc_now_iso()
    safe_ts = ts.replace(":", "").replace("-", "").replace("+00:00", "Z").split(".")[0]
    safe_ledger = slugify_project_ref(ledger_ref, empty="main")
    filename = (
        f"taskledger-task-{project_slug}-{safe_ledger}-{task_id}-{safe_ts}.tar.gz"
    )
    return Path(filename)


def _collect_artifact_members(
    paths: V2Paths,
    *,
    selected_task_ids: set[str] | None = None,
) -> list[tuple[str, Path]]:
    artifact_roots = [paths.tasks_dir.glob("task-*/artifacts/**/*")]
    if selected_task_ids is None:
        artifact_roots.append(
            (paths.project_dir / "agent-logs" / "artifacts").glob("**/*")
        )
    members: list[tuple[str, Path]] = []
    for iterator in artifact_roots:
        for source_path in iterator:
            if not source_path.is_file():
                continue
            if selected_task_ids is not None:
                match = re.search(
                    r"/tasks/(task-\d+)/artifacts/", source_path.as_posix()
                )
                if match is None or match.group(1) not in selected_task_ids:
                    continue
            relative = source_path.relative_to(paths.project_dir)
            archive_name = f"{ARTIFACTS_PREFIX}{relative.as_posix()}"
            members.append((archive_name, source_path))
    members.sort(key=lambda item: item[0])
    return members


def _extract_artifact_members(
    source_path: Path,
    *,
    artifact_members: list[str],
    workspace_root: Path,
    task_id_map: Mapping[str, str] | None = None,
) -> int:
    if not artifact_members:
        return 0
    paths = ensure_v2_layout(workspace_root)
    with tarfile.open(source_path, "r:gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        extracted = 0
        for member_name in artifact_members:
            if member_name not in members:
                raise LaunchError(f"Archive member not found: {member_name!r}")
            if not member_name.startswith(ARTIFACTS_PREFIX):
                raise LaunchError(f"Unexpected archive member: {member_name!r}")
            relative = Path(member_name[len(ARTIFACTS_PREFIX) :])
            if relative.is_absolute() or ".." in relative.parts:
                raise LaunchError(f"Unsafe archive member path: {member_name!r}")
            if task_id_map:
                parts = list(relative.parts)
                if "tasks" in parts:
                    idx = parts.index("tasks")
                    if idx + 1 < len(parts):
                        old_task_id = parts[idx + 1]
                        mapped_task_id = task_id_map.get(old_task_id)
                        if mapped_task_id is not None:
                            parts[idx + 1] = mapped_task_id
                            relative = Path(*parts)
            info = members[member_name]
            stream = tar.extractfile(info)
            if stream is None:
                raise LaunchError(f"Archive member {member_name!r} cannot be read")
            content = stream.read()
            destination = paths.project_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            extracted += 1
    return extracted


def _validate_archive_members(members: dict[str, tarfile.TarInfo]) -> list[str]:
    if MANIFEST_MEMBER not in members:
        raise LaunchError(f"Archive missing {MANIFEST_MEMBER}")
    if PAYLOAD_MEMBER not in members:
        raise LaunchError(f"Archive missing {PAYLOAD_MEMBER}")

    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise LaunchError(
            f"Archive contains too many members: {len(members)} > {MAX_ARCHIVE_MEMBERS}"
        )
    required = {MANIFEST_MEMBER, PAYLOAD_MEMBER}
    artifact_members: list[str] = []
    total_artifact_bytes = 0
    for name, info in members.items():
        if name.startswith("/") or ".." in Path(name).parts:
            raise LaunchError(f"Unsafe archive member path: {name!r}")
        if name in required:
            if not info.isfile():
                raise LaunchError(f"Archive member {name!r} is not a regular file")
            if name == MANIFEST_MEMBER and info.size > MAX_MANIFEST_BYTES:
                raise LaunchError(
                    "Archive manifest is too large: "
                    f"{info.size} > {MAX_MANIFEST_BYTES} bytes"
                )
            if name == PAYLOAD_MEMBER and info.size > MAX_PAYLOAD_BYTES:
                raise LaunchError(
                    "Archive payload is too large: "
                    f"{info.size} > {MAX_PAYLOAD_BYTES} bytes"
                )
            required.discard(name)
            continue
        if not name.startswith(ARTIFACTS_PREFIX):
            raise LaunchError(f"Unexpected archive member: {name!r}")
        if not info.isfile():
            raise LaunchError(f"Archive member {name!r} is not a regular file")
        if info.size > MAX_ARTIFACT_MEMBER_BYTES:
            raise LaunchError(
                "Archive artifact member is too large: "
                f"{name!r} ({info.size} > {MAX_ARTIFACT_MEMBER_BYTES} bytes)"
            )
        total_artifact_bytes += info.size
        if total_artifact_bytes > MAX_TOTAL_ARTIFACT_BYTES:
            raise LaunchError(
                "Archive artifact payload is too large: "
                f"{total_artifact_bytes} > {MAX_TOTAL_ARTIFACT_BYTES} bytes"
            )
        artifact_members.append(name)
    if required:
        raise LaunchError(f"Missing required archive members: {sorted(required)}")
    return sorted(artifact_members)


def _taskledger_version() -> str:
    from taskledger._version import __version__

    return __version__


def _sanitize_counts(raw: object) -> dict[str, object]:
    """Filter a dict to only include {str: int} entries."""
    result: dict[str, object] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, int):
                result[key] = value
    return result

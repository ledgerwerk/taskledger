from __future__ import annotations

import io
import json
import shutil
import tarfile
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
from taskledger.ids import slugify_project_ref
from taskledger.storage.agent_logs import (
    append_agent_command_log,
    load_agent_command_logs,
)
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.events import append_event, load_events
from taskledger.storage.indexes import rebuild_v2_indexes
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
    resolve_v2_paths,
    save_active_task_state,
    save_change,
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


def export_project_payload(
    workspace_root: Path,
    *,
    include_bodies: bool = False,
    include_run_artifacts: bool = False,
) -> dict[str, object]:
    v2_payload = _export_v2_payload(workspace_root, include_bodies=include_bodies)
    return {
        "kind": "taskledger_export",
        "version": 2,
        "schema_version": 2,
        "generated_at": utc_now_iso(),
        "project_dir": str(resolve_v2_paths(workspace_root).project_dir),
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
) -> dict[str, object]:
    normalized_lock_policy = normalize_import_lock_policy(lock_policy)
    _assert_payload_project_uuid(workspace_root, payload)
    raw_v2 = payload.get("v2")
    if not isinstance(raw_v2, dict):
        raise LaunchError("Import payload is missing v2 task state.")
    counts = _payload_counts(payload)
    if dry_run:
        return {
            "kind": "taskledger_import",
            "replace": replace,
            "dry_run": True,
            "lock_policy": normalized_lock_policy,
            "project_uuid": payload.get("project_uuid"),
            "project_name": payload.get("project_name"),
            "project_slug": payload.get("project_slug"),
            "ledger_ref": payload.get("ledger_ref"),
            "counts": counts,
        }
    paths = ensure_v2_layout(workspace_root)
    if replace:
        _clear_v2_state(paths)
    _import_v2_payload(
        workspace_root,
        payload,
        replace=replace,
        lock_policy=normalized_lock_policy,
    )
    rebuilt_counts = rebuild_v2_indexes(paths)
    counts = {key: value for key, value in rebuilt_counts.items()}
    return {
        "kind": "taskledger_import",
        "replace": replace,
        "dry_run": False,
        "lock_policy": normalized_lock_policy,
        "project_uuid": payload.get("project_uuid"),
        "project_name": payload.get("project_name"),
        "project_slug": payload.get("project_slug"),
        "ledger_ref": payload.get("ledger_ref"),
        "counts": counts,
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
) -> dict[str, object]:
    tasks = list_v2_tasks(workspace_root)
    introductions = list_v2_introductions(workspace_root)
    payload: dict[str, object] = {
        "tasks": [item.to_dict() for item in tasks],
        "active_task": (
            active_state.to_dict()
            if (active_state := load_active_task_state(workspace_root)) is not None
            else None
        ),
        "introductions": [item.to_dict() for item in introductions],
        "releases": [item.to_dict() for item in list_v2_releases(workspace_root)],
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
        ],
        "agent_command_logs": [
            item.to_dict() for item in load_agent_command_logs(workspace_root)
        ],
    }
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

    payload = export_project_payload(
        workspace_root,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
    )
    payload["version"] = 3
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
    )

    output_path = output_path or _default_archive_path(project_slug, paths.ledger_ref)
    if output_path.exists():
        raise LaunchError(
            f"Output file already exists: {output_path}. Use --overwrite to replace."
        )

    artifact_members = _collect_artifact_members(paths) if include_run_artifacts else []
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
        "counts": payload["counts"],
        "include_run_artifacts": include_run_artifacts,
        "filename_policy": "project-ledger-timestamp-v1",
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
) -> dict[str, object]:
    """Import a taskledger archive into the current project."""
    normalized_lock_policy = normalize_import_lock_policy(lock_policy)
    archive = read_project_archive(source_path)
    payload = cast(dict[str, object], archive["payload"])
    manifest = cast(dict[str, object], archive["manifest"])
    artifact_members = cast(list[str], archive.get("artifact_members", []))

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
        return {
            "kind": "taskledger_archive_import",
            "source_path": str(source_path),
            "project_uuid": archive_uuid,
            "project_name": project_name,
            "project_slug": project_slug,
            "ledger_ref": ledger_ref,
            "replace": replace,
            "dry_run": True,
            "lock_policy": normalized_lock_policy,
            "counts": counts,
            "imported": counts,
            "next_command": "taskledger next-action",
        }

    result = import_project_payload(
        workspace_root,
        payload=payload,
        replace=replace,
        dry_run=False,
        lock_policy=normalized_lock_policy,
    )
    imported_artifacts = _extract_artifact_members(
        source_path,
        artifact_members=artifact_members,
        workspace_root=workspace_root,
    )
    return {
        "kind": "taskledger_archive_import",
        "source_path": str(source_path),
        "project_uuid": archive_uuid,
        "project_name": project_name,
        "project_slug": project_slug,
        "ledger_ref": ledger_ref,
        "replace": replace,
        "dry_run": False,
        "lock_policy": normalized_lock_policy,
        "counts": result.get("counts", {}),
        "imported": result.get("counts", {}),
        "imported_artifacts": imported_artifacts,
        "next_command": "taskledger next-action",
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


def _collect_artifact_members(paths: V2Paths) -> list[tuple[str, Path]]:
    artifact_roots = [
        paths.tasks_dir.glob("task-*/artifacts/**/*"),
        (paths.project_dir / "agent-logs" / "artifacts").glob("**/*"),
    ]
    members: list[tuple[str, Path]] = []
    for iterator in artifact_roots:
        for source_path in iterator:
            if not source_path.is_file():
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

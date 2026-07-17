from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from taskledger.domain.policies import derive_active_stage
from taskledger.errors import LaunchError
from taskledger.exchange import (
    export_project_payload,
    import_project_archive,
    import_project_payload,
    parse_project_import_payload,
    write_project_archive,
    write_project_snapshot,
)
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.tree import TreeOptions, build_tree
from taskledger.storage.init import init_canonical_project_state, init_project_state
from taskledger.storage.ledgercore_backend import locate_taskledger_project
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.paths import load_project_locator, resolve_project_paths
from taskledger.storage.project_identity import (
    load_project_uuid,
    project_name_or_default,
)
from taskledger.storage.task_store import (
    list_changes,
    list_introductions,
    list_plans,
    list_questions,
    list_runs,
    list_tasks,
    load_active_locks,
    load_active_task_state,
    resolve_task,
)


def init_project(
    workspace_root: Path,
    *,
    taskledger_dir: Path | None = None,
    project_name: str | None = None,
    create_sibling_store: bool = False,
    data_storage: str = "external",
    external_root: str | None = "../ledger",
    local_storage_override: bool = False,
) -> dict[str, object]:
    if taskledger_dir is not None:
        locator = locate_taskledger_project(workspace_root)
        if locator is not None and locator.source == "canonical":
            raise LaunchError(
                "--taskledger-dir is a legacy layout option. Canonical projects use "
                "Ledger workspace/cache roots from .ledger/ledger.local.toml, "
                "LEDGER_WORKSPACE_ROOT, and LEDGER_CACHE_ROOT."
            )
        paths, created = init_project_state(
            workspace_root,
            taskledger_dir=taskledger_dir,
            project_name=project_name,
        )
        resolved_project_name = project_name_or_default(
            paths.config_path, workspace_root=paths.workspace_root
        )
        return {
            "kind": "taskledger_init",
            "mode": "legacy",
            "root": str(paths.project_dir),
            "project_dir": str(paths.project_dir),
            "workspace_root": str(paths.workspace_root),
            "config_path": str(paths.config_path),
            "taskledger_dir": str(paths.taskledger_dir),
            "project_name": resolved_project_name,
            "created": created,
        }
    context, created = init_canonical_project_state(
        workspace_root,
        project_name=project_name,
        create_sibling_store=create_sibling_store,
        data_storage=data_storage,
        external_root=external_root,
    )
    assert context.layout is not None
    return {
        "kind": "taskledger_init",
        "schema_version": 2,
        "mode": "canonical",
        "project_root": str(context.project_root),
        "project_uuid": context.project_uuid,
        "manifest_path": str(context.layout.manifest_path),
        "local_config_path": str(context.layout.local_config_path),
        "config_path": str(context.config_path),
        "created": created,
        "project_name": context.project_name,
        "mounts": {
            name: {
                "path": str(context.layout.mounts[name].path),
                "storage": str(context.layout.mounts[name].storage),
                "source": str(context.layout.mounts[name].source),
            }
            for name in ("data", "indexes")
        },
        "local_storage_override": local_storage_override,
    }


def _project_counts_fast(workspace_root: Path) -> dict[str, int]:
    """Fast count using file globbing instead of parsing all records."""
    paths = resolve_project_paths(workspace_root)
    ledgers_dir = paths.taskledger_dir / "ledgers"

    tasks_count = 0
    intros_count = 0
    plans_count = 0
    questions_count = 0
    runs_count = 0
    changes_count = 0

    if ledgers_dir.exists():
        for task_dir in ledgers_dir.glob("*/"):
            if task_dir.is_dir():
                tasks_count += 1
                plans_count += len(list(task_dir.glob("plans/*.yaml")))
                questions_count += len(list(task_dir.glob("questions/*.yaml")))
                runs_count += len(list(task_dir.glob("runs/*.yaml")))
                changes_count += len(list(task_dir.glob("changes/*.yaml")))

        intros_dir = ledgers_dir / "introductions"
        if intros_dir.exists():
            intros_count = len(list(intros_dir.glob("*.yaml")))

    locks_count = len(load_active_locks(workspace_root))

    return {
        "tasks": tasks_count,
        "introductions": intros_count,
        "plans": plans_count,
        "questions": questions_count,
        "runs": runs_count,
        "changes": changes_count,
        "locks": locks_count,
    }


def _storage_status_fields(workspace_root: Path) -> dict[str, object]:
    from taskledger.storage.project_context import load_project_context

    context = load_project_context(workspace_root, require_initialized=False)
    if context.mode != "canonical" or context.layout is None:
        return {}
    return {
        "workspace_provider": context.workspace_provider,
        "store_root": str(context.store_root) if context.store_root else None,
        "store_marker": (
            str(context.store_marker_path) if context.store_marker_path else None
        ),
        "binding": str(context.binding_path) if context.binding_path else None,
        "authoritative_path": str(context.paths.data_root),
        "index_path": str(context.paths.indexes_root),
        "mounts": {
            name: {
                "storage": str(mount.storage),
                "scope": str(mount.scope),
                "path": str(mount.path),
                "source": str(mount.source),
            }
            for name, mount in context.layout.mounts.items()
        },
    }


def project_status_summary(
    workspace_root: Path, *, check_health: bool = False
) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    identity = _project_identity(workspace_root)
    health: dict[str, object] = {"checked": check_health}

    if check_health:
        doctor = inspect_v2_project(workspace_root)
        health["healthy"] = bool(doctor["healthy"])
    else:
        health["healthy"] = None

    return {
        "kind": "taskledger_status",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "taskledger_dir": str(paths.taskledger_dir),
        "project_dir": str(paths.project_dir),
        "ledger_ref": identity["ledger_ref"],
        "project_uuid": identity["project_uuid"],
        "project_name": identity["project_name"],
        "counts": _project_counts_fast(workspace_root),
        "health": health,
        "active_task": _active_task_status(workspace_root),
        **_storage_status_fields(workspace_root),
    }


def project_status(workspace_root: Path) -> dict[str, object]:
    doctor = inspect_v2_project(workspace_root)
    tasks = list_tasks(workspace_root)
    locks = load_active_locks(workspace_root)
    paths = resolve_project_paths(workspace_root)
    identity = _project_identity(workspace_root)
    return {
        "kind": "taskledger_status",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "taskledger_dir": str(paths.taskledger_dir),
        "project_dir": str(paths.project_dir),
        "ledger_ref": identity["ledger_ref"],
        "project_uuid": identity["project_uuid"],
        "project_name": identity["project_name"],
        "counts": _project_counts(workspace_root),
        "healthy": bool(doctor["healthy"]),
        "active_task": _active_task_status(workspace_root),
        "errors": list(cast(list[object], doctor["errors"])),
        "warnings": list(cast(list[object], doctor["warnings"])),
        "repair_hints": list(cast(list[object], doctor["repair_hints"])),
        **_storage_status_fields(workspace_root),
        "tasks": [
            {
                "id": task.id,
                "slug": task.slug,
                "title": task.title,
                "status": task.status_stage,
                "status_stage": task.status_stage,
                "active_stage": derive_active_stage(
                    next(
                        (
                            lock
                            for lock in locks
                            if lock.task_id == task.id and not lock_is_expired(lock)
                        ),
                        None,
                    ),
                    list_runs(workspace_root, task.id),
                ),
                "accepted_plan_version": task.accepted_plan_version,
                "latest_plan_version": task.latest_plan_version,
            }
            for task in tasks
        ],
        "doctor": doctor,
    }


def project_doctor(workspace_root: Path) -> dict[str, object]:
    return inspect_v2_project(workspace_root)


def project_export(
    workspace_root: Path,
    *,
    include_bodies: bool = False,
    include_run_artifacts: bool = False,
) -> dict[str, object]:
    return export_project_payload(
        workspace_root,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
    )


def project_import(
    workspace_root: Path,
    *,
    text: str,
    format_name: str = "json",
    replace: bool = False,
    dry_run: bool = False,
    lock_policy: str = "quarantine",
) -> dict[str, object]:
    payload = parse_project_import_payload(text, format_name=format_name)
    return import_project_payload(
        workspace_root,
        payload=payload,
        replace=replace,
        dry_run=dry_run,
        lock_policy=lock_policy,
    )


def project_snapshot(
    workspace_root: Path,
    *,
    output_dir: Path,
    include_bodies: bool = False,
    include_run_artifacts: bool = False,
) -> dict[str, object]:
    return write_project_snapshot(
        workspace_root,
        output_dir=output_dir,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
    )


def project_tree(
    workspace_root: Path,
    *,
    task_ref: str | None = None,
    include_all_ledgers: bool = False,
    details: bool = False,
    include_archived: bool = False,
) -> dict[str, Any]:
    return build_tree(
        workspace_root,
        TreeOptions(
            task_ref=task_ref,
            include_all_ledgers=include_all_ledgers,
            details=details,
            include_archived=include_archived,
        ),
    )


def _project_counts(workspace_root: Path) -> dict[str, int]:
    tasks = list_tasks(workspace_root)
    return {
        "tasks": len(tasks),
        "introductions": len(list_introductions(workspace_root)),
        "plans": sum(len(list_plans(workspace_root, task.id)) for task in tasks),
        "questions": sum(
            len(list_questions(workspace_root, task.id)) for task in tasks
        ),
        "runs": sum(len(list_runs(workspace_root, task.id)) for task in tasks),
        "changes": sum(len(list_changes(workspace_root, task.id)) for task in tasks),
        "locks": len(load_active_locks(workspace_root)),
    }


def project_export_archive(
    workspace_root: Path,
    *,
    output_path: Path | None = None,
    include_bodies: bool = True,
    include_run_artifacts: bool = False,
    task_refs: Sequence[str] = (),
    overwrite: bool = False,
) -> dict[str, object]:
    """Export current-ledger state into a compressed archive file."""
    return write_project_archive(
        workspace_root,
        output_path=output_path,
        include_bodies=include_bodies,
        include_run_artifacts=include_run_artifacts,
        task_refs=task_refs,
        overwrite=overwrite,
    )


def project_import_archive(
    workspace_root: Path,
    *,
    source_path: Path,
    replace: bool = False,
    dry_run: bool = False,
    lock_policy: str = "quarantine",
    id_policy: str = "preserve",
) -> dict[str, object]:
    """Import a taskledger archive into the current project."""
    return import_project_archive(
        workspace_root,
        source_path=source_path,
        replace=replace,
        dry_run=dry_run,
        lock_policy=lock_policy,
        id_policy=id_policy,
    )


def _active_task_status(workspace_root: Path) -> dict[str, object] | None:
    state = load_active_task_state(workspace_root)
    if state is None:
        return None
    task = resolve_task(workspace_root, state.task_id)
    return {
        "task_id": task.id,
        "slug": task.slug,
        "title": task.title,
        "status_stage": task.status_stage,
    }


def _project_identity(workspace_root: Path) -> dict[str, object]:
    locator = load_project_locator(workspace_root)
    paths = resolve_project_paths(workspace_root)
    return {
        "ledger_ref": paths.project_dir.name,
        "project_uuid": load_project_uuid(locator.config_path),
        "project_name": project_name_or_default(
            locator.config_path, workspace_root=locator.workspace_root
        ),
    }


__all__ = [
    "init_project",
    "project_status_summary",
    "project_status",
    "project_doctor",
    "project_export",
    "project_import",
    "project_export_archive",
    "project_import_archive",
    "project_snapshot",
    "project_tree",
]

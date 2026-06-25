from __future__ import annotations

from pathlib import Path
from typing import cast

from taskledger.domain.states import TASKLEDGER_STORAGE_LAYOUT_VERSION
from taskledger.storage.events import load_events
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.migrations import inspect_records_for_migration
from taskledger.storage.paths import (
    load_project_locator,
    resolve_project_paths,
)
from taskledger.storage.task_store import (
    ensure_v2_layout,
    list_changes,
    list_plans,
    list_questions,
    list_runs,
    list_tasks,
    load_active_locks,
    load_active_task_state,
    resolve_run,
)


def _relative_project_path(workspace_root: Path, path: Path) -> str:
    """Convert absolute path to relative path from workspace root."""
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return path.as_posix()


def _add_diagnostic(
    diagnostics: list[dict[str, object]],
    messages: list[str],
    *,
    severity: str,
    code: str,
    message: str,
    repair_hints: list[str] | None = None,
    **fields: object,
) -> None:
    """Add a structured diagnostic entry."""
    item: dict[str, object] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    item.update({key: value for key, value in fields.items() if value is not None})
    if repair_hints:
        item["repair_hints"] = repair_hints
    diagnostics.append(item)
    messages.append(message)


def inspect_v2_project(workspace_root: Path) -> dict[str, object]:  # noqa: C901
    resolved_paths = resolve_project_paths(workspace_root)
    locator = load_project_locator(workspace_root)
    errors: list[str] = []
    warnings: list[str] = []
    repair_hints: list[str] = []
    run_lock_mismatches: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    paths = ensure_v2_layout(workspace_root)
    from taskledger.services.doctor_checks.migration_checks import scan_migration_state
    from taskledger.services.doctor_checks.project_scan import scan_project_config
    from taskledger.services.doctor_checks.task_checks import scan_task_integrity

    scan_project_config(
        workspace_root=workspace_root,
        resolved_paths=resolved_paths,
        locator=locator,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
    )

    ensure_v2_layout(workspace_root)
    tasks = list_tasks(workspace_root)
    task_map = {task.id: task for task in tasks}
    locks = load_active_locks(workspace_root)
    broken_links: list[dict[str, object]] = []
    expired_locks: list[dict[str, object]] = []

    task_runs = {task.id: list_runs(workspace_root, task.id) for task in tasks}
    run_map = {
        (task_id, run.run_id): run
        for task_id, runs in task_runs.items()
        for run in runs
    }

    try:
        active_state = load_active_task_state(workspace_root)
    except Exception as exc:
        active_state = None
        errors.append(f"Active task state is invalid: {exc}")
    if active_state is not None:
        active_task = task_map.get(active_state.task_id)
        if active_task is None:
            errors.append(f"Active task points to missing task {active_state.task_id}.")
        elif active_task.status_stage in {"cancelled", "done"}:
            warnings.append(
                f"Active task {active_task.id} is {active_task.status_stage}."
            )

    scan_task_integrity(
        workspace_root=workspace_root,
        paths=paths,
        tasks=tasks,
        task_map=task_map,
        locks=locks,
        task_runs=task_runs,
        run_map=run_map,
        active_state=active_state,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
        broken_links=broken_links,
        run_lock_mismatches=run_lock_mismatches,
        diagnostics=diagnostics,
    )

    for lock in locks:
        lock_task = task_map.get(lock.task_id)
        if lock_task is None:
            errors.append(
                f"Lock {lock.lock_id} references missing task {lock.task_id}."
            )
            continue
        try:
            if lock_is_expired(lock):
                expired_locks.append(lock.to_dict())
        except Exception as exc:
            errors.append(str(exc))
        try:
            run = resolve_run(workspace_root, lock.task_id, lock.run_id)
        except Exception:
            errors.append(
                f"Lock {lock.lock_id} references missing run {lock.run_id} "
                f"for task {lock.task_id}."
            )
            continue
        if run.status != "running":
            errors.append(
                f"Lock {lock.lock_id} references non-running run {run.run_id}."
            )
        expected_stage = {
            "planning": "planning",
            "implementation": "implementing",
            "validation": "validating",
        }[run.run_type]
        if lock.stage != expected_stage:
            errors.append(
                f"Lock {lock.lock_id} stage {lock.stage} does not match "
                f"run {run.run_id} type {run.run_type}."
            )

    scan_migration_state(
        tasks=tasks,
        paths=paths,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
    )
    for task in tasks:
        if task.status_stage != "implemented":
            continue
        impl_run = run_map.get((task.id, task.latest_implementation_run or ""))
        if (
            impl_run is None
            or impl_run.run_type != "implementation"
            or impl_run.status != "finished"
        ):
            continue
        from taskledger.services.workspace_snapshot import (
            compare_implementation_snapshot,
        )

        evaluation = compare_implementation_snapshot(workspace_root, task, impl_run)
        if not evaluation.ok:
            warnings.append(
                f"Task {task.id} is implemented but validation is blocked by "
                "implementation snapshot mismatch."
            )
            if evaluation.command_hint:
                repair_hints.append(evaluation.command_hint)
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "IMPLEMENTATION_SNAPSHOT_MISMATCH",
                    "task_id": task.id,
                    "message": evaluation.message,
                    "command_hint": evaluation.command_hint,
                    "details": evaluation.to_dict(),
                }
            )

    if broken_links:
        errors.append("V2 task records contain broken references.")
    if expired_locks:
        warnings.append("Expired task locks require explicit resolution.")
        repair_hints.append(
            "Break stale locks explicitly with "
            '`taskledger repair lock <task> --reason "..."`.'
        )

    return {
        "kind": "taskledger_doctor",
        "counts": {
            "tasks": len(tasks),
            "plans": sum(len(list_plans(workspace_root, task.id)) for task in tasks),
            "questions": sum(
                len(list_questions(workspace_root, task.id)) for task in tasks
            ),
            "runs": sum(len(task_runs[task.id]) for task in tasks),
            "changes": sum(
                len(list_changes(workspace_root, task.id)) for task in tasks
            ),
            "locks": len(locks),
            "active_task": 1 if active_state is not None else 0,
        },
        "healthy": not errors,
        "errors": errors,
        "warnings": warnings,
        "repair_hints": repair_hints,
        "broken_links": broken_links,
        "expired_locks": expired_locks,
        "run_lock_mismatches": run_lock_mismatches,
        "diagnostics": diagnostics,
    }


def inspect_v2_locks(workspace_root: Path) -> dict[str, object]:
    payload = inspect_v2_project(workspace_root)
    expired_locks = list(cast(list[object], payload["expired_locks"]))
    run_lock_mismatches = list(cast(list[object], payload["run_lock_mismatches"]))
    return {
        "kind": "taskledger_lock_inspection",
        "healthy": not expired_locks and not run_lock_mismatches,
        "expired_locks": expired_locks,
        "run_lock_mismatches": run_lock_mismatches,
    }


def inspect_v2_schema(workspace_root: Path) -> dict[str, object]:
    try:
        payload = inspect_v2_project(workspace_root)
        schema_errors = [
            item
            for item in cast(list[str], payload["errors"])
            if "schema" in item.lower() or "version" in item.lower()
        ]
    except Exception as exc:
        schema_errors = [str(exc)]
    needed, issues = inspect_records_for_migration(workspace_root)
    schema_errors.extend(issue.message for issue in issues)
    schema_errors.extend(
        (
            f"{item.object_type} record requires schema migration "
            f"{item.current_version} -> {item.target_version}: {item.path}"
        )
        for item in needed
    )
    # Check storage.yaml layout version
    try:
        from taskledger.storage.meta import read_storage_meta

        meta = read_storage_meta(workspace_root)
        if meta is None:
            schema_errors.append(
                "Missing storage.yaml."
                " Run 'taskledger init' or 'taskledger migrate apply'."
            )
        elif meta.storage_layout_version > TASKLEDGER_STORAGE_LAYOUT_VERSION:
            schema_errors.append(
                f"Storage layout {meta.storage_layout_version} is newer than "
                f"supported {TASKLEDGER_STORAGE_LAYOUT_VERSION}. Upgrade taskledger."
            )
        elif meta.storage_layout_version < TASKLEDGER_STORAGE_LAYOUT_VERSION:
            schema_errors.append(
                f"Storage layout {meta.storage_layout_version}"
                " requires migration to"
                f" {TASKLEDGER_STORAGE_LAYOUT_VERSION}."
                " Run 'taskledger migrate apply --backup'."
            )
    except Exception as exc:
        schema_errors.append(f"Cannot read storage.yaml: {exc}")

    return {
        "kind": "taskledger_schema_inspection",
        "healthy": not schema_errors,
        "errors": schema_errors,
    }


def inspect_v2_indexes(workspace_root: Path) -> dict[str, object]:
    paths = ensure_v2_layout(workspace_root)
    missing = [
        str(path.relative_to(paths.project_dir))
        for path in (
            paths.active_locks_index_path,
            paths.dependencies_index_path,
            paths.introductions_index_path,
        )
        if not path.exists()
    ]
    # Check task index staleness.

    from taskledger.storage.task_index import (
        TASK_INDEX_FILENAME,
        _read_index,
    )
    from taskledger.storage.task_store import task_markdown_path

    stale_task_entries: list[str] = []
    task_index_path = paths.indexes_dir / TASK_INDEX_FILENAME
    if task_index_path.exists():
        index_data = _read_index(paths)
        if index_data is not None:
            entries = index_data.get("entries", [])
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    task_id = entry.get("id")
                    if not isinstance(task_id, str):
                        continue
                    task_path = task_markdown_path(paths, task_id)
                    if not task_path.exists():
                        stale_task_entries.append(f"{task_id}: file missing")
                    else:
                        try:
                            stat = task_path.stat()
                            if (
                                entry.get("size") != stat.st_size
                                or entry.get("mtime_ns") != stat.st_mtime_ns
                            ):
                                stale_task_entries.append(f"{task_id}: stale")
                        except OSError:
                            stale_task_entries.append(f"{task_id}: stat error")
    else:
        missing.append(str(task_index_path.relative_to(paths.project_dir)))

    event_errors: list[str] = []
    try:
        load_events(paths.events_dir)
    except Exception as exc:
        event_errors.append(str(exc))
    healthy = not missing and not event_errors and not stale_task_entries
    return {
        "kind": "taskledger_index_inspection",
        "healthy": healthy,
        "missing_indexes": missing,
        "stale_task_entries": stale_task_entries[:20],
        "event_errors": event_errors,
    }


def cleanup_orphan_slug_dirs(workspace_root: Path) -> dict[str, object]:
    """Remove empty slug-named directories under tasks/ that have no task.md."""
    paths = ensure_v2_layout(workspace_root)
    tasks = list_tasks(workspace_root)
    task_slugs = {task.slug for task in tasks if task.slug}
    removed: list[str] = []
    for child in sorted(paths.tasks_dir.iterdir()):
        if (
            child.is_dir()
            and not child.name.startswith("task-")
            and child.name in task_slugs
            and not (child / "task.md").exists()
            and not any(child.iterdir())
        ):
            child.rmdir()
            removed.append(child.name)
    return {
        "kind": "taskledger_repair_task_dirs",
        "removed": removed,
        "count": len(removed),
    }

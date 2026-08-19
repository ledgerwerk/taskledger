from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from taskledger.domain.models import (
    ActiveTaskState,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
)
from taskledger.domain.states import TASKLEDGER_STORAGE_LAYOUT_VERSION
from taskledger.storage.events import load_events
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.migrations import inspect_records_for_migration
from taskledger.storage.paths import (
    ProjectLocator,
    ProjectPaths,
    load_project_locator,
    resolve_project_paths,
)
from taskledger.storage.task_store import (
    V2Paths,
    ensure_v2_layout,
    list_changes_from_paths,
    list_plans_from_paths,
    list_questions_from_paths,
    list_runs_from_paths,
    list_tasks,
    load_active_locks_from_paths,
    load_active_task_state,
)


@dataclass(frozen=True)
class DoctorScanContext:
    """Immutable scan context built once per doctor invocation."""

    workspace_root: Path
    resolved_paths: ProjectPaths
    paths: V2Paths
    locator: ProjectLocator  # ProjectLocator
    tasks: tuple[TaskRecord, ...]
    task_by_id: Mapping[str, TaskRecord]
    locks: tuple[TaskLock, ...]
    runs_by_task: Mapping[str, tuple[TaskRunRecord, ...]]
    run_by_key: Mapping[tuple[str, str], TaskRunRecord]
    active_state: ActiveTaskState | None


def _build_scan_context(workspace_root: Path) -> DoctorScanContext:
    """Build the immutable scan context once at the start of a doctor invocation."""
    resolved_paths = resolve_project_paths(workspace_root)
    locator = load_project_locator(workspace_root)
    paths = ensure_v2_layout(workspace_root)

    tasks = tuple(list_tasks(workspace_root))
    task_by_id: dict[str, TaskRecord] = {task.id: task for task in tasks}

    locks = tuple(load_active_locks_from_paths(paths))

    runs_by_task: dict[str, tuple[TaskRunRecord, ...]] = {}
    run_by_key: dict[tuple[str, str], TaskRunRecord] = {}
    for task in tasks:
        task_runs = tuple(list_runs_from_paths(paths, task.id))
        runs_by_task[task.id] = task_runs
        for run in task_runs:
            run_by_key[(task.id, run.run_id)] = run

    try:
        active_state = load_active_task_state(workspace_root)
    except Exception:  # noqa: BLE001
        active_state = None

    return DoctorScanContext(
        workspace_root=workspace_root,
        resolved_paths=resolved_paths,
        paths=paths,
        locator=locator,
        tasks=tasks,
        task_by_id=task_by_id,
        locks=locks,
        runs_by_task=runs_by_task,
        run_by_key=run_by_key,
        active_state=active_state,
    )


def _inspect_v2_project_phases(workspace_root: Path) -> dict[str, object]:
    ctx = _build_scan_context(workspace_root)

    errors: list[str] = []
    warnings: list[str] = []
    repair_hints: list[str] = []
    run_lock_mismatches: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    broken_links: list[dict[str, object]] = []
    expired_locks: list[dict[str, object]] = []

    from taskledger.services.doctor_checks.migration_checks import scan_migration_state
    from taskledger.services.doctor_checks.project_scan import scan_project_config
    from taskledger.services.doctor_checks.task_checks import scan_task_integrity

    scan_project_config(
        workspace_root=workspace_root,
        resolved_paths=ctx.resolved_paths,
        locator=ctx.locator,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
    )

    # Active task check
    if ctx.active_state is not None:
        active_task = ctx.task_by_id.get(ctx.active_state.task_id)
        if active_task is None:
            errors.append(
                f"Active task points to missing task {ctx.active_state.task_id}."
            )
        elif active_task.status_stage in {"cancelled", "done"}:
            warnings.append(
                f"Active task {active_task.id} is {active_task.status_stage}."
            )

    scan_task_integrity(
        workspace_root=workspace_root,
        paths=ctx.paths,
        tasks=list(ctx.tasks),
        task_map=dict(ctx.task_by_id),
        locks=list(ctx.locks),
        task_runs={tid: list(runs) for tid, runs in ctx.runs_by_task.items()},
        run_map=dict(ctx.run_by_key),
        active_state=ctx.active_state,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
        broken_links=broken_links,
        run_lock_mismatches=run_lock_mismatches,
        diagnostics=diagnostics,
    )

    for lock in ctx.locks:
        lock_task = ctx.task_by_id.get(lock.task_id)
        if lock_task is None:
            errors.append(
                f"Lock {lock.lock_id} references missing task {lock.task_id}."
            )
            continue
        try:
            if lock_is_expired(lock):
                expired_locks.append(lock.to_dict())
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        # Use pre-built run_map instead of resolve_run per task.
        run = ctx.run_by_key.get((lock.task_id, lock.run_id))
        if run is None:
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
        tasks=list(ctx.tasks),
        paths=ctx.paths,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
    )

    # Implementation snapshot comparison with one shared workspace capture.
    from taskledger.services.workspace_snapshot import (
        capture_current_workspace_state,
        compare_implementation_snapshot,
    )

    current_ws = capture_current_workspace_state(
        workspace_root,
        include_content=True,
    )
    for task in ctx.tasks:
        if task.status_stage != "implemented":
            continue
        impl_run = ctx.run_by_key.get((task.id, task.latest_implementation_run or ""))
        if (
            impl_run is None
            or impl_run.run_type != "implementation"
            or impl_run.status != "finished"
        ):
            continue

        evaluation = compare_implementation_snapshot(
            workspace_root, task, impl_run, current=current_ws
        )
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

    # Counts computed via path-bound readers to avoid repeated
    # ensure_v2_layout / load_project_context calls per task.
    total_plans = sum(
        len(list_plans_from_paths(ctx.paths, task.id)) for task in ctx.tasks
    )
    total_questions = sum(
        len(list_questions_from_paths(ctx.paths, task.id)) for task in ctx.tasks
    )
    total_runs = sum(len(runs) for runs in ctx.runs_by_task.values())
    total_changes = sum(
        len(list_changes_from_paths(ctx.paths, task.id)) for task in ctx.tasks
    )

    return {
        "kind": "taskledger_doctor",
        "counts": {
            "tasks": len(ctx.tasks),
            "plans": total_plans,
            "questions": total_questions,
            "runs": total_runs,
            "changes": total_changes,
            "locks": len(ctx.locks),
            "active_task": 1 if ctx.active_state is not None else 0,
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


def inspect_v2_project(workspace_root: Path) -> dict[str, object]:
    """Run doctor checks through the phase-based scan implementation."""
    return _inspect_v2_project_with_boundary(workspace_root)


def inspect_v2_locks(workspace_root: Path) -> dict[str, object]:
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.task_store import resolve_v2_paths

    try:
        paths = resolve_v2_paths(workspace_root)
        inventory = build_lock_inventory(paths)
    except Exception as exc:  # noqa: BLE001
        return {
            "kind": "taskledger_lock_inspection",
            "healthy": False,
            "errors": [str(exc)],
            "expired_locks": [],
            "run_lock_mismatches": [],
            "summary": {},
            "entries": [],
        }

    expired_locks: list[dict[str, object]] = []
    stale_locks: list[dict[str, object]] = []
    malformed_locks: list[dict[str, object]] = []
    unverifiable_locks: list[dict[str, object]] = []
    live_locks: list[dict[str, object]] = []
    errors: list[str] = []
    next_commands: list[str] = []

    for entry in inventory.entries:
        entry_dict = entry.to_dict()
        if entry.is_malformed:
            malformed_locks.append(entry_dict)
            errors.append(f"Malformed lock {entry.path}: {entry.parse_error}")
            continue
        classification = entry.classification
        if classification == "expired":
            expired_locks.append(entry_dict)
        elif classification in {
            "active_dead_local_process",
        }:
            stale_locks.append(entry_dict)
        elif classification in {
            "active_unverifiable_remote_or_unknown_process",
            "active_no_pid",
            "active_harness_session",
            "active_other_actor",
        }:
            unverifiable_locks.append(entry_dict)
        elif classification in {
            "active_live_local_process",
            "active_same_actor",
        }:
            live_locks.append(entry_dict)
        else:
            live_locks.append(entry_dict)

    # Collect remediation from stale/expired entries.
    for expired_or_stale in (*expired_locks, *stale_locks):
        diag = expired_or_stale.get("diagnostics", {})
        if isinstance(diag, dict):
            for cmd in diag.get("remediation", []):
                if isinstance(cmd, str) and not cmd.startswith("#"):
                    next_commands.append(cmd)

    healthy = (
        not expired_locks
        and not stale_locks
        and not malformed_locks
        and not unverifiable_locks
    )
    # Also include run_lock_mismatches from the full doctor check.
    payload = inspect_v2_project(workspace_root)
    run_lock_mismatches = list(cast(list[object], payload["run_lock_mismatches"]))

    if run_lock_mismatches:
        healthy = False

    return {
        "kind": "taskledger_lock_inspection",
        "healthy": healthy,
        "errors": errors,
        "summary": {
            "total": inventory.lock_file_count,
            "live": len(live_locks),
            "expired": len(expired_locks),
            "stale": len(stale_locks),
            "malformed": len(malformed_locks),
            "unverifiable": len(unverifiable_locks),
        },
        "live_locks": live_locks,
        "expired_locks": expired_locks,
        "stale_locks": stale_locks,
        "malformed_locks": malformed_locks,
        "unverifiable_locks": unverifiable_locks,
        "run_lock_mismatches": run_lock_mismatches,
        "next_commands": list(dict.fromkeys(next_commands)),
        "entries": [e.to_dict() for e in inventory.entries],
    }


def inspect_v2_schema(workspace_root: Path) -> dict[str, object]:
    try:
        payload = inspect_v2_project(workspace_root)
        schema_errors = [
            item
            for item in cast(list[str], payload["errors"])
            if "schema" in item.lower() or "version" in item.lower()
        ]
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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


def _inspect_v2_project_with_boundary(workspace_root: Path) -> dict[str, object]:
    from taskledger.errors import TaskledgerRegistrationMissing
    from taskledger.services.doctor_checks.project_scan import (
        scan_canonical_boundary,
    )

    try:
        return _inspect_v2_project_phases(workspace_root)
    except TaskledgerRegistrationMissing as exc:
        boundary = scan_canonical_boundary(workspace_root)
        errors = list(cast(list[object], boundary["errors"]))
        warnings = list(cast(list[object], boundary["warnings"]))
        diagnostics = list(cast(list[object], boundary["diagnostics"]))
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": exc.code,
                "message": str(exc),
                "details": dict(exc.details),
            }
        )
        return {
            "kind": "taskledger_doctor",
            "counts": {
                "tasks": 0,
                "plans": 0,
                "questions": 0,
                "runs": 0,
                "changes": 0,
                "locks": 0,
                "active_task": 0,
            },
            "healthy": False,
            "errors": errors,
            "warnings": warnings,
            "repair_hints": list(cast(list[object], boundary["repair_hints"])),
            "broken_links": [],
            "expired_locks": [],
            "run_lock_mismatches": [],
            "diagnostics": diagnostics,
        }

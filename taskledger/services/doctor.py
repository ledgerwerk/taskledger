from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from taskledger import timing as _timing
from taskledger.domain.models import (
    ActiveTaskState,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
)
from taskledger.domain.states import TASKLEDGER_STORAGE_LAYOUT_VERSION
from taskledger.errors import LaunchError
from taskledger.services.lock_inventory import LockInventory
from taskledger.storage.events import load_events
from taskledger.storage.locks import lock_is_expired
from taskledger.storage.migrations import (
    MigrationNeeded,
    inspect_records_for_migration,
)
from taskledger.storage.paths import (
    ProjectLocator,
    ProjectPaths,
    load_project_locator,
    resolve_project_paths,
)
from taskledger.storage.task_ids import (
    IncompleteTaskAllocation,
)
from taskledger.storage.task_store import (
    V2Paths,
    list_changes_from_paths,
    list_plans_from_paths,
    list_questions_from_paths,
    list_runs_from_paths,
    list_tasks,
    read_active_task_state_raw,
    require_v2_layout,
    resolve_v2_paths,
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
    active_reference: dict[str, object]
    incomplete_task_allocations: tuple[IncompleteTaskAllocation, ...]
    identity_inventory_valid: bool
    scan_errors: tuple[str, ...]
    scan_diagnostics: tuple[dict[str, object], ...]

    artifact_limit_bytes: int


def _append_identity_conflict_diagnostics(
    paths: V2Paths,
    failure: Exception,
    diagnostics: list[dict[str, object]],
) -> None:
    from taskledger.storage.task_identity import inspect_task_identity_conflicts

    try:
        conflict_groups = inspect_task_identity_conflicts(paths)
    except Exception as diagnostic_exc:  # noqa: BLE001
        diagnostics.append(
            {
                "severity": "warning",
                "code": "IDENTITY_CONFLICT_DIAGNOSTICS_INCOMPLETE",
                "phase": "task_identity_conflicts",
                "message": str(diagnostic_exc),
            }
        )
        return
    error_details = getattr(failure, "details", {})
    primary_legacy_id = (
        error_details.get("legacy_task_id") if isinstance(error_details, dict) else None
    )
    for conflict in conflict_groups:
        if (
            conflict.get("identity_kind") == "legacy_task_id"
            and conflict.get("identity") == primary_legacy_id
        ):
            continue
        identity_kind = str(conflict.get("identity_kind"))
        identity = str(conflict.get("identity"))
        diagnostics.append(
            {
                "severity": "error",
                "code": "TASKLEDGER_TASK_IDENTITY_CONFLICT",
                "phase": "task_identity_conflicts",
                "identity_kind": identity_kind,
                "identity": identity,
                "sources": conflict.get("sources", []),
                "message": f"Task identity conflict for {identity_kind} {identity!r}.",
            }
        )


def _scan_doctor_tasks(
    paths: V2Paths,
    scan_errors: list[str],
    scan_diagnostics: list[dict[str, object]],
) -> tuple[
    tuple[TaskRecord, ...],
    dict[str, TaskRecord],
    tuple[IncompleteTaskAllocation, ...],
    bool,
]:
    from taskledger.storage.task_identity import scan_task_identity_inventory
    from taskledger.storage.task_store import _load_task

    identity_inventory_valid = True
    try:
        identities = scan_task_identity_inventory(paths).entries
    except Exception as exc:  # noqa: BLE001
        scan_errors.append(str(exc))
        scan_diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "TASK_IDENTITY_SCAN_FAILED"),
                "phase": "task_identity",
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )
        _append_identity_conflict_diagnostics(paths, exc, scan_diagnostics)
        identities = None
        identity_inventory_valid = False

    candidates: list[tuple[Path, str | None, str | None]] = []
    incomplete: list[IncompleteTaskAllocation] = []
    if identities is not None:
        for identity in identities:
            source_kind: Literal["legacy_directory", "uuid_directory"] = (
                "legacy_directory"
                if identity.source_kind == "legacy_task"
                else "uuid_directory"
            )
            if identity.state == "incomplete":
                try:
                    files = tuple(
                        sorted(child.name for child in identity.path.iterdir())
                    )
                except OSError as exc:
                    files = ()
                    scan_errors.append(str(exc))
                    scan_diagnostics.append(
                        {
                            "severity": "error",
                            "code": "INCOMPLETE_ALLOCATION_READ_FAILED",
                            "phase": "task_identity",
                            "path": str(identity.path),
                            "message": str(exc),
                        }
                    )
                incomplete.append(
                    IncompleteTaskAllocation(
                        task_id=identity.task_id,
                        path=identity.path,
                        files=files,
                        source_kind=source_kind,
                        legacy_task_id=identity.legacy_task_id,
                        task_uuid=str(identity.task_uuid),
                    )
                )
            task_path = identity.path / "task.md"
            if task_path.is_file():
                candidates.append(
                    (task_path, identity.task_id, str(identity.task_uuid))
                )
    else:
        try:
            children = sorted(paths.tasks_dir.iterdir(), key=lambda child: child.name)
        except OSError as exc:
            children = []
            scan_errors.append(str(exc))
            scan_diagnostics.append(
                {
                    "severity": "error",
                    "code": "TASK_DIRECTORY_SCAN_FAILED",
                    "phase": "task_identity",
                    "path": str(paths.tasks_dir),
                    "message": str(exc),
                }
            )
        for child in children:
            try:
                if child.is_symlink() or not child.is_dir():
                    continue
                task_path = child / "task.md"
                if task_path.is_file():
                    raw_id = child.name if child.name.startswith("task-") else None
                    candidates.append((task_path, raw_id, None))
                elif child.name.startswith("task-") or (
                    len(child.name) == 36 and child.name.count("-") == 4
                ):
                    files = tuple(sorted(item.name for item in child.iterdir()))
                    if files:
                        incomplete.append(
                            IncompleteTaskAllocation(
                                task_id=child.name
                                if child.name.startswith("task-")
                                else None,
                                path=child,
                                files=files,
                                source_kind=(
                                    "legacy_directory"
                                    if child.name.startswith("task-")
                                    else "uuid_directory"
                                ),
                                legacy_task_id=(
                                    child.name
                                    if child.name.startswith("task-")
                                    else None
                                ),
                                task_uuid=(
                                    child.name
                                    if len(child.name) == 36
                                    and child.name.count("-") == 4
                                    else None
                                ),
                            )
                        )
            except OSError as exc:
                scan_errors.append(str(exc))
                scan_diagnostics.append(
                    {
                        "severity": "error",
                        "code": "TASK_BUNDLE_SCAN_FAILED",
                        "phase": "task_identity",
                        "path": str(child),
                        "message": str(exc),
                    }
                )

    tasks_list: list[TaskRecord] = []
    for task_path, task_id, task_uuid in candidates:
        try:
            task = _load_task(
                task_path,
                paths=paths if identities is not None else None,
                task_id=task_id,
                task_uuid=task_uuid,
            )
        except Exception as exc:  # noqa: BLE001
            scan_errors.append(str(exc))
            scan_diagnostics.append(
                {
                    "severity": "error",
                    "code": getattr(exc, "code", "TASK_RELATION_UNRESOLVED"),
                    "phase": "task_record",
                    "path": str(task_path),
                    "task_id": task_id,
                    "message": str(exc),
                    "details": getattr(exc, "details", {}),
                }
            )
            try:
                task = _load_task(task_path, task_id=task_id, task_uuid=task_uuid)
            except Exception as raw_exc:  # noqa: BLE001
                scan_errors.append(str(raw_exc))
                scan_diagnostics.append(
                    {
                        "severity": "error",
                        "code": getattr(raw_exc, "code", "TASK_RECORD_UNREADABLE"),
                        "phase": "task_record",
                        "path": str(task_path),
                        "task_id": task_id,
                        "message": str(raw_exc),
                    }
                )
                continue
        tasks_list.append(task)

    id_counts: dict[str, int] = {}
    for task in tasks_list:
        id_counts[task.id] = id_counts.get(task.id, 0) + 1
    for task_id, count in id_counts.items():
        if count > 1:
            message = f"Multiple task records share display ID {task_id}."
            scan_errors.append(message)
            scan_diagnostics.append(
                {
                    "severity": "error",
                    "code": "TASK_DISPLAY_ID_COLLISION",
                    "phase": "task_identity",
                    "task_id": task_id,
                    "message": message,
                }
            )
    tasks = tuple(tasks_list)
    task_by_id = {task.id: task for task in tasks if id_counts[task.id] == 1}
    return tasks, task_by_id, tuple(incomplete), identity_inventory_valid


def _build_scan_context(workspace_root: Path) -> DoctorScanContext:
    """Build a best-effort, read-only scan context for one doctor invocation."""
    from taskledger.services.active_task_recovery import inspect_active_task_reference
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.artifact_policy import ABSOLUTE_MAX_ARTIFACT_BYTES
    from taskledger.storage.project_config import (
        load_project_config_document,
        merge_project_config,
    )

    resolved_paths = resolve_project_paths(workspace_root)
    locator = load_project_locator(workspace_root)
    paths = resolve_v2_paths(workspace_root)
    scan_errors: list[str] = []
    scan_diagnostics: list[dict[str, object]] = []
    (
        tasks,
        task_by_id,
        incomplete_task_allocations,
        identity_inventory_valid,
    ) = _scan_doctor_tasks(paths, scan_errors, scan_diagnostics)
    if not identity_inventory_valid:
        scan_diagnostics.append(
            {
                "severity": "warning",
                "code": "IDENTITY_DEPENDENT_SCANS_SKIPPED",
                "counts_complete": False,
                "skipped_scans": [
                    "task_plans",
                    "task_questions",
                    "task_changes",
                    "task_runs",
                    "task_relationships",
                ],
                "phase": "identity_dependent_scans",
                "message": (
                    "Task plan, question, change, run, and relationship scans were "
                    "skipped because the task identity inventory is invalid."
                ),
            }
        )

    try:
        lock_inventory = build_lock_inventory(paths)
        locks = tuple(
            entry.lock for entry in lock_inventory.entries if entry.lock is not None
        )
        for entry in lock_inventory.entries:
            if entry.is_malformed:
                message = entry.parse_error or f"Malformed lock {entry.path}."
                scan_errors.append(message)
                scan_diagnostics.append(
                    {
                        "severity": "error",
                        "code": "MALFORMED_LOCK",
                        "phase": "lock_inventory",
                        "path": str(entry.path),
                        "message": message,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        locks = ()
        scan_errors.append(str(exc))
        scan_diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "LOCK_INVENTORY_FAILED"),
                "phase": "lock_inventory",
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )

    runs_by_task: dict[str, tuple[TaskRunRecord, ...]] = {}
    run_by_key: dict[tuple[str, str], TaskRunRecord] = {}

    for task in tasks if identity_inventory_valid else ():
        if task.id not in task_by_id:
            continue
        try:
            task_runs = tuple(list_runs_from_paths(paths, task.task_uuid or task.id))
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            scan_errors.append(message)
            scan_diagnostics.append(
                {
                    "severity": "error",
                    "code": getattr(exc, "code", "TASK_RUN_SCAN_FAILED"),
                    "phase": "run_inventory",
                    "task_id": task.id,
                    "message": message,
                }
            )
            continue
        runs_by_task[task.id] = task_runs
        for run in task_runs:
            run_by_key[(task.id, run.run_id)] = run

    active_reference = inspect_active_task_reference(paths)
    try:
        active_state = read_active_task_state_raw(paths)
    except Exception:  # noqa: BLE001
        active_state = None
    active_classification = active_reference.get("classification")
    if active_classification in {
        "missing",
        "ambiguous",
        "resolution_blocked",
        "malformed",
    }:
        code = (
            "ACTIVE_TASK_REFERENCE_MISSING"
            if active_classification == "missing"
            else "ACTIVE_TASK_STATE_MALFORMED"
            if active_classification == "malformed"
            else "ACTIVE_TASK_REFERENCE_UNRESOLVED"
        )
        active_message = active_reference.get("message")
        if isinstance(active_message, str):
            diagnostic_message = active_message
        elif active_classification == "missing":
            diagnostic_message = (
                f"Active task points to missing task {active_reference.get('task_id')}."
            )
        else:
            diagnostic_message = (
                "Active-task reference cannot be resolved safely: "
                f"{active_classification}."
            )
        scan_errors.append(diagnostic_message)
        scan_diagnostics.append(
            {
                "severity": "error",
                "code": code,
                "phase": "active_task_reference",
                "path": str(paths.active_task_path),
                "task_id": active_reference.get("task_id"),
                "task_uuid": active_reference.get("task_uuid"),
                "proof_summary": active_reference.get("proof_summary"),
                "candidates": active_reference.get("candidates", []),
                "protected": active_reference.get("protected", False),
                "protection_blockers": active_reference.get("protection_blockers", []),
                "message": diagnostic_message,
            }
        )
    try:
        artifact_limit_bytes = merge_project_config(
            load_project_config_document(resolved_paths.config_path)
        ).artifact_max_bytes
    except Exception as exc:  # noqa: BLE001
        artifact_limit_bytes = ABSOLUTE_MAX_ARTIFACT_BYTES
        scan_errors.append(str(exc))
        scan_diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "PROJECT_CONFIG_UNREADABLE"),
                "phase": "project_config",
                "path": str(resolved_paths.config_path),
                "message": str(exc),
            }
        )

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
        active_reference=active_reference,
        incomplete_task_allocations=incomplete_task_allocations,
        identity_inventory_valid=identity_inventory_valid,
        scan_errors=tuple(scan_errors),
        scan_diagnostics=tuple(scan_diagnostics),
        artifact_limit_bytes=artifact_limit_bytes,
    )


def _inspect_implementation_snapshots(
    workspace_root: Path,
    ctx: DoctorScanContext,
    warnings: list[str],
    repair_hints: list[str],
    diagnostics: list[dict[str, object]],
) -> None:
    from taskledger.services.workspace_snapshot import (
        capture_current_workspace_state,
        compare_implementation_snapshot,
    )

    candidates: list[tuple[TaskRecord, TaskRunRecord]] = []
    for task in ctx.tasks:
        if task.status_stage != "implemented":
            continue
        run = ctx.run_by_key.get((task.id, task.latest_implementation_run or ""))
        if (
            run is not None
            and run.run_type == "implementation"
            and run.status == "finished"
        ):
            candidates.append((task, run))
    if not candidates:
        return

    current_workspace = capture_current_workspace_state(
        workspace_root, include_content=True
    )
    for task, run in candidates:
        evaluation = compare_implementation_snapshot(
            workspace_root, task, run, current=current_workspace
        )
        if evaluation.ok:
            continue
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


def _count_task_records_readonly(
    paths: V2Paths,
    tasks: tuple[TaskRecord, ...],
    loader: Callable[[V2Paths, str], Sequence[object]],
    *,
    record_name: str,
    errors: list[str],
    diagnostics: list[dict[str, object]],
) -> int:
    total = 0
    for task in tasks:
        task_ref = task.task_uuid or task.id
        try:
            total += len(loader(paths, task_ref))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Unable to inspect {record_name} for {task.id}: {exc}")
            diagnostics.append(
                {
                    "severity": "error",
                    "code": f"{record_name.upper()}_SCAN_FAILED",
                    "phase": f"{record_name}_inventory",
                    "task_id": task.id,
                    "message": str(exc),
                }
            )
    return total


def _inspect_active_task(
    ctx: DoctorScanContext, errors: list[str], warnings: list[str]
) -> None:
    if ctx.active_state is None:
        return
    if ctx.active_reference.get("classification") != "valid":
        return
    if not ctx.identity_inventory_valid:
        return
    active_task = ctx.task_by_id.get(ctx.active_state.task_id)
    if active_task is None:
        errors.append(f"Active task points to missing task {ctx.active_state.task_id}.")
    elif active_task.status_stage in {"cancelled", "done"}:
        warnings.append(f"Active task {active_task.id} is {active_task.status_stage}.")


def _inspect_task_integrity(
    workspace_root: Path,
    ctx: DoctorScanContext,
    *,
    errors: list[str],
    warnings: list[str],
    repair_hints: list[str],
    broken_links: list[dict[str, object]],
    run_lock_mismatches: list[dict[str, object]],
    diagnostics: list[dict[str, object]],
) -> None:
    if not ctx.identity_inventory_valid:
        return
    from taskledger.services.doctor_checks.task_checks import scan_task_integrity

    try:
        with _timing.stage("task_integrity"):
            scan_task_integrity(
                workspace_root=workspace_root,
                paths=ctx.paths,
                tasks=list(ctx.tasks),
                task_map=dict(ctx.task_by_id),
                locks=list(ctx.locks),
                task_runs={
                    task_id: list(runs) for task_id, runs in ctx.runs_by_task.items()
                },
                run_map=dict(ctx.run_by_key),
                active_state=ctx.active_state,
                errors=errors,
                warnings=warnings,
                repair_hints=repair_hints,
                broken_links=broken_links,
                run_lock_mismatches=run_lock_mismatches,
                diagnostics=diagnostics,
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "TASK_INTEGRITY_SCAN_FAILED"),
                "phase": "task_integrity",
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )


def _inspect_lock_consistency(
    ctx: DoctorScanContext,
    *,
    errors: list[str],
    expired_locks: list[dict[str, object]],
) -> None:
    with _timing.stage("lock_consistency"):
        for lock in ctx.locks:
            try:
                if lock_is_expired(lock):
                    expired_locks.append(lock.to_dict())
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
            if not ctx.identity_inventory_valid:
                continue
            lock_task = ctx.task_by_id.get(lock.task_id)
            if lock_task is None:
                errors.append(
                    f"Lock {lock.lock_id} references missing task {lock.task_id}."
                )
                continue
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


def _count_identity_dependent_records(
    ctx: DoctorScanContext,
    *,
    errors: list[str],
    diagnostics: list[dict[str, object]],
) -> tuple[int, int, int, int]:
    tasks = ctx.tasks if ctx.identity_inventory_valid else ()
    total_plans = _count_task_records_readonly(
        ctx.paths,
        tasks,
        list_plans_from_paths,
        record_name="plans",
        errors=errors,
        diagnostics=diagnostics,
    )
    total_questions = _count_task_records_readonly(
        ctx.paths,
        tasks,
        list_questions_from_paths,
        record_name="questions",
        errors=errors,
        diagnostics=diagnostics,
    )
    total_changes = _count_task_records_readonly(
        ctx.paths,
        tasks,
        list_changes_from_paths,
        record_name="changes",
        errors=errors,
        diagnostics=diagnostics,
    )
    total_runs = sum(len(runs) for runs in ctx.runs_by_task.values())
    return total_plans, total_questions, total_runs, total_changes


def _inspect_v2_project_phases(workspace_root: Path) -> dict[str, object]:
    with _timing.stage("scan_context"):
        ctx = _build_scan_context(workspace_root)

    errors: list[str] = list(ctx.scan_errors)
    warnings: list[str] = []
    repair_hints: list[str] = []
    run_lock_mismatches: list[dict[str, object]] = []
    diagnostics = list(ctx.scan_diagnostics)
    broken_links: list[dict[str, object]] = []
    expired_locks: list[dict[str, object]] = []

    from taskledger.services.doctor_checks.migration_checks import scan_migration_state
    from taskledger.services.doctor_checks.project_scan import scan_project_config

    try:
        with _timing.stage("project_config"):
            scan_project_config(
                workspace_root=workspace_root,
                resolved_paths=ctx.resolved_paths,
                locator=ctx.locator,
                errors=errors,
                warnings=warnings,
                repair_hints=repair_hints,
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "PROJECT_CONFIG_SCAN_FAILED"),
                "phase": "project_config",
                "message": str(exc),
            }
        )

    for allocation in ctx.incomplete_task_allocations:
        allocation_id = (
            allocation.legacy_task_id or allocation.task_uuid or allocation.path.name
        )
        message = f"Incomplete task allocation {allocation_id} is missing task.md."
        errors.append(message)
        diagnostics.append(
            {
                "severity": "error",
                "code": "INCOMPLETE_TASK_ALLOCATION",
                "message": message,
                "task_id": allocation.display_task_id,
                "legacy_task_id": allocation.legacy_task_id,
                "task_uuid": allocation.task_uuid,
                "path": str(allocation.path),
                "files": list(allocation.files),
            }
        )
    if ctx.incomplete_task_allocations:
        repair_hints.append(
            "Review one coordinated plan with "
            "`taskledger --json repair allocations --all`; "
            "apply only if every selected source is safe and matches the reviewed plan."
        )
    identity_conflicts_present = any(
        item.get("code") == "TASKLEDGER_TASK_IDENTITY_CONFLICT" for item in diagnostics
    )
    if identity_conflicts_present:
        repair_hints.append(
            "Review authoritative identity conflicts with "
            "`taskledger repair allocations --conflicts`."
        )
        try:
            from taskledger.services.allocation_recovery import (
                plan_identity_conflict_recovery,
            )

            conflict_plan = plan_identity_conflict_recovery(
                resolve_v2_paths(workspace_root)
            )
            actions = conflict_plan.get("actions", [])
        except Exception:  # noqa: BLE001
            actions = []
        if (
            isinstance(actions, list)
            and actions
            and any(
                isinstance(action, dict)
                and action.get("repair_mode") == "retire_shadowing_tombstone"
                and action.get("requires_operator_override") is True
                for action in actions
            )
            and all(
                isinstance(action, dict)
                and (
                    action.get("apply_safe") is True
                    or (
                        action.get("repair_mode") == "retire_shadowing_tombstone"
                        and action.get("requires_operator_override") is True
                    )
                )
                for action in actions
            )
        ):
            repair_hints.append(
                "If you explicitly accept the unverifiable tombstone risk, review the "
                "override plan with `taskledger repair allocations --conflicts "
                "--allow-unverifiable`."
            )
    _inspect_active_task(ctx, errors, warnings)
    if ctx.active_reference.get("classification") == "missing":
        repair_hints.append(
            "Review the raw active-task pointer with "
            "`taskledger --json repair active-task --action clear`; "
            "apply only the fresh safe plan."
        )
    elif ctx.active_reference.get("classification") in {
        "ambiguous",
        "resolution_blocked",
    }:
        repair_hints.append(
            "Inspect candidates with `taskledger --json repair active-task`; "
            "do not guess a replacement UUID."
        )
    _inspect_task_integrity(
        workspace_root,
        ctx,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
        broken_links=broken_links,
        run_lock_mismatches=run_lock_mismatches,
        diagnostics=diagnostics,
    )

    from taskledger.services.doctor_checks.artifact_checks import (
        find_oversized_artifacts,
    )

    try:
        with _timing.stage("artifact_policy"):
            for diagnostic in find_oversized_artifacts(
                ctx.paths, max_bytes=ctx.artifact_limit_bytes
            ):
                diagnostics.append(diagnostic)
                errors.append(str(diagnostic["message"]))
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "ARTIFACT_SCAN_FAILED"),
                "phase": "artifact_policy",
                "message": str(exc),
            }
        )
    _inspect_lock_consistency(ctx, errors=errors, expired_locks=expired_locks)
    try:
        with _timing.stage("migration_state"):
            scan_migration_state(
                tasks=list(ctx.tasks),
                paths=ctx.paths,
                errors=errors,
                warnings=warnings,
                repair_hints=repair_hints,
            )
    except Exception as exc:  # noqa: BLE001
        if ctx.identity_inventory_valid or str(exc) not in errors:
            errors.append(str(exc))
            diagnostics.append(
                {
                    "severity": "error",
                    "code": getattr(exc, "code", "MIGRATION_SCAN_FAILED"),
                    "phase": "migration_state",
                    "message": str(exc),
                }
            )

    try:
        with _timing.stage("workspace_snapshot"):
            _inspect_implementation_snapshots(
                workspace_root, ctx, warnings, repair_hints, diagnostics
            )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Unable to inspect implementation snapshots: {exc}")
        diagnostics.append(
            {
                "severity": "warning",
                "code": "IMPLEMENTATION_SNAPSHOT_SCAN_FAILED",
                "phase": "workspace_snapshot",
                "message": str(exc),
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

    (
        total_plans,
        total_questions,
        total_runs,
        total_changes,
    ) = _count_identity_dependent_records(
        ctx,
        errors=errors,
        diagnostics=diagnostics,
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
        "counts_complete": ctx.identity_inventory_valid,
        "skipped_scans": (
            []
            if ctx.identity_inventory_valid
            else [
                "task_plans",
                "task_questions",
                "task_changes",
                "task_runs",
                "task_relationships",
            ]
        ),
        "active_task_reference": ctx.active_reference,
        "healthy": not errors,
        "errors": errors,
        "warnings": warnings,
        "repair_hints": repair_hints,
        "broken_links": broken_links,
        "expired_locks": expired_locks,
        "run_lock_mismatches": run_lock_mismatches,
        "incomplete_task_allocations": [
            {
                "task_id": allocation.task_id,
                "path": str(allocation.path),
                "files": list(allocation.files),
            }
            for allocation in ctx.incomplete_task_allocations
        ],
        "diagnostics": diagnostics,
    }


def inspect_v2_project(workspace_root: Path) -> dict[str, object]:
    """Run doctor checks through the phase-based scan implementation."""
    return _inspect_v2_project_with_boundary(workspace_root)


def _run_lock_mismatches(
    paths: V2Paths, inventory: LockInventory
) -> tuple[list[dict[str, object]], list[str]]:
    from taskledger.domain.policies import derive_active_stage
    from taskledger.storage.common import try_load_json_object
    from taskledger.storage.sidecar_index import SIDECAR_INDEX_FILENAME
    from taskledger.storage.task_index import (
        TaskSummaryRecord,
        _read_index,
    )
    from taskledger.storage.task_store import list_runs_from_paths

    errors: list[str] = []
    task_summaries: dict[str, TaskSummaryRecord] = {}
    task_index = _read_index(paths)
    task_entries = task_index.get("entries") if task_index is not None else None
    if isinstance(task_entries, list):
        for raw in task_entries:
            if isinstance(raw, dict):
                try:
                    summary = TaskSummaryRecord.from_dict(raw)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Invalid task index entry: {exc}")
                    continue
                task_summaries[summary.task_uuid or summary.id] = summary

    sidecar_data = try_load_json_object(
        paths.indexes_dir / SIDECAR_INDEX_FILENAME, "sidecar index"
    )
    raw_sidecars = sidecar_data.get("entries") if sidecar_data is not None else None
    sidecars = (
        {key: value for key, value in raw_sidecars.items() if isinstance(value, dict)}
        if isinstance(raw_sidecars, dict)
        else {}
    )
    active_locks = {
        entry.lock.task_uuid or entry.lock.task_id: entry.lock
        for entry in inventory.entries
        if entry.lock is not None and not lock_is_expired(entry.lock)
    }
    candidate_task_ids = set(active_locks)
    for task_id, sidecar in sidecars.items():
        runs = sidecar.get("runs")
        running = runs.get("running") if isinstance(runs, dict) else None
        if isinstance(running, list) and running:
            candidate_task_ids.add(task_id)

    try:
        task_directories = sorted(paths.tasks_dir.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        task_directories = []
        errors.append(f"Unable to enumerate task bundles for lock inspection: {exc}")
    for task_directory in task_directories:
        runs_directory = task_directory / "runs"
        if (
            not task_directory.is_symlink()
            and task_directory.is_dir()
            and (
                task_directory.name.startswith("task-")
                or (
                    len(task_directory.name) == 36
                    and task_directory.name.count("-") == 4
                )
            )
            and not runs_directory.is_symlink()
            and runs_directory.is_dir()
        ):
            candidate_task_ids.add(task_directory.name)
    mismatches: list[dict[str, object]] = []
    for task_ref in sorted(candidate_task_ids):
        task = task_summaries.get(task_ref)
        task_id = task.id if task is not None else task_ref
        try:
            runs = list_runs_from_paths(paths, task_ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Unable to inspect runs for {task_id}: {exc}")
            continue
        running_runs = [run for run in runs if run.status == "running"]
        lock = active_locks.get(task_ref)
        active_stage = derive_active_stage(lock, running_runs)
        if running_runs and active_stage is None:
            errors.append(
                f"Task {task_id} has a running run without a matching active lock."
            )
            task = task_summaries.get(task_ref)
            for run in running_runs:
                next_command = f"taskledger task show --task {task_id}"
                note = "Inspect task and run state before choosing repair."
                if run.run_type == "planning":
                    next_command = (
                        "taskledger repair run "
                        f"--task {task_id} --run {run.run_id} "
                        '--reason "Finish orphaned planning run."'
                    )
                    note = "Planning run can be explicitly finished with repair run."
                elif run.run_type == "implementation":
                    if (
                        task is not None
                        and run.run_id == task.latest_implementation_run
                        and task.status_stage
                        in {"approved", "implementing", "failed_validation"}
                    ):
                        next_command = (
                            "taskledger implement resume "
                            f"--task {task_id} --run {run.run_id} "
                            '--reason "Reacquire implementation lock."'
                        )
                        note = (
                            "Reacquire the missing implementation lock for this "
                            "running run."
                        )
                    else:
                        next_command = "taskledger doctor locks"
                        note = (
                            "Historical or non-resumable implementation run. "
                            "Inspect run state before repair."
                        )
                mismatches.append(
                    {
                        "kind": "running_run_without_matching_lock",
                        "task_id": task_id,
                        "run_id": run.run_id,
                        "run_type": run.run_type,
                        "status": run.status,
                        "next_command": next_command,
                        "note": note,
                    }
                )
        elif lock is not None and active_stage is None:
            errors.append(
                f"Task {task_id} has a {lock.stage} lock without a running run."
            )
            mismatches.append(
                {
                    "kind": "lock_without_running_run",
                    "task_id": task_id,
                    "lock_id": lock.lock_id,
                    "run_id": lock.run_id,
                    "run_type": lock.run_type,
                    "next_command": f"taskledger lock show --task {task_id}",
                }
            )
    return mismatches, errors


def inspect_v2_locks(workspace_root: Path) -> dict[str, object]:
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.task_store import resolve_v2_paths

    errors: list[str] = []
    diagnostics: list[dict[str, object]] = []
    try:
        paths = resolve_v2_paths(workspace_root)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        diagnostic = {
            "severity": "error",
            "code": getattr(exc, "code", "LOCK_PATH_RESOLUTION_FAILED"),
            "phase": "lock_inventory",
            "message": message,
            "details": getattr(exc, "details", {}),
        }
        return {
            "kind": "taskledger_lock_inspection",
            "healthy": False,
            "errors": [message],
            "expired_locks": [],
            "run_lock_mismatches": [],
            "summary": {},
            "entries": [],
            "diagnostics": [diagnostic],
        }

    from taskledger.storage.task_identity import scan_task_identity_inventory

    try:
        scan_task_identity_inventory(paths)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "TASK_IDENTITY_SCAN_FAILED"),
                "phase": "task_identity",
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )
    try:
        inventory = build_lock_inventory(paths)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "LOCK_INVENTORY_FAILED"),
                "phase": "lock_inventory",
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )
        return {
            "kind": "taskledger_lock_inspection",
            "healthy": False,
            "errors": errors,
            "expired_locks": [],
            "run_lock_mismatches": [],
            "summary": {},
            "entries": [],
            "diagnostics": diagnostics,
        }

    expired_locks: list[dict[str, object]] = []
    stale_locks: list[dict[str, object]] = []
    malformed_locks: list[dict[str, object]] = []
    unverifiable_locks: list[dict[str, object]] = []
    live_locks: list[dict[str, object]] = []
    next_commands: list[str] = []

    for entry in inventory.entries:
        entry_dict = entry.to_dict()
        if entry.is_malformed:
            malformed_locks.append(entry_dict)
            errors.append(f"Malformed lock {entry.path}: {entry.parse_error}")
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "MALFORMED_LOCK",
                    "phase": "lock_inventory",
                    "path": str(entry.path),
                    "message": entry.parse_error or "Malformed lock record.",
                }
            )
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

    try:
        run_lock_mismatches, mismatch_errors = _run_lock_mismatches(paths, inventory)
        errors.extend(mismatch_errors)
    except Exception as exc:  # noqa: BLE001
        run_lock_mismatches = []
        errors.append(str(exc))
        diagnostics.append(
            {
                "severity": "error",
                "code": getattr(exc, "code", "RUN_LOCK_SCAN_FAILED"),
                "phase": "run_lock_consistency",
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
        )
    for mismatch in run_lock_mismatches:
        command = mismatch.get("next_command")
        if isinstance(command, str):
            next_commands.append(command)
    healthy = (
        not expired_locks
        and not stale_locks
        and not malformed_locks
        and not unverifiable_locks
        and not run_lock_mismatches
        and not errors
    )

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
        "diagnostics": diagnostics,
    }


def inspect_v2_schema(workspace_root: Path) -> dict[str, object]:
    project_diagnostics: list[dict[str, object]] = []
    try:
        payload = inspect_v2_project(workspace_root)
        raw_diagnostics = payload.get("diagnostics", [])
        if isinstance(raw_diagnostics, list):
            project_diagnostics = [
                item for item in raw_diagnostics if isinstance(item, dict)
            ]
        schema_errors = [
            item
            for item in cast(list[str], payload["errors"])
            if "schema" in item.lower() or "version" in item.lower()
        ]
        for diagnostic in project_diagnostics:
            code = str(diagnostic.get("code", "")).upper()
            if diagnostic.get("severity") == "error" and (
                "IDENTITY" in code or "RELATION" in code or "AMBIGUOUS" in code
            ):
                message = diagnostic.get("message")
                if isinstance(message, str):
                    schema_errors.append(message)
    except Exception as exc:  # noqa: BLE001
        schema_errors = [str(exc)]
        project_diagnostics = [
            {
                "severity": "error",
                "code": getattr(exc, "code", "SCHEMA_PROJECT_SCAN_FAILED"),
                "message": str(exc),
            }
        ]
    needed: list[MigrationNeeded] = []
    try:
        needed, issues = inspect_records_for_migration(workspace_root)
        schema_errors.extend(issue.message for issue in issues)
    except Exception as exc:  # noqa: BLE001
        schema_errors.append(f"Unable to inspect schema records: {exc}")
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
        "diagnostics": project_diagnostics
        + [
            {"severity": "error", "code": "SCHEMA_CHECK_FAILED", "message": error}
            for error in schema_errors
        ],
    }


def _inspect_v2_indexes_readonly(workspace_root: Path) -> dict[str, object]:
    paths = require_v2_layout(workspace_root)
    from taskledger.storage.indexes import index_is_dirty
    from taskledger.storage.sidecar_index import SIDECAR_INDEX_FILENAME

    dirty_indexes = [
        name
        for name, dirty in (
            ("task_index", index_is_dirty(paths, "task_index")),
            ("sidecar_index", index_is_dirty(paths, "sidecar_index")),
            ("dependencies", index_is_dirty(paths, "dependencies")),
            ("introductions", index_is_dirty(paths, "introductions")),
            ("active_locks", index_is_dirty(paths, "active_locks")),
        )
        if dirty
    ]
    missing = [
        str(path.relative_to(paths.project_dir))
        for path in (
            paths.active_locks_index_path,
            paths.dependencies_index_path,
            paths.introductions_index_path,
            paths.indexes_dir / SIDECAR_INDEX_FILENAME,
        )
        if not path.exists()
    ]
    # Check task index staleness.

    from taskledger.storage.task_index import (
        TASK_INDEX_FILENAME,
        _read_index,
    )

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
                    task_label = task_id if isinstance(task_id, str) else "?"
                    raw_path = entry.get("path")
                    if not isinstance(raw_path, str):
                        stale_task_entries.append(f"{task_label}: path missing")
                        continue
                    task_path = (paths.ledger_dir / raw_path).resolve()
                    if task_path.name != "task.md" or not task_path.is_relative_to(
                        paths.tasks_dir.resolve()
                    ):
                        stale_task_entries.append(f"{task_label}: invalid task path")
                    elif not task_path.is_file():
                        stale_task_entries.append(f"{task_label}: file missing")
                    else:
                        try:
                            stat = task_path.stat()
                            if (
                                entry.get("size") != stat.st_size
                                or entry.get("mtime_ns") != stat.st_mtime_ns
                            ):
                                stale_task_entries.append(f"{task_label}: stale")
                        except OSError:
                            stale_task_entries.append(f"{task_label}: stat error")
    else:
        missing.append(str(task_index_path.relative_to(paths.project_dir)))

    event_errors: list[str] = []
    try:
        load_events(paths.events_dir)
    except Exception as exc:  # noqa: BLE001
        event_errors.append(str(exc))
    healthy = (
        not missing
        and not event_errors
        and not stale_task_entries
        and not dirty_indexes
    )
    diagnostics = [
        {
            "severity": "warning",
            "code": "INDEX_MISSING",
            "phase": "index_inspection",
            "path": path,
            "message": f"Derived index is missing: {path}.",
        }
        for path in missing
    ]
    diagnostics.extend(
        {
            "severity": "warning",
            "code": "INDEX_DIRTY",
            "phase": "index_inspection",
            "index": name,
            "message": f"Derived index is marked dirty: {name}.",
        }
        for name in dirty_indexes
    )
    diagnostics.extend(
        {
            "severity": "warning",
            "code": "STALE_TASK_INDEX_ENTRY",
            "phase": "index_inspection",
            "message": message,
        }
        for message in stale_task_entries
    )
    diagnostics.extend(
        {
            "severity": "error",
            "code": "EVENT_LOG_READ_FAILED",
            "phase": "event_log",
            "message": message,
        }
        for message in event_errors
    )
    return {
        "kind": "taskledger_index_inspection",
        "healthy": healthy,
        "missing_indexes": missing,
        "dirty_indexes": dirty_indexes,
        "stale_task_entries": stale_task_entries[:20],
        "event_errors": event_errors,
        "errors": list(event_errors),
        "diagnostics": diagnostics,
    }


def inspect_v2_indexes(workspace_root: Path) -> dict[str, object]:
    """Inspect derived indexes without rebuilding or changing any index state."""
    try:
        return _inspect_v2_indexes_readonly(workspace_root)
    except Exception as exc:  # noqa: BLE001
        diagnostic = {
            "severity": "error",
            "code": getattr(exc, "code", "INDEX_INSPECTION_FAILED"),
            "phase": "index_inspection",
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
        return {
            "kind": "taskledger_index_inspection",
            "healthy": False,
            "missing_indexes": [],
            "dirty_indexes": [],
            "stale_task_entries": [],
            "event_errors": [],
            "errors": [str(exc)],
            "diagnostics": [diagnostic],
        }


def cleanup_orphan_slug_dirs(workspace_root: Path) -> dict[str, object]:
    """Remove empty slug-named directories under tasks/ that have no task.md."""
    paths = require_v2_layout(workspace_root)
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
        with _timing.stage_timer():
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
    except LaunchError as exc:
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
            "errors": [str(exc)],
            "warnings": [],
            "repair_hints": list(exc.remediation),
            "broken_links": [],
            "expired_locks": [],
            "run_lock_mismatches": [],
            "diagnostics": [
                {"severity": "error", "code": exc.code, "message": str(exc)}
            ],
        }
    except Exception as exc:  # noqa: BLE001
        diagnostic = {
            "severity": "error",
            "code": getattr(exc, "code", "DOCTOR_SCAN_FAILED"),
            "phase": "doctor_scan",
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
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
            "errors": [str(exc)],
            "warnings": [],
            "repair_hints": [],
            "broken_links": [],
            "expired_locks": [],
            "run_lock_mismatches": [],
            "diagnostics": [diagnostic],
        }

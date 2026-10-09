"""Repair API for project identity, task allocation, and lock recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from taskledger.domain.models import TaskRecord
    from taskledger.storage.task_identity import TaskIdentity, _IdentitySource
    from taskledger.storage.task_ids import IncompleteTaskAllocation
    from taskledger.storage.task_store import V2Paths
from taskledger.errors import LaunchError
from taskledger.storage.paths import load_project_locator
from taskledger.storage.project_identity import (
    ensure_project_uuid,
    load_project_uuid,
    normalize_project_uuid,
)


def repair_project_identity(
    workspace_root: Path,
    *,
    apply: bool = False,
    project_uuid: str | None = None,
) -> dict[str, object]:
    """Inspect or repair missing project identity.

    Read-only default: report identity status, config path, whether UUID is
    missing.

    Apply: atomically generate (or set explicit) UUID.
    """
    locator = load_project_locator(workspace_root)
    config_path = locator.config_path
    current_uuid = load_project_uuid(config_path)

    if project_uuid is not None:
        explicit_uuid = normalize_project_uuid(project_uuid)
    else:
        explicit_uuid = None

    if current_uuid is not None and explicit_uuid is not None:
        if current_uuid != explicit_uuid:
            raise LaunchError(
                f"Config already has project UUID {current_uuid}. "
                "Cannot replace with a different UUID."
            )
        return {
            "kind": "project_identity_repair",
            "status": "present",
            "config_path": str(config_path),
            "project_uuid": current_uuid,
            "changed": False,
        }

    if current_uuid is not None:
        return {
            "kind": "project_identity_repair",
            "status": "present",
            "config_path": str(config_path),
            "project_uuid": current_uuid,
            "changed": False,
        }

    # UUID is missing.
    if not apply:
        return {
            "kind": "project_identity_repair",
            "status": "missing",
            "config_path": str(config_path),
            "project_uuid": None,
            "changed": False,
            "action": "generate and persist a UUID",
            "next_command": "taskledger repair project-identity --apply",
        }

    # Apply: generate or use explicit UUID.
    if explicit_uuid is not None:
        from taskledger.storage.atomic import atomic_write_text
        from taskledger.storage.project_identity import insert_or_append_project_uuid

        text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        updated = insert_or_append_project_uuid(text, explicit_uuid)
        atomic_write_text(config_path, updated)
        new_uuid = explicit_uuid
    else:
        new_uuid = ensure_project_uuid(config_path)

    return {
        "kind": "project_identity_repair",
        "status": "generated",
        "config_path": str(config_path),
        "project_uuid": new_uuid,
        "previous_uuid": None,
        "changed": True,
        "next_commands": [
            f"git add {config_path.name}",
            "taskledger migrate inspect",
        ],
    }


def repair_locks(
    workspace_root: Path,
    *,
    apply: bool = False,
    reason: str = "",
) -> dict[str, object]:
    """Bulk-repair stale locks (expired and dead local process only).

    Default mode is dry-run. Requires --apply and --reason for mutation.
    """
    from taskledger.services.lock_inventory import (
        build_lock_inventory,
    )
    from taskledger.services.run_store import break_lock, break_orphan_lock
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    inventory = build_lock_inventory(paths)
    safe = inventory.safe_repairable
    orphans = tuple(
        entry
        for entry in inventory.entries
        if entry.classification == "orphan_missing_task"
    )
    eligible = (*safe, *orphans)
    if not eligible:
        return {
            "kind": "bulk_lock_repair",
            "status": "nothing_to_repair",
            "dry_run": not apply,
            "safe_repairable": 0,
            "orphan_missing_task": 0,
            "total_locks": inventory.lock_file_count,
        }

    if not apply:
        return {
            "kind": "bulk_lock_repair",
            "status": "dry_run",
            "dry_run": True,
            "safe_repairable": len(safe),
            "orphan_missing_task": len(orphans),
            "total_locks": inventory.lock_file_count,
            "entries": [
                {
                    "task_id": e.task_id,
                    "classification": e.classification,
                    "path": str(e.path),
                    "remediation": list(e.diagnostics.remediation)
                    if e.diagnostics
                    else [],
                }
                for e in eligible
            ],
            "next_command": (
                "taskledger repair locks --apply "
                '--reason "Clear stale locks before storage migration."'
            ),
        }

    if not reason.strip():
        raise LaunchError("Bulk lock repair requires --reason when using --apply.")

    repaired: list[str] = []
    orphan_repaired: list[str] = []
    failed: list[dict[str, str]] = []
    for entry in eligible:
        if entry.task_id is None:
            failed.append(
                {
                    "path": str(entry.path),
                    "error": "Cannot determine task_id from lock path.",
                }
            )
            continue
        try:
            if entry.classification == "orphan_missing_task":
                break_orphan_lock(workspace_root, entry.task_id, reason=reason)
                orphan_repaired.append(entry.task_id)
            else:
                break_lock(workspace_root, entry.task_id, reason=reason)
            repaired.append(entry.task_id)
        except Exception as exc:  # noqa: BLE001
            failed.append(
                {
                    "task_id": entry.task_id,
                    "error": str(exc),
                }
            )

    return {
        "kind": "bulk_lock_repair",
        "status": "applied",
        "dry_run": False,
        "repaired": repaired,
        "orphan_missing_task_repaired": orphan_repaired,
        "failed": failed,
        "reason": reason,
    }


def _identity_source_payload(
    paths: V2Paths, source: _IdentitySource
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": source.source_kind,
        "task_uuid": str(source.task_uuid),
        "state": source.state,
        "legacy_task_id": source.legacy_task_id,
        "path": source.path.relative_to(paths.ledger_dir).as_posix(),
    }
    if source.state == "live" and source.path.is_dir():
        from taskledger.storage.task_ids import allocation_source_fingerprint

        payload["source_fingerprint"] = allocation_source_fingerprint(source.path)
    return payload


def _classify_allocation_repair(
    paths: V2Paths, allocation: IncompleteTaskAllocation
) -> dict[str, object]:
    from taskledger.storage.task_identity import inspect_task_identity_sources

    sources = inspect_task_identity_sources(paths)
    expected_kind = (
        "legacy_task" if allocation.source_kind == "legacy_directory" else "uuid_task"
    )
    selected_sources = tuple(
        source for source in sources if source.path == allocation.path
    )
    selected = selected_sources[0] if len(selected_sources) == 1 else None
    collision_findings: tuple[_IdentitySource, ...] = ()
    surviving_identity: dict[str, object] | None = None
    repair_mode = "blocked_identity_conflict"

    selected_matches = (
        selected is not None
        and selected.source_kind == expected_kind
        and selected.state == "incomplete"
        and selected.legacy_task_id == allocation.legacy_task_id
        and (
            allocation.task_uuid is None
            or str(selected.task_uuid) == allocation.task_uuid
        )
    )
    if selected_matches and selected is not None:
        uuid_claimants = tuple(
            source for source in sources if source.task_uuid == selected.task_uuid
        )
        if allocation.legacy_task_id is not None:
            legacy_claimants = tuple(
                source
                for source in sources
                if source.legacy_task_id == allocation.legacy_task_id
            )
            collision_findings = tuple(
                source for source in legacy_claimants if source is not selected
            )
            if len(uuid_claimants) == 1 and len(legacy_claimants) == 1:
                repair_mode = "quarantine_and_tombstone"
            elif (
                len(uuid_claimants) == 1
                and len(legacy_claimants) == 2
                and sum(
                    source.source_kind == "uuid_task" and source.state == "live"
                    for source in collision_findings
                )
                == 1
                and all(
                    source.source_kind == "uuid_task" and source.state == "live"
                    for source in collision_findings
                )
            ):
                repair_mode = "quarantine_shadowed_legacy_source"
                survivor = collision_findings[0]
                surviving_identity = _identity_source_payload(paths, survivor)
        else:
            uuid_claimants = tuple(
                source for source in sources if source.task_uuid == selected.task_uuid
            )
            collision_findings = tuple(
                source for source in uuid_claimants if source is not selected
            )
            if len(uuid_claimants) == 1:
                repair_mode = "quarantine_and_tombstone"

    selected_identity = (
        _identity_source_payload(paths, selected) if selected is not None else None
    )
    return {
        "repair_mode": repair_mode,
        "apply_safe": repair_mode != "blocked_identity_conflict",
        "collision_findings": [
            _identity_source_payload(paths, source) for source in collision_findings
        ],
        "surviving_identity": surviving_identity,
        "selected_identity": selected_identity,
    }


def _allocation_repair_plan_entry(
    paths: V2Paths, allocation: IncompleteTaskAllocation
) -> dict[str, object]:
    source_id = allocation.legacy_task_id or allocation.task_uuid
    quarantine_path = (
        paths.ledger_dir
        / "_recovery"
        / "incomplete-task-allocations"
        / allocation.path.name
    )
    tombstone_name = allocation.legacy_task_id or allocation.task_uuid
    if source_id is None or tombstone_name is None:
        raise LaunchError(
            f"Incomplete allocation lacks a physical source identity: {allocation.path}"
        )
    if allocation.legacy_task_id is not None:
        if (
            allocation.source_kind != "legacy_directory"
            or allocation.path.name != allocation.legacy_task_id
        ):
            raise LaunchError(
                "Legacy allocation identity does not match physical source "
                f"{allocation.path}."
            )
    elif (
        allocation.source_kind != "uuid_directory"
        or allocation.path.name != allocation.task_uuid
    ):
        raise LaunchError(
            "UUID allocation identity does not match physical source "
            f"{allocation.path}."
        )

    warnings: list[str] = []
    if (
        allocation.legacy_task_id is not None
        and allocation.display_task_id is not None
        and allocation.legacy_task_id != allocation.display_task_id
    ):
        warnings.append(
            "Computed display ID differs from physical legacy source ID; "
            "repair targets the physical source ID."
        )
    classification = _classify_allocation_repair(paths, allocation)
    planned_tombstone = None
    if classification["repair_mode"] == "quarantine_and_tombstone":
        planned_tombstone = (
            paths.ledger_dir / "tombstones" / f"{tombstone_name}.toml"
        ).as_posix()
    return {
        "physical_source": allocation.path.relative_to(paths.ledger_dir).as_posix(),
        "source_path": allocation.path.as_posix(),
        "source_kind": allocation.source_kind,
        "legacy_source_id": allocation.legacy_task_id,
        "task_uuid": allocation.task_uuid,
        "display_task_id": allocation.display_task_id,
        "source_id": source_id,
        "entries": list(allocation.files),
        "source_fingerprint": allocation.source_fingerprint,
        "planned_quarantine": quarantine_path.as_posix(),
        "planned_tombstone": planned_tombstone,
        "warnings": warnings,
        **classification,
    }


def _allocation_plan_fingerprint(
    *,
    task_id: str | None,
    entries: list[dict[str, object]],
    identity_conflicts: tuple[dict[str, object], ...],
) -> str:
    scope = "all" if task_id is None else f"source:{task_id}"
    content = json.dumps(
        {
            "scope": scope,
            "entries": entries,
            "identity_conflicts": identity_conflicts,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_allocation_sources_for_apply(
    paths: V2Paths,
    allocations: tuple[IncompleteTaskAllocation, ...],
    plans: list[dict[str, object]],
) -> None:
    from taskledger.storage.task_ids import allocation_source_fingerprint

    if len(allocations) != len(plans):
        raise LaunchError(
            "Allocation repair plan changed since dry-run; inspect a fresh plan.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    for allocation, plan in zip(allocations, plans, strict=True):
        source_path = allocation.path
        if (
            source_path.is_symlink()
            or not source_path.is_dir()
            or plan.get("source_path") != source_path.as_posix()
            or plan.get("source_kind") != allocation.source_kind
        ):
            raise LaunchError(
                f"Allocation source identity changed after planning: {source_path}.",
                code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                details={"source_path": str(source_path)},
            )
        current_fingerprint = allocation_source_fingerprint(source_path)
        if current_fingerprint != plan.get("source_fingerprint"):
            raise LaunchError(
                f"Allocation source changed after planning: {source_path}.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                details={"source_path": str(source_path)},
            )
        current = _allocation_repair_plan_entry(paths, allocation)
        if not bool(plan.get("apply_safe")) or not bool(current.get("apply_safe")):
            raise LaunchError(
                f"Allocation identity conflict blocks repair: {source_path}.",
                code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                details={"source_path": str(source_path)},
            )
        if any(
            current.get(key) != plan.get(key)
            for key in (
                "repair_mode",
                "collision_findings",
                "selected_identity",
                "surviving_identity",
                "planned_tombstone",
            )
        ):
            raise LaunchError(
                "Allocation repair ownership changed since dry-run; "
                "inspect a fresh plan before apply.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                details={"source_path": str(source_path)},
            )


def _verify_allocation_repair_postcondition(
    paths: V2Paths,
    allocation: IncompleteTaskAllocation,
    plan: dict[str, object],
) -> None:
    from taskledger.storage.task_identity import scan_task_identity_inventory

    source_path = allocation.path
    quarantine_path = Path(str(plan["planned_quarantine"]))
    if source_path.exists() or not quarantine_path.is_dir():
        raise LaunchError(
            f"Allocation repair postcondition failed for physical source {source_path}."
        )
    inventory = scan_task_identity_inventory(paths)
    repair_mode = str(plan.get("repair_mode"))
    if repair_mode == "quarantine_shadowed_legacy_source":
        survivor = plan.get("surviving_identity")
        if not isinstance(survivor, dict) or allocation.legacy_task_id is None:
            raise LaunchError("Shadowed allocation repair lacks its reviewed survivor.")
        matches = tuple(
            identity
            for identity in inventory.entries
            if identity.legacy_task_id == allocation.legacy_task_id
        )
        survivor_path = str(survivor.get("path"))
        if (
            len(matches) != 1
            or str(matches[0].task_uuid) != survivor.get("task_uuid")
            or matches[0].path.relative_to(paths.ledger_dir).as_posix() != survivor_path
            or matches[0].source_kind != "uuid_task"
            or matches[0].state != "live"
            or (
                paths.ledger_dir / "tombstones" / f"{allocation.legacy_task_id}.toml"
            ).exists()
        ):
            raise LaunchError(
                "Allocation repair postcondition failed: the reviewed live owner "
                f"does not solely own {allocation.legacy_task_id}."
            )
        return

    if (
        repair_mode != "quarantine_and_tombstone"
        or plan.get("planned_tombstone") is None
    ):
        raise LaunchError(
            "Allocation repair postcondition received an unsupported repair mode."
        )
    if allocation.legacy_task_id is not None:
        matches = tuple(
            identity
            for identity in inventory.entries
            if identity.legacy_task_id == allocation.legacy_task_id
        )
        if (
            len(matches) != 1
            or matches[0].source_kind != "tombstone"
            or matches[0].state != "tombstone"
        ):
            raise LaunchError(
                "Allocation repair postcondition failed for legacy source "
                f"{allocation.legacy_task_id}."
            )
        return

    match = next(
        (
            identity
            for identity in inventory.entries
            if str(identity.task_uuid) == allocation.task_uuid
        ),
        None,
    )
    if match is None or match.state != "tombstone":
        raise LaunchError(
            "Allocation repair postcondition failed for physical source "
            f"{allocation.path}."
        )


def _apply_one_allocation_repair(
    workspace_root: Path,
    paths: V2Paths,
    allocation: IncompleteTaskAllocation,
    plan: dict[str, object],
    *,
    reason: str,
) -> tuple[dict[str, object] | None, str | None]:
    from taskledger.services.task_events import append_task_event
    from taskledger.storage.task_identity import (
        invalidate_task_identity_inventory,
        write_task_identity_tombstone,
    )
    from taskledger.storage.task_ids import (
        allocation_source_fingerprint,
        write_task_id_tombstone,
    )

    source_path = allocation.path
    quarantine_path = Path(str(plan["planned_quarantine"]))
    repair_mode = str(plan.get("repair_mode"))
    planned_tombstone = plan.get("planned_tombstone")
    tombstone_path: Path | None = None
    if repair_mode == "quarantine_and_tombstone":
        if not isinstance(planned_tombstone, str):
            return None, "Tombstone repair plan has no tombstone destination."
        tombstone_path = Path(planned_tombstone)
    elif repair_mode == "quarantine_shadowed_legacy_source":
        if planned_tombstone is not None:
            return None, "Shadowed-source repair must not create a tombstone."
    else:
        return None, "Blocked allocation identity conflict cannot be applied."

    if quarantine_path.exists():
        return None, f"Quarantine destination already exists: {quarantine_path}"
    if tombstone_path is not None and tombstone_path.exists():
        return None, f"Tombstone destination already exists: {tombstone_path}"

    moved = False
    tombstone_created = False
    written_tombstone: Path | None = None
    rollback_errors: list[str] = []
    try:
        current_fingerprint = allocation_source_fingerprint(source_path)
        if current_fingerprint != allocation.source_fingerprint:
            raise LaunchError(
                f"Allocation source changed after planning: {source_path}."
            )
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.rename(quarantine_path)
        moved = True
        relative_quarantine = quarantine_path.relative_to(paths.ledger_dir).as_posix()
        if repair_mode == "quarantine_and_tombstone":
            if allocation.legacy_task_id is not None:
                written_tombstone = write_task_id_tombstone(
                    paths,
                    allocation.legacy_task_id,
                    reason=reason,
                    quarantined_path=quarantine_path,
                )
            else:
                if allocation.task_uuid is None:
                    raise LaunchError(
                        "Allocation has no authoritative physical identity: "
                        f"{source_path}"
                    )
                written_tombstone = write_task_identity_tombstone(
                    paths,
                    allocation.task_uuid,
                    reason=reason,
                    quarantined_path=relative_quarantine,
                )
            tombstone_created = True
        invalidate_task_identity_inventory()
        _verify_allocation_repair_postcondition(paths, allocation, plan)
        event_tombstone_path = (
            written_tombstone.relative_to(paths.ledger_dir).as_posix()
            if written_tombstone is not None
            else None
        )
        survivor = plan.get("surviving_identity")
        surviving_task_uuid = (
            survivor.get("task_uuid") if isinstance(survivor, dict) else None
        )
        surviving_source_path = (
            survivor.get("path") if isinstance(survivor, dict) else None
        )
        append_task_event(
            workspace_root,
            "*",
            "repair.task_allocation_quarantined",
            {
                "source_kind": allocation.source_kind,
                "source_path": plan["physical_source"],
                "legacy_task_id": allocation.legacy_task_id,
                "task_uuid": allocation.task_uuid,
                "display_task_id": allocation.display_task_id,
                "source_fingerprint": allocation.source_fingerprint,
                "repair_mode": repair_mode,
                "reason": reason.strip(),
                "quarantined_path": relative_quarantine,
                "tombstone_path": event_tombstone_path,
                "surviving_task_uuid": surviving_task_uuid,
                "surviving_source_path": surviving_source_path,
            },
        )
        return (
            {
                "source_id": plan["source_id"],
                "legacy_task_id": allocation.legacy_task_id,
                "task_uuid": allocation.task_uuid,
                "display_task_id": allocation.display_task_id,
                "repair_mode": repair_mode,
                "source_path": str(source_path),
                "quarantined_path": str(quarantine_path),
                "tombstone_path": (
                    str(written_tombstone) if written_tombstone is not None else None
                ),
                "surviving_task_uuid": surviving_task_uuid,
                "surviving_source_path": surviving_source_path,
            },
            None,
        )
    except Exception as exc:  # noqa: BLE001
        if tombstone_created and tombstone_path is not None:
            try:
                tombstone_path.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(f"remove tombstone: {rollback_exc}")
        if moved and quarantine_path.exists() and not source_path.exists():
            try:
                source_path.parent.mkdir(parents=True, exist_ok=True)
                quarantine_path.rename(source_path)
            except OSError as rollback_exc:
                rollback_errors.append(f"restore source: {rollback_exc}")
        invalidate_task_identity_inventory()
        error = str(exc)
        if rollback_errors:
            error += "; rollback incomplete: " + "; ".join(rollback_errors)
        return None, error


def repair_allocations(
    workspace_root: Path,
    *,
    apply: bool = False,
    reason: str = "",
    task_id: str | None = None,
    all_allocations: bool = False,
    plan_id: str | None = None,
) -> dict[str, object]:
    """Inspect or transactionally quarantine selected physical allocations."""
    from contextlib import nullcontext

    from taskledger.services.allocation_recovery import apply_allocation_repair_batch
    from taskledger.storage.task_identity import (
        identity_mutation_lock,
        inspect_task_identity_conflicts,
    )
    from taskledger.storage.task_ids import discover_incomplete_task_allocations
    from taskledger.storage.task_store import resolve_v2_paths

    if task_id is not None and all_allocations:
        raise LaunchError("Choose either --task-id or --all, not both.")
    if apply and task_id is None and not all_allocations:
        raise LaunchError(
            "Applying allocation repair requires an explicit --task-id or --all."
        )
    if apply and not reason.strip():
        raise LaunchError(
            "Incomplete task allocation repair requires --reason when using --apply."
        )
    if apply and not plan_id:
        raise LaunchError(
            "Applying allocation repair requires the plan_id from a reviewed dry-run."
        )
    if not apply and plan_id is not None:
        raise LaunchError("--plan-id is only valid when applying a dry-run plan.")

    paths = resolve_v2_paths(workspace_root)
    mutation_lock = identity_mutation_lock(paths) if apply else nullcontext()
    with mutation_lock:
        allocations = discover_incomplete_task_allocations(paths)
        if task_id is not None:
            selected = tuple(
                allocation
                for allocation in allocations
                if allocation.legacy_task_id == task_id
                or allocation.task_uuid == task_id
                or allocation.path.name == task_id
            )
            if not selected:
                code = "TASKLEDGER_REPAIR_PLAN_CHANGED" if apply else None
                raise LaunchError(
                    "No incomplete physical task allocation matches "
                    f"source ID {task_id!r}.",
                    code=code,
                )
        else:
            selected = allocations
        if not selected:
            if apply:
                raise LaunchError(
                    "Allocation repair plan changed; inspect a fresh dry-run.",
                    code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                )
            return {
                "kind": "task_allocation_repair",
                "status": "nothing_to_repair",
                "dry_run": True,
                "incomplete_allocations": [],
                "identity_conflicts": list(inspect_task_identity_conflicts(paths)),
            }

        entries = [_allocation_repair_plan_entry(paths, item) for item in selected]
        identity_conflicts = inspect_task_identity_conflicts(paths)
        computed_plan_id = _allocation_plan_fingerprint(
            task_id=task_id,
            entries=entries,
            identity_conflicts=identity_conflicts,
        )
        if apply and plan_id != computed_plan_id:
            raise LaunchError(
                "Allocation repair plan changed since dry-run; "
                "inspect a fresh plan before apply.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                details={
                    "expected_plan_id": plan_id,
                    "current_plan_id": computed_plan_id,
                },
            )
        if not apply:
            selector = f"--task-id {task_id}" if task_id is not None else "--all"
            apply_safe = all(bool(entry["apply_safe"]) for entry in entries)
            return {
                "kind": "task_allocation_repair",
                "status": "dry_run",
                "dry_run": True,
                "plan_id": computed_plan_id,
                "apply_safe": apply_safe,
                "incomplete_allocations": entries,
                "identity_conflicts": list(identity_conflicts),
                "next_command": (
                    "taskledger repair allocations "
                    f"{selector} --apply --plan-id {computed_plan_id} --reason "
                    '"Quarantine incomplete task allocation."'
                    if apply_safe
                    else None
                ),
            }

        _validate_allocation_sources_for_apply(paths, selected, entries)
        result = apply_allocation_repair_batch(
            workspace_root,
            paths,
            selected,
            entries,
            plan_id=computed_plan_id,
            reason=reason,
            scope="all" if all_allocations or task_id is None else "task_id",
        )
        result["scope"] = "all" if all_allocations or task_id is None else "task_id"
        result["source_selector"] = task_id
        return result


def repair_allocation_conflicts(
    workspace_root: Path,
    *,
    apply: bool = False,
    plan_id: str | None = None,
    reason: str = "",
    allow_unverifiable: bool = False,
    tombstone_id: str | None = None,
) -> dict[str, object]:
    """Plan or apply a reviewed batch repair for task identity conflicts."""
    from taskledger.services.allocation_recovery import (
        apply_identity_conflict_repair_batch,
        plan_identity_conflict_recovery,
    )
    from taskledger.storage.task_store import resolve_v2_paths

    if apply and not reason.strip():
        raise LaunchError("Identity conflict repair requires --reason when applying.")
    if apply and not plan_id:
        raise LaunchError(
            "Applying identity conflict repair requires the reviewed dry-run plan_id."
        )
    if not apply and plan_id is not None:
        raise LaunchError("--plan-id is only valid when applying a conflict plan.")

    paths = resolve_v2_paths(workspace_root)
    if apply:
        result = apply_identity_conflict_repair_batch(
            workspace_root,
            paths,
            plan_id=str(plan_id),
            reason=reason,
            allow_unverifiable=allow_unverifiable,
            tombstone_id=tombstone_id,
        )
        if result.get("status") in {"audit_pending", "rollback_incomplete"}:
            transaction_id = result.get("transaction_id")
            if isinstance(transaction_id, str):
                result["next_command"] = (
                    f"taskledger repair allocations --recover {transaction_id}"
                )
        return result

    plan = plan_identity_conflict_recovery(
        paths,
        allow_unverifiable=allow_unverifiable,
        tombstone_id=tombstone_id,
    )
    if tombstone_id is not None:
        conflicts = plan.get("identity_conflicts", [])
        if not isinstance(conflicts, list) or not any(
            isinstance(conflict, dict)
            and conflict.get("identity_kind") == "legacy_task_id"
            and conflict.get("identity") == tombstone_id
            for conflict in conflicts
        ):
            raise LaunchError(
                f"No authoritative identity conflict exists for {tombstone_id!r}."
            )
    next_command: str | None = None
    if plan.get("apply_safe"):
        selector = f" --tombstone-id {tombstone_id}" if tombstone_id is not None else ""
        override = " --allow-unverifiable" if allow_unverifiable else ""
        next_command = (
            "taskledger repair allocations --conflicts"
            f"{selector}{override} --apply --plan-id {plan['plan_id']} "
            '--reason "User approved reviewed identity conflict recovery."'
        )
    return {**plan, "next_command": next_command}


def repair_active_task(
    workspace_root: Path,
    *,
    action: str = "clear",
    target_uuid: str | None = None,
    apply: bool = False,
    plan_id: str | None = None,
    reason: str = "",
) -> dict[str, object]:
    """Diagnose or perform an explicitly reviewed active-task recovery."""
    from taskledger.services.active_task_recovery import repair_active_task as repair

    return repair(
        workspace_root,
        action=action,
        target_uuid=target_uuid,
        apply=apply,
        plan_id=plan_id,
        reason=reason,
    )


def list_allocation_repair_transactions(
    workspace_root: Path,
) -> dict[str, object]:
    """List durable allocation-repair transaction journals without mutation."""
    from taskledger.services.allocation_recovery import (
        list_allocation_repair_transactions as list_transactions,
    )
    from taskledger.storage.task_store import resolve_v2_paths

    return list_transactions(resolve_v2_paths(workspace_root))


def recover_allocation_repair_transaction(
    workspace_root: Path,
    transaction_id: str,
    *,
    apply: bool = False,
    plan_id: str | None = None,
    reason: str = "",
) -> dict[str, object]:
    """Review or apply journal-backed allocation transaction recovery."""
    from taskledger.services.allocation_recovery import (
        recover_allocation_repair_transaction as recover_transaction,
    )
    from taskledger.storage.task_store import resolve_v2_paths

    return recover_transaction(
        workspace_root,
        resolve_v2_paths(workspace_root),
        transaction_id,
        apply=apply,
        plan_id=plan_id,
        reason=reason,
    )


def _read_allocation_tombstone(path: Path) -> dict[str, object]:
    import importlib

    try:
        tomllib = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        tomllib = importlib.import_module("tomli")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Unable to read allocation tombstone {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise LaunchError(
            f"Invalid allocation tombstone {path}: expected a TOML table."
        )
    return document


def _allocation_tombstone_reconciliation_plan(
    workspace_root: Path,
    *,
    source_id: str,
    tombstone_id: str,
) -> tuple[dict[str, object], Path, Path, Path]:
    import hashlib
    import json

    from taskledger.ids import TASK_ID_FORMAT
    from taskledger.storage.events import load_events
    from taskledger.storage.task_identity import inspect_legacy_identity_claims
    from taskledger.storage.task_store import resolve_v2_paths

    for value in (source_id, tombstone_id):
        try:
            parts = TASK_ID_FORMAT.parse_parts(value)
        except ValueError as exc:
            raise LaunchError(
                f"Invalid task ID in tombstone reconciliation: {value!r}."
            ) from exc
        if TASK_ID_FORMAT.format(parts.number) != value or parts.number < 1:
            raise LaunchError(
                f"Non-canonical task ID in tombstone reconciliation: {value!r}."
            )
    if source_id == tombstone_id:
        raise LaunchError("Source task ID and misattributed tombstone ID must differ.")

    paths = resolve_v2_paths(workspace_root)
    old_tombstone = paths.ledger_dir / "tombstones" / f"{tombstone_id}.toml"
    if not old_tombstone.is_file():
        raise LaunchError(f"Misattributed tombstone does not exist: {old_tombstone}")
    source_claims = inspect_legacy_identity_claims(paths, source_id)
    previous_claims = inspect_legacy_identity_claims(paths, tombstone_id)
    if source_claims:
        raise LaunchError(
            f"Correct source ID {source_id} already has physical identity claimants."
        )
    if not any(
        source.path == old_tombstone and source.source_kind == "tombstone"
        for source in previous_claims
    ):
        raise LaunchError(
            "The reviewed tombstone is not an authoritative identity claimant."
        )
    source_claimants = [
        _identity_source_payload(paths, source) for source in source_claims
    ]
    previous_claimants = [
        _identity_source_payload(paths, source) for source in previous_claims
    ]
    document = _read_allocation_tombstone(old_tombstone)
    if (
        document.get("schema_version") != 1
        or document.get("object_type") != "task_id_tombstone"
        or document.get("id") != tombstone_id
        or not isinstance(document.get("quarantined_path"), str)
    ):
        raise LaunchError(f"Invalid legacy task tombstone: {old_tombstone}")

    quarantine_rel = str(document["quarantined_path"])
    quarantine_path = (paths.ledger_dir / quarantine_rel).resolve()
    recovery_root = (
        paths.ledger_dir / "_recovery" / "incomplete-task-allocations"
    ).resolve()
    if (
        not quarantine_path.is_dir()
        or not quarantine_path.is_relative_to(recovery_root)
        or Path(quarantine_rel).name != tombstone_id
    ):
        raise LaunchError("Tombstone quarantine path is unsafe or mismatched.")

    expected_old_tombstone = f"tombstones/{tombstone_id}.toml"
    matching_events = []
    for event in load_events(paths.events_dir):
        if event.event != "repair.task_allocation_quarantined":
            continue
        data = event.data
        if (
            data.get("tombstone_path") == expected_old_tombstone
            and data.get("quarantined_path") == quarantine_rel
        ):
            matching_events.append(event)
    if not matching_events:
        raise LaunchError(
            "No allocation repair event proves this tombstone/quarantine provenance."
        )

    event_source_ids: set[str] = set()
    for event in matching_events:
        stored_source_id = event.data.get("legacy_task_id")
        stored_source_path = event.data.get("source_path")
        if isinstance(stored_source_id, str):
            event_source_ids.add(stored_source_id)
        if isinstance(stored_source_path, str):
            event_source_ids.add(Path(stored_source_path).name)
    if event_source_ids and event_source_ids != {source_id}:
        raise LaunchError(
            "Repair event source identity disagrees with the requested correction.",
            code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
            details={
                "requested_source_id": source_id,
                "recorded_source_ids": sorted(event_source_ids),
            },
        )

    preserved_tombstone = (
        paths.ledger_dir
        / "recovery"
        / "misattributed-allocation-tombstones"
        / f"{tombstone_id}.toml"
    )
    new_tombstone = paths.ledger_dir / "tombstones" / f"{source_id}.toml"
    if preserved_tombstone.exists():
        raise LaunchError(
            f"Preserved tombstone destination already exists: {preserved_tombstone}"
        )
    if new_tombstone.exists():
        raise LaunchError(f"Correct source tombstone already exists: {new_tombstone}")

    evidence_status = "verified_event" if event_source_ids else "operator_asserted"
    plan: dict[str, object] = {
        "source_id": source_id,
        "previous_tombstone_id": tombstone_id,
        "quarantined_path": str(quarantine_path),
        "quarantined_relative_path": quarantine_rel,
        "preserved_tombstone": str(preserved_tombstone),
        "new_tombstone": str(new_tombstone),
        "evidence_status": evidence_status,
        "event_ids": sorted(event.event_id for event in matching_events),
        "source_claimants": source_claimants,
        "previous_claimants": previous_claimants,
        "tombstone_sha256": hashlib.sha256(old_tombstone.read_bytes()).hexdigest(),
    }
    fingerprint = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    plan["plan_id"] = fingerprint
    return plan, old_tombstone, preserved_tombstone, new_tombstone


def audit_allocation_repairs(workspace_root: Path) -> dict[str, object]:
    """Report allocation tombstone provenance without mutating storage."""
    from taskledger.storage.events import load_events
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    events = load_events(paths.events_dir)
    reconciled = {
        str(event.data.get("previous_tombstone_id"))
        for event in events
        if event.event == "repair.task_allocation_tombstone_reconciled"
    }
    entries: list[dict[str, object]] = []
    for event in events:
        if event.event != "repair.task_allocation_quarantined":
            continue
        data = event.data
        tombstone_path = data.get("tombstone_path")
        source_path = data.get("source_path")
        legacy_task_id = data.get("legacy_task_id")
        tombstone_id = (
            Path(tombstone_path).stem if isinstance(tombstone_path, str) else None
        )
        physical_id = (
            legacy_task_id
            if isinstance(legacy_task_id, str)
            else Path(source_path).name
            if isinstance(source_path, str)
            else None
        )
        repair_mode = data.get("repair_mode")
        if (
            repair_mode == "quarantine_shadowed_legacy_source"
            and tombstone_id is None
            and isinstance(data.get("surviving_task_uuid"), str)
        ):
            status = "existing_owner_preserved"
        elif tombstone_id in reconciled:
            status = "reconciled"
        elif physical_id is None or tombstone_id is None:
            status = "unverifiable"
        elif physical_id != tombstone_id:
            status = "identity_mismatch"
        else:
            status = "verified"
        entries.append(
            {
                "event_id": event.event_id,
                "status": status,
                "repair_mode": repair_mode,
                "surviving_task_uuid": data.get("surviving_task_uuid"),
                "surviving_source_path": data.get("surviving_source_path"),
                "physical_source_id": physical_id,
                "tombstone_id": tombstone_id,
                "quarantined_path": data.get("quarantined_path"),
                "source_fingerprint": data.get("source_fingerprint"),
            }
        )
    for event in events:
        if event.event != "repair.task_allocation_shadow_tombstone_retired":
            continue
        data = event.data
        entries.append(
            {
                "event_id": event.event_id,
                "status": "shadow_tombstone_retired",
                "repair_mode": "retire_shadowing_tombstone",
                "physical_source_id": None,
                "tombstone_id": data.get("legacy_task_id"),
                "previous_tombstone_path": data.get("previous_tombstone_path"),
                "preserved_tombstone": data.get("preserved_tombstone"),
                "quarantined_path": data.get("quarantined_path"),
                "surviving_task_uuid": data.get("surviving_task_uuid"),
                "surviving_source_path": data.get("surviving_source_path"),
                "source_fingerprint": data.get("surviving_source_fingerprint"),
                "evidence_status": data.get("evidence_status"),
                "operator_override": data.get("operator_override"),
                "transaction_id": data.get("transaction_id"),
            }
        )
    return {
        "kind": "task_allocation_repair_audit",
        "entries": entries,
        "summary": {
            status: sum(1 for entry in entries if entry["status"] == status)
            for status in (
                "verified",
                "identity_mismatch",
                "unverifiable",
                "existing_owner_preserved",
                "reconciled",
                "shadow_tombstone_retired",
            )
        },
    }


def reconcile_allocation_tombstone(
    workspace_root: Path,
    *,
    source_id: str,
    tombstone_id: str,
    apply: bool = False,
    plan_id: str | None = None,
    reason: str = "",
) -> dict[str, object]:
    """Correct a misattributed tombstone without losing its recovery payload."""
    from taskledger.services.task_events import append_task_event
    from taskledger.storage.task_identity import (
        inspect_legacy_identity_claims,
        inspect_task_identity_conflicts,
        invalidate_task_identity_inventory,
    )
    from taskledger.storage.task_ids import write_task_id_tombstone
    from taskledger.storage.task_store import resolve_v2_paths

    if apply and not reason.strip():
        raise LaunchError(
            "Tombstone reconciliation requires --reason when using --apply."
        )
    if apply and not plan_id:
        raise LaunchError(
            "Tombstone reconciliation requires its reviewed dry-run plan_id."
        )
    if not apply and plan_id is not None:
        raise LaunchError(
            "--plan-id is only valid when applying a reconciliation plan."
        )

    plan, old_tombstone, preserved_tombstone, new_tombstone = (
        _allocation_tombstone_reconciliation_plan(
            workspace_root, source_id=source_id, tombstone_id=tombstone_id
        )
    )
    if apply and plan_id != plan["plan_id"]:
        raise LaunchError(
            "Tombstone reconciliation plan changed since dry-run; "
            "inspect a fresh plan.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
            details={"expected_plan_id": plan_id, "current_plan_id": plan["plan_id"]},
        )
    if not apply:
        return {
            "kind": "task_allocation_tombstone_reconciliation",
            "status": "dry_run",
            "dry_run": True,
            **plan,
            "warning": (
                "Source identity is operator-asserted; verify it against independent "
                "physical evidence before applying."
                if plan["evidence_status"] == "operator_asserted"
                else None
            ),
            "next_command": (
                "taskledger repair allocations --reconcile-source-id "
                f"{source_id} --tombstone-id {tombstone_id} --apply "
                f'--plan-id {plan["plan_id"]} --reason "..."'
            ),
        }

    preserved_tombstone.parent.mkdir(parents=True, exist_ok=True)
    preserved = False
    created = False
    rollback_errors: list[str] = []
    try:
        old_tombstone.rename(preserved_tombstone)
        preserved = True
        written = write_task_id_tombstone(
            resolve_v2_paths(workspace_root),
            source_id,
            reason=reason,
            quarantined_path=Path(str(plan["quarantined_path"])),
        )
        created = True
        paths = resolve_v2_paths(workspace_root)
        invalidate_task_identity_inventory()
        source_matches = inspect_legacy_identity_claims(paths, source_id)
        previous_matches = inspect_legacy_identity_claims(paths, tombstone_id)
        tombstone_document = _read_allocation_tombstone(written)
        old_tombstone_relative = f"tombstones/{tombstone_id}.toml"
        expected_previous = plan.get("previous_claimants")
        actual_previous = [
            _identity_source_payload(paths, identity)
            for identity in previous_matches
            if identity.path != old_tombstone
        ]
        if (
            len(source_matches) != 1
            or source_matches[0].source_kind != "tombstone"
            or source_matches[0].state != "tombstone"
            or source_matches[0].path != written
            or tombstone_document.get("schema_version") != 1
            or tombstone_document.get("object_type") != "task_id_tombstone"
            or tombstone_document.get("id") != source_id
            or tombstone_document.get("reason") != reason.strip()
            or tombstone_document.get("quarantined_path")
            != plan["quarantined_relative_path"]
            or not isinstance(expected_previous, list)
            or actual_previous
            != [
                claimant
                for claimant in expected_previous
                if isinstance(claimant, dict)
                and claimant.get("path") != old_tombstone_relative
            ]
        ):
            raise LaunchError("Tombstone reconciliation local postcondition failed.")
        remaining_conflicts = list(inspect_task_identity_conflicts(paths))
        ledger_healthy = not remaining_conflicts
        append_task_event(
            workspace_root,
            "*",
            "repair.task_allocation_tombstone_reconciled",
            {
                "source_id": source_id,
                "previous_tombstone_id": tombstone_id,
                "quarantined_path": plan["quarantined_relative_path"],
                "preserved_tombstone": preserved_tombstone.relative_to(
                    resolve_v2_paths(workspace_root).ledger_dir
                ).as_posix(),
                "new_tombstone": written.relative_to(
                    resolve_v2_paths(workspace_root).ledger_dir
                ).as_posix(),
                "evidence_status": plan["evidence_status"],
                "reason": reason.strip(),
            },
        )
        return {
            "kind": "task_allocation_tombstone_reconciliation",
            "status": "applied",
            "dry_run": False,
            "changed": True,
            **plan,
            "preserved_tombstone": str(preserved_tombstone),
            "new_tombstone": str(written),
            "reason": reason.strip(),
            "remaining_conflicts": remaining_conflicts,
            "ledger_healthy": ledger_healthy,
        }
    except Exception as exc:
        if created:
            try:
                new_tombstone.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(f"remove corrected tombstone: {rollback_exc}")
        if preserved and preserved_tombstone.exists() and not old_tombstone.exists():
            try:
                preserved_tombstone.rename(old_tombstone)
            except OSError as rollback_exc:
                rollback_errors.append(f"restore original tombstone: {rollback_exc}")
        invalidate_task_identity_inventory()
        error = str(exc)
        if rollback_errors:
            error += "; rollback incomplete: " + "; ".join(rollback_errors)
        raise LaunchError(
            f"Tombstone reconciliation failed: {error}",
            code="TASKLEDGER_REPAIR_RECONCILIATION_FAILED",
            details={"source_id": source_id, "tombstone_id": tombstone_id},
        ) from exc


def _load_relation_repair_source(
    paths: V2Paths,
    *,
    task_uuid: str,
    field: str,
    requirement_id: str | None,
) -> tuple[
    TaskRecord, Path, dict[str, object], str, bytes, str | None, str, str | None
]:
    from taskledger.domain.models import DependencyRequirement
    from taskledger.storage.frontmatter import read_markdown_front_matter
    from taskledger.storage.task_store import load_task_bundle_by_uuid

    source_task = load_task_bundle_by_uuid(paths, task_uuid)
    if requirement_id is None:
        source_path = paths.tasks_dir / task_uuid / "task.md"
    else:
        source_path = (
            paths.tasks_dir / task_uuid / "requirements" / f"{requirement_id}.md"
        )
    bundle_dir = paths.tasks_dir / task_uuid
    if (
        bundle_dir.is_symlink()
        or source_path.parent.is_symlink()
        or source_path.is_symlink()
    ):
        raise LaunchError(f"Relation repair refuses symlink source: {source_path}")
    if not source_path.is_file():
        raise LaunchError(f"Relation source record not found: {source_path}")
    source_bytes = source_path.read_bytes()
    metadata, body = read_markdown_front_matter(source_path)
    if source_path.read_bytes() != source_bytes:
        raise LaunchError(
            f"Relation source changed while reading: {source_path}.",
            code="TASKLEDGER_RELATION_SOURCE_CHANGED",
            details={"source": str(source_path), "field": field},
        )
    current_uuid = metadata.get(field)
    if current_uuid is not None and not isinstance(current_uuid, str):
        raise LaunchError(
            f"Relation field {field} in {source_path} must be a UUID string."
        )
    target_uuid = current_uuid
    if requirement_id is None:
        if field != "parent_task_uuid":
            raise LaunchError("Task records support only parent_task_uuid repair.")
        target_id = metadata.get("parent_task_id", "")
        if not isinstance(target_id, str) or (not target_id and current_uuid is None):
            raise LaunchError(
                f"No parent task alias is available in {source_path} to repair."
            )
    else:
        requirement = DependencyRequirement.from_dict(metadata)
        if requirement.id is not None and requirement.id != requirement_id:
            raise LaunchError(
                f"Requirement ID in {source_path} does not match {requirement_id!r}."
            )
        if field == "required_task_uuid":
            target_id = requirement.required_task_id or requirement.task_id
        else:
            target_id = requirement.parent_task_id or source_task.id
            if requirement.parent_task_id is None and target_uuid is None:
                target_uuid = task_uuid
    return (
        source_task,
        source_path,
        metadata,
        body,
        source_bytes,
        current_uuid,
        target_id,
        target_uuid,
    )


def _resolve_relation_repair_target(
    paths: V2Paths,
    *,
    source_path: Path,
    field: str,
    target_id: str,
    target_uuid: str | None,
) -> TaskIdentity:
    from taskledger.storage.task_identity import (
        invalidate_task_identity_inventory,
        task_identity_for_stored_ref,
    )

    invalidate_task_identity_inventory()

    try:
        identity = task_identity_for_stored_ref(
            paths, task_id=target_id, task_uuid=target_uuid
        )
    except LaunchError as exc:
        raise LaunchError(
            f"Cannot safely resolve {field} in {source_path}: {exc}",
            code="TASKLEDGER_RELATION_RESOLUTION_FAILED",
            details={
                "source": str(source_path),
                "field": field,
                "task_id": target_id,
                "task_uuid": target_uuid,
                "cause_code": exc.code,
                "cause": str(exc),
            },
        ) from exc
    if identity.state != "live" or not (identity.path / "task.md").is_file():
        raise LaunchError(
            f"Relation {field} in {source_path} targets non-live task {target_id!r}.",
            code="TASKLEDGER_RELATION_RESOLUTION_FAILED",
            details={
                "source": str(source_path),
                "field": field,
                "task_id": target_id,
                "task_uuid": str(identity.task_uuid),
                "target_state": identity.state,
            },
        )
    return identity


def _task_relation_repair_plan(
    paths: V2Paths,
    *,
    source_task: TaskRecord,
    source_path: Path,
    source_bytes: bytes,
    field: str,
    requirement_id: str | None,
    current_uuid: str | None,
    target_id: str,
    identity: TaskIdentity,
) -> dict[str, object]:
    plan: dict[str, object] = {
        "task_id": source_task.id,
        "task_uuid": source_task.task_uuid,
        "source_path": str(source_path),
        "source_relative_path": source_path.relative_to(paths.ledger_dir).as_posix(),
        "source_fingerprint": hashlib.sha256(source_bytes).hexdigest(),
        "field": field,
        "current_relation_uuid": current_uuid,
        "requirement_id": requirement_id,
        "target_reference": target_id,
        "target_task_id": identity.task_id,
        "target_task_uuid": str(identity.task_uuid),
        "target_source_fingerprint": hashlib.sha256(
            (identity.path / "task.md").read_bytes()
        ).hexdigest(),
        "target_source_kind": identity.source_kind,
        "target_identity_path": str(identity.path),
        "target_legacy_task_id": identity.legacy_task_id,
    }
    plan["plan_id"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return plan


def _apply_task_relation_repair(
    workspace_root: Path,
    paths: V2Paths,
    *,
    source_task: TaskRecord,
    source_path: Path,
    metadata: dict[str, object],
    body: str,
    source_bytes: bytes,
    field: str,
    identity: TaskIdentity,
    plan: dict[str, object],
    reason: str,
) -> dict[str, object]:
    from taskledger.domain.models import TaskEvent
    from taskledger.services.task_events import default_actor, default_harness
    from taskledger.storage.atomic import atomic_write_text
    from taskledger.storage.events import append_event, next_event_id
    from taskledger.storage.frontmatter import (
        read_markdown_front_matter,
        write_markdown_front_matter,
    )
    from taskledger.timeutils import utc_now_iso

    updated_metadata = dict(metadata)
    if field == "required_task_uuid":
        updated_metadata["task_id"] = identity.task_id
        updated_metadata["required_task_id"] = identity.task_id
    else:
        updated_metadata["parent_task_id"] = identity.task_id
    updated_metadata[field] = str(identity.task_uuid)
    expected_fields = [field]
    if field == "required_task_uuid":
        expected_fields.extend(("task_id", "required_task_id"))
    else:
        expected_fields.append("parent_task_id")

    wrote_source = False
    written_bytes: bytes | None = None
    audit_event_id: str | None = None
    try:
        target_fingerprint = plan.get("target_source_fingerprint")
        target_path = identity.path / "task.md"
        if (
            not isinstance(target_fingerprint, str)
            or hashlib.sha256(target_path.read_bytes()).hexdigest()
            != target_fingerprint
        ):
            raise LaunchError(
                f"Relation target changed after planning: {target_path}.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                details={"source": str(source_path), "field": field},
            )
        if source_path.read_bytes() != source_bytes:
            raise LaunchError(
                f"Relation source changed after planning: {source_path}.",
                code="TASKLEDGER_RELATION_SOURCE_CHANGED",
                details={"source": str(source_path), "field": field},
            )
        write_markdown_front_matter(source_path, updated_metadata, body)
        wrote_source = True
        written_bytes = source_path.read_bytes()
        verified_metadata, _ = read_markdown_front_matter(source_path)
        if any(
            verified_metadata.get(key) != updated_metadata.get(key)
            for key in expected_fields
        ):
            raise LaunchError(
                f"Relation repair postcondition failed for {source_path}.",
                code="TASKLEDGER_RELATION_BACKFILL_FAILED",
                details={"source": str(source_path), "field": field},
            )
        timestamp = utc_now_iso()
        audit_event_id = next_event_id(paths.events_dir, timestamp)
        append_event(
            paths.events_dir,
            TaskEvent(
                ts=timestamp,
                event="repair.task_relation_uuid_backfilled",
                task_id=source_task.id,
                task_uuid=str(source_task.task_uuid),
                actor=default_actor(),
                harness=default_harness(),
                event_id=audit_event_id,
                data={
                    **plan,
                    "reason": reason.strip(),
                    "actor_action": "explicit_apply",
                },
            ),
        )
    except Exception as exc:
        rollback_error: str | None = None
        try:
            if wrote_source:
                current_bytes = (
                    source_path.read_bytes() if source_path.exists() else None
                )
                if current_bytes == written_bytes:
                    atomic_write_text(source_path, source_bytes.decode("utf-8"))
                elif current_bytes != source_bytes:
                    rollback_error = (
                        "source changed after relation write; "
                        "preserving the newer content"
                    )
        except (OSError, UnicodeDecodeError, LaunchError) as rollback_exc:
            rollback_error = str(rollback_exc)
        message = str(exc)
        if rollback_error is not None:
            message += f"; rollback failed: {rollback_error}"
        raise LaunchError(
            f"Relation repair failed: {message}",
            code="TASKLEDGER_RELATION_REPAIR_FAILED",
            details={"source": str(source_path), "field": field},
        ) from exc

    return {
        "kind": "task_relation_repair",
        "status": "applied",
        "dry_run": False,
        "changed": True,
        **plan,
        "reason": reason.strip(),
        "audit_event_id": audit_event_id,
    }


def repair_task_relation(
    workspace_root: Path,
    *,
    task_uuid: str,
    field: str,
    requirement_id: str | None = None,
    apply: bool = False,
    plan_id: str | None = None,
    reason: str = "",
) -> dict[str, object]:
    """Backfill one task-relation UUID using a reviewed, content-bound plan."""
    from taskledger.ids import parse_uuid7
    from taskledger.storage.task_store import resolve_v2_paths

    if apply and not reason.strip():
        raise LaunchError("Relation repair requires --reason when using --apply.")
    if apply and not plan_id:
        raise LaunchError("Relation repair requires the reviewed dry-run --plan-id.")
    if not apply and plan_id is not None:
        raise LaunchError("--plan-id is only valid when applying a relation repair.")
    try:
        canonical_uuid = str(parse_uuid7(task_uuid.strip().lower()))
    except ValueError as exc:
        raise LaunchError(f"Invalid source task UUIDv7: {task_uuid!r}.") from exc
    if field not in {"parent_task_uuid", "required_task_uuid"}:
        raise LaunchError(
            "Relation field must be parent_task_uuid or required_task_uuid.",
            code="USAGE_ERROR",
            exit_code=2,
        )
    if requirement_id is None and field != "parent_task_uuid":
        raise LaunchError("required_task_uuid repair requires --requirement-id.")
    if requirement_id is not None and (
        Path(requirement_id).name != requirement_id
        or not requirement_id.startswith("req-")
    ):
        raise LaunchError("Invalid requirement ID for relation repair.")

    paths = resolve_v2_paths(workspace_root)
    (
        source_task,
        source_path,
        metadata,
        body,
        source_bytes,
        current_uuid,
        target_id,
        target_uuid,
    ) = _load_relation_repair_source(
        paths,
        task_uuid=canonical_uuid,
        field=field,
        requirement_id=requirement_id,
    )
    if not target_id and target_uuid is None:
        raise LaunchError(
            f"No task reference is available for {field} in {source_path}.",
            code="TASKLEDGER_RELATION_RESOLUTION_FAILED",
            details={"source": str(source_path), "field": field},
        )
    identity = _resolve_relation_repair_target(
        paths,
        source_path=source_path,
        field=field,
        target_id=target_id,
        target_uuid=target_uuid,
    )
    plan = _task_relation_repair_plan(
        paths,
        source_task=source_task,
        source_path=source_path,
        source_bytes=source_bytes,
        field=field,
        requirement_id=requirement_id,
        current_uuid=current_uuid,
        target_id=target_id,
        identity=identity,
    )
    if current_uuid is not None:
        return {
            "kind": "task_relation_repair",
            "status": "already_present",
            "dry_run": not apply,
            "changed": False,
            **plan,
        }
    if not apply:
        return {
            "kind": "task_relation_repair",
            "status": "dry_run",
            "dry_run": True,
            "changed": False,
            **plan,
            "next_command": (
                "taskledger repair relation --task-uuid "
                f"{canonical_uuid} --field {field}"
                + (f" --requirement-id {requirement_id}" if requirement_id else "")
                + f' --apply --plan-id {plan["plan_id"]} --reason "..."'
            ),
        }
    if plan_id != plan["plan_id"]:
        raise LaunchError(
            "Relation repair source or mapping changed since dry-run; "
            "inspect a fresh plan.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
            details={"expected_plan_id": plan_id, "current_plan_id": plan["plan_id"]},
        )
    return _apply_task_relation_repair(
        workspace_root,
        paths,
        source_task=source_task,
        source_path=source_path,
        metadata=metadata,
        body=body,
        source_bytes=source_bytes,
        field=field,
        identity=identity,
        plan=plan,
        reason=reason,
    )

"""Repair API: project identity repair and bulk lock repair."""

from __future__ import annotations

from pathlib import Path

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


def repair_allocations(
    workspace_root: Path,
    *,
    apply: bool = False,
    reason: str = "",
) -> dict[str, object]:
    """Inspect or quarantine incomplete non-empty task allocations."""
    from taskledger.services.task_events import append_task_event
    from taskledger.storage.task_identity import (
        task_identity_inventory,
        write_task_identity_tombstone,
    )
    from taskledger.storage.task_ids import (
        IncompleteTaskAllocation,
        write_task_id_tombstone,
    )
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    allocations = tuple(
        IncompleteTaskAllocation(
            identity.task_id,
            identity.path,
            tuple(sorted(path.name for path in identity.path.iterdir())),
        )
        for identity in task_identity_inventory(paths).entries
        if identity.state == "incomplete"
    )
    entries = [
        {
            "task_id": allocation.task_id,
            "path": str(allocation.path),
            "files": list(allocation.files),
        }
        for allocation in allocations
    ]
    if not allocations:
        return {
            "kind": "task_allocation_repair",
            "status": "nothing_to_repair",
            "dry_run": not apply,
            "incomplete_allocations": [],
        }
    if not apply:
        return {
            "kind": "task_allocation_repair",
            "status": "dry_run",
            "dry_run": True,
            "incomplete_allocations": entries,
            "next_command": (
                "taskledger repair allocations --apply "
                '--reason "Quarantine incomplete task allocation."'
            ),
        }
    if not reason.strip():
        raise LaunchError(
            "Incomplete task allocation repair requires --reason when using --apply."
        )

    repaired: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for allocation in allocations:
        is_legacy_allocation = allocation.path.name.startswith("task-")
        identity_name = (
            allocation.task_id if is_legacy_allocation else allocation.path.name
        )
        quarantine_path = (
            paths.tasks_dir.parent
            / "_recovery"
            / "incomplete-task-allocations"
            / identity_name
        )
        if quarantine_path.exists():
            failed.append(
                {
                    "task_id": allocation.task_id,
                    "error": (
                        f"Quarantine destination already exists: {quarantine_path}"
                    ),
                }
            )
            continue
        try:
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            if is_legacy_allocation:
                write_task_id_tombstone(
                    paths,
                    allocation.task_id,
                    reason=reason,
                    quarantined_path=quarantine_path,
                )
            allocation.path.rename(quarantine_path)
            relative_quarantine = quarantine_path.relative_to(
                paths.ledger_dir
            ).as_posix()
            if is_legacy_allocation:
                tombstone_path = (
                    paths.ledger_dir / "tombstones" / f"{allocation.task_id}.toml"
                )
            else:
                try:
                    tombstone_path = write_task_identity_tombstone(
                        paths,
                        allocation.path.name,
                        reason=reason,
                        quarantined_path=relative_quarantine,
                    )
                except Exception:
                    quarantine_path.rename(allocation.path)
                    raise
            append_task_event(
                workspace_root,
                "*",
                "repair.task_allocation_quarantined",
                {
                    "task_id": allocation.task_id,
                    "reason": reason.strip(),
                    "quarantined_path": relative_quarantine,
                    "tombstone_path": tombstone_path.relative_to(
                        paths.ledger_dir
                    ).as_posix(),
                },
            )
            repaired.append(
                {
                    "task_id": allocation.task_id,
                    "quarantined_path": str(quarantine_path),
                    "tombstone_path": str(tombstone_path),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failed.append({"task_id": allocation.task_id, "error": str(exc)})
    return {
        "kind": "task_allocation_repair",
        "status": "applied",
        "dry_run": False,
        "repaired": repaired,
        "failed": failed,
        "reason": reason.strip(),
    }

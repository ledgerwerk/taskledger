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
    from taskledger.services.run_store import break_lock
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    inventory = build_lock_inventory(paths)
    safe = inventory.safe_repairable

    if not safe:
        return {
            "kind": "bulk_lock_repair",
            "status": "nothing_to_repair",
            "dry_run": not apply,
            "safe_repairable": 0,
            "total_locks": inventory.lock_file_count,
        }

    if not apply:
        return {
            "kind": "bulk_lock_repair",
            "status": "dry_run",
            "dry_run": True,
            "safe_repairable": len(safe),
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
                for e in safe
            ],
            "next_command": (
                "taskledger repair locks --apply "
                '--reason "Clear stale locks before storage migration."'
            ),
        }

    if not reason.strip():
        raise LaunchError("Bulk lock repair requires --reason when using --apply.")

    repaired: list[str] = []
    failed: list[dict[str, str]] = []
    for entry in safe:
        if entry.task_id is None:
            failed.append(
                {
                    "path": str(entry.path),
                    "error": "Cannot determine task_id from lock path.",
                }
            )
            continue
        try:
            break_lock(workspace_root, entry.task_id, reason=reason)
            repaired.append(entry.task_id)
        except Exception as exc:
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
        "failed": failed,
        "reason": reason,
    }

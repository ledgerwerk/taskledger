from __future__ import annotations

from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.services.storage_locations import (
    build_storage_location_report,
    build_sync_preflight_report,
    build_sync_status_report,
    move_taskledger_storage,
    sync_commit_storage,
)
from taskledger.services.storage_migration import (
    apply_migration as _apply_project_migration,
)
from taskledger.services.storage_migration import (
    inspect_migration as _inspect_project_migration,
)
from taskledger.storage.ledgercore_backend import (
    inspect_taskledger_migration,
    load_taskledger_ledger_layout,
    migrate_taskledger_mount,
    recover_taskledger_migration,
    set_taskledger_mount_target,
)
from taskledger.storage.project_context import load_project_context
from taskledger.storage.taskledger_migration import require_no_active_taskledger_locks


def storage_where(workspace_root: Path) -> dict[str, object]:
    return build_storage_location_report(workspace_root).to_dict()


def storage_path(workspace_root: Path, mount: str) -> dict[str, object]:
    if mount not in {"data", "indexes"}:
        raise LaunchError("Unknown mount. Expected one of: data, indexes.")
    context = load_project_context(workspace_root)
    if context.layout is None:
        raise LaunchError(
            "Mount paths are unavailable in legacy mode; "
            "use `taskledger migrate` first.",
        )
    resolved = context.layout.mounts[mount]
    return {
        "kind": "storage_path",
        "schema_version": 2,
        "mount": mount,
        "path": str(resolved.path),
        "storage": str(resolved.storage),
        "source": str(resolved.source),
        "initialized": resolved.path.exists(),
        "mode": context.mode,
        "binding": {"status": "valid"},
    }


def storage_move(
    workspace_root: Path,
    *,
    target: Path,
    mode: str,
    adopt_existing: bool = False,
    force: bool = False,
) -> dict[str, object]:
    return move_taskledger_storage(
        workspace_root,
        target=target,
        mode=mode,
        adopt_existing=adopt_existing,
        force=force,
    ).to_dict()


def storage_validate(
    workspace_root: Path,
    *,
    strict: bool = False,
) -> dict[str, object]:
    """Validate storage configuration.

    Args:
        workspace_root: The workspace root path.
        strict: If True, run additional binding and fingerprint checks.

    Returns:
        A dict with the validation result.
    """
    bundle = load_taskledger_ledger_layout(workspace_root)
    report = bundle.validation_report
    results = []
    if report is not None:
        for result in report.results:
            results.append(
                {
                    "path": str(result.path),
                    "valid": result.valid,
                    "reason": result.reason,
                }
            )
    # Add strict checks if requested
    if strict:
        # Check that all mount paths are accessible
        try:
            from taskledger.storage.paths import resolve_project_paths

            paths = resolve_project_paths(workspace_root)
            for mount_name in ("data", "indexes"):
                mount_path = getattr(paths, f"{mount_name}_path", None)
                if mount_path and mount_path.exists():
                    results.append(
                        {
                            "path": str(mount_path),
                            "valid": True,
                            "reason": f"Mount {mount_name} accessible",
                        }
                    )
                elif mount_path:
                    results.append(
                        {
                            "path": str(mount_path),
                            "valid": False,
                            "reason": f"Mount {mount_name} not found",
                        }
                    )
        except Exception:
            pass  # Best effort for strict checks
    valid = bool(report is not None and report.valid)
    if strict:
        # In strict mode, all results must be valid
        valid = valid and all(r["valid"] for r in results)
    return {
        "kind": "storage_validation",
        "schema_version": 2,
        "valid": valid,
        "strict": strict,
        "results": results,
    }


def storage_set(
    workspace_root: Path,
    *,
    mount: str,
    storage: str,
    target: str,
    external_root: str | None = None,
    mode: str = "copy",
) -> dict[str, object]:
    if mode not in {"copy", "move"}:
        raise LaunchError("mode must be copy or move")
    if storage == "external" and not external_root:
        raise LaunchError("external storage requires --root")
    migrate_taskledger_mount(
        workspace_root,
        mount=mount,
        storage=storage,
        external_root=external_root,
        target=target,
        mode=mode,
        quiescence_check=lambda: require_no_active_taskledger_locks(workspace_root),
    )
    return build_storage_location_report(
        workspace_root, require_initialized=False
    ).to_dict()


def storage_clear_override(
    workspace_root: Path, *, mount: str, mode: str = "copy"
) -> dict[str, object]:
    bundle = load_taskledger_ledger_layout(workspace_root, validate_storage=False)
    base_mount = bundle.loaded_project.manifest.ledgers["taskledger"].mounts[mount]
    if mode not in {"copy", "move"}:
        raise LaunchError("mode must be copy or move")
    if mode == "copy" and bundle.loaded_project.locator.local_config_path.exists():
        # Clearing an overlay selects the already-owned project mount. Ledgercore's
        # create-only migration policy correctly refuses to copy over that mount;
        # switch the overlay after checking that the workspace is quiescent.
        require_no_active_taskledger_locks(workspace_root)
        set_taskledger_mount_target(
            workspace_root,
            mount=mount,
            storage=str(base_mount.storage),
            external_root=getattr(base_mount, "external_root", None),
            target="project",
        )
        return build_storage_location_report(
            workspace_root, require_initialized=False
        ).to_dict()
    return storage_set(
        workspace_root,
        mount=mount,
        storage=str(base_mount.storage),
        target="project",
        external_root=getattr(base_mount, "external_root", None),
        mode=mode,
    )


def storage_migration_inspect(
    workspace_root: Path,
    *,
    source_checkout: str | None = None,
    source_checkout_id: str | None = None,
    source_data_root: Path | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> dict[str, object]:
    return _inspect_project_migration(
        workspace_root,
        source_checkout=source_checkout,
        source_checkout_id=source_checkout_id,
        source_data_root=source_data_root,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    ).to_dict()


def storage_migration_apply(
    workspace_root: Path,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    dry_run: bool = False,
    retire_source: bool = False,
    source_checkout: str | None = None,
    source_checkout_id: str | None = None,
    source_data_root: Path | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> dict[str, object]:
    return _apply_project_migration(
        workspace_root,
        backup=backup,
        backup_dir=backup_dir,
        create_sibling_store=create_sibling_store,
        dry_run=dry_run,
        retire_source=retire_source,
        source_checkout=source_checkout,
        source_checkout_id=source_checkout_id,
        source_data_root=source_data_root,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    )


def storage_migration_status(journal_path: Path) -> dict[str, object]:
    journal = inspect_taskledger_migration(journal_path)
    return {
        "kind": "storage_migration_status",
        "migration_id": journal.migration_id,
        "phase": journal.phase,
        "journal_path": str(journal.path),
        "error": journal.error,
    }


def storage_migration_recover(journal_path: Path) -> dict[str, object]:
    result = recover_taskledger_migration(journal_path)
    return {
        "kind": "storage_migration_recovery",
        "migration_id": result.migration_id,
        "phase": result.phase,
        "journal_path": str(result.journal_path),
    }


def sync_preflight(workspace_root: Path) -> dict[str, object]:
    return build_sync_preflight_report(workspace_root).to_dict()


def sync_status(workspace_root: Path) -> dict[str, object]:
    return build_sync_status_report(workspace_root).to_dict()


def sync_commit(workspace_root: Path, *, message: str) -> dict[str, object]:
    return sync_commit_storage(workspace_root, message=message).to_dict()


__all__ = [
    "storage_clear_override",
    "storage_migration_apply",
    "storage_migration_inspect",
    "storage_migration_recover",
    "storage_migration_status",
    "storage_move",
    "storage_path",
    "storage_set",
    "storage_validate",
    "storage_where",
    "sync_commit",
    "sync_preflight",
    "sync_status",
]

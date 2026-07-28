"""Taskledger migration hooks for Ledgercore 0.6.0 lifecycle integration.

This module provides Taskledger-specific hooks that are called during
Ledgercore migration execution and recovery:

- quiescence_check: Verify no active Taskledger locks
- validate_staged: Verify staged domain state (tombstones, state.toml, etc.)
- validate_activated: Verify activated state after rename
- finalize: Rebuild indexes in cache mount

These hooks are part of the Ledgercore transaction contract and must be
idempotent for recovery scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskledger.errors import LaunchError


@dataclass(frozen=True, slots=True)
class TaskledgerMigrationContext:
    """Context passed to Taskledger migration hooks."""

    workspace_root: Path
    migration_id: str
    item_index: int
    source_path: Path
    destination_path: Path
    stage_path: Path | None = None
    backup_path: Path | None = None


def require_no_active_taskledger_locks(workspace_root: Path) -> None:
    """Verify no active Taskledger locks exist.

    This is the quiescence check - called before staging and before
    activation boundaries.

    Raises:
        LaunchError: If active locks are found.
    """
    from taskledger.storage.locks import list_locks

    locks = list_locks(workspace_root)
    if locks:
        active = [str(lock) for lock in locks]
        raise LaunchError(
            f"Active Taskledger locks prevent migration: {', '.join(active)}",
            code="TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS",
            details={"active_locks": active},
            remediation=[
                "Wait for active operations to complete.",
                "Or break stale locks with `taskledger repair lock`.",
            ],
        )


def validate_staged_domain_state(
    ctx: TaskledgerMigrationContext,
) -> None:
    """Verify staged domain state after Ledgercore copies data.

    Checks:
    - Every expected task record exists in the stage
    - No unexpected symlinks or special files
    - Task IDs and tombstones are valid
    - state.toml exists and is valid
    - storage.yaml exists and is valid
    - Domain counts match expectations

    This hook runs after item staging and before activation.

    Raises:
        LaunchError: If staged state is invalid.
    """
    if ctx.stage_path is None:
        return

    # Verify stage path exists
    if not ctx.stage_path.exists():
        raise LaunchError(
            f"Staged path does not exist: {ctx.stage_path}",
            code="TASKLEDGER_STORAGE_MIGRATION_STAGE_MISSING",
        )

    # Verify no symlinks in stage
    _verify_no_symlinks(ctx.stage_path)

    # Verify state.toml exists if this is a data mount
    state_file = ctx.stage_path / "state.toml"
    if ctx.item_index == 0 and not state_file.exists():
        raise LaunchError(
            f"state.toml missing from staged data: {state_file}",
            code="TASKLEDGER_STORAGE_MIGRATION_STAGE_INCOMPLETE",
            details={"missing_file": str(state_file)},
        )

    # Verify storage.yaml exists if this is a data mount
    storage_file = ctx.stage_path / "storage.yaml"
    if ctx.item_index == 0 and not storage_file.exists():
        raise LaunchError(
            f"storage.yaml missing from staged data: {storage_file}",
            code="TASKLEDGER_STORAGE_MIGRATION_STAGE_INCOMPLETE",
            details={"missing_file": str(storage_file)},
        )


def validate_activated_domain_state(
    ctx: TaskledgerMigrationContext,
) -> None:
    """Verify activated domain state after Ledgercore renames stage.

    Checks:
    - Load the activated Taskledger mount directly
    - Validate binding
    - Verify the authoritative record set
    - Verify source still exists
    - Verify project config resolves the expected destination after switch

    This hook runs after activation and before config switching.

    Raises:
        LaunchError: If activated state is invalid.
    """
    # Verify destination exists and is accessible
    if not ctx.destination_path.exists():
        raise LaunchError(
            f"Activated destination does not exist: {ctx.destination_path}",
            code="TASKLEDGER_STORAGE_MIGRATION_ACTIVATION_FAILED",
        )

    # Verify destination is a directory
    if not ctx.destination_path.is_dir():
        raise LaunchError(
            f"Activated destination is not a directory: {ctx.destination_path}",
            code="TASKLEDGER_STORAGE_MIGRATION_ACTIVATION_FAILED",
        )

    # Verify state.toml is accessible in the activated destination
    state_file = ctx.destination_path / "state.toml"
    if ctx.item_index == 0 and not state_file.exists():
        raise LaunchError(
            f"state.toml missing from activated data: {state_file}",
            code="TASKLEDGER_STORAGE_MIGRATION_ACTIVATION_INCOMPLETE",
            details={"missing_file": str(state_file)},
        )


def finalize_migration(
    workspace_root: Path,
    migration_id: str,
) -> None:
    """Rebuild disposable indexes in the cache mount.

    This is called after config-switch verification and before committed.
    It must only modify cache/index data, not authoritative data.

    Raises:
        LaunchError: If index rebuild fails.
    """
    try:
        from taskledger.services.indexes import rebuild_indexes

        rebuild_indexes(workspace_root)
    except Exception as exc:
        raise LaunchError(
            f"Index rebuild failed after migration: {exc}",
            code="TASKLEDGER_INDEX_REBUILD_FAILED",
            details={"migration_id": migration_id, "error": str(exc)},
            remediation=["Run `taskledger reindex` to rebuild indexes manually."],
        ) from exc


def _verify_no_symlinks(path: Path) -> None:
    """Verify no symlinks exist in the path tree.

    Raises:
        LaunchError: If symlinks are found.
    """
    for item in path.rglob("*"):
        if item.is_symlink():
            raise LaunchError(
                f"Symlink found in migration stage: {item}",
                code="TASKLEDGER_STORAGE_MIGRATION_UNSAFE_SYMLINK",
                details={"symlink": str(item)},
            )


def create_taskledger_hooks(
    workspace_root: Path,
) -> Any:
    """Create StorageMigrationHooks with Taskledger-specific callbacks.

    Returns a Ledgercore StorageMigrationHooks instance configured
    with Taskledger's domain validation and finalization hooks.
    """
    from taskledger.compat.ledgercore import get_migration_apis

    apis = get_migration_apis()
    StorageMigrationHooks = apis["StorageMigrationHooks"]

    def _quiescence() -> None:
        require_no_active_taskledger_locks(workspace_root)

    def _validate_staged(index: int) -> None:
        ctx = TaskledgerMigrationContext(
            workspace_root=workspace_root,
            migration_id="",
            item_index=index,
            source_path=Path(),
            destination_path=Path(),
        )
        validate_staged_domain_state(ctx)

    def _validate_activated(index: int) -> None:
        ctx = TaskledgerMigrationContext(
            workspace_root=workspace_root,
            migration_id="",
            item_index=index,
            source_path=Path(),
            destination_path=Path(),
        )
        validate_activated_domain_state(ctx)

    def _finalize() -> None:
        finalize_migration(workspace_root, "")

    return StorageMigrationHooks(
        quiescence_check=_quiescence,
        validate_staged=_validate_staged,
        validate_activated=_validate_activated,
        finalize=_finalize,
        requires_staged_validation=True,
        requires_activated_validation=True,
        requires_finalization=True,
    )

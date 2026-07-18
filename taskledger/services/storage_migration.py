"""Taskledger storage migration orchestration.

The CLI and public API use this module as the single migration entrypoint.
Storage-specific planning and execution remain behind the coordinator so the
callers cannot accidentally select different migration implementations.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from taskledger.storage.layout_migration import (
    TaskledgerMigrationInspection,
)
from taskledger.storage.layout_migration import (
    apply_migration as _apply_migration,
)
from taskledger.storage.layout_migration import (
    inspect_migration as _inspect_migration,
)


def inspect_migration(
    start: Path,
    *,
    source_checkout: str | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> TaskledgerMigrationInspection:
    """Inspect the project migration without changing the filesystem."""
    return _inspect_migration(
        start,
        source_checkout=source_checkout,
        environ=environ,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    )


def apply_migration(
    start: Path,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    dry_run: bool = False,
    retire_source: bool = False,
    source_checkout: str | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> dict[str, object]:
    """Inspect and apply one project migration through one coordinator."""
    inspection = inspect_migration(
        start,
        source_checkout=source_checkout,
        environ=environ,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    )
    if dry_run:
        return {
            "kind": "taskledger_migration_inspection",
            "status": "dry_run",
            "inspection": inspection.to_dict(),
        }
    return _apply_migration(
        inspection,
        backup=backup,
        backup_dir=backup_dir,
        create_sibling_store=create_sibling_store,
        retire_source=retire_source,
    )


__all__ = ["TaskledgerMigrationInspection", "apply_migration", "inspect_migration"]

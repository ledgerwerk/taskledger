"""Taskledger storage migration orchestration.

The CLI and public API use this module as the single migration entrypoint.
Storage-specific planning and execution remain behind the coordinator so the
callers cannot accidentally select different migration implementations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class MigrationOptions:
    sibling_ledger_root: Path | None = None
    source_data_root: Path | None = None
    source_checkout_id: str | None = None
    project_uuid: str | None = None
    create_sibling_store: bool = False
    adopt_sibling_store: bool = False


def inspect_migration(
    start: Path,
    *,
    options: MigrationOptions | None = None,
    source_checkout: str | None = None,
    source_checkout_id: str | None = None,
    source_data_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> TaskledgerMigrationInspection:
    """Inspect the project migration without changing the filesystem."""
    selected = options or MigrationOptions(
        sibling_ledger_root=sibling_ledger_root,
        source_data_root=source_data_root,
        source_checkout_id=source_checkout_id or source_checkout,
        project_uuid=project_uuid,
    )
    return _inspect_migration(
        start,
        source_checkout_id=selected.source_checkout_id,
        source_data_root=selected.source_data_root,
        environ=environ,
        project_uuid=selected.project_uuid,
        sibling_ledger_root=selected.sibling_ledger_root,
        create_sibling_store=selected.create_sibling_store,
        adopt_sibling_store=selected.adopt_sibling_store,
    )


def apply_migration(
    start: Path,
    *,
    options: MigrationOptions | None = None,
    backup: bool = True,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    dry_run: bool = False,
    retire_source: bool = False,
    source_checkout: str | None = None,
    source_checkout_id: str | None = None,
    source_data_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> dict[str, object]:
    """Inspect and apply one project migration through one coordinator."""
    selected = options or MigrationOptions(
        sibling_ledger_root=sibling_ledger_root,
        source_data_root=source_data_root,
        source_checkout_id=source_checkout_id or source_checkout,
        project_uuid=project_uuid,
        create_sibling_store=create_sibling_store,
    )
    inspection = inspect_migration(start, options=selected, environ=environ)
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
        create_sibling_store=selected.create_sibling_store,
        adopt_sibling_store=selected.adopt_sibling_store,
        retire_source=retire_source,
    )


__all__ = [
    "MigrationOptions",
    "TaskledgerMigrationInspection",
    "apply_migration",
    "inspect_migration",
]

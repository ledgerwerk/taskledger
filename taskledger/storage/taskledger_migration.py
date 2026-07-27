"""Taskledger domain orchestration around Ledgercore storage migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskledger.storage.ledgercore_backend import (
    execute_taskledger_layout_migration,
)
from taskledger.storage.paths import probe_taskledger_project


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TaskledgerMigrationPlan:
    ledgercore_plan: Any | None
    domain_plan: Any | None
    active_lock_count: int
    blockers: tuple[MigrationIssue, ...]
    warnings: tuple[MigrationIssue, ...]


def require_no_active_taskledger_locks(project_root: Path) -> None:
    probe = probe_taskledger_project(project_root)
    if probe.source == "canonical" and not probe.registration_present:
        return
    from taskledger.services.lock_inventory import (
        build_lock_inventory,
        require_migration_safe_locks,
    )
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(project_root)
    inventory = build_lock_inventory(paths)
    require_migration_safe_locks(inventory, project_root=project_root)


def execute_taskledger_migration(
    plan: Any,
    *,
    project_root: Path,
    mode: str = "move",
) -> Any:
    return execute_taskledger_layout_migration(
        plan,
        mode=mode,
        project_root=project_root,
        quiescence_check=lambda: require_no_active_taskledger_locks(project_root),
    )


__all__ = [
    "MigrationIssue",
    "TaskledgerMigrationPlan",
    "execute_taskledger_migration",
    "require_no_active_taskledger_locks",
]

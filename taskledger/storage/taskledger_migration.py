"""Taskledger domain orchestration around Ledgercore storage migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskledger.errors import LaunchError
from taskledger.storage.ledgercore_backend import (
    execute_taskledger_layout_migration,
)
from taskledger.storage.task_store import load_active_locks


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
    locks = load_active_locks(project_root)
    if locks:
        raise LaunchError(
            f"Taskledger storage migration is blocked by {len(locks)} active lock(s).",
            code="TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS",
            details={"active_lock_count": len(locks)},
        )


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

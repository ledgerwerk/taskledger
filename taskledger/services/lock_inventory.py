"""Unified lock inventory: enumerate, read, diagnose, classify.

The inventory reads every ``task-*/lock.yaml`` once, preserves parse errors
per file, and diagnoses each readable lock.  Callers no longer need to
catch ``LaunchError`` and silently return zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from taskledger.domain.actor import ActorRef
from taskledger.domain.models import TaskLock
from taskledger.errors import LaunchError
from taskledger.services.lock_diagnostics import (
    CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
    CLASSIFICATION_ACTIVE_HARNESS_SESSION,
    CLASSIFICATION_ACTIVE_LIVE_LOCAL_PROCESS,
    CLASSIFICATION_ACTIVE_NO_PID,
    CLASSIFICATION_ACTIVE_OTHER_ACTOR,
    CLASSIFICATION_ACTIVE_SAME_ACTOR,
    CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS,
    CLASSIFICATION_EXPIRED,
    CLASSIFICATION_NONE,
    LockDiagnostics,
    diagnose_lock,
)
from taskledger.storage.locks import lock_is_expired, read_lock
from taskledger.storage.task_store import V2Paths

logger = logging.getLogger(__name__)

# Classifications that are safe to repair automatically.
SAFE_REPAIR_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        CLASSIFICATION_EXPIRED,
        CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
    }
)

# Classifications that block migration (non-safe active locks).
ACTIVE_BLOCKING_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        CLASSIFICATION_ACTIVE_LIVE_LOCAL_PROCESS,
        CLASSIFICATION_ACTIVE_SAME_ACTOR,
        CLASSIFICATION_ACTIVE_HARNESS_SESSION,
        CLASSIFICATION_ACTIVE_OTHER_ACTOR,
        CLASSIFICATION_ACTIVE_NO_PID,
        CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS,
    }
)


@dataclass(frozen=True, slots=True)
class LockInventoryEntry:
    task_id: str | None
    path: Path
    lock: TaskLock | None
    diagnostics: LockDiagnostics | None
    parse_error: str | None

    @property
    def is_malformed(self) -> bool:
        return self.parse_error is not None

    @property
    def is_expired(self) -> bool:
        if self.lock is None:
            return False
        try:
            return lock_is_expired(self.lock)
        except LaunchError:
            return False

    @property
    def is_active(self) -> bool:
        if self.lock is None:
            return False
        return not self.is_expired

    @property
    def classification(self) -> str:
        if self.diagnostics is not None:
            return self.diagnostics.classification
        if self.is_malformed:
            return "malformed"
        return CLASSIFICATION_NONE

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "task_id": self.task_id,
            "path": str(self.path),
            "classification": self.classification,
        }
        if self.lock is not None:
            result["lock"] = self.lock.to_dict()
        if self.diagnostics is not None:
            result["diagnostics"] = self.diagnostics.to_dict()
        if self.parse_error is not None:
            result["parse_error"] = self.parse_error
        return result


@dataclass(frozen=True, slots=True)
class LockInventory:
    entries: tuple[LockInventoryEntry, ...]

    @property
    def lock_file_count(self) -> int:
        return len(self.entries)

    @property
    def active_count(self) -> int:
        return sum(1 for e in self.entries if e.is_active and not e.is_malformed)

    @property
    def expired_count(self) -> int:
        return sum(1 for e in self.entries if e.is_expired)

    @property
    def stale_count(self) -> int:
        """Expired or dead local owner."""
        stale_classifications = {
            CLASSIFICATION_EXPIRED,
            CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
        }
        return sum(1 for e in self.entries if e.classification in stale_classifications)

    @property
    def malformed_count(self) -> int:
        return sum(1 for e in self.entries if e.is_malformed)

    @property
    def unverifiable_count(self) -> int:
        return sum(
            1
            for e in self.entries
            if e.classification
            == CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
        )

    @property
    def no_pid_count(self) -> int:
        return sum(
            1 for e in self.entries if e.classification == CLASSIFICATION_ACTIVE_NO_PID
        )

    @property
    def harness_session_count(self) -> int:
        return sum(
            1
            for e in self.entries
            if e.classification == CLASSIFICATION_ACTIVE_HARNESS_SESSION
        )

    @property
    def other_actor_count(self) -> int:
        return sum(
            1
            for e in self.entries
            if e.classification == CLASSIFICATION_ACTIVE_OTHER_ACTOR
        )

    @property
    def migration_blockers(self) -> tuple[LockInventoryEntry, ...]:
        """Entries that block migration (malformed or active non-safe)."""
        return tuple(
            e
            for e in self.entries
            if e.is_malformed or e.classification in ACTIVE_BLOCKING_CLASSIFICATIONS
        )

    @property
    def safe_repairable(self) -> tuple[LockInventoryEntry, ...]:
        """Entries that can be safely repaired automatically."""
        return tuple(
            e for e in self.entries if e.classification in SAFE_REPAIR_CLASSIFICATIONS
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "lock_file_count": self.lock_file_count,
            "active_count": self.active_count,
            "expired_count": self.expired_count,
            "stale_count": self.stale_count,
            "malformed_count": self.malformed_count,
            "unverifiable_count": self.unverifiable_count,
            "no_pid_count": self.no_pid_count,
            "harness_session_count": self.harness_session_count,
            "other_actor_count": self.other_actor_count,
            "entries": [e.to_dict() for e in self.entries],
        }


def build_lock_inventory(
    paths: V2Paths,
    *,
    current_actor: ActorRef | None = None,
) -> LockInventory:
    """Build a lock inventory by reading every ``task-*/lock.yaml``.

    Parse errors are preserved per-file and never silenced.
    """
    entries: list[LockInventoryEntry] = []
    for lock_path in sorted(paths.tasks_dir.glob("task-*/lock.yaml")):
        parent_name = lock_path.parent.name
        task_id = parent_name if parent_name.startswith("task-") else None
        lock: TaskLock | None = None
        parse_error: str | None = None
        try:
            lock = read_lock(lock_path)
        except Exception as exc:
            parse_error = f"Failed to read lock {lock_path}: {exc}"
            logger.warning("Malformed lock file %s: %s", lock_path, exc)

        diagnostics: LockDiagnostics | None = None
        if lock is not None:
            try:
                diagnostics = diagnose_lock(
                    lock,
                    task_id=task_id,
                    current_actor=current_actor,
                )
            except Exception as exc:
                parse_error = f"Failed to diagnose lock {lock_path}: {exc}"
                logger.warning("Lock diagnosis failed %s: %s", lock_path, exc)

        entries.append(
            LockInventoryEntry(
                task_id=task_id,
                path=lock_path,
                lock=lock,
                diagnostics=diagnostics,
                parse_error=parse_error,
            )
        )

    return LockInventory(entries=tuple(entries))


def require_migration_safe_locks(
    inventory: LockInventory,
    *,
    project_root: Path,
) -> None:
    """Raise LaunchError if any locks block migration.

    Blocks on:
    - malformed lock files
    - active locks in non-safe classifications
    """
    if inventory.lock_file_count == 0:
        return

    blockers = inventory.migration_blockers
    if not blockers:
        return

    details: dict[str, object] = {
        "lock_file_count": inventory.lock_file_count,
        "active_count": inventory.active_count,
        "expired_count": inventory.expired_count,
        "malformed_count": inventory.malformed_count,
        "stale_count": inventory.stale_count,
        "blocker_task_ids": [e.task_id for e in blockers if e.task_id is not None],
        "blocker_classifications": [e.classification for e in blockers],
    }

    has_malformed = inventory.malformed_count > 0
    has_active_blockers = any(
        e.classification in ACTIVE_BLOCKING_CLASSIFICATIONS for e in blockers
    )

    if has_malformed:
        raise LaunchError(
            f"Taskledger storage migration is blocked by "
            f"{inventory.malformed_count} malformed lock file(s) and "
            f"{inventory.active_count} active lock(s). "
            f"Repair malformed locks and stale locks before migrating.",
            code="TASKLEDGER_STORAGE_MIGRATION_LOCK_STATE_INVALID",
            details=details,
        )

    if has_active_blockers:
        raise LaunchError(
            f"Taskledger storage migration is blocked by "
            f"{inventory.active_count} active lock(s). "
            f"Break stale locks with `taskledger repair locks --apply` "
            f"or individually with `taskledger repair lock --task <id>`.",
            code="TASKLEDGER_STORAGE_MIGRATION_ACTIVE_LOCKS",
            details=details,
        )

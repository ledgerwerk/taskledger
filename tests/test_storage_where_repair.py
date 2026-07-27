"""Tests for storage where diagnostics and repair improvements.

Covers acceptance criteria from the storage-where-repair brief:
- Lock inventory semantics (expired != active, malformed tracking)
- Mode-aware rendering (legacy vs canonical)
- Git path-state diagnostics
- Migration identity determinism
- Project identity repair
- Config immutability
- Bulk lock repair safety
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from taskledger.api.config import config_set
from taskledger.api.repair import repair_locks, repair_project_identity
from taskledger.domain.lock import TaskLock
from taskledger.errors import LaunchError
from taskledger.services.lock_inventory import build_lock_inventory
from taskledger.services.storage_locations import build_storage_location_report
from taskledger.storage.locks import lock_status
from taskledger.storage.task_store import resolve_v2_paths
from tests.support.builders import init_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _make_lock_payload(
    task_id: str,
    *,
    expired: bool = False,
    pid: int | None = 12345,
    actor_type: str = "agent",
    actor_name: str = "test-agent",
) -> dict:
    """Build a valid lock YAML payload."""
    now = datetime.now(timezone.utc)
    expires_at = (
        (now - timedelta(hours=1)).isoformat()
        if expired
        else (now + timedelta(hours=1)).isoformat()
    )
    return {
        "schema_version": 1,
        "object_type": "lock",
        "file_version": "v2",
        "lock_id": f"lock-{task_id}",
        "task_id": task_id,
        "stage": "implementing",
        "run_type": "implementation",
        "run_id": f"run-{task_id}",
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "lease_seconds": 7200,
        "reason": "implementation",
        "holder": {
            "actor_type": actor_type,
            "actor_name": actor_name,
            "host": "localhost",
            "pid": pid,
        },
    }


def _write_lock_yaml(
    tasks_dir: Path,
    task_id: str,
    *,
    expired: bool = False,
    pid: int | None = 12345,
    actor_type: str = "agent",
    actor_name: str = "test-agent",
) -> Path:
    """Write a lock.yaml for testing."""
    lock_dir = tasks_dir / task_id
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "lock.yaml"
    payload = _make_lock_payload(
        task_id,
        expired=expired,
        pid=pid,
        actor_type=actor_type,
        actor_name=actor_name,
    )
    lock_path.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    return lock_path


def _write_malformed_lock_yaml(tasks_dir: Path, task_id: str) -> Path:
    """Write a malformed lock.yaml."""
    lock_dir = tasks_dir / task_id
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "lock.yaml"
    lock_path.write_text("{{invalid yaml content", encoding="utf-8")
    return lock_path


def _remove_project_uuid(config_path: Path) -> None:
    """Remove project_uuid line from a TOML config file."""
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        lines = [
            line
            for line in text.splitlines()
            if not line.strip().startswith("project_uuid")
        ]
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Lock status semantics
# ---------------------------------------------------------------------------


class TestLockStatusSemantics:
    """Defect 1: 'Active locks' means non-expired locks."""

    def test_lock_status_active_when_not_expired(self) -> None:
        """Active lock returns active=True, expired=False."""
        from taskledger.domain.actor import ActorRef

        now = datetime.now(timezone.utc)
        lock = TaskLock(
            lock_id="lock-1",
            task_id="task-0001",
            stage="implementing",
            run_id="run-1",
            holder=ActorRef(
                actor_type="agent",
                actor_name="test",
                host="localhost",
                pid=1234,
            ),
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=1)).isoformat(),
            reason="implementation",
        )
        status = lock_status(lock)
        assert status["present"] is True
        assert status["active"] is True
        assert status["expired"] is False

    def test_lock_status_inactive_when_expired(self) -> None:
        """Expired lock returns active=False, expired=True."""
        from taskledger.domain.actor import ActorRef

        now = datetime.now(timezone.utc)
        lock = TaskLock(
            lock_id="lock-1",
            task_id="task-0001",
            stage="implementing",
            run_id="run-1",
            holder=ActorRef(
                actor_type="agent",
                actor_name="test",
                host="localhost",
                pid=1234,
            ),
            created_at=(now - timedelta(hours=2)).isoformat(),
            expires_at=(now - timedelta(hours=1)).isoformat(),
            reason="implementation",
        )
        status = lock_status(lock)
        assert status["present"] is True
        assert status["active"] is False
        assert status["expired"] is True

    def test_lock_status_absent(self) -> None:
        """No lock returns present=False."""
        status = lock_status(None)
        assert status["present"] is False
        assert status["active"] is False
        assert status["expired"] is False


# ---------------------------------------------------------------------------
# Lock inventory
# ---------------------------------------------------------------------------


class TestLockInventory:
    """Defect 2 & 3: Lock inventory tracks all locks and preserves errors."""

    def test_lock_inventory_counts_expired_separately(
        self, tmp_path: Path
    ) -> None:
        """Expired locks are not counted as active."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        # Write one active and one expired lock.
        _write_lock_yaml(paths.tasks_dir, "task-0001", expired=False)
        _write_lock_yaml(paths.tasks_dir, "task-0002", expired=True)

        inventory = build_lock_inventory(paths)
        assert inventory.lock_file_count == 2
        assert inventory.active_count == 1
        assert inventory.expired_count == 1

    def test_lock_inventory_keeps_parse_error_path(
        self, tmp_path: Path
    ) -> None:
        """Malformed lock files are tracked with their path and error."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        _write_malformed_lock_yaml(paths.tasks_dir, "task-0001")

        inventory = build_lock_inventory(paths)
        assert inventory.malformed_count == 1
        assert inventory.lock_file_count == 1

        entry = inventory.entries[0]
        assert entry.is_malformed is True
        assert entry.parse_error is not None
        assert "task-0001" in str(entry.path)

    def test_lock_inventory_classifies_dead_local_owner(
        self, tmp_path: Path
    ) -> None:
        """Lock with non-running PID is classified as dead local process."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        # Use a PID that is almost certainly not running.
        _write_lock_yaml(paths.tasks_dir, "task-0001", pid=999999999)

        inventory = build_lock_inventory(paths)
        assert inventory.lock_file_count == 1

        entry = inventory.entries[0]
        assert entry.classification in {
            "active_dead_local_process",
            "active_unverifiable_remote_or_unknown_process",
        }

    def test_lock_inventory_migration_blockers(self, tmp_path: Path) -> None:
        """Migration blockers include malformed and active non-safe locks."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        _write_malformed_lock_yaml(paths.tasks_dir, "task-0001")
        _write_lock_yaml(paths.tasks_dir, "task-0002", expired=True)

        inventory = build_lock_inventory(paths)
        blockers = inventory.migration_blockers
        # Malformed is a blocker, expired is not.
        assert len(blockers) == 1
        assert blockers[0].is_malformed is True

    def test_lock_inventory_safe_repairable(self, tmp_path: Path) -> None:
        """Safe repairable includes expired and dead local process."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        _write_lock_yaml(paths.tasks_dir, "task-0001", expired=True)
        _write_lock_yaml(paths.tasks_dir, "task-0002", expired=False)

        inventory = build_lock_inventory(paths)
        safe = inventory.safe_repairable
        # Expired is safe; the non-expired one may also be safe
        # if it's classified as dead_local_process.
        assert len(safe) >= 1
        expired_entries = [e for e in safe if e.is_expired]
        assert len(expired_entries) == 1


# ---------------------------------------------------------------------------
# Storage where mode-aware rendering
# ---------------------------------------------------------------------------


class TestStorageWhereRendering:
    """Defect 5: Storage where is mode-aware."""

    def test_legacy_storage_where_has_legacy_fields(
        self, tmp_path: Path
    ) -> None:
        """Legacy storage report includes workspace, config, storage paths."""
        init_workspace(tmp_path)
        report = build_storage_location_report(tmp_path)
        payload = report.to_dict()

        assert payload["mode"] == "legacy"
        assert "workspace_root" in payload
        assert "config_path" in payload
        assert "taskledger_dir" in payload

    def test_legacy_storage_where_no_manifest_section(
        self, tmp_path: Path
    ) -> None:
        """Legacy report does not include canonical manifest section."""
        init_workspace(tmp_path)
        report = build_storage_location_report(tmp_path)
        payload = report.to_dict()

        # Legacy mode should not have manifest key.
        assert "manifest" not in payload or payload.get("manifest") is None

    def test_storage_where_lock_breakdown(self, tmp_path: Path) -> None:
        """Storage report includes lock breakdown with correct counts."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        _write_lock_yaml(paths.tasks_dir, "task-0001", expired=False)
        _write_lock_yaml(paths.tasks_dir, "task-0002", expired=True)

        report = build_storage_location_report(tmp_path)
        payload = report.to_dict()

        assert payload["lock_file_count"] == 2
        assert payload["active_lock_count"] == 1
        assert payload["expired_lock_count"] == 1


# ---------------------------------------------------------------------------
# Git path-state diagnostics
# ---------------------------------------------------------------------------


class TestGitPathState:
    """Defect 6: Git warning is based on actual Git state."""

    def test_storage_where_includes_git_state(self, tmp_path: Path) -> None:
        """Storage report includes Git tracked/ignored state."""
        init_workspace(tmp_path)
        report = build_storage_location_report(tmp_path)
        payload = report.to_dict()

        # In a fresh tmp dir, Git state should be detectable.
        assert "git_tracked" in payload or "git" in payload


# ---------------------------------------------------------------------------
# Migration identity
# ---------------------------------------------------------------------------


class TestMigrationIdentity:
    """Defect 4: Migration inspection is deterministic for missing UUID."""

    def test_migration_inspect_missing_uuid_is_blocked(
        self, tmp_path: Path
    ) -> None:
        """Missing project UUID produces a blocker, not a random UUID."""
        from taskledger.storage.layout_migration import inspect_migration

        init_workspace(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        _remove_project_uuid(config_path)

        result = inspect_migration(tmp_path)
        result_dict = result.to_dict()

        # Should be blocked.
        assert result_dict["status"] == "blocked"

        # Should have PROJECT_UUID_MISSING issue.
        issue_codes = [i["code"] for i in result_dict.get("issues", [])]
        assert "PROJECT_UUID_MISSING" in issue_codes

        # Project UUID should be None.
        assert result_dict["project"]["uuid"] is None

    def test_migration_inspect_deterministic(self, tmp_path: Path) -> None:
        """Two consecutive inspections return the same result."""
        from taskledger.storage.layout_migration import inspect_migration

        init_workspace(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        _remove_project_uuid(config_path)

        first = inspect_migration(tmp_path).to_dict()
        second = inspect_migration(tmp_path).to_dict()

        assert first == second


# ---------------------------------------------------------------------------
# Project identity repair
# ---------------------------------------------------------------------------


class TestProjectIdentityRepair:
    """P0: Project identity repair generates and persists UUID atomically."""

    def test_repair_project_identity_read_only(self, tmp_path: Path) -> None:
        """Read-only mode reports missing UUID without mutation."""
        init_workspace(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        _remove_project_uuid(config_path)

        result = repair_project_identity(tmp_path, apply=False)
        assert result["status"] == "missing"
        assert result["changed"] is False
        assert result["project_uuid"] is None

    def test_repair_project_identity_apply_generates_uuid(
        self, tmp_path: Path
    ) -> None:
        """Apply mode generates and persists a UUID."""
        init_workspace(tmp_path)
        config_path = tmp_path / "taskledger.toml"
        _remove_project_uuid(config_path)

        result = repair_project_identity(tmp_path, apply=True)
        assert result["status"] == "generated"
        assert result["changed"] is True
        assert result["project_uuid"] is not None

        # Verify persistence.
        from taskledger.storage.project_identity import load_project_uuid

        persisted = load_project_uuid(config_path)
        assert persisted == result["project_uuid"]

    def test_repair_project_identity_idempotent(self, tmp_path: Path) -> None:
        """Repair is idempotent when UUID already exists."""
        init_workspace(tmp_path)

        result = repair_project_identity(tmp_path, apply=True)
        assert result["status"] == "present"
        assert result["changed"] is False
        assert result["project_uuid"] is not None


# ---------------------------------------------------------------------------
# Config immutability
# ---------------------------------------------------------------------------


class TestConfigImmutability:
    """Defect 7: project_uuid is immutable via config set."""

    def test_config_set_rejects_project_uuid(self, tmp_path: Path) -> None:
        """config set rejects project_uuid as immutable."""
        init_workspace(tmp_path)

        with pytest.raises(LaunchError, match="immutable"):
            config_set(tmp_path, key="project_uuid", value_text='"new-uuid"')


# ---------------------------------------------------------------------------
# Bulk lock repair
# ---------------------------------------------------------------------------


class TestBulkLockRepair:
    """P1: Bulk lock repair is safe and defaults to dry-run."""

    def test_bulk_lock_repair_dry_run(self, tmp_path: Path) -> None:
        """Dry-run reports what would be repaired without mutation."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        _write_lock_yaml(paths.tasks_dir, "task-0001", expired=True)

        result = repair_locks(tmp_path, apply=False, reason="")
        assert result["dry_run"] is True
        assert result["status"] == "dry_run"
        assert result["safe_repairable"] >= 1

    def test_bulk_lock_repair_requires_reason_for_apply(
        self, tmp_path: Path
    ) -> None:
        """Apply mode requires a non-empty reason."""
        init_workspace(tmp_path)
        paths = resolve_v2_paths(tmp_path)

        _write_lock_yaml(paths.tasks_dir, "task-0001", expired=True)

        with pytest.raises(LaunchError, match="reason"):
            repair_locks(tmp_path, apply=True, reason="")

    def test_bulk_lock_repair_nothing_to_repair(self, tmp_path: Path) -> None:
        """No safe locks returns nothing_to_repair status."""
        init_workspace(tmp_path)

        result = repair_locks(tmp_path, apply=False, reason="")
        assert result["status"] == "nothing_to_repair"
        assert result["safe_repairable"] == 0


# ---------------------------------------------------------------------------
# Command inventory
# ---------------------------------------------------------------------------


class TestCommandInventory:
    """Repair commands are registered in command inventory."""

    def test_repair_project_identity_registered(self) -> None:
        """repair project-identity is in command inventory."""
        from taskledger.command_inventory import COMMAND_METADATA

        assert "repair project-identity" in COMMAND_METADATA

    def test_repair_locks_registered(self) -> None:
        """repair locks is in command inventory."""
        from taskledger.command_inventory import COMMAND_METADATA

        assert "repair locks" in COMMAND_METADATA

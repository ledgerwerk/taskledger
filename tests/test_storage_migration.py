"""Tests for storage version enforcement, migration framework, and migrate CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.domain.models import (
    ActiveActorState,
    ActiveHarnessState,
    ActiveTaskState,
    DependencyRequirement,
    FileLink,
    TaskTodo,
)
from taskledger.domain.states import (
    TASKLEDGER_RECORD_SCHEMA_VERSION,
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_STORAGE_LAYOUT_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
)
from taskledger.errors import LaunchError
from taskledger.storage.meta import StorageMeta, read_storage_meta, write_storage_meta

# ---------------------------------------------------------------------------
# Phase 2: Storage version constants
# ---------------------------------------------------------------------------


class TestStorageVersionConstants:
    # specmason: req=REQ-0054 ac=AC-0590
    def test_storage_layout_version_is_5(self) -> None:
        assert TASKLEDGER_STORAGE_LAYOUT_VERSION == 5

    # specmason: req=REQ-0054 ac=AC-0583
    def test_record_schema_version_matches_schema_version(self) -> None:
        assert TASKLEDGER_RECORD_SCHEMA_VERSION == TASKLEDGER_SCHEMA_VERSION

    # specmason: req=REQ-0054 ac=AC-0587
    def test_schema_version_is_1(self) -> None:
        assert TASKLEDGER_SCHEMA_VERSION == 1

    # specmason: req=REQ-0054 ac=AC-0594
    def test_v2_file_version(self) -> None:
        assert TASKLEDGER_V2_FILE_VERSION == "v2"


# ---------------------------------------------------------------------------
# Phase 2: StorageMeta read/write
# ---------------------------------------------------------------------------


class TestStorageMeta:
    # specmason: req=REQ-0054 ac=AC-0586
    def test_roundtrip(self, tmp_path: Path) -> None:
        meta = StorageMeta(created_with_taskledger="0.1.0")
        write_storage_meta(tmp_path, meta)
        loaded = read_storage_meta(tmp_path)
        assert loaded is not None
        assert loaded.storage_layout_version == TASKLEDGER_STORAGE_LAYOUT_VERSION
        assert loaded.record_schema_version == TASKLEDGER_RECORD_SCHEMA_VERSION
        assert loaded.created_with_taskledger == "0.1.0"

    # specmason: req=REQ-0054 ac=AC-0563
    def test_missing_storage_yaml_returns_none(self, tmp_path: Path) -> None:
        assert read_storage_meta(tmp_path) is None

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        tl_dir = tmp_path / ".taskledger"
        tl_dir.mkdir()
        (tl_dir / "storage.yaml").write_text("not: valid: yaml: [", encoding="utf-8")
        with pytest.raises(LaunchError, match="Invalid storage.yaml"):
            read_storage_meta(tmp_path)

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        tl_dir = tmp_path / ".taskledger"
        tl_dir.mkdir()
        (tl_dir / "storage.yaml").write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(LaunchError, match="must contain a YAML mapping"):
            read_storage_meta(tmp_path)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        tl_dir = tmp_path / ".taskledger"
        tl_dir.mkdir()
        (tl_dir / "storage.yaml").write_text(
            "storage_layout_version: 2\n", encoding="utf-8"
        )
        with pytest.raises(LaunchError, match="Missing or invalid"):
            read_storage_meta(tmp_path)

    # specmason: req=REQ-0054 ac=AC-0591
    def test_to_dict_keys(self) -> None:
        meta = StorageMeta()
        d = meta.to_dict()
        assert "storage_layout_version" in d
        assert "record_schema_version" in d
        assert "created_with_taskledger" in d
        assert "created_at" in d


# ---------------------------------------------------------------------------
# Phase 2: Active state models include file_version
# ---------------------------------------------------------------------------


class TestActiveStateFileVersion:
    # specmason: req=REQ-0054 ac=AC-0561
    def test_active_task_state_has_file_version(self) -> None:
        state = ActiveTaskState(task_id="task-0001")
        d = state.to_dict()
        assert d["file_version"] == TASKLEDGER_V2_FILE_VERSION

    # specmason: req=REQ-0054 ac=AC-0562
    # specmason: req=REQ-0054 ac=AC-0588
    # specmason: req=REQ-0054 ac=AC-0589
    def test_active_actor_state_has_file_version(self) -> None:
        state = ActiveActorState()
        d = state.to_dict()
        assert d["file_version"] == TASKLEDGER_V2_FILE_VERSION

    # specmason: req=REQ-0054 ac=AC-0561
    def test_active_harness_state_has_file_version(self) -> None:
        state = ActiveHarnessState()
        d = state.to_dict()
        assert d["file_version"] == TASKLEDGER_V2_FILE_VERSION

    # specmason: req=REQ-0054 ac=AC-0562
    def test_active_task_roundtrip_with_file_version(self) -> None:
        state = ActiveTaskState(task_id="task-0001")
        restored = ActiveTaskState.from_dict(state.to_dict())
        assert restored.file_version == TASKLEDGER_V2_FILE_VERSION

    # specmason: req=REQ-0054 ac=AC-0561
    def test_active_task_legacy_no_file_version(self) -> None:
        data = {
            "schema_version": 1,
            "object_type": "active_task",
            "task_id": "task-0001",
            "activated_at": "2026-01-01T00:00:00+00:00",
            "activated_by": {"actor_type": "agent", "actor_name": "test"},
        }
        state = ActiveTaskState.from_dict(data)
        assert state.file_version == TASKLEDGER_V2_FILE_VERSION


# ---------------------------------------------------------------------------
# Phase 2: Sidecar model version enforcement
# ---------------------------------------------------------------------------


class TestSidecarVersionEnforcement:
    # specmason: req=REQ-0054 ac=AC-0593
    def test_todo_accepts_valid_v2(self) -> None:
        todo = TaskTodo.from_dict(
            {
                "id": "todo-0001",
                "text": "test",
                "schema_version": 1,
                "object_type": "todo",
                "file_version": "v2",
            }
        )
        assert todo.id == "todo-0001"

    # specmason: req=REQ-0054 ac=AC-0592
    def test_todo_accepts_legacy_no_version(self) -> None:
        todo = TaskTodo.from_dict({"id": "todo-0001", "text": "test"})
        assert todo.id == "todo-0001"

    def test_todo_rejects_too_new_schema(self) -> None:
        with pytest.raises(LaunchError, match="schema too new"):
            TaskTodo.from_dict(
                {
                    "id": "todo-0001",
                    "text": "test",
                    "schema_version": 99,
                    "object_type": "todo",
                    "file_version": "v2",
                }
            )

    def test_todo_rejects_wrong_object_type(self) -> None:
        with pytest.raises(LaunchError, match="Invalid object_type"):
            TaskTodo.from_dict(
                {
                    "id": "todo-0001",
                    "text": "test",
                    "schema_version": 1,
                    "object_type": "wrong",
                    "file_version": "v2",
                }
            )

    # specmason: req=REQ-0054 ac=AC-0592
    def test_todo_rejects_wrong_file_version(self) -> None:
        with pytest.raises(LaunchError, match="Unsupported file version"):
            TaskTodo.from_dict(
                {
                    "id": "todo-0001",
                    "text": "test",
                    "schema_version": 1,
                    "object_type": "todo",
                    "file_version": "v99",
                }
            )

    # specmason: req=REQ-0054 ac=AC-0568
    def test_link_accepts_valid_v2(self) -> None:
        link = FileLink.from_dict(
            {
                "path": "/foo.py",
                "schema_version": 1,
                "object_type": "link",
                "file_version": "v2",
            }
        )
        assert link.path == "/foo.py"

    # specmason: req=REQ-0054 ac=AC-0567
    def test_link_accepts_legacy_no_version(self) -> None:
        link = FileLink.from_dict({"path": "/foo.py"})
        assert link.path == "/foo.py"

    # specmason: req=REQ-0054 ac=AC-0565
    def test_link_rejects_too_new_schema(self) -> None:
        with pytest.raises(LaunchError, match="schema too new"):
            FileLink.from_dict(
                {
                    "path": "/foo.py",
                    "schema_version": 99,
                    "object_type": "link",
                    "file_version": "v2",
                }
            )

    # specmason: req=REQ-0054 ac=AC-0585
    def test_requirement_accepts_valid_v2(self) -> None:
        req = DependencyRequirement.from_dict(
            {
                "task_id": "task-0001",
                "schema_version": 1,
                "object_type": "requirement",
                "file_version": "v2",
            }
        )
        assert req.task_id == "task-0001"

    # specmason: req=REQ-0054 ac=AC-0584
    def test_requirement_accepts_legacy_no_version(self) -> None:
        req = DependencyRequirement.from_dict({"task_id": "task-0001"})
        assert req.task_id == "task-0001"

    # specmason: req=REQ-0054 ac=AC-0585
    def test_requirement_rejects_too_new_schema(self) -> None:
        with pytest.raises(LaunchError, match="schema too new"):
            DependencyRequirement.from_dict(
                {
                    "task_id": "task-0001",
                    "schema_version": 99,
                    "object_type": "requirement",
                    "file_version": "v2",
                }
            )


# ---------------------------------------------------------------------------
# Phase 2: Init writes storage.yaml
# ---------------------------------------------------------------------------


class TestInitWritesStorageYaml:
    # specmason: req=REQ-0054 ac=AC-0565
    def test_init_creates_storage_yaml(self, tmp_path: Path) -> None:
        from taskledger.storage.init import init_project_state

        _paths, created = init_project_state(tmp_path)
        storage_yaml = tmp_path / ".taskledger" / "storage.yaml"
        assert storage_yaml.exists()
        assert any("storage.yaml" in c for c in created)

    # specmason: req=REQ-0054 ac=AC-0565
    def test_init_idempotent(self, tmp_path: Path) -> None:
        from taskledger.storage.init import init_project_state

        init_project_state(tmp_path)
        _paths, created2 = init_project_state(tmp_path)
        assert not any("storage.yaml" in c for c in created2)


# ---------------------------------------------------------------------------
# Phase 3: Migration framework
# ---------------------------------------------------------------------------


class TestMigrationFramework:
    def test_required_layout_migrations_empty_when_current(self) -> None:
        from taskledger.storage.migrations import required_layout_migrations

        result = required_layout_migrations(
            TASKLEDGER_STORAGE_LAYOUT_VERSION,
            TASKLEDGER_STORAGE_LAYOUT_VERSION,
        )
        assert result == []

    # specmason: req=REQ-0054 ac=AC-0566
    def test_required_layout_migrations_raises_for_unsupported(self) -> None:
        from taskledger.storage.migrations import required_layout_migrations

        with pytest.raises(LaunchError, match="No migration path"):
            required_layout_migrations(1, TASKLEDGER_STORAGE_LAYOUT_VERSION)

    # specmason: req=REQ-0054 ac=AC-0566
    def test_scan_records_empty_on_fresh_workspace(self, tmp_path: Path) -> None:
        from taskledger.storage.init import init_project_state
        from taskledger.storage.migrations import scan_records_for_migration

        init_project_state(tmp_path)
        needed = scan_records_for_migration(tmp_path)
        assert needed == []


# ---------------------------------------------------------------------------
# Phase 3: Migrate CLI commands
# ---------------------------------------------------------------------------


class TestMigrateCLI:
    # specmason: req=REQ-0054 ac=AC-0581
    def test_migrate_status_no_storage(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from taskledger.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--root", str(tmp_path), "migrate", "status"])
        assert result.exit_code == 0
        assert "MIGRATION_SOURCE_NOT_FOUND" in result.output

    # specmason: req=REQ-0054 ac=AC-0582
    def test_migrate_status_up_to_date(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from taskledger.cli import app
        from taskledger.storage.init import init_project_state

        init_project_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["--root", str(tmp_path), "migrate", "status"])
        assert result.exit_code == 0
        assert "blocked" in result.output

    # specmason: req=REQ-0054 ac=AC-0576
    def test_migrate_plan_no_storage(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from taskledger.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--root", str(tmp_path), "migrate", "plan"])
        assert result.exit_code == 0
        assert "MIGRATION_SOURCE_NOT_FOUND" in result.output

    # specmason: req=REQ-0054 ac=AC-0570
    def test_migrate_apply_no_storage(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from taskledger.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--root", str(tmp_path), "migrate", "apply"])
        assert result.exit_code == 4  # CONFLICT (storage migration issue)

    # specmason: req=REQ-0054 ac=AC-0572
    def test_migrate_apply_up_to_date(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from taskledger.cli import app
        from taskledger.storage.init import init_project_state

        init_project_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app, ["--root", str(tmp_path), "migrate", "apply", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "blocked" in result.output

    # specmason: req=REQ-0054 ac=AC-0573
    def test_migrate_commands_in_inventory(self) -> None:
        from taskledger.command_inventory import COMMAND_METADATA

        assert "migrate status" in COMMAND_METADATA
        assert "migrate plan" in COMMAND_METADATA
        assert "migrate apply" in COMMAND_METADATA


# ---------------------------------------------------------------------------
# Phase 3: Doctor schema checks storage layout version
# ---------------------------------------------------------------------------


class TestDoctorSchemaLayoutVersion:
    # specmason: req=REQ-0054 ac=AC-0563
    def test_doctor_schema_missing_storage_yaml(self, tmp_path: Path) -> None:
        from taskledger.storage.init import init_project_state

        init_project_state(tmp_path)
        # Remove storage.yaml
        storage_yaml = tmp_path / ".taskledger" / "storage.yaml"
        if storage_yaml.exists():
            storage_yaml.unlink()

        from taskledger.services.doctor import inspect_v2_schema

        result = inspect_v2_schema(tmp_path)
        assert not result["healthy"]
        assert any("storage.yaml" in e for e in result["errors"])

    # specmason: req=REQ-0054 ac=AC-0563
    def test_doctor_schema_up_to_date(self, tmp_path: Path) -> None:
        from taskledger.services.doctor import inspect_v2_schema
        from taskledger.storage.init import init_project_state

        init_project_state(tmp_path)
        result = inspect_v2_schema(tmp_path)
        # Should not have storage layout errors if up to date
        layout_errors = [
            e
            for e in result["errors"]
            if "layout" in e.lower() or "storage" in e.lower()
        ]
        assert layout_errors == []

    # specmason: req=REQ-0054 ac=AC-0566
    def test_inspect_records_for_migration_reports_malformed_markdown(
        self, tmp_path: Path
    ) -> None:
        from taskledger.storage.init import init_project_state
        from taskledger.storage.migrations import inspect_records_for_migration

        init_project_state(tmp_path)
        task_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks" / "task-0001"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_path = task_dir / "task.md"
        task_path.write_text("---\nobject_type: task\nslug: [\n---\n", encoding="utf-8")

        _needed, issues = inspect_records_for_migration(tmp_path)

        assert any(issue.path == task_path for issue in issues)

    # specmason: req=REQ-0054 ac=AC-0564
    def test_doctor_schema_reports_malformed_task_record(self, tmp_path: Path) -> None:
        from taskledger.services.doctor import inspect_v2_schema
        from taskledger.storage.init import init_project_state

        init_project_state(tmp_path)
        task_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks" / "task-0001"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_path = task_dir / "task.md"
        task_path.write_text("---\nobject_type: task\nslug: [\n---\n", encoding="utf-8")

        result = inspect_v2_schema(tmp_path)

        assert not result["healthy"]
        assert any(str(task_path) in error for error in result["errors"])


# ---------------------------------------------------------------------------
# Phase 4: Branch-scoped ledger migration (v2 -> v3)
# ---------------------------------------------------------------------------


class TestBranchScopedLedgerMigration:
    """Tests for layout v2 -> v3 migration moving legacy root state to ledgers."""

    # specmason: req=REQ-0054 ac=AC-0569
    def test_migrate_apply_moves_legacy_unscoped_state_to_current_ledger(
        self, tmp_path: Path
    ) -> None:
        """Test moving root tasks and active-task into ledger namespace."""
        import yaml

        from taskledger.domain.models import ActiveTaskState
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        # Initialize workspace
        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        config_path = tmp_path / ".taskledger.toml"

        # Create a task in the current ledger
        ledger_dir = root / "ledgers" / "main"
        task_dir = ledger_dir / "tasks" / "task-0021"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_md = task_dir / "task.md"
        task_md.write_text(
            """---
schema_version: 1
object_type: task
file_version: v2
id: task-0021
slug: test-task
title: Test Task
status: draft
status_stage: draft
created_at: '2026-05-01T09:00:00+00:00'
updated_at: '2026-05-01T09:00:00+00:00'
---
Test Task
""",
            encoding="utf-8",
        )

        # Simulate legacy root layout by moving task back to root
        # and setting version to 2
        legacy_tasks_dir = root / "tasks"
        legacy_tasks_dir.mkdir(parents=True, exist_ok=True)
        legacy_task_dir = legacy_tasks_dir / "task-0021"
        import shutil

        shutil.move(str(task_dir), str(legacy_task_dir))

        # Move active-task.yaml to root
        active_task = ActiveTaskState(task_id="task-0021", previous_task_id=None)
        active_yaml = root / "active-task.yaml"
        active_yaml.write_text(yaml.safe_dump(active_task.to_dict()), encoding="utf-8")
        (ledger_dir / "active-task.yaml").unlink(missing_ok=True)

        # Update storage to layout 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Set too-low task counter in TOML (not INI)
        if not config_path.exists():
            # Create basic config if it doesn't exist
            config_path.write_text(
                "ledger_ref = 'main'\nledger_next_task_number = 3\n",
                encoding="utf-8",
            )
        else:
            config_text = config_path.read_text(encoding="utf-8")
            config_text = config_text.replace(
                "ledger_next_task_number = 1", "ledger_next_task_number = 3"
            )
            config_path.write_text(config_text, encoding="utf-8")

        # Apply migration
        applied = apply_layout_migrations(tmp_path, 2, dry_run=False)

        assert "branch-scoped-ledgers" in applied

        # Verify legacy paths are gone
        assert not (root / "tasks").exists()
        assert not (root / "active-task.yaml").exists()

        # Verify task moved to ledger
        assert (ledger_dir / "tasks" / "task-0021" / "task.md").exists()
        assert (ledger_dir / "active-task.yaml").exists()

        # Verify storage updated to v5
        from taskledger.storage.meta import read_storage_meta

        meta = read_storage_meta(tmp_path)
        assert meta is not None
        assert meta.storage_layout_version == 5
        assert meta.last_migrated_with_taskledger is not None
        assert meta.last_migrated_at is not None

        # Preserve the configured counter while branch-scoped storage migrates.
        config_text = config_path.read_text(encoding="utf-8")
        import re

        match = re.search(r"ledger_next_task_number\s*=\s*(\d+)", config_text)
        assert match is not None
        next_num = int(match.group(1))
        assert next_num >= 3

    # specmason: req=REQ-0054 ac=AC-0582
    def test_migrate_status_reports_branch_scoped_migration_needed(
        self, tmp_path: Path
    ) -> None:
        """Test migrate status detects legacy root state."""
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import required_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"

        # Create legacy root tasks directory
        (root / "tasks").mkdir(parents=True, exist_ok=True)

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Check migrations needed
        migrations = required_layout_migrations(2, 3)

        assert len(migrations) == 1
        assert migrations[0].name == "branch-scoped-ledgers"
        assert migrations[0].from_version == 2
        assert migrations[0].to_version == 3

    # specmason: req=REQ-0054 ac=AC-0571
    def test_migrate_apply_noop_for_already_branch_scoped_v2_workspace(
        self, tmp_path: Path
    ) -> None:
        """Test migration is no-op for already-correct branch-scoped v2 workspace."""
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create a task in the ledger (already correct layout)
        task_dir = ledger_dir / "tasks" / "task-0001"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_md = task_dir / "task.md"
        task_md.write_text(
            """---
schema_version: 1
object_type: task
file_version: v2
id: task-0001
slug: test-task
title: Test Task
status: draft
status_stage: draft
created_at: '2026-05-01T09:00:00+00:00'
updated_at: '2026-05-01T09:00:00+00:00'
---
Test Task
""",
            encoding="utf-8",
        )

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Apply migration (should succeed even though no legacy paths)
        applied = apply_layout_migrations(tmp_path, 2, dry_run=False)

        assert "branch-scoped-ledgers" in applied

        # Verify task still exists
        assert (task_dir / "task.md").exists()

        # Verify layout updated to 5
        from taskledger.storage.meta import read_storage_meta

        meta = read_storage_meta(tmp_path)
        assert meta is not None
        assert meta.storage_layout_version == 5

        # Second migration should be no-op
        applied2 = apply_layout_migrations(tmp_path, 5, dry_run=False)
        assert len(applied2) == 0

    # specmason: req=REQ-0054 ac=AC-0580
    def test_migrate_renumbers_older_root_task_on_conflict(
        self, tmp_path: Path
    ) -> None:
        """Test migration keeps older tasks at lower IDs, renumbers newer tasks.

        Strategy: Older root tasks keep lower IDs, newer ledger tasks get higher IDs.
        """
        from datetime import datetime, timezone

        from taskledger.domain.models import TaskRecord
        from taskledger.storage.frontmatter import write_markdown_front_matter
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create newer task in ledger (newer: 2026-04-30)
        ledger_task = TaskRecord(
            id="task-0001",
            slug="task-0001",
            title="Ledger Task",
            body="Ledger task body",
            status_stage="draft",
            created_at=datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc),
        )
        ledger_task_dir = ledger_dir / "tasks" / "task-0001"
        ledger_task_dir.mkdir(parents=True, exist_ok=True)
        ledger_metadata = ledger_task.to_dict()
        ledger_body = ledger_metadata.pop("body", "")
        write_markdown_front_matter(
            ledger_task_dir / "task.md", ledger_metadata, ledger_body
        )

        # Create older conflicting task in root (older: 2026-04-28)
        root_task = TaskRecord(
            id="task-0001",
            slug="task-0001",
            title="Root Task",
            body="Root task body",
            status_stage="draft",
            created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
        )
        root_task_dir = root / "tasks" / "task-0001"
        root_task_dir.mkdir(parents=True, exist_ok=True)
        root_metadata = root_task.to_dict()
        root_body = root_metadata.pop("body", "")
        write_markdown_front_matter(root_task_dir / "task.md", root_metadata, root_body)

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Migration should succeed
        apply_layout_migrations(tmp_path, 2, dry_run=False)

        # Root task-0001 (older) should remain at task-0001
        assert (ledger_dir / "tasks" / "task-0001" / "task.md").exists()
        root_content = (ledger_dir / "tasks" / "task-0001" / "task.md").read_text()
        assert "Root Task" in root_content
        assert "id: task-0001" in root_content

        # Ledger task (newer) should be renumbered to task-0002
        assert (ledger_dir / "tasks" / "task-0002" / "task.md").exists()
        ledger_content = (ledger_dir / "tasks" / "task-0002" / "task.md").read_text()
        assert "Ledger Task" in ledger_content
        assert "id: task-0002" in ledger_content

    # specmason: req=REQ-0054 ac=AC-0579
    def test_migrate_handles_multiple_task_id_conflicts(self, tmp_path: Path) -> None:
        """Test migration handles multiple simultaneous task conflicts.

        Strategy: Older root tasks keep lower IDs, newer ledger tasks get higher IDs.
        """
        from datetime import datetime, timezone

        from taskledger.domain.models import TaskRecord
        from taskledger.storage.frontmatter import write_markdown_front_matter
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create multiple tasks in ledger (newer)
        for i in [1, 2, 3]:
            task = TaskRecord(
                id=f"task-{i:04d}",
                slug=f"task-{i:04d}",
                title=f"Ledger Task {i}",
                body=f"Ledger task {i} body",
                status_stage="draft",
                created_at=datetime(2026, 4, 30, 10, 0, i, tzinfo=timezone.utc),
            )
            task_dir = ledger_dir / "tasks" / f"task-{i:04d}"
            task_dir.mkdir(parents=True, exist_ok=True)
            metadata = task.to_dict()
            body = metadata.pop("body", "")
            write_markdown_front_matter(task_dir / "task.md", metadata, body)

        # Create conflicting older tasks in root
        for i in [1, 2, 3]:
            task = TaskRecord(
                id=f"task-{i:04d}",
                slug=f"task-{i:04d}",
                title=f"Root Task {i}",
                body=f"Root task {i} body",
                status_stage="draft",
                created_at=datetime(2026, 4, 28, 10, 0, i, tzinfo=timezone.utc),
            )
            task_dir = root / "tasks" / f"task-{i:04d}"
            task_dir.mkdir(parents=True, exist_ok=True)
            metadata = task.to_dict()
            body = metadata.pop("body", "")
            write_markdown_front_matter(task_dir / "task.md", metadata, body)

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Migration should succeed
        apply_layout_migrations(tmp_path, 2, dry_run=False)

        # All root tasks (older) should remain at task-0001-0003
        for i in [1, 2, 3]:
            assert (ledger_dir / "tasks" / f"task-{i:04d}" / "task.md").exists()
            content = (ledger_dir / "tasks" / f"task-{i:04d}" / "task.md").read_text()
            assert f"Root Task {i}" in content

        # All ledger tasks (newer) should be renumbered to task-0004-0006
        for i, new_id in [(1, 4), (2, 5), (3, 6)]:
            assert (ledger_dir / "tasks" / f"task-{new_id:04d}" / "task.md").exists()
            content = (
                ledger_dir / "tasks" / f"task-{new_id:04d}" / "task.md"
            ).read_text()
            assert f"Ledger Task {i}" in content
            assert f"id: task-{new_id:04d}" in content

    # specmason: req=REQ-0054 ac=AC-0577
    def test_migrate_preserves_task_timestamps_after_renumbering(
        self, tmp_path: Path
    ) -> None:
        """Test that task creation timestamps are preserved during renumbering.

        Strategy: Older root tasks keep lower IDs, newer ledger tasks get higher IDs.
        """
        from datetime import datetime, timezone

        from taskledger.domain.models import TaskRecord
        from taskledger.storage.frontmatter import write_markdown_front_matter
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create root task with specific timestamp (older: 2026-01-01)
        original_ts = datetime(2026, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
        root_task = TaskRecord(
            id="task-0001",
            slug="task-0001",
            title="Original Task",
            body="Original task body",
            status_stage="draft",
            created_at=original_ts,
        )
        root_task_dir = root / "tasks" / "task-0001"
        root_task_dir.mkdir(parents=True, exist_ok=True)
        root_metadata = root_task.to_dict()
        root_body = root_metadata.pop("body", "")
        write_markdown_front_matter(root_task_dir / "task.md", root_metadata, root_body)

        # Create newer ledger task with conflicting ID (newer: 2026-04-30)
        newer_ts = datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc)
        ledger_task = TaskRecord(
            id="task-0001",
            slug="task-0001",
            title="Ledger Task",
            body="Ledger task body",
            status_stage="draft",
            created_at=newer_ts,
        )
        ledger_task_dir = ledger_dir / "tasks" / "task-0001"
        ledger_task_dir.mkdir(parents=True, exist_ok=True)
        ledger_metadata = ledger_task.to_dict()
        ledger_body = ledger_metadata.pop("body", "")
        write_markdown_front_matter(
            ledger_task_dir / "task.md", ledger_metadata, ledger_body
        )

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Migrate
        apply_layout_migrations(tmp_path, 2, dry_run=False)

        # Root task (older) should remain at task-0001 with original timestamp
        root_content = (ledger_dir / "tasks" / "task-0001" / "task.md").read_text()
        assert "2026-01-01 12:34:56" in root_content
        assert "id: task-0001" in root_content
        assert "Original Task" in root_content

        # Ledger task (newer) should be renumbered to task-0002
        ledger_content = (ledger_dir / "tasks" / "task-0002" / "task.md").read_text()
        assert "id: task-0002" in ledger_content
        assert "Ledger Task" in ledger_content

    # specmason: req=REQ-0054 ac=AC-0578
    def test_migrate_apply_removes_legacy_root_indexes_and_rebuilds(
        self, tmp_path: Path
    ) -> None:
        """Test that root indexes are removed and ledger indexes rebuilt."""
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create legacy root indexes
        root_indexes = root / "indexes"
        root_indexes.mkdir(parents=True, exist_ok=True)
        (root_indexes / "legacy.json").write_text("[]", encoding="utf-8")

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Apply migration
        apply_layout_migrations(tmp_path, 2, dry_run=False)

        # Root indexes should be gone
        assert not root_indexes.exists()

        # Ledger indexes should be rebuilt
        assert (ledger_dir / "indexes").is_dir()

    # specmason: req=REQ-0054 ac=AC-0575
    def test_migrate_merges_active_task_keeping_newer(self, tmp_path: Path) -> None:
        """Test that active-task.yaml files merge by keeping the newer activation."""
        import yaml

        from taskledger.domain.models import ActiveTaskState, ActorRef
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create older active-task.yaml in root
        old_active = ActiveTaskState(
            task_id="task-0001",
            activated_at="2026-04-20T10:00:00+00:00",
            activated_by=ActorRef(actor_type="user", actor_name="user1"),
        )
        root_active_path = root / "active-task.yaml"
        root_active_path.write_text(
            yaml.dump(old_active.to_dict(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        # Create newer active-task.yaml in ledger
        new_active = ActiveTaskState(
            task_id="task-0005",
            activated_at="2026-04-25T15:30:00+00:00",
            activated_by=ActorRef(actor_type="user", actor_name="user2"),
        )
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_active_path = ledger_dir / "active-task.yaml"
        ledger_active_path.write_text(
            yaml.dump(new_active.to_dict(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Apply migration
        apply_layout_migrations(tmp_path, 2, dry_run=False)

        # Root active-task.yaml should be gone
        assert not root_active_path.exists()

        # Ledger active-task.yaml should contain newer activation
        result_content = ledger_active_path.read_text()
        assert "task-0005" in result_content  # Newer activation kept
        assert "2026-04-25" in result_content  # Newer timestamp

    # specmason: req=REQ-0054 ac=AC-0574
    def test_migrate_merges_active_task_from_root_if_newer(
        self, tmp_path: Path
    ) -> None:
        """Test that active-task.yaml merge uses root version if it's newer."""
        import yaml

        from taskledger.domain.models import ActiveTaskState, ActorRef
        from taskledger.storage.init import init_project_state
        from taskledger.storage.meta import StorageMeta, write_storage_meta
        from taskledger.storage.migrations import apply_layout_migrations

        init_project_state(tmp_path)
        root = tmp_path / ".taskledger"
        ledger_dir = root / "ledgers" / "main"

        # Create newer active-task.yaml in root
        new_active = ActiveTaskState(
            task_id="task-0003",
            activated_at="2026-04-28T14:00:00+00:00",
            activated_by=ActorRef(actor_type="user", actor_name="user1"),
        )
        root_active_path = root / "active-task.yaml"
        root_active_path.write_text(
            yaml.dump(new_active.to_dict(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        # Create older active-task.yaml in ledger
        old_active = ActiveTaskState(
            task_id="task-0002",
            activated_at="2026-04-15T09:00:00+00:00",
            activated_by=ActorRef(actor_type="user", actor_name="user2"),
        )
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_active_path = ledger_dir / "active-task.yaml"
        ledger_active_path.write_text(
            yaml.dump(old_active.to_dict(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        # Set layout to 2
        write_storage_meta(tmp_path, StorageMeta(storage_layout_version=2))

        # Apply migration
        apply_layout_migrations(tmp_path, 2, dry_run=False)

        # Root active-task.yaml should be gone
        assert not root_active_path.exists()

        # Ledger active-task.yaml should contain newer activation from root
        result_content = ledger_active_path.read_text()
        assert "task-0003" in result_content  # Newer activation from root kept
        assert "2026-04-28" in result_content  # Newer timestamp from root

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.layout_migration import MigrationIssue, inspect_migration

CANONICAL_UUID = "6bddbb56-b273-4aae-9860-bfa4de93f115"
LEGACY_UUID = "bf999c8f-4e9e-46d6-9275-892c24d19f85"


def _manifest_without_taskledger() -> str:
    return f'''schema_version = 3

[project]
uuid = "{CANONICAL_UUID}"
name = "archledger"

[ledgers.releaseledger.mounts.data]
storage = "project"

[ledgers.releaseledger.mounts.indexes]
storage = "cache"
'''


def _legacy_source(path: Path, *, task_text: str = "legacy") -> None:
    tasks = path / "ledgers" / "main" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "task-0001.md").write_text(task_text + "\n", encoding="utf-8")
    (path / "storage.yaml").write_text(
        "storage_layout_version: 5\nrecord_schema_version: 1\n",
        encoding="utf-8",
    )


def _archledger_project(root: Path, source: Path) -> None:
    (root / ".ledger").mkdir()
    (root / ".ledger" / "ledger.toml").write_text(
        _manifest_without_taskledger(), encoding="utf-8"
    )
    (root / ".taskledger.toml").write_text(
        f'config_version = 2\nproject_uuid = "{LEGACY_UUID}"\n'
        f'taskledger_dir = "{source}"\n',
        encoding="utf-8",
    )


def test_issue_serialization_preserves_structured_details() -> None:
    issue = MigrationIssue(
        "blocker",
        "TARGET_STORAGE_META_MISSING",
        "The target data root has no storage.yaml.",
        ("Back up the target and rerun the migration.",),
        {"missing_path": "/tmp/data/storage.yaml", "authoritative_files": 0},
    )

    assert issue.to_dict() == {
        "severity": "blocker",
        "code": "TARGET_STORAGE_META_MISSING",
        "message": "The target data root has no storage.yaml.",
        "remediation": ["Back up the target and rerun the migration."],
        "details": {"missing_path": "/tmp/data/storage.yaml", "authoritative_files": 0},
    }


def test_canonical_manifest_does_not_hide_legacy_source(tmp_path: Path) -> None:
    source = tmp_path / "ledger" / "taskledger" / LEGACY_UUID / "data"
    _legacy_source(source)
    _archledger_project(tmp_path, source)
    sibling = tmp_path / "ledger"
    (sibling / ".ledger-store").write_text(
        "Ledgercore sibling store\n", encoding="utf-8"
    )

    inspection = inspect_migration(tmp_path, sibling_ledger_root=sibling)
    payload = inspection.to_dict()

    assert payload["project"]["uuid"] == CANONICAL_UUID
    assert payload["project"]["canonical_uuid"] == CANONICAL_UUID
    assert payload["project"]["legacy_uuid"] == LEGACY_UUID
    assert payload["project"]["identity_transition"] == "adopt-canonical"
    assert payload["source"]["data"] == str(source.resolve())
    assert payload["source"]["selected_reason"] == "configured legacy source"
    assert payload["target"]["data"] == str(
        sibling / "taskledger" / CANONICAL_UUID / "data"
    )
    assert "PARTIAL_MIGRATION" not in {issue["code"] for issue in payload["issues"]}
    assert "TASKLEDGER_REGISTRATION_MISSING" in {
        issue["code"] for issue in payload["issues"]
    }


def test_stale_config_falls_back_to_unique_uuid_store(tmp_path: Path) -> None:
    sibling = tmp_path / "ledger"
    source = sibling / "taskledger" / LEGACY_UUID / "data"
    _legacy_source(source)
    _archledger_project(tmp_path, tmp_path / "missing-legacy-source")
    (sibling / ".ledger-store").write_text(
        "Ledgercore sibling store\n", encoding="utf-8"
    )

    payload = inspect_migration(tmp_path, sibling_ledger_root=sibling).to_dict()

    assert payload["source"]["data"] == str(source.resolve())
    assert payload["source"]["selected_reason"] == "legacy UUID sibling store"
    assert "LEGACY_CONFIG_PATH_STALE" in {issue["code"] for issue in payload["issues"]}


def test_split_brain_target_reports_conflicting_task_ids_without_apply_command(
    tmp_path: Path,
) -> None:
    sibling = tmp_path / "ledger"
    source = sibling / "taskledger" / LEGACY_UUID / "data"
    target = sibling / "taskledger" / CANONICAL_UUID / "data"
    _legacy_source(source, task_text="legacy task")
    _legacy_source(target, task_text="new target task")
    (target / ".ledger-project.toml").write_text(
        "schema_version = 1\n"
        f'project_uuid = "{CANONICAL_UUID}"\n'
        'ledger = "taskledger"\nmount = "data"\n',
        encoding="utf-8",
    )
    _archledger_project(tmp_path, source)
    (sibling / ".ledger-store").write_text(
        "Ledgercore sibling store\n", encoding="utf-8"
    )

    payload = inspect_migration(tmp_path, sibling_ledger_root=sibling).to_dict()
    codes = {issue["code"] for issue in payload["issues"]}

    assert payload["ready"] is False
    assert "SOURCE_TARGET_SPLIT_BRAIN" in codes
    assert "task-0001" in json.dumps(payload)
    assert "apply" not in payload["commands"]


def test_explicit_source_data_root_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "explicit-source"
    _legacy_source(source)
    _archledger_project(tmp_path, tmp_path / "missing")
    sibling = tmp_path / "ledger"
    sibling.mkdir()
    (sibling / ".ledger-store").write_text(
        "Ledgercore sibling store\n", encoding="utf-8"
    )

    payload = inspect_migration(
        tmp_path,
        sibling_ledger_root=sibling,
        source_data_root=source,
    ).to_dict()

    assert payload["source"]["data"] == str(source.resolve())
    assert payload["source"]["selected_reason"] == "explicit source-data-root"


def test_manifest_merge_preserves_existing_ledger_registrations() -> None:
    from ledgercore.manifest import parse_ledger_manifest_v3

    from taskledger.storage.ledgercore_backend import (
        build_taskledger_manifest_with_registration,
    )

    existing = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {"uuid": CANONICAL_UUID, "name": "archledger"},
            "ledgers": {
                "releaseledger": {
                    "mounts": {
                        "data": {"storage": "project"},
                        "indexes": {"storage": "cache"},
                    }
                },
                "archledger": {
                    "mounts": {"data": {"storage": "project"}},
                },
            },
        }
    )

    result = build_taskledger_manifest_with_registration(
        existing,
        project_uuid=CANONICAL_UUID,
        project_name="renamed project",
    )

    assert set(result.ledgers) == {"releaseledger", "archledger", "taskledger"}
    assert result.ledgers["releaseledger"] == existing.ledgers["releaseledger"]
    assert result.ledgers["archledger"] == existing.ledgers["archledger"]


def test_metadata_only_target_is_backed_up_and_replaced(tmp_path: Path) -> None:
    sibling = tmp_path / "ledger"
    source = sibling / "taskledger" / LEGACY_UUID / "data"
    target = sibling / "taskledger" / CANONICAL_UUID / "data"
    _legacy_source(source)
    target.mkdir(parents=True)
    (target / ".ledger-project.toml").write_text(
        "schema_version = 1\n"
        f'project_uuid = "{CANONICAL_UUID}"\n'
        'ledger = "taskledger"\nmount = "data"\n',
        encoding="utf-8",
    )
    (target / "state.toml").write_text("schema_version = 2\n", encoding="utf-8")
    (target / "storage.yaml").write_text(
        "storage_layout_version: 5\n", encoding="utf-8"
    )
    _archledger_project(tmp_path, source)
    (sibling / ".ledger-store").write_text(
        "Ledgercore sibling store\n", encoding="utf-8"
    )

    from taskledger.storage.layout_migration import apply_layout_migration

    result = apply_layout_migration(tmp_path, sibling_ledger_root=sibling)

    assert result["status"] == "applied"
    backup = Path(str(result["backup"]))
    assert (backup / "target-data" / ".ledger-project.toml").is_file()
    assert (target / "ledgers" / "main" / "tasks" / "task-0001.md").is_file()
    assert source.is_dir()


def test_cli_renders_remediation_and_shared_source_options(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from taskledger.cli import app

    source = tmp_path / "source"
    sibling = tmp_path / "ledger"
    _legacy_source(source)
    _archledger_project(tmp_path, source)
    sibling.mkdir()
    (sibling / ".ledger-store").write_text(
        "Ledgercore sibling store\n", encoding="utf-8"
    )

    result = CliRunner().invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "migrate",
            "plan",
            "--sibling-ledger-root",
            str(sibling),
            "--source-data-root",
            str(source),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "TASKLEDGER_REGISTRATION_MISSING" in result.stdout
    assert "remedy" in result.stdout
    assert "Apply" in result.stdout
    assert "--backup" not in result.stdout


def test_source_checkout_rejects_paths() -> None:
    from pathlib import Path as _Path

    with pytest.raises(LaunchError, match="checkout identifier"):
        inspect_migration(_Path.cwd(), source_checkout_id="../checkout")


def test_create_sibling_store_dry_run_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    sibling = tmp_path / "ledger"
    _legacy_source(source)
    _archledger_project(tmp_path, source)

    from taskledger.services.storage_migration import (
        MigrationOptions,
        apply_migration,
    )

    result = apply_migration(
        tmp_path,
        options=MigrationOptions(
            sibling_ledger_root=sibling,
            source_data_root=source,
            create_sibling_store=True,
        ),
        dry_run=True,
    )

    inspection = result["inspection"]
    assert isinstance(inspection, dict)
    assert inspection["would_create_sibling_store"] is True
    assert not sibling.exists()

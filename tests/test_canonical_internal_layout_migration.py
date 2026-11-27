from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.layout_migration import inspect_migration
from taskledger.storage.project_context import load_project_context


def _canonical_project(root: Path):
    result = CliRunner().invoke(
        app, ["--root", str(root), "init", "--create-sibling-store"]
    )
    assert result.exit_code == 0, result.stdout
    marker = root.parent / "ledger" / ".ledger-store"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("Ledgercore sibling store\n", encoding="utf-8")
    context = load_project_context(root)
    assert marker.is_file()
    return context


def _invoke_json(root: Path, command: str, subcommand: str) -> dict[str, object]:
    result = CliRunner().invoke(
        app, ["--root", str(root), "--json", command, subcommand]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_complete_canonical_store_without_receipt_is_up_to_date(
    tmp_path: Path,
) -> None:
    context = _canonical_project(tmp_path / "project")
    receipts = list((context.paths.data_root / "migrations").glob("*.json"))
    assert receipts == []

    inspection = inspect_migration(context.project_root)

    assert inspection.target_classification == "COMPLETE_CANONICAL"
    assert inspection.internal_layout_status == "current"
    assert inspection.migration_required is False
    assert inspection.to_dict()["status"] == "up_to_date"

    status_payload = _invoke_json(context.project_root, "migrate", "status")
    assert status_payload["ok"] is True
    assert status_payload["result"]["status"] == "up_to_date"

    apply_payload = _invoke_json(context.project_root, "migrate", "apply")
    final = inspect_migration(context.project_root)

    assert apply_payload["result"]["status"] == "up_to_date"
    assert final.to_dict()["status"] == "up_to_date"
    assert list((context.paths.data_root / "migrations").glob("*.json")) == []


def test_complete_canonical_apply_reconciles_stale_task_directory_layout(
    tmp_path: Path,
) -> None:
    context = _canonical_project(tmp_path / "project")
    legacy_dir = context.paths.tasks_dir / "task-0001"
    legacy_dir.mkdir()
    (legacy_dir / "allocation.marker").write_text("reserved\n", encoding="utf-8")

    inspection = inspect_migration(context.project_root)

    assert inspection.target_classification == "COMPLETE_CANONICAL"
    assert inspection.internal_layout_status == "reconciliation_required"
    assert inspection.migration_required is True
    assert inspection.to_dict()["status"] == "migration_needed"
    assert any(
        issue.code == "TASK_DIRECTORY_LAYOUT_DRIFT" for issue in inspection.issues
    )

    status_payload = _invoke_json(context.project_root, "migrate", "status")
    assert status_payload["result"]["status"] == "migration_needed"

    apply_payload = _invoke_json(context.project_root, "migrate", "apply")
    final = inspect_migration(context.project_root)

    assert apply_payload["result"]["status"] == "applied"
    assert apply_payload["result"]["internal_layout"]["current"] is True
    assert not legacy_dir.exists()
    assert final.internal_layout_status == "current"
    assert final.to_dict()["status"] == "up_to_date"

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.project_identity import load_project_uuid

pytestmark = [
    pytest.mark.cli,
    pytest.mark.integration,
    pytest.mark.git,
    pytest.mark.slow,
]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        snapshot[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return snapshot


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-storage-where-reports-external-storage-details
def test_storage_where_reports_external_storage_details(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    storage = tmp_path / "state" / "repo"
    workspace.mkdir()

    init_result = runner.invoke(
        app,
        ["--root", str(workspace), "init", "--taskledger-dir", str(storage)],
    )
    assert init_result.exit_code == 0, init_result.stdout

    result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "storage", "where"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["taskledger_dir"] == storage.resolve().as_posix()
    assert data["inside_workspace"] is False
    assert data["is_git_repo"] is False
    assert data["ledger_ref"] == "main"


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-storage-move-copy-updates-config-and-preserves-project-uuid
def test_storage_move_copy_updates_config_and_preserves_project_uuid(
    tmp_path: Path,
) -> None:
    """Storage move is a legacy feature; use explicit legacy project."""
    workspace = tmp_path / "repo"
    target = tmp_path / "state" / "repo"
    workspace.mkdir()
    taskledger_dir = workspace / ".taskledger"

    init_result = runner.invoke(
        app, ["--root", str(workspace), "init", "--taskledger-dir", str(taskledger_dir)]
    )
    assert init_result.exit_code == 0, init_result.stdout
    original_uuid = load_project_uuid(workspace / "taskledger.toml")

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "storage",
            "move",
            "--to",
            str(target),
            "--mode",
            "copy",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["source"] == taskledger_dir.resolve().as_posix()
    assert data["target"] == target.resolve().as_posix()
    assert data["backup_path"] is None
    assert (target / "storage.yaml").exists()
    assert (target / "ledgers" / "main" / "tasks").is_dir()
    assert taskledger_dir.exists()
    assert load_project_uuid(workspace / "taskledger.toml") == original_uuid


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-storage-move-refuses-non-empty-target
def test_storage_move_refuses_non_empty_target(tmp_path: Path) -> None:
    """Storage move is a legacy feature; use explicit legacy project."""
    workspace = tmp_path / "repo"
    target = tmp_path / "state" / "repo"
    workspace.mkdir()
    taskledger_dir = workspace / ".taskledger"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("occupied\n", encoding="utf-8")

    init_result = runner.invoke(
        app, ["--root", str(workspace), "init", "--taskledger-dir", str(taskledger_dir)]
    )
    assert init_result.exit_code == 0, init_result.stdout

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "storage",
            "move",
            "--to",
            str(target),
            "--mode",
            "copy",
        ],
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert "Target exists and is not empty" in payload["error"]["message"]


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-sync-preflight-is-read-only-and-warns-about-active-locks
def test_sync_preflight_is_read_only_and_warns_about_active_locks(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--root",
                str(workspace),
                "task",
                "create",
                "Sync docs",
                "--slug",
                "sync-docs",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--root", str(workspace), "task", "activate", "sync-docs"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--root", str(workspace), "plan", "start"]).exit_code == 0
    )

    before = _snapshot_tree(workspace)
    result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "sync", "preflight"],
    )
    after = _snapshot_tree(workspace)

    assert result.exit_code == 0, result.stdout
    assert before == after
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["taskledger_dir_exists"] is True
    assert data["location"]["active_lock_count"] == 1
    assert any("active lock" in item.lower() for item in data["warnings"])


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-sync-preflight-warns-when-in-repo-storage-is-tracked
def test_sync_preflight_warns_when_in_repo_storage_is_tracked(tmp_path: Path) -> None:
    """Use canonical project with project-scoped data so it is inside workspace git."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    # Use project data storage so data lives inside the workspace.
    assert (
        runner.invoke(
            app,
            [
                "--root",
                str(workspace),
                "init",
                "--data-storage",
                "project",
            ],
        ).exit_code
        == 0
    )

    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Taskledger Test")
    # Stage canonical files.
    _git(workspace, "add", ".ledger")

    result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "sync", "preflight"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["tracked_in_workspace_git"] is True
    assert any("tracked by git" in item.lower() for item in data["warnings"])


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-sync-status-reports-git-changes-for-external-state-repo
def test_sync_status_reports_git_changes_for_external_state_repo(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    storage = tmp_path / "state" / "repo"
    workspace.mkdir()
    assert (
        runner.invoke(
            app,
            ["--root", str(workspace), "init", "--taskledger-dir", str(storage)],
        ).exit_code
        == 0
    )

    _git(storage, "init")

    result = runner.invoke(app, ["--root", str(workspace), "--json", "sync", "status"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["git_root"] == storage.resolve().as_posix()
    assert data["clean"] is False
    assert data["status_lines"]


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-sync-commit-commits-external-state-repo
def test_sync_commit_commits_external_state_repo(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    storage = tmp_path / "state" / "repo"
    workspace.mkdir()
    assert (
        runner.invoke(
            app,
            ["--root", str(workspace), "init", "--taskledger-dir", str(storage)],
        ).exit_code
        == 0
    )

    _git(storage, "init")
    _git(storage, "config", "user.email", "test@example.com")
    _git(storage, "config", "user.name", "Taskledger Test")

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "commit",
            "--message",
            "Initial taskledger state",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["commit"]
    status = _git(storage, "status", "--short")
    assert status.stdout.strip() == ""


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-sync-help-includes-aliases-and-git-group
def test_sync_help_includes_aliases_and_git_group(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    result = runner.invoke(app, ["--root", str(workspace), "sync", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "preflight" in result.stdout
    assert "status" in result.stdout
    assert "commit" in result.stdout
    assert "export" in result.stdout
    assert "import" in result.stdout
    assert "git" in result.stdout


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-sync-export-alias-writes-archive
def test_sync_export_alias_writes_archive(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    root_archive = tmp_path / "root-export.tar.gz"
    sync_archive = tmp_path / "sync-export.tar.gz"
    root_result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "export", "-o", str(root_archive)],
    )
    sync_result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "sync", "export", "-o", str(sync_archive)],
    )

    assert root_result.exit_code == 0, root_result.stdout
    assert sync_result.exit_code == 0, sync_result.stdout
    root_payload = json.loads(root_result.stdout)
    sync_payload = json.loads(sync_result.stdout)
    assert (
        root_payload["result"]["kind"]
        == sync_payload["result"]["kind"]
        == "taskledger_archive_export"
    )
    assert root_archive.exists()
    assert sync_archive.exists()


# sw: f=specs/behavior/features/storage_sync/storage-sync.feature
# sw: s=@bdd-storage-sync-export-conflicting-output-args-include-command-specific-hint
def test_export_conflicting_output_args_include_command_specific_hint(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    root_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "export",
            "first.tar.gz",
            "-o",
            "second.tar.gz",
        ],
    )
    sync_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "export",
            "first.tar.gz",
            "-o",
            "second.tar.gz",
        ],
    )

    assert root_result.exit_code == 2, root_result.stdout
    assert sync_result.exit_code == 2, sync_result.stdout
    root_payload = json.loads(root_result.stdout)
    sync_payload = json.loads(sync_result.stdout)
    assert "taskledger export -o OUT.tar.gz" in root_payload["error"]["message"]
    assert "taskledger sync export -o OUT.tar.gz" in sync_payload["error"]["message"]

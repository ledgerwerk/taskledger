from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.project_identity import load_project_uuid


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
    assert data["taskledger_dir"] == str(storage.resolve())
    assert data["inside_workspace"] is False
    assert data["is_git_repo"] is False
    assert data["ledger_ref"] == "main"


def test_storage_move_copy_updates_config_and_preserves_project_uuid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    target = tmp_path / "state" / "repo"
    workspace.mkdir()

    init_result = runner.invoke(app, ["--root", str(workspace), "init"])
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
    assert data["source"] == str((workspace / ".taskledger").resolve())
    assert data["target"] == str(target.resolve())
    assert data["backup_path"] is None
    assert (target / "storage.yaml").exists()
    assert (target / "ledgers" / "main" / "tasks").is_dir()
    assert (workspace / ".taskledger").exists()
    assert load_project_uuid(workspace / "taskledger.toml") == original_uuid
    assert f"taskledger_dir = '{target.resolve().as_posix()}'" in (
        workspace / "taskledger.toml"
    ).read_text(encoding="utf-8")


def test_storage_move_refuses_non_empty_target(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    target = tmp_path / "state" / "repo"
    workspace.mkdir()
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("occupied\n", encoding="utf-8")

    init_result = runner.invoke(app, ["--root", str(workspace), "init"])
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


def test_sync_preflight_warns_when_in_repo_storage_is_tracked(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Taskledger Test")
    _git(workspace, "add", "taskledger.toml", ".taskledger")

    result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "sync", "preflight"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["tracked_in_workspace_git"] is True
    assert any("tracked by git" in item.lower() for item in data["warnings"])


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
    assert data["git_root"] == str(storage.resolve())
    assert data["clean"] is False
    assert data["status_lines"]


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

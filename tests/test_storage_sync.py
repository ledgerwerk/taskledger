from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.api.project import init_project as init_project_api
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


# specmason: req=REQ-0056 ac=AC-0610
def test_storage_where_reports_external_storage_details(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    init_result = init_project_api(workspace, external_root="../state")
    data_root = Path(str(init_result["mounts"]["data"]["path"]))

    result = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "storage", "where"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["mode"] == "canonical"
    assert data["mounts"]["data"]["path"] == data_root.as_posix()
    assert data["mounts"]["data"]["storage"] == "external"
    assert Path(data["mounts"]["data"]["path"]).is_relative_to(tmp_path / "state")


# specmason: req=REQ-0056 ac=AC-0608
def test_storage_move_requires_explicit_migration_for_legacy_projects(
    tmp_path: Path,
) -> None:
    from taskledger.migrations.legacy_init import init_legacy_project_state

    workspace = tmp_path / "repo"
    target = tmp_path / "state" / "repo"
    workspace.mkdir()
    paths, _ = init_legacy_project_state(workspace)
    original_uuid = load_project_uuid(paths.config_path)

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
    assert payload["error"]["code"] == "TASKLEDGER_MIGRATION_REQUIRED"
    assert paths.taskledger_dir.exists()
    assert not target.exists()
    assert load_project_uuid(paths.config_path) == original_uuid


# specmason: req=REQ-0056 ac=AC-0609
def test_storage_move_does_not_touch_legacy_target_before_migration(
    tmp_path: Path,
) -> None:
    from taskledger.migrations.legacy_init import init_legacy_project_state

    workspace = tmp_path / "repo"
    target = tmp_path / "state" / "repo"
    workspace.mkdir()
    paths, _ = init_legacy_project_state(workspace)
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("occupied\n", encoding="utf-8")

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
    assert payload["error"]["code"] == "TASKLEDGER_MIGRATION_REQUIRED"
    assert paths.taskledger_dir.exists()
    assert (target / "keep.txt").read_text(encoding="utf-8") == "occupied\n"


# specmason: req=REQ-0056 ac=AC-0614
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


# specmason: req=REQ-0056 ac=AC-0615
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


# specmason: req=REQ-0056 ac=AC-0616
def test_sync_status_reports_git_changes_for_external_state_repo(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    init_result = init_project_api(workspace, external_root="../state")
    storage = Path(str(init_result["mounts"]["data"]["path"]))

    _git(storage, "init")

    result = runner.invoke(app, ["--root", str(workspace), "--json", "sync", "status"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["result"]
    assert data["git_root"] == storage.resolve().as_posix()
    assert data["clean"] is False
    assert data["status_lines"]


# specmason: req=REQ-0056 ac=AC-0611
def test_sync_commit_commits_external_state_repo(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    init_result = init_project_api(workspace, external_root="../state")
    storage = Path(str(init_result["mounts"]["data"]["path"]))

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


# specmason: req=REQ-0056 ac=AC-0613
def test_sync_help_lists_only_storage_and_git_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    result = runner.invoke(app, ["--root", str(workspace), "sync", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "preflight" in result.stdout
    assert "status" in result.stdout
    assert "commit" in result.stdout
    assert "export" not in result.stdout
    assert "import" not in result.stdout
    assert "git" in result.stdout


# specmason: req=REQ-0056 ac=AC-0612
def test_sync_archive_aliases_are_unregistered(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    for command in ("export", "import"):
        result = runner.invoke(
            app,
            ["--root", str(workspace), "sync", command, "--help"],
        )
        assert result.exit_code != 0, command


# specmason: req=REQ-0056 ac=AC-0607
def test_export_conflicting_output_args_include_command_specific_hint(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    result = runner.invoke(
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

    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert "taskledger export -o OUT.tar.gz" in payload["error"]["message"]

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def test_sync_git_help_includes_commands_and_hooks(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    git_help = runner.invoke(app, ["--root", str(workspace), "sync", "git", "--help"])
    hooks_help = runner.invoke(
        app, ["--root", str(workspace), "sync", "git", "hooks", "--help"]
    )

    assert git_help.exit_code == 0, git_help.stdout
    assert "init" in git_help.stdout
    assert "status" in git_help.stdout
    assert "import-local" in git_help.stdout
    assert "export-local" in git_help.stdout
    assert "pull" in git_help.stdout
    assert "push" in git_help.stdout
    assert "sync" in git_help.stdout
    assert "hooks" in git_help.stdout
    assert hooks_help.exit_code == 0, hooks_help.stdout
    assert "install" in hooks_help.stdout
    assert "status" in hooks_help.stdout
    assert "uninstall" in hooks_help.stdout


def test_sync_git_init_status_export_and_hooks(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    sync_repo = tmp_path / "state-repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    init_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "init",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert init_result.exit_code == 0, init_result.stdout
    init_payload = json.loads(init_result.stdout)
    assert init_payload["result"]["kind"] == "taskledger_sync_git_init"
    assert (sync_repo / "project-a" / "storage.yaml").exists()

    _git(sync_repo, "config", "user.email", "test@example.com")
    _git(sync_repo, "config", "user.name", "Taskledger Test")

    status_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "status",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert status_result.exit_code == 0, status_result.stdout
    status_payload = json.loads(status_result.stdout)
    assert status_payload["result"]["kind"] == "taskledger_sync_git_status"
    assert status_payload["result"]["taskledger_dir_matches"] is True

    export_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "export-local",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
            "--message",
            "Initial state",
            "--allow-dirty",
        ],
    )
    assert export_result.exit_code == 0, export_result.stdout
    export_payload = json.loads(export_result.stdout)
    assert export_payload["result"]["kind"] == "taskledger_sync_git_export_local"
    assert export_payload["result"]["committed"] is True

    hooks_install = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "hooks",
            "install",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert hooks_install.exit_code == 0, hooks_install.stdout
    hooks_status = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "hooks",
            "status",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert hooks_status.exit_code == 0, hooks_status.stdout
    status_payload = json.loads(hooks_status.stdout)
    assert all(
        item["status"] == "managed" for item in status_payload["result"]["hooks"]
    )

    hooks_uninstall = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "hooks",
            "uninstall",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert hooks_uninstall.exit_code == 0, hooks_uninstall.stdout
    uninstall_payload = json.loads(hooks_uninstall.stdout)
    assert uninstall_payload["result"]["removed"]

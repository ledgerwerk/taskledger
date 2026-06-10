from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app

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


def _git(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "safe.bareRepository=all", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _output(result: object) -> str:
    stdout = getattr(result, "stdout", "")
    stderr = getattr(result, "stderr", "")
    return f"{stdout}{stderr}"


def _init_sync_workspace(
    tmp_path: Path,
    *,
    workspace_name: str = "repo",
    sync_repo: Path | None = None,
    project_path: str = "project-a",
) -> tuple[Path, Path]:
    workspace = tmp_path / workspace_name
    if workspace.exists():
        raise AssertionError(f"workspace already exists: {workspace}")
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0
    if sync_repo is None:
        sync_repo = tmp_path / "state-repo"
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
            project_path,
        ],
    )
    assert init_result.exit_code == 0, _output(init_result)
    _git(sync_repo, "config", "user.email", "test@example.com")
    _git(sync_repo, "config", "user.name", "Taskledger Test")
    _git(sync_repo, "add", ".")
    staged_diff = _git(
        sync_repo,
        "diff",
        "--cached",
        "--quiet",
        "--exit-code",
        check=False,
    )
    if staged_diff.returncode != 0:
        _git(sync_repo, "commit", "-m", "Initial sync state")
    return workspace, sync_repo


def test_sync_git_help_promotes_pull_and_push(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert runner.invoke(app, ["--root", str(workspace), "init"]).exit_code == 0

    git_help = runner.invoke(app, ["--root", str(workspace), "sync", "git", "--help"])
    hooks_help = runner.invoke(
        app,
        ["--root", str(workspace), "sync", "git", "hooks", "--help"],
    )

    assert git_help.exit_code == 0, _output(git_help)
    assert "init" in git_help.stdout
    assert "status" in git_help.stdout
    assert "cd" in git_help.stdout
    assert "path" in git_help.stdout
    assert "commit" in git_help.stdout
    assert "import-local" in git_help.stdout
    assert "export-local" in git_help.stdout
    assert "pull" in git_help.stdout
    assert "push" in git_help.stdout
    assert "hooks" in git_help.stdout

    assert hooks_help.exit_code == 0, _output(hooks_help)
    assert "install" in hooks_help.stdout
    assert "status" in hooks_help.stdout
    assert "uninstall" in hooks_help.stdout


def test_sync_git_status_splits_project_and_outside_dirty_state(tmp_path: Path) -> None:
    workspace, sync_repo = _init_sync_workspace(tmp_path)
    (sync_repo / "project-a" / "local-note.txt").write_text(
        "project\n",
        encoding="utf-8",
    )
    (sync_repo / "project-b").mkdir()
    (sync_repo / "project-b" / "other.txt").write_text("outside\n", encoding="utf-8")

    result = runner.invoke(
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

    assert result.exit_code == 0, _output(result)
    payload = json.loads(result.stdout)["result"]
    assert payload["kind"] == "taskledger_sync_git_status"
    assert payload["project_path"] == "project-a"
    assert payload["project_dirty"] is True
    assert payload["dirty"] is True
    assert payload["outside_dirty"] is True
    assert payload["outside_dirty_count"] == 1
    assert payload["status_lines"] == payload["project_status_lines"]
    assert any(
        "project-a/local-note.txt" in line for line in payload["project_status_lines"]
    )
    assert any("project-b" in line for line in payload["outside_status_lines"])


def test_sync_git_commit_ignores_unrelated_dirty_paths(tmp_path: Path) -> None:
    workspace, sync_repo = _init_sync_workspace(tmp_path)
    (sync_repo / "project-a" / "local-note.txt").write_text(
        "project\n",
        encoding="utf-8",
    )
    (sync_repo / "project-b").mkdir()
    (sync_repo / "project-b" / "other.txt").write_text("outside\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "commit",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
            "--message",
            "Sync project-a",
        ],
    )

    assert result.exit_code == 0, _output(result)
    payload = json.loads(result.stdout)["result"]
    assert payload["kind"] == "taskledger_sync_git_commit"
    assert payload["committed"] is True
    assert any("ignored" in warning for warning in payload["warnings"])

    show = _git(
        sync_repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    ).stdout.splitlines()
    assert "project-a/local-note.txt" in show
    assert "project-b/other.txt" not in show
    assert "project-b" in _git(sync_repo, "status", "--short", "--", "project-b").stdout


def test_sync_git_export_local_remains_compatibility_alias(tmp_path: Path) -> None:
    workspace, sync_repo = _init_sync_workspace(tmp_path)
    (sync_repo / "project-a" / "alias-note.txt").write_text(
        "compat\n",
        encoding="utf-8",
    )

    result = runner.invoke(
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
            "Compatibility export",
        ],
    )

    assert result.exit_code == 0, _output(result)
    payload = json.loads(result.stdout)["result"]
    assert payload["kind"] == "taskledger_sync_git_export_local"
    assert payload["committed"] is True


def test_sync_git_cd_and_path_report_expected_locations(tmp_path: Path) -> None:
    workspace, sync_repo = _init_sync_workspace(tmp_path)

    cd_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "sync",
            "git",
            "cd",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert cd_result.exit_code == 0, _output(cd_result)
    assert cd_result.stdout.strip().replace("\\", "/") == str(sync_repo).replace(
        "\\", "/"
    )

    cd_json = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "cd",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )
    assert cd_json.exit_code == 0, _output(cd_json)
    cd_payload = json.loads(cd_json.stdout)["result"]
    assert cd_payload["kind"] == "taskledger_sync_git_paths"
    assert Path(cd_payload["repo_path"]) == sync_repo
    assert cd_payload["project_path"] == "project-a"
    assert Path(cd_payload["storage_path"]) == sync_repo / "project-a"

    path_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "path",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
            "--kind",
            "storage",
        ],
    )
    assert path_result.exit_code == 0, _output(path_result)
    path_payload = json.loads(path_result.stdout)["result"]
    assert path_payload["selected_kind"] == "storage"
    assert Path(path_payload["selected_path"]) == sync_repo / "project-a"


def test_sync_git_pull_fails_fast_for_dirty_shared_repo(tmp_path: Path) -> None:
    workspace, sync_repo = _init_sync_workspace(tmp_path)
    (sync_repo / "project-b").mkdir()
    (sync_repo / "project-b" / "other.txt").write_text("outside\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "sync",
            "git",
            "pull",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )

    assert result.exit_code != 0
    output = _output(result)
    assert "whole sync repository" in output
    assert "--allow-dirty" in output


def test_sync_git_push_commits_all_sync_repo_changes_and_pushes(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))

    workspace, sync_repo = _init_sync_workspace(tmp_path)
    _git(sync_repo, "remote", "add", "origin", str(remote))
    _git(sync_repo, "push", "-u", "origin", "main")

    (sync_repo / "project-a" / "local-note.txt").write_text(
        "project\n",
        encoding="utf-8",
    )
    (sync_repo / "project-b").mkdir()
    (sync_repo / "project-b" / "other.txt").write_text("outside\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "push",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )

    assert result.exit_code == 0, _output(result)
    payload = json.loads(result.stdout)["result"]
    assert payload["kind"] == "taskledger_sync_git_push"
    assert payload["committed"] is True
    assert payload["pushed"] is True
    assert payload["commit_hash"]
    assert payload["include_outside_project"] is True
    assert payload["outside_dirty_count"] == 1
    assert any("included" in warning for warning in payload["warnings"])

    pushed_files = _git(
        sync_repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    ).stdout.splitlines()
    assert "project-a/local-note.txt" in pushed_files
    assert "project-b/other.txt" in pushed_files
    assert (
        _git(sync_repo, "log", "-1", "--pretty=%s").stdout.strip()
        == "Sync taskledger state for project-a"
    )


def test_sync_git_pull_runs_git_pull_without_manual_cd(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))

    workspace, sync_repo = _init_sync_workspace(tmp_path)
    _git(sync_repo, "remote", "add", "origin", str(remote))
    _git(sync_repo, "push", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")

    other = tmp_path / "other-clone"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Taskledger Test")
    (other / "project-a").mkdir(exist_ok=True)
    (other / "project-a" / "pulled-note.txt").write_text("remote\n", encoding="utf-8")
    _git(other, "add", "--all")
    _git(other, "commit", "-m", "Remote state update")
    _git(other, "push", "origin", "main")

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "sync",
            "git",
            "pull",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-a",
        ],
    )

    assert result.exit_code == 0, _output(result)
    payload = json.loads(result.stdout)["result"]
    assert payload["kind"] == "taskledger_sync_git_pull"
    assert payload["pulled"] is True
    assert payload["doctor_healthy"] is True
    assert payload["warnings"] == []
    assert (sync_repo / "project-a" / "pulled-note.txt").exists()


def test_sync_git_hooks_install_rejects_cross_project_managed_hook(
    tmp_path: Path,
) -> None:
    workspace_a, sync_repo = _init_sync_workspace(tmp_path, workspace_name="repo-a")
    install_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace_a),
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
    assert install_result.exit_code == 0, _output(install_result)

    workspace_b, _ = _init_sync_workspace(
        tmp_path,
        workspace_name="repo-b",
        sync_repo=sync_repo,
        project_path="project-b",
    )
    conflict_result = runner.invoke(
        app,
        [
            "--root",
            str(workspace_b),
            "sync",
            "git",
            "hooks",
            "install",
            "--repo",
            str(sync_repo),
            "--project-path",
            "project-b",
        ],
    )

    assert conflict_result.exit_code != 0
    assert "multi-project-safe" in _output(conflict_result)

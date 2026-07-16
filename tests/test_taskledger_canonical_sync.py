from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.services.git_sync import (
    build_git_sync_config,
    git_sync_commit,
    git_sync_export_local,
    git_sync_import_local,
    git_sync_paths,
    init_git_sync_repo,
    install_git_hooks,
)
from taskledger.services.storage_locations import build_storage_location_report
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import load_project_context


def _init(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project, create_sibling_store=True)
    subprocess.run(["git", "-C", str(tmp_path / "ledger"), "init"], check=True)
    return project


def test_canonical_sync_derives_sibling_repo_and_path(tmp_path: Path) -> None:
    project = _init(tmp_path)
    context = load_project_context(project)
    expected_project_path = f"taskledger/{context.project_uuid}"
    config = build_git_sync_config(project)
    assert config.repo_path == tmp_path / "ledger"
    assert config.project_path == expected_project_path
    paths = git_sync_paths(project)
    assert paths["repo_path"] == str(tmp_path / "ledger")
    assert paths["project_path"] == expected_project_path

    location = build_storage_location_report(project).to_dict()
    assert location["workspace_provider"] == "sibling-ledger"
    assert location["relative_path"] == expected_project_path


def test_canonical_sync_rejects_storage_selectors(tmp_path: Path) -> None:
    project = _init(tmp_path)
    with pytest.raises(LaunchError, match="CANONICAL_SYNC_PATH_FIXED"):
        build_git_sync_config(project, repo=tmp_path / "other")
    with pytest.raises(LaunchError, match="CANONICAL_SYNC_PATH_FIXED"):
        build_git_sync_config(project, project_path="other")


def test_canonical_git_init_does_not_move_storage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context, _ = init_canonical_project_state(project, create_sibling_store=True)
    data_root = context.paths.data_root
    before = sorted(path.relative_to(data_root) for path in data_root.rglob("*"))

    payload = init_git_sync_repo(project)

    assert payload["taskledger_dir_updated"] is False
    assert (tmp_path / "ledger" / ".git").is_dir()
    assert (
        sorted(path.relative_to(data_root) for path in data_root.rglob("*")) == before
    )


def test_canonical_git_commit_limits_committed_paths(tmp_path: Path) -> None:
    project = _init(tmp_path)
    context = load_project_context(project)
    repo = tmp_path / "ledger"
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Taskledger Test"],
        check=True,
    )
    task_file = repo / "taskledger" / context.project_uuid / "task-state.txt"
    outside_file = repo / "plan" / "plan-state.txt"
    task_file.write_text("task\n", encoding="utf-8")
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("plan\n", encoding="utf-8")

    payload = git_sync_commit(project, message="Task state")

    assert payload["include_outside_project"] is False
    committed = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-only", "--format="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert f"taskledger/{context.project_uuid}/task-state.txt" in committed
    assert "plan/plan-state.txt" not in committed
    assert outside_file.exists()


def test_canonical_local_sync_aliases_are_rejected(tmp_path: Path) -> None:
    project = _init(tmp_path)
    with pytest.raises(LaunchError, match="CANONICAL_SYNC_PATH_FIXED"):
        git_sync_import_local(project)
    with pytest.raises(LaunchError, match="CANONICAL_SYNC_PATH_FIXED"):
        git_sync_export_local(project)


def test_canonical_hooks_reindex_fixed_sibling_store(tmp_path: Path) -> None:
    project = _init(tmp_path)
    payload = install_git_hooks(project)
    assert payload["installed"] == ["post-merge", "post-checkout", "post-rewrite"]
    hook = (tmp_path / "ledger" / ".git" / "hooks" / "post-merge").read_text(
        encoding="utf-8"
    )
    assert "reindex" in hook
    assert "import-local" not in hook
    assert "taskledger" in hook

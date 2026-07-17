from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.services.git_sync import build_git_sync_config
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.ledgercore_backend import set_taskledger_mount_target


def test_git_sync_derives_repository_and_data_relative_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project, data_storage="project")
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)

    config = build_git_sync_config(project)

    assert config.repo_path == project
    assert config.project_path == ".ledger/taskledger/data"


def test_user_data_without_git_has_clear_error(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project)
    set_taskledger_mount_target(
        project,
        mount="data",
        storage="user-data",
        external_root=None,
        target="local",
    )

    with pytest.raises(LaunchError, match="TASKLEDGER_STORAGE_NOT_GIT_BACKED"):
        build_git_sync_config(project)

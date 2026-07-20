"""Tests for taskledger.storage.init."""

from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import ensure_project_exists, init_project_state


# specmason: req=REQ-0053 ac=AC-0560
def test_init_project_state_creates_structure(tmp_path: Path) -> None:
    paths, created = init_project_state(tmp_path)
    assert paths.project_dir.exists()
    assert paths.config_path.exists()
    assert paths.config_path == tmp_path / "taskledger.toml"
    assert paths.repo_index_path.exists()
    assert (paths.project_dir / "indexes" / "active_locks.json").exists()
    assert not (paths.project_dir / "indexes" / "tasks.json").exists()
    assert not (paths.project_dir / "indexes" / "latest_runs.json").exists()
    assert not (paths.project_dir / "indexes" / "plan_versions.json").exists()
    assert not (paths.project_dir / "project.toml").exists()
    assert len(created) > 0


# specmason: req=REQ-0053 ac=AC-0560
def test_init_project_state_idempotent(tmp_path: Path) -> None:
    init_project_state(tmp_path)
    _, created = init_project_state(tmp_path)
    assert created == []


# specmason: req=REQ-0053 ac=AC-0558
def test_ensure_project_exists_after_init(tmp_path: Path) -> None:
    init_project_state(tmp_path)
    paths = ensure_project_exists(tmp_path)
    assert paths.workspace_root == tmp_path


# specmason: req=REQ-0053 ac=AC-0558
def test_ensure_project_exists_raises_without_init(tmp_path: Path) -> None:
    with pytest.raises(LaunchError, match="not initialized"):
        ensure_project_exists(tmp_path)


# specmason: req=REQ-0053 ac=AC-0558
def test_ensure_project_exists_rejects_legacy_item_index(tmp_path: Path) -> None:
    init_project_state(tmp_path)
    paths, _ = init_project_state(tmp_path)
    items_dir = paths.taskledger_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    (items_dir / "index.json").write_text("[]")
    with pytest.raises(LaunchError, match="Legacy item"):
        ensure_project_exists(tmp_path)


# specmason: req=REQ-0053 ac=AC-0558
def test_ensure_project_exists_rejects_legacy_memory_index(tmp_path: Path) -> None:
    init_project_state(tmp_path)
    paths, _ = init_project_state(tmp_path)
    mem_dir = paths.taskledger_dir / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "index.json").write_text("[]")
    with pytest.raises(LaunchError, match="Legacy memory"):
        ensure_project_exists(tmp_path)


# specmason: req=REQ-0053 ac=AC-0559
def test_init_creates_expected_directories(tmp_path: Path) -> None:
    paths, _ = init_project_state(tmp_path)
    assert (paths.project_dir / "intros").is_dir()
    assert paths.releases_dir.is_dir()
    assert (paths.project_dir / "tasks").is_dir()
    assert (paths.project_dir / "events").is_dir()
    assert (paths.project_dir / "indexes").is_dir()

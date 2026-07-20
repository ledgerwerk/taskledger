"""Tests for taskledger.storage.repos."""

from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_project_state
from taskledger.storage.repos import (
    ProjectRepo,
    add_repo,
    clear_default_execution_repo,
    load_repos,
    remove_repo,
    resolve_repo,
    resolve_repo_root,
    save_repos,
    set_default_execution_repo,
    set_repo_role,
)


def _paths(tmp_path: Path):
    paths, _ = init_project_state(tmp_path)
    return paths


# specmason: req=REQ-0055 ac=AC-0595
def test_save_and_load_repos(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo = ProjectRepo(
        name="test-repo",
        slug="test-repo",
        path=str(tmp_path),
        kind="generic",
        branch=None,
        notes=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    save_repos(paths, [repo])
    loaded = load_repos(paths)
    assert len(loaded) == 1
    assert loaded[0].name == "test-repo"


# specmason: req=REQ-0055 ac=AC-0595
# specmason: req=REQ-0055 ac=AC-0597
# specmason: req=REQ-0055 ac=AC-0598
# specmason: req=REQ-0055 ac=AC-0600
# specmason: req=REQ-0055 ac=AC-0603
# specmason: req=REQ-0055 ac=AC-0606
def test_add_repo(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "my-code"
    repo_dir.mkdir()
    repo = add_repo(paths, name="my-code", path=repo_dir, kind="generic", role="write")
    assert repo.name == "my-code"
    assert repo.slug == "my-code"
    loaded = load_repos(paths)
    assert len(loaded) == 1


def test_add_repo_rejects_duplicate_name(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "my-code"
    repo_dir.mkdir()
    add_repo(paths, name="my-code", path=repo_dir, kind="generic", role="write")
    with pytest.raises(LaunchError, match="already exists"):
        add_repo(paths, name="my-code", path=repo_dir, kind="generic", role="write")


def test_add_repo_rejects_invalid_kind(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    with pytest.raises(LaunchError, match="Unsupported project repo kind"):
        add_repo(paths, name="code", path=repo_dir, kind="invalid", role="read")


# specmason: req=REQ-0055 ac=AC-0605
def test_add_repo_rejects_invalid_role(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    with pytest.raises(LaunchError, match="Unsupported project repo role"):
        add_repo(paths, name="code", path=repo_dir, kind="generic", role="invalid")


def test_add_repo_rejects_preferred_readonly(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    with pytest.raises(LaunchError, match="Read-only"):
        add_repo(
            paths,
            name="code",
            path=repo_dir,
            kind="generic",
            role="read",
            preferred_for_execution=True,
        )


def test_add_repo_rejects_nonexistent_path(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(LaunchError, match="does not exist"):
        add_repo(
            paths,
            name="code",
            path=tmp_path / "nope",
            kind="generic",
            role="read",
        )


# specmason: req=REQ-0055 ac=AC-0601
# specmason: req=REQ-0055 ac=AC-0602
def test_resolve_repo(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "my-code"
    repo_dir.mkdir()
    add_repo(paths, name="my-code", path=repo_dir, kind="generic", role="write")
    found = resolve_repo(paths, "my-code")
    assert found.name == "my-code"


# specmason: req=REQ-0055 ac=AC-0601
# specmason: req=REQ-0055 ac=AC-0602
def test_resolve_repo_by_slugified_ref(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "My Code"
    repo_dir.mkdir()
    add_repo(paths, name="My Code", path=repo_dir, kind="generic", role="write")
    found = resolve_repo(paths, "my-code")
    assert found.name == "My Code"


# specmason: req=REQ-0055 ac=AC-0601
def test_resolve_repo_unknown_raises(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(LaunchError, match="Unknown"):
        resolve_repo(paths, "nope")


# specmason: req=REQ-0055 ac=AC-0601
def test_resolve_repo_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "my-code"
    repo_dir.mkdir()
    add_repo(paths, name="my-code", path=repo_dir, kind="generic", role="write")
    root = resolve_repo_root(paths, "my-code")
    assert root == repo_dir.resolve()


# specmason: req=REQ-0055 ac=AC-0599
def test_remove_repo(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "my-code"
    repo_dir.mkdir()
    add_repo(paths, name="my-code", path=repo_dir, kind="generic", role="write")
    removed = remove_repo(paths, "my-code")
    assert removed.name == "my-code"
    assert load_repos(paths) == []


# specmason: req=REQ-0055 ac=AC-0605
def test_set_repo_role(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    add_repo(paths, name="code", path=repo_dir, kind="generic", role="read")
    updated = set_repo_role(paths, "code", role="both")
    assert updated.role == "both"


# specmason: req=REQ-0055 ac=AC-0605
def test_set_repo_role_rejects_invalid(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    add_repo(paths, name="code", path=repo_dir, kind="generic", role="read")
    with pytest.raises(LaunchError, match="Unsupported project repo role"):
        set_repo_role(paths, "code", role="nope")


# specmason: req=REQ-0055 ac=AC-0605
def test_set_repo_role_rejects_readonly_if_preferred(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    add_repo(paths, name="code", path=repo_dir, kind="generic", role="write")
    set_default_execution_repo(paths, "code")
    with pytest.raises(LaunchError, match="read-only"):
        set_repo_role(paths, "code", role="read")


# specmason: req=REQ-0055 ac=AC-0604
def test_set_default_execution_repo(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    add_repo(paths, name="code", path=repo_dir, kind="generic", role="write")
    result = set_default_execution_repo(paths, "code")
    assert result.preferred_for_execution is True


# specmason: req=REQ-0055 ac=AC-0604
def test_set_default_execution_repo_rejects_readonly(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    add_repo(paths, name="code", path=repo_dir, kind="generic", role="read")
    with pytest.raises(LaunchError, match="read-only"):
        set_default_execution_repo(paths, "code")


# specmason: req=REQ-0055 ac=AC-0596
def test_clear_default_execution_repo(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo_dir = tmp_path / "code"
    repo_dir.mkdir()
    add_repo(paths, name="code", path=repo_dir, kind="generic", role="write")
    set_default_execution_repo(paths, "code")
    updated = clear_default_execution_repo(paths)
    assert all(not r.preferred_for_execution for r in updated)

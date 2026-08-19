from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.services.workspace_snapshot import (
    WorkspaceContentSnapshot,
    WorktreePathEntry,
    capture_current_workspace_state,
    capture_workspace_content_snapshot,
    save_workspace_snapshot_manifest,
)
from taskledger.storage.init import init_canonical_project_state


def test_snapshot_deserialization_round_trip() -> None:
    entry = WorktreePathEntry(
        path="src/example.py",
        status="modified",
        exists=True,
        kind="file",
        size=12,
        content_hash="sha256:abc",
    )
    snapshot = WorkspaceContentSnapshot(
        git_commit="abc123",
        dirty=True,
        content_hash="sha256:content",
        paths_hash="sha256:paths",
        entry_count=1,
        entries=(entry,),
        captured_at="2026-07-10T00:00:00Z",
    )

    restored = WorkspaceContentSnapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot


def test_snapshot_deserialization_uses_fallbacks_for_invalid_values() -> None:
    entry = WorktreePathEntry.from_dict(
        {
            "path": "README.md",
            "status": "modified",
            "exists": True,
            "kind": "file",
            "size": "unknown",
            "content_hash": 42,
        }
    )
    snapshot = WorkspaceContentSnapshot.from_dict(
        {
            "entries": [
                {
                    "path": "README.md",
                    "status": "modified",
                    "exists": True,
                    "kind": "file",
                    "size": 10,
                    "content_hash": "sha256:readme",
                },
                "invalid entry",
            ],
            "git_commit": 42,
            "dirty": "yes",
            "content_hash": 42,
            "paths_hash": 42,
            "entry_count": "unknown",
            "captured_at": 42,
        }
    )

    assert entry.size is None
    assert entry.content_hash is None
    assert snapshot.git_commit is None
    assert snapshot.dirty is None
    assert snapshot.content_hash is None
    assert snapshot.paths_hash is None
    assert snapshot.entry_count == 1
    assert len(snapshot.entries) == 1
    assert snapshot.captured_at is None


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Taskledger Test")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-m", "initial")


def test_workspace_content_snapshot_excludes_canonical_taskledger_project_data(
    tmp_path: Path,
) -> None:
    _init_git(tmp_path)
    context, _ = init_canonical_project_state(tmp_path, data_storage="project")
    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")

    generated = context.paths.data_root / "ledgers" / "main" / "runs" / "runtime.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("runtime\n", encoding="utf-8")

    snapshot = capture_workspace_content_snapshot(tmp_path)
    paths = {entry.path for entry in snapshot.entries}

    assert "tracked.txt" in paths
    assert generated.relative_to(context.paths.workspace_root).as_posix() not in paths


def test_workspace_content_snapshot_never_hashes_its_own_manifest(
    tmp_path: Path,
) -> None:
    _init_git(tmp_path)
    context, _ = init_canonical_project_state(tmp_path, data_storage="project")
    manifest = (
        context.paths.data_root
        / "ledgers"
        / "main"
        / "runs"
        / "task-0004"
        / "run-0002.workspace-snapshot.json"
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"old": true}\n', encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")

    snapshot = capture_workspace_content_snapshot(tmp_path)
    paths = {entry.path for entry in snapshot.entries}

    assert "tracked.txt" in paths
    assert manifest.relative_to(tmp_path).as_posix() not in paths


def test_snapshot_manifest_self_reference_raises_invariant_error(
    tmp_path: Path,
) -> None:
    _init_git(tmp_path)
    context, _ = init_canonical_project_state(tmp_path, data_storage="project")
    manifest = (
        context.paths.data_root
        / "ledgers"
        / "main"
        / "runs"
        / "task-0004"
        / "run-0002.workspace-snapshot.json"
    )
    manifest_ref = manifest.relative_to(tmp_path).as_posix()
    snapshot = WorkspaceContentSnapshot(
        git_commit="HEAD",
        dirty=True,
        content_hash="sha256:content",
        paths_hash="sha256:paths",
        entry_count=1,
        entries=(
            WorktreePathEntry(
                path=manifest_ref,
                status="untracked",
                exists=True,
                kind="file",
                size=1,
                content_hash="sha256:manifest",
            ),
        ),
        captured_at=None,
    )

    with pytest.raises(LaunchError) as raised:
        save_workspace_snapshot_manifest(tmp_path, "task-0004", "run-0002", snapshot)

    assert raised.value.code == "WORKSPACE_SNAPSHOT_SELF_REFERENCE"
    assert "do not refresh" in str(raised.value)


def test_workspace_content_snapshot_does_not_hide_taskledger_project_config(
    tmp_path: Path,
) -> None:
    _init_git(tmp_path)
    context, _ = init_canonical_project_state(tmp_path, data_storage="project")
    del context
    config = tmp_path / ".ledger" / "taskledger" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )
    ledger_manifest = tmp_path / ".ledger" / "ledger.toml"
    ledger_manifest.write_text(
        ledger_manifest.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )

    snapshot = capture_workspace_content_snapshot(tmp_path)
    paths = {entry.path for entry in snapshot.entries}

    assert ".ledger/taskledger/config.toml" in paths
    assert ".ledger/ledger.toml" in paths


def test_snapshot_exclusion_resolution_fails_closed_for_broken_canonical_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_git(tmp_path)
    init_canonical_project_state(tmp_path, data_storage="project")

    def fail_context(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise LaunchError("canonical context is unreadable")

    from taskledger.storage import project_context

    monkeypatch.setattr(project_context, "load_project_context", fail_context)

    with pytest.raises(LaunchError) as raised:
        capture_workspace_content_snapshot(tmp_path)

    assert raised.value.code == "WORKSPACE_SNAPSHOT_EXCLUSIONS_UNAVAILABLE"
    assert "taskledger doctor" in str(raised.value)


def test_workspace_content_snapshot_still_excludes_legacy_taskledger_state(
    tmp_path: Path,
) -> None:
    _init_git(tmp_path)
    legacy_state = tmp_path / ".taskledger" / "generated.json"
    legacy_state.parent.mkdir()
    legacy_state.write_text("{}\n", encoding="utf-8")

    snapshot = capture_workspace_content_snapshot(tmp_path)

    assert ".taskledger/generated.json" not in {
        entry.path for entry in snapshot.entries
    }


def test_workspace_content_snapshot_excludes_external_root_inside_parent_git_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "app"
    project.mkdir(parents=True)
    _init_git(repo)
    context, _ = init_canonical_project_state(
        project,
        data_storage="external",
        external_root="../ledger",
    )
    generated = context.paths.data_root / "generated.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("{}\n", encoding="utf-8")
    (project / "source.txt").write_text("changed\n", encoding="utf-8")

    snapshot = capture_workspace_content_snapshot(project)
    paths = {entry.path for entry in snapshot.entries}

    assert "app/source.txt" in paths
    assert generated.relative_to(repo).as_posix() not in paths


def test_workspace_content_snapshot_excludes_nested_project_storage_under_parent_git(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "releaseledger"
    project.mkdir(parents=True)
    _init_git(repo)
    context, _ = init_canonical_project_state(project, data_storage="project")
    generated = context.paths.data_root / "generated.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("{}\n", encoding="utf-8")
    config = project / ".ledger" / "taskledger" / "config.toml"
    config.write_text(config.read_text(encoding="utf-8") + "\n# changed\n")
    (project / "src.txt").write_text("source\n", encoding="utf-8")

    snapshot = capture_workspace_content_snapshot(project)
    paths = {entry.path for entry in snapshot.entries}

    assert "releaseledger/src.txt" in paths
    assert "releaseledger/.ledger/taskledger/config.toml" in paths
    assert generated.relative_to(repo).as_posix() not in paths


def test_shared_workspace_content_capture_matches_direct_capture(
    tmp_path: Path,
) -> None:
    _init_git(tmp_path)
    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")

    direct = capture_workspace_content_snapshot(tmp_path)
    shared = capture_current_workspace_state(tmp_path, include_content=True)

    assert shared.content_captured is True
    assert shared.content_entries == direct.entries
    assert direct.content_hash is not None
    assert direct.paths_hash is not None

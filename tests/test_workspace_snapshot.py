from __future__ import annotations

from taskledger.services.workspace_snapshot import (
    WorkspaceContentSnapshot,
    WorktreePathEntry,
)


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

from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.ledger_manifest import ensure_taskledger_registration

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def test_registration_is_idempotent(tmp_path: Path) -> None:
    first = ensure_taskledger_registration(
        tmp_path, project_uuid=UUID, project_name="demo"
    )
    original = first.manifest_path.read_text(encoding="utf-8")
    second = ensure_taskledger_registration(
        tmp_path, project_uuid=UUID, project_name="demo"
    )
    assert first.created and first.changed
    assert not second.changed
    assert second.manifest_path.read_text(encoding="utf-8") == original


def test_existing_registration_and_comments_survive(tmp_path: Path) -> None:
    manifest = tmp_path / ".ledger" / "ledger.toml"
    manifest.parent.mkdir()
    manifest.write_text(
        (
            f'schema_version = 2\n[project]\nuuid = "{UUID}"\n# keep this\n'
            '[storage.workspace]\ndefault_provider = "user-data"\n'
            'namespace = "ledgerwerk"\n'
            '[storage.cache]\ndefault_provider = "user-cache"\n'
            'namespace = "ledgerwerk"\n'
            '[ledgers.other.config]\nlocation = "project"\n'
            'path = "other/config.toml"\n'
        ),
        encoding="utf-8",
    )
    ensure_taskledger_registration(tmp_path, project_uuid=UUID)
    text = manifest.read_text(encoding="utf-8")
    assert "keep this" in text
    assert "ledgers.other" in text
    assert "ledgers.taskledger.mounts.indexes" in text


def test_conflicting_mount_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / ".ledger" / "ledger.toml"
    manifest.parent.mkdir()
    manifest.write_text(
        (
            f'schema_version = 2\n[project]\nuuid = "{UUID}"\n'
            '[ledgers.taskledger.config]\nlocation = "project"\n'
            'path = "task/config.toml"\n'
            '[ledgers.taskledger.mounts.data]\nstorage = "workspace"\n'
            'scope = "project"\npath = "task/data"\n'
        ),
        encoding="utf-8",
    )
    with pytest.raises(LaunchError, match="conflicting"):
        ensure_taskledger_registration(tmp_path, project_uuid=UUID)

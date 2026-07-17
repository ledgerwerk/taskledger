from __future__ import annotations

from pathlib import Path

from ledgercore.migration import _staging_path


def test_ancestor_to_child_migration_stages_outside_source(tmp_path: Path) -> None:
    source = tmp_path / "uuid"
    destination = source / "data"

    staging, staging_root = _staging_path(source, destination, "migration-1")

    assert staging == tmp_path / "uuid.migrating-migration-1" / "data"
    assert staging_root == tmp_path / "uuid.migrating-migration-1"
    assert not staging.is_relative_to(source)
    assert not staging_root.is_relative_to(source)

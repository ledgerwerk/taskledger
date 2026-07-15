from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import load_project_context


def test_fresh_canonical_context_is_read_only_before_initialization(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ledger").mkdir()
    (tmp_path / ".ledger" / "ledger.toml").write_text(
        (
            "schema_version = 2\n[project]\n"
            'uuid = "081c7c05-2d10-42b7-9b37-3d814c2f400a"\n\n'
            '[ledgers.other.config]\nlocation = "project"\npath = "other/config.toml"\n'
        ),
        encoding="utf-8",
    )
    before = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    with pytest.raises(LaunchError, match="unknown ledger registration"):
        load_project_context(tmp_path)
    after = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    assert after == before


def test_canonical_init_is_repository_local_by_default(tmp_path: Path) -> None:
    context, _ = init_canonical_project_state(tmp_path, project_name="demo")
    assert context.mode == "canonical"
    assert context.project_uuid
    assert set(context.layout.mounts) == {"data", "indexes"}
    assert context.layout.mounts["data"].storage == "repository"
    assert context.paths.data_root == tmp_path / ".ledger" / "task" / "taskledger"
    assert context.paths.storage_meta_path.exists()
    assert not (tmp_path.parent / "ledger").exists()
    assert not (tmp_path / ".taskledger").exists()


def test_explicit_sibling_root_is_uuid_scoped(tmp_path: Path) -> None:
    sibling_root = tmp_path / "shared-ledger"
    project = tmp_path / "project"
    project.mkdir()
    context, _ = init_canonical_project_state(
        project,
        sibling_ledger_root=sibling_root,
        create_store=True,
    )
    assert context.paths.data_root == sibling_root / "taskledger" / context.project_uuid
    assert context.layout.mounts["data"].storage == "workspace"
    assert (sibling_root / ".ledger-store").is_file()
    assert (context.paths.data_root / ".ledger-project.toml").is_file()


def test_nested_canonical_context_uses_project_root(tmp_path: Path) -> None:
    context, _ = init_canonical_project_state(tmp_path)
    nested = tmp_path / "src" / "module.py"
    nested.parent.mkdir()
    nested.write_text("", encoding="utf-8")
    assert load_project_context(nested).project_uuid == context.project_uuid

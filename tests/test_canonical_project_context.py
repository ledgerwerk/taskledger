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
            "[ledgers.taskledger.config]\nlocation = 'project'\n"
            "path = 'task/config.toml'\n\n"
            "[ledgers.taskledger.mounts.data]\n"
            "storage = 'workspace'\nscope = 'project'\npath = 'task/taskledger'\n\n"
            "[ledgers.taskledger.mounts.indexes]\n"
            "storage = 'cache'\nscope = 'checkout'\n"
            "path = 'task/taskledger-indexes'\n"
        ),
        encoding="utf-8",
    )
    before = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    with pytest.raises(LaunchError, match="SIBLING_PROVIDER_REQUIRED"):
        load_project_context(tmp_path, require_initialized=False)
    after = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    assert after == before


def test_canonical_init_uses_fixed_direct_sibling_store(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sibling = tmp_path / "ledger"
    sibling.mkdir()
    (sibling / ".ledger-store").write_text("store\n", encoding="utf-8")

    context, _ = init_canonical_project_state(project, project_name="demo")

    assert context.mode == "canonical"
    assert context.project_uuid
    assert context.layout is not None
    assert context.layout.mounts["data"].storage == "workspace"
    assert context.paths.data_root == sibling / "task" / "taskledger"
    assert not (project / ".ledger" / "task" / "taskledger").exists()
    assert (context.paths.data_root / ".ledger-project.toml").is_file()


def test_explicit_store_creation_uses_fixed_sibling_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    context, _ = init_canonical_project_state(project, create_sibling_store=True)

    assert context.paths.data_root == tmp_path / "ledger" / "task" / "taskledger"
    assert (tmp_path / "ledger" / ".ledger-store").is_file()


def test_nested_canonical_context_uses_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context, _ = init_canonical_project_state(project, create_sibling_store=True)
    nested = project / "src" / "module.py"
    nested.parent.mkdir()
    nested.write_text("", encoding="utf-8")
    assert load_project_context(nested).project_uuid == context.project_uuid

from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import load_project_context


def _marked_store(project_root: Path) -> Path:
    store = project_root.parent / "ledger"
    store.mkdir()
    (store / ".ledger-store").write_text("Ledgercore sibling store\n", encoding="utf-8")
    return store


def test_existing_marked_store_resolves_direct_data_and_lazy_cache(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = _marked_store(project)

    context, _ = init_canonical_project_state(project)

    assert context.paths.data_root == store / "task" / "taskledger"
    assert context.paths.data_root != context.paths.indexes_root
    assert not (project / ".ledger" / "task" / "taskledger").exists()
    assert not context.paths.indexes_root.exists()
    assert context.workspace_provider == "sibling-ledger"
    assert context.data_mount_source == "local-provider"
    assert context.binding_path == context.paths.data_root / ".ledger-project.toml"


def test_missing_store_requires_explicit_creation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(LaunchError, match="SIBLING_ROOT_MISSING"):
        init_canonical_project_state(project)

    context, _ = init_canonical_project_state(project, create_sibling_store=True)
    assert (tmp_path / "ledger" / ".ledger-store").is_file()
    assert context.paths.data_root.exists()


def test_workspace_root_and_environment_overrides_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _marked_store(project)
    context, _ = init_canonical_project_state(project)

    local = project / ".ledger" / "ledger.local.toml"
    local.write_text(
        "schema_version = 1\n[storage.workspace]\nroot = '../other'\n",
        encoding="utf-8",
    )
    with pytest.raises(LaunchError, match="WORKSPACE_ROOT_CONFLICT"):
        load_project_context(project)

    local.write_text(
        "schema_version = 1\n[storage.workspace]\nprovider = 'sibling-ledger'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LEDGER_WORKSPACE_ROOT", str(tmp_path / "other"))
    with pytest.raises(LaunchError, match="WORKSPACE_ENV_UNSUPPORTED"):
        load_project_context(project)

    monkeypatch.delenv("LEDGER_WORKSPACE_ROOT")
    assert load_project_context(project).paths.data_root == context.paths.data_root


def test_binding_rejects_nonempty_unbound_direct_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = _marked_store(project)
    target = store / "task" / "taskledger"
    target.mkdir(parents=True)
    (target / "foreign.txt").write_text("foreign", encoding="utf-8")

    with pytest.raises(LaunchError, match="non-empty and unbound"):
        init_canonical_project_state(project)

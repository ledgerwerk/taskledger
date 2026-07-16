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

    assert context.paths.data_root == store / "taskledger" / context.project_uuid
    assert context.paths.data_root != context.paths.indexes_root
    assert not (project / ".ledger" / "taskledger").exists()
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


def test_binding_rejects_nonempty_unbound_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = _marked_store(project)
    project_uuid = "081c7c05-2d10-42b7-9b37-3d814c2f400a"
    target = store / "taskledger" / project_uuid
    target.mkdir(parents=True)
    (target / "foreign.txt").write_text("foreign", encoding="utf-8")

    with pytest.raises(LaunchError, match="non-empty and unbound"):
        init_canonical_project_state(project, project_uuid=project_uuid)


def test_projects_share_store_without_sharing_uuid_scoped_data(
    tmp_path: Path,
) -> None:
    store = tmp_path / "ledger"
    store.mkdir()
    (store / ".ledger-store").write_text("store\n", encoding="utf-8")
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    context_a, _ = init_canonical_project_state(project_a)
    context_b, _ = init_canonical_project_state(project_b)

    assert context_a.project_uuid != context_b.project_uuid
    assert context_a.paths.data_root == store / "taskledger" / context_a.project_uuid
    assert context_b.paths.data_root == store / "taskledger" / context_b.project_uuid
    assert context_a.paths.data_root != context_b.paths.data_root

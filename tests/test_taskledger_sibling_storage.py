from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state


def _init_external_store(store: Path) -> None:
    """Create a canonical external store marker."""
    from ledgercore import initialize_external_store

    initialize_external_store(store)


def test_existing_marked_store_resolves_direct_data_and_lazy_cache(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = project.parent / "ledger"
    store.mkdir()
    _init_external_store(store)

    context, _ = init_canonical_project_state(project)

    expected = store / "taskledger" / context.project_uuid / "data"
    assert context.paths.data_root == expected
    assert context.paths.data_root != context.paths.indexes_root


def test_missing_store_is_created_by_init(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    # Canonical init creates the external store if it doesn't exist.
    context, created = init_canonical_project_state(project)
    assert context.paths.data_root.exists()
    assert (tmp_path / "ledger" / ".ledger-store.toml").is_file()


def test_binding_rejects_nonempty_unbound_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = project.parent / "ledger"
    store.mkdir()
    _init_external_store(store)
    project_uuid = "081c7c05-2d10-42b7-9b37-3d814c2f400a"
    # Canonical data path includes /data suffix.
    target = store / "taskledger" / project_uuid / "data"
    target.mkdir(parents=True)
    (target / "foreign.txt").write_text("foreign", encoding="utf-8")

    with pytest.raises(LaunchError, match="non-empty and unbound"):
        init_canonical_project_state(project, project_uuid=project_uuid)


def test_binding_accepts_populated_matching_bound_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = project.parent / "ledger"
    store.mkdir()
    _init_external_store(store)

    # First init creates bindings.
    context_a, _ = init_canonical_project_state(project)
    # Populate the data directory.
    (context_a.paths.data_root / "somefile.txt").write_text("data", encoding="utf-8")

    # Second init must succeed idempotently.
    context_b, _ = init_canonical_project_state(project)
    assert context_b.project_uuid == context_a.project_uuid
    assert context_b.paths.data_root == context_a.paths.data_root


def test_projects_share_store_without_sharing_uuid_scoped_data(
    tmp_path: Path,
) -> None:
    store = tmp_path / "ledger"
    store.mkdir()
    _init_external_store(store)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    context_a, _ = init_canonical_project_state(project_a)
    context_b, _ = init_canonical_project_state(project_b)

    assert context_a.project_uuid != context_b.project_uuid
    expected_a = store / "taskledger" / context_a.project_uuid / "data"
    expected_b = store / "taskledger" / context_b.project_uuid / "data"
    assert context_a.paths.data_root == expected_a
    assert context_b.paths.data_root == expected_b
    assert context_a.paths.data_root != context_b.paths.data_root

from __future__ import annotations

from pathlib import Path

from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.ledgercore_backend import (
    load_taskledger_ledger_layout,
    set_taskledger_mount_target,
)
from taskledger.storage.project_context import load_project_context


def test_schema3_default_external_context(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    context, _ = init_canonical_project_state(project, project_name="demo")

    assert context.config_path == project / ".ledger/taskledger/config.toml"
    assert context.layout is not None
    assert context.layout.mounts["data"].storage == "external"
    assert context.layout.mounts["data"].path.as_posix().endswith("/data")
    assert context.layout.mounts["indexes"].storage == "cache"
    assert context.layout.mounts["indexes"].path.as_posix().endswith("/indexes")
    assert not (project / ".ledger/ledger.local.toml").exists()
    assert (tmp_path / "ledger/.ledger-store.toml").is_file()


def test_schema3_user_data_override_is_local(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project)

    set_taskledger_mount_target(
        project,
        mount="data",
        storage="user-data",
        external_root=None,
        target="local",
    )
    context = load_project_context(project, require_initialized=False)

    assert context.layout is not None
    assert context.layout.mounts["data"].storage == "user-data"
    assert context.local_overrides_present
    assert (project / ".ledger/ledger.local.toml").is_file()


def test_schema3_project_storage_is_resolved_without_writes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project, data_storage="project")
    before = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))

    bundle = load_taskledger_ledger_layout(project)
    context = load_project_context(project, require_initialized=False)
    after = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))

    assert bundle.resolved_layout.mounts["data"].path == (
        project / ".ledger/taskledger/data"
    )
    assert context.layout == bundle.resolved_layout
    assert before == after

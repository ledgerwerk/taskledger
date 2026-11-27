from __future__ import annotations

from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.storage.common import write_text
from taskledger.storage.meta import StorageMeta, write_storage_meta
from taskledger.storage.paths import (
    CANONICAL_PROJECT_CONFIG_FILENAME,
    ProjectPaths,
    load_project_locator,
    project_paths_for_root,
)
from taskledger.storage.project_config import render_default_taskledger_toml
from taskledger.storage.project_identity import ensure_project_uuid, new_project_uuid


# Legacy initializer is inserted below.
def init_legacy_project_state(
    workspace_root: Path,
    *,
    taskledger_dir: Path | None = None,
    config_filename: str = CANONICAL_PROJECT_CONFIG_FILENAME,
    project_name: str | None = None,
) -> tuple[ProjectPaths, list[str]]:
    """Initialize the explicitly selected legacy Taskledger layout."""
    existing = load_project_locator(workspace_root, config_filename=config_filename)
    requested = load_project_locator(
        workspace_root,
        taskledger_dir_override=taskledger_dir,
        config_filename=config_filename,
    )
    if (
        taskledger_dir is not None
        and existing.config_path.exists()
        and existing.taskledger_dir != requested.taskledger_dir
    ):
        raise LaunchError(
            f"Existing taskledger config points to {existing.taskledger_dir}. "
            f"Refusing to reinitialize with {requested.taskledger_dir}."
        )
    paths = project_paths_for_root(
        requested.workspace_root,
        requested.taskledger_dir,
        config_path=requested.config_path,
    )
    created: list[str] = []
    ledger_dir = paths.taskledger_dir / "ledgers" / "main"
    for directory in (
        paths.taskledger_dir,
        ledger_dir,
        ledger_dir / "intros",
        ledger_dir / "tasks",
        ledger_dir / "events",
        ledger_dir / "indexes",
        ledger_dir / "releases",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory))
    if not paths.config_path.exists() and requested.source != "legacy":
        write_text(
            paths.config_path,
            render_default_taskledger_toml(
                taskledger_dir=str(taskledger_dir or Path(".taskledger")),
                config_version=2,
                project_uuid=new_project_uuid(),
                project_name=project_name or requested.workspace_root.name,
            ),
        )
        created.append(str(paths.config_path))
    for path in (
        paths.repo_index_path,
        ledger_dir / "indexes" / "active_locks.json",
        ledger_dir / "indexes" / "dependencies.json",
        ledger_dir / "indexes" / "introductions.json",
    ):
        if not path.exists():
            write_text(path, "[]\n")
            created.append(str(path))
    if paths.config_path.exists():
        ensure_project_uuid(paths.config_path)
    storage_path = paths.taskledger_dir / "storage.yaml"
    if not storage_path.exists():
        write_storage_meta(
            paths.workspace_root,
            StorageMeta(created_with_taskledger="legacy"),
        )
        created.append(str(storage_path))
    return paths, created

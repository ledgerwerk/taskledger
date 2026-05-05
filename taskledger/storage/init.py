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


def _storage_yaml_path(workspace_root: Path) -> Path:
    return load_project_locator(workspace_root).taskledger_dir / "storage.yaml"


def init_project_state(
    workspace_root: Path,
    *,
    taskledger_dir: Path | None = None,
    config_filename: str = CANONICAL_PROJECT_CONFIG_FILENAME,
    project_name: str | None = None,
) -> tuple[ProjectPaths, list[str]]:
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
            "Existing taskledger config points to "
            f"{existing.taskledger_dir}. Refusing to reinitialize with "
            f"{requested.taskledger_dir}."
        )
    if (
        taskledger_dir is not None
        and existing.source == "legacy"
        and not existing.config_path.exists()
    ):
        raise LaunchError(
            "Legacy workspaces cannot change taskledger_dir through init without "
            "an explicit migration."
        )
    paths = project_paths_for_root(
        requested.workspace_root,
        requested.taskledger_dir,
        config_path=requested.config_path,
    )
    created: list[str] = []
    # Create the taskledger root directory
    for directory in (paths.taskledger_dir,):
        if directory.exists():
            continue
        directory.mkdir(parents=True, exist_ok=True)
        created.append(str(directory))
    # Create the scoped ledger directory structure
    ledger_dir = paths.taskledger_dir / "ledgers" / "main"
    for directory in (
        ledger_dir,
        ledger_dir / "intros",
        ledger_dir / "tasks",
        ledger_dir / "events",
        ledger_dir / "indexes",
        ledger_dir / "releases",
    ):
        if directory.exists():
            continue
        directory.mkdir(parents=True, exist_ok=True)
        created.append(str(directory))
    config_spec: list[tuple[Path, str]] = []
    if _should_write_root_config(existing, paths):
        taskledger_dir_value = _taskledger_dir_setting(
            taskledger_dir or Path(".taskledger")
        )
        effective_project_name = project_name or requested.workspace_root.name
        config_spec = [
            (
                paths.config_path,
                render_default_taskledger_toml(
                    taskledger_dir=taskledger_dir_value,
                    config_version=2,
                    project_uuid=new_project_uuid(),
                    project_name=effective_project_name,
                ),
            )
        ]
    for path, contents in (
        *config_spec,
        (paths.repo_index_path, "[]\n"),
        (ledger_dir / "indexes" / "active_locks.json", "[]\n"),
        (ledger_dir / "indexes" / "dependencies.json", "[]\n"),
        (ledger_dir / "indexes" / "introductions.json", "[]\n"),
    ):
        if path.exists():
            continue
        write_text(path, contents)
        created.append(str(path))
    # Write storage.yaml at taskledger root
    storage_path = paths.taskledger_dir / "storage.yaml"
    if not storage_path.exists():
        try:
            from taskledger._version import __version__ as tl_version
        except ImportError:
            tl_version = "0.1.0"
        meta = StorageMeta(created_with_taskledger=tl_version)
        write_storage_meta(paths.workspace_root, meta)
        created.append(str(storage_path))
    # Backfill project_uuid for existing configs that lack it.
    if paths.config_path.exists():
        ensure_project_uuid(paths.config_path)
    return paths, created


def ensure_project_exists(workspace_root: Path) -> ProjectPaths:
    locator = load_project_locator(workspace_root)
    paths = project_paths_for_root(
        locator.workspace_root,
        locator.taskledger_dir,
        config_path=locator.config_path,
    )
    ledger_dir = paths.taskledger_dir / "ledgers" / "main"
    missing = [
        path
        for path in (
            ledger_dir / "tasks",
            ledger_dir / "intros",
            ledger_dir / "events",
            ledger_dir / "indexes",
            paths.releases_dir,
        )
        if not path.exists()
    ]
    if missing:
        raise LaunchError(
            "Project state is not initialized. Run 'taskledger init' first."
        )
    _ensure_additive_project_files(paths)
    _reject_legacy_item_memory_indexes(paths)
    return paths


def _ensure_additive_project_files(paths: ProjectPaths) -> None:
    for directory in (
        paths.taskledger_dir,
        paths.taskledger_dir / "intros",
        paths.taskledger_dir / "tasks",
        paths.taskledger_dir / "events",
        paths.taskledger_dir / "indexes",
        paths.releases_dir,
    ):
        if directory.exists():
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LaunchError(f"Failed to create {directory}: {exc}") from exc
    for path in (
        paths.repo_index_path,
        paths.taskledger_dir / "indexes" / "active_locks.json",
        paths.taskledger_dir / "indexes" / "dependencies.json",
        paths.taskledger_dir / "indexes" / "introductions.json",
    ):
        if path.exists():
            continue
        write_text(path, "[]\n")


def _reject_legacy_item_memory_indexes(paths: ProjectPaths) -> None:
    legacy_item_index = paths.taskledger_dir / "items" / "index.json"
    legacy_memory_index = paths.taskledger_dir / "memories" / "index.json"
    if legacy_item_index.exists():
        raise LaunchError(
            "Legacy item JSON storage is unsupported after this refactor: "
            f"remove {legacy_item_index}."
        )
    if legacy_memory_index.exists():
        raise LaunchError(
            "Legacy memory JSON storage is unsupported after this refactor: "
            f"remove {legacy_memory_index}."
        )


def _should_write_root_config(
    locator: object,
    paths: ProjectPaths,
) -> bool:
    if paths.config_path.exists():
        return False
    source = getattr(locator, "source", "")
    return source not in {"legacy"}


def _taskledger_dir_setting(taskledger_dir: Path) -> str:
    if not taskledger_dir.is_absolute():
        return taskledger_dir.as_posix()
    if taskledger_dir.exists():
        resolved = taskledger_dir
    else:
        resolved = taskledger_dir.resolve()
    return resolved.as_posix()

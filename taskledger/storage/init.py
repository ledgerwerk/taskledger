from __future__ import annotations

import importlib
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.storage.common import write_text
from taskledger.storage.ledger_local_config import ensure_sibling_workspace_provider
from taskledger.storage.meta import StorageMeta, write_storage_meta
from taskledger.storage.paths import (
    CANONICAL_PROJECT_CONFIG_FILENAME,
    ProjectPaths,
    find_project_config,
    load_project_locator,
    project_paths_for_root,
)
from taskledger.storage.project_config import render_default_taskledger_toml
from taskledger.storage.project_context import TaskledgerProjectContext
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


def _ensure_sibling_store(
    project_root: Path,
    *,
    create_sibling_store: bool,
) -> Path:
    sibling_root = (project_root / ".." / "ledger").resolve(strict=False)
    if sibling_root.is_symlink():
        raise LaunchError(
            f"TASKLEDGER_SIBLING_ROOT_UNMARKED: symlink root {sibling_root}"
        )
    if sibling_root.exists() and not sibling_root.is_dir():
        raise LaunchError(f"TASKLEDGER_SIBLING_ROOT_NOT_DIRECTORY: {sibling_root}")
    if not sibling_root.exists():
        if not create_sibling_store:
            raise LaunchError(
                f"TASKLEDGER_SIBLING_ROOT_MISSING: {sibling_root}. "
                "Use --create-sibling-store to initialize it."
            )
        sibling_root.mkdir(parents=True, exist_ok=False)
    marker = sibling_root / ".ledger-store"
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise LaunchError(f"TASKLEDGER_SIBLING_MARKER_INVALID: {marker}")
    if not marker.exists():
        if not create_sibling_store:
            raise LaunchError(
                f"TASKLEDGER_SIBLING_ROOT_UNMARKED: {sibling_root}. "
                "Use --create-sibling-store to initialize it."
            )
        if any(sibling_root.iterdir()):
            raise LaunchError(
                "Refusing to initialize non-empty unmarked sibling root "
                f"{sibling_root}."
            )
        marker.write_text("Ledgercore sibling store\n", encoding="utf-8")
    return sibling_root


def init_canonical_project_state(
    workspace_root: Path,
    *,
    project_name: str | None = None,
    project_uuid: str | None = None,
    create_sibling_store: bool = False,
) -> tuple[TaskledgerProjectContext, list[str]]:
    """Initialize the canonical Ledgercore-backed Taskledger layout."""
    import uuid

    from ledgercore import locate_ledger_project

    from taskledger.storage.atomic import atomic_write_text
    from taskledger.storage.ledger_manifest import ensure_taskledger_registration
    from taskledger.storage.project_config import render_canonical_taskledger_config
    from taskledger.storage.project_context import load_project_context
    from taskledger.storage.yaml_store import write_yaml_object

    try:
        tomllib = importlib.import_module("tomllib")
    except ModuleNotFoundError:
        tomllib = importlib.import_module("tomli")
    root = workspace_root.expanduser().resolve()
    existing = locate_ledger_project(
        root, legacy_tool_filenames=(".taskledger.toml", "taskledger.toml")
    )
    legacy_config = find_project_config(root)
    if (existing is not None and existing.source == "legacy-tool") or (
        legacy_config is None and (root / ".taskledger" / "storage.yaml").exists()
    ):
        legacy = load_project_locator(root)
        raise LaunchError(
            f"Legacy Taskledger project detected at {legacy.taskledger_dir}. "
            "Run `taskledger migrate plan`, then `taskledger migrate apply --backup`."
        )
    selected_uuid = project_uuid
    if existing is not None and existing.source == "canonical":
        manifest_path = existing.manifest_path
        try:
            document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            selected_uuid = str(document["project"]["uuid"])
            manifest_name = document.get("project", {}).get("name")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise LaunchError(
                f"Invalid Ledger manifest {manifest_path}: {exc}"
            ) from exc
        if project_name is not None and manifest_name not in {None, project_name}:
            raise LaunchError(
                f"Project name conflicts with existing Ledger manifest {manifest_path}."
            )
        effective_name = project_name or (
            manifest_name if isinstance(manifest_name, str) else root.name
        )
    else:
        selected_uuid = selected_uuid or str(uuid.uuid4())
        effective_name = project_name or root.name
    _ensure_sibling_store(root, create_sibling_store=create_sibling_store)
    registration = ensure_taskledger_registration(
        root, project_uuid=selected_uuid, project_name=effective_name
    )
    local_result = ensure_sibling_workspace_provider(root)
    local_config_path = local_result.path
    context = load_project_context(root, require_initialized=False, allow_legacy=False)
    paths = context.paths
    created: list[str] = (
        [str(registration.manifest_path)] if registration.changed else []
    )
    if local_result.changed:
        created.append(str(local_config_path))
    if not paths.config_path.exists():
        atomic_write_text(paths.config_path, render_canonical_taskledger_config())
        created.append(str(paths.config_path))
    paths.data_root.mkdir(parents=True, exist_ok=True)
    from taskledger.storage.project_binding import create_project_binding

    create_project_binding(paths.data_root, project_uuid=selected_uuid)
    for directory in (
        paths.ledger_data_dir,
        paths.introductions_dir,
        paths.releases_dir,
        paths.tasks_dir,
        paths.events_dir,
        paths.agent_logs_dir,
        paths.ledger_data_dir / "tombstones",
        paths.data_root / "migrations",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory))
    if not paths.storage_meta_path.exists():
        try:
            from taskledger._version import __version__ as version
        except ImportError:
            version = "0.1.0"
        write_yaml_object(
            paths.storage_meta_path,
            {
                "storage_layout_version": 5,
                "record_schema_version": 1,
                "created_with_taskledger": version,
                "created_at": __import__(
                    "taskledger.timeutils", fromlist=["utc_now_iso"]
                ).utc_now_iso(),
                "last_migrated_with_taskledger": None,
                "last_migrated_at": None,
            },
        )
        created.append(str(paths.storage_meta_path))
    if not paths.state_path.exists():
        atomic_write_text(
            paths.state_path,
            (
                "schema_version = 2\n"
                'ledger_ref = "main"\n'
                'ledger_parent_ref = ""\n'
                'ledger_branch_guard = "off"\n'
            ),
        )
        created.append(str(paths.state_path))
    return load_project_context(root), created

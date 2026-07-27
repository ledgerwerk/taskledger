"""Explicit Taskledger initialization for canonical and legacy projects."""

from __future__ import annotations

import uuid
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.common import write_text
from taskledger.storage.ledgercore_backend import (
    StorageBindingError,
    ensure_taskledger_ledger_registration,
    initialize_taskledger_bindings,
    initialize_taskledger_external_store,
    load_taskledger_ledger_layout,
    locate_taskledger_project,
    read_ledger_manifest,
    read_storage_binding,
)
from taskledger.storage.meta import StorageMeta, write_storage_meta
from taskledger.storage.paths import (
    CANONICAL_PROJECT_CONFIG_FILENAME,
    ProjectPaths,
    load_project_locator,
    project_paths_for_root,
)
from taskledger.storage.project_config import (
    load_canonical_project_config,
    render_canonical_taskledger_config,
    render_default_taskledger_toml,
)
from taskledger.storage.project_context import (
    TaskledgerProjectContext,
    load_project_context,
)
from taskledger.storage.project_identity import ensure_project_uuid, new_project_uuid
from taskledger.storage.yaml_store import write_yaml_object


def _storage_yaml_path(workspace_root: Path) -> Path:
    return load_project_locator(workspace_root).taskledger_dir / "storage.yaml"


def init_project_state(
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


def _reject_legacy_json_indexes(
    data_root: Path,
    *,
    mode: str,
) -> None:
    """Reject obsolete JSON item/memory indexes for canonical and legacy projects."""
    for name, label in (("items", "item"), ("memories", "memory")):
        legacy_index = data_root / name / "index.json"
        if legacy_index.exists():
            raise LaunchError(
                f"Legacy {label} JSON storage is unsupported: {legacy_index}. "
                f"Project mode: {mode}. Data root: {data_root}. "
                "Remove or migrate the obsolete index before continuing."
            )


def ensure_project_exists(workspace_root: Path) -> ProjectPaths:
    locator = load_project_locator(workspace_root)
    if locator.source == "canonical":
        context = load_project_context(workspace_root)
        _reject_legacy_json_indexes(context.paths.data_root, mode="canonical")
        return project_paths_for_root(
            context.project_root,
            context.paths.data_root,
            config_path=context.config_path,
            ledger_ref=context.ledger_state.ref,
        )
    paths = project_paths_for_root(
        locator.workspace_root,
        locator.taskledger_dir,
        config_path=locator.config_path,
    )
    _reject_legacy_json_indexes(paths.taskledger_dir, mode="legacy")
    required = (
        paths.project_dir / "tasks",
        paths.project_dir / "intros",
        paths.project_dir / "events",
        paths.project_dir / "indexes",
        paths.releases_dir,
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        raise LaunchError(
            "Project state is not initialized. Run 'taskledger init' first."
        )
    return paths


def _count_legacy_tasks(taskledger_dir: Path) -> int:
    """Count tasks in a legacy Taskledger data directory."""
    count = 0
    for ledger_dir in (taskledger_dir / "ledgers").glob("*"):
        tasks_dir = ledger_dir / "tasks"
        if tasks_dir.is_dir():
            count += len(list(tasks_dir.glob("task-*")))
    return count


def init_canonical_project_state(
    workspace_root: Path,
    *,
    project_name: str | None = None,
    project_uuid: str | None = None,
    create_sibling_store: bool = False,
    data_storage: str = "external",
    external_root: str | None = "../ledger",
) -> tuple[TaskledgerProjectContext, list[str]]:
    """Create a schema-3 project through the Ledgercore adapter."""
    del create_sibling_store
    root = workspace_root.expanduser().resolve()
    discovered = locate_taskledger_project(root)
    if discovered is not None and discovered.is_legacy:
        legacy = load_project_locator(root)
        task_count = _count_legacy_tasks(legacy.taskledger_dir)
        raise LaunchError(
            f"Legacy Taskledger project detected at {legacy.taskledger_dir}. "
            "Run `taskledger migrate plan`, then `taskledger migrate apply`.",
            code="TASKLEDGER_LEGACY_PROJECT_REQUIRES_MIGRATION",
            details={
                "legacy_config": str(legacy.config_path),
                "legacy_data_root": str(legacy.taskledger_dir),
                "task_count": task_count,
                "next_commands": [
                    "taskledger migrate plan",
                    "taskledger migrate apply",
                ],
            },
        )
    selected_uuid = project_uuid or str(uuid.uuid4())
    effective_name = project_name or root.name
    manifest_path = root / ".ledger" / "ledger.toml"
    previous_manifest = (
        manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
    )
    existing_registration = None
    if discovered is not None and not discovered.is_legacy:
        manifest = read_ledger_manifest(discovered.manifest_path)
        selected_uuid = manifest.project_uuid
        if project_uuid is not None and str(uuid.UUID(project_uuid)) != selected_uuid:
            raise LaunchError(
                "EXPLICIT_PROJECT_UUID_CONFLICT: project UUID conflicts with the "
                "existing Ledger manifest.",
                code="EXPLICIT_PROJECT_UUID_CONFLICT",
                details={"expected": selected_uuid, "actual": project_uuid},
            )
        effective_name = project_name or manifest.project_name or effective_name
        existing_registration = manifest.ledgers.get("taskledger")
        _validate_existing_canonical_taskledger_config(root, selected_uuid)
        if existing_registration is not None:
            existing_data = existing_registration.mounts.get("data")
            if existing_data is not None:
                data_storage = str(existing_data.storage)
                external_root = existing_data.external_root
    try:
        ensure_taskledger_ledger_registration(
            root,
            project_uuid=selected_uuid,
            project_name=effective_name,
            data_storage=data_storage,
            external_root=external_root,
        )
        bundle = load_taskledger_ledger_layout(root, validate_storage=False)
        layout = bundle.resolved_layout
        created: list[str] = []
        if initialize_taskledger_external_store(layout):
            data_root = layout.mounts["data"].root
            if data_root is not None:
                created.append(str(data_root))
        initialize_taskledger_bindings(
            layout,
            initialize_config=True,
            initialize_data=True,
            initialize_indexes=True,
        )
        if layout.tool_config_path is not None and not layout.tool_config_path.exists():
            atomic_write_text(
                layout.tool_config_path, render_canonical_taskledger_config()
            )
            created.append(str(layout.tool_config_path))
    except Exception:
        if previous_manifest is not None:
            atomic_write_text(manifest_path, previous_manifest)
        elif manifest_path.exists():
            manifest_path.unlink()
        raise
    paths = load_project_context(
        root, require_initialized=False, allow_legacy=False
    ).paths
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
            StorageMeta(created_with_taskledger=version).to_dict(),
        )
        created.append(str(paths.storage_meta_path))
    if not paths.state_path.exists():
        atomic_write_text(
            paths.state_path,
            "schema_version = 2\n"
            'ledger_ref = "main"\n'
            'ledger_parent_ref = ""\n'
            'ledger_branch_guard = "off"\n',
        )
        created.append(str(paths.state_path))
    return load_project_context(root), created


def _validate_existing_canonical_taskledger_config(
    root: Path,
    project_uuid: str,
) -> None:
    """Validate orphan config and its optional existing Ledgercore marker."""
    config_dir = root / ".ledger" / "taskledger"
    config_path = config_dir / "config.toml"
    marker_path = config_dir / ".ledger-project.toml"
    if config_path.exists():
        try:
            load_canonical_project_config(config_path)
        except LaunchError as exc:
            raise LaunchError(
                f"TASKLEDGER_ORPHAN_CONFIG_INVALID: {exc}",
                code="TASKLEDGER_ORPHAN_CONFIG_INVALID",
                details={"config_path": str(config_path)},
            ) from exc
    if not marker_path.exists():
        return
    try:
        binding = read_storage_binding(marker_path)
    except StorageBindingError as exc:
        raise LaunchError(
            f"TASKLEDGER_CONFIG_BINDING_INVALID: {exc}",
            code="TASKLEDGER_CONFIG_BINDING_INVALID",
            details={"binding_path": str(marker_path)},
        ) from exc
    expected = {
        "project_uuid": project_uuid,
        "tool": "taskledger",
        "mount": "config",
        "storage": "project",
    }
    actual = {
        "project_uuid": binding.project_uuid,
        "tool": binding.tool,
        "mount": binding.mount,
        "storage": binding.storage,
    }
    if actual != expected:
        raise LaunchError(
            "TASKLEDGER_CONFIG_BINDING_INVALID: existing Taskledger config "
            "binding does not match the canonical project.",
            code="TASKLEDGER_CONFIG_BINDING_INVALID",
            details={
                "binding_path": str(marker_path),
                "expected": expected,
                "actual": actual,
            },
        )


__all__ = [
    "ensure_project_exists",
    "init_canonical_project_state",
    "init_project_state",
]

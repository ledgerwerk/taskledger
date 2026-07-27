"""Taskledger project context built on Ledgercore's resolved layout."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from taskledger.errors import LaunchError
from taskledger.storage.ledger_config import LedgerConfig, load_ledger_config
from taskledger.storage.ledgercore_backend import (
    DATA_MOUNT,
    INDEX_MOUNT,
    TaskledgerLedgerLayout,
    load_taskledger_ledger_layout,
    locate_taskledger_project,
)
from taskledger.storage.paths import (
    DEFAULT_TASKLEDGER_DIR_NAME,
    ProjectPaths,
    load_project_locator,
    project_paths_for_root,
)
from taskledger.storage.project_config import (
    ProjectConfig,
    load_canonical_project_config,
    load_project_config_document,
    merge_project_config,
)

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover
    tomllib = importlib.import_module("tomli")

ProjectMode = Literal["canonical", "legacy", "uninitialized"]
InitializationStatus = Literal[
    "uninitialized",
    "legacy",
    "schema_migration_required",
    "registration_missing",
    "registration_invalid",
    "config_missing",
    "config_binding_missing",
    "config_binding_invalid",
    "data_missing",
    "data_binding_missing",
    "data_binding_invalid",
    "external_store_invalid",
    "storage_migration_incomplete",
    "missing_storage_meta",
    "invalid_state",
    "ready",
]

CANONICAL_LEDGER_NAME = "taskledger"
CANONICAL_LEDGER_CODE = "tl"
CANONICAL_CONFIG_VERSION = 3
CANONICAL_STORAGE_LAYOUT_VERSION = 5
CANONICAL_MOUNT_NAMES = (DATA_MOUNT, INDEX_MOUNT)
CANONICAL_DATA_RELATIVE_PATH = Path("data")
CANONICAL_INDEX_RELATIVE_PATH = Path("indexes")
LEGACY_CONFIG_FILENAMES = (".taskledger.toml", "taskledger.toml")


@dataclass(frozen=True, slots=True)
class TaskledgerInitializationState:
    status: InitializationStatus
    message: str | None = None


@dataclass(frozen=True, slots=True)
class TaskledgerPaths:
    workspace_root: Path
    config_path: Path
    data_root: Path
    logs_root: Path
    indexes_root: Path
    storage_meta_path: Path
    state_path: Path
    actor_path: Path
    harness_path: Path
    ledger_ref: str
    ledger_data_dir: Path
    ledger_logs_dir: Path
    ledger_indexes_dir: Path
    introductions_dir: Path
    releases_dir: Path
    tasks_dir: Path
    events_dir: Path
    agent_logs_dir: Path
    active_task_path: Path
    repo_registry_path: Path
    task_index_path: Path
    sidecar_index_path: Path
    active_locks_index_path: Path
    dependencies_index_path: Path
    introductions_index_path: Path

    @property
    def project_dir(self) -> Path:
        return self.ledger_data_dir

    @property
    def ledger_dir(self) -> Path:
        return self.ledger_data_dir

    @property
    def repo_index_path(self) -> Path:
        return self.repo_registry_path

    @property
    def taskledger_dir(self) -> Path:
        """Deprecated compatibility alias for the resolved data mount."""
        return self.data_root

    @property
    def events_dir_legacy(self) -> Path:
        return self.events_dir


@dataclass(frozen=True, slots=True)
class TaskledgerProjectContext:
    mode: ProjectMode
    project_root: Path
    project_uuid: str | None
    project_name: str
    config_path: Path
    config: ProjectConfig
    ledger_state: LedgerConfig
    paths: TaskledgerPaths
    initialization: TaskledgerInitializationState
    layout: Any | None
    legacy_locator: ProjectPaths | None
    loaded_project: Any | None = None
    storage_validation: Any | None = None
    local_overrides_present: bool = False
    # Compatibility fields are derived values, not configuration ownership.
    store_root: Path | None = None
    store_marker_path: Path | None = None
    binding_path: Path | None = None
    workspace_provider: None = None
    data_mount_source: str | None = None


def _safe_child(root: Path, *parts: str) -> Path:
    candidate = root.joinpath(*parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise LaunchError(f"Taskledger path escapes mount {root}: {candidate}") from exc
    return candidate


def _paths_for_mounts(
    workspace_root: Path,
    config_path: Path,
    data_root: Path,
    logs_root: Path,
    indexes_root: Path,
    ledger_ref: str,
) -> TaskledgerPaths:
    if (
        not ledger_ref
        or ledger_ref in {".", ".."}
        or "/" in ledger_ref
        or "\\" in ledger_ref
    ):
        raise LaunchError(
            f"Invalid ledger reference for path construction: {ledger_ref!r}"
        )
    data_ledger = _safe_child(data_root, "ledgers", ledger_ref)
    logs_ledger = _safe_child(logs_root, "ledgers", ledger_ref)
    indexes_ledger = _safe_child(indexes_root, "ledgers", ledger_ref)
    return TaskledgerPaths(
        workspace_root=workspace_root,
        config_path=config_path,
        data_root=data_root,
        logs_root=logs_root,
        indexes_root=indexes_root,
        storage_meta_path=_safe_child(data_root, "storage.yaml"),
        state_path=_safe_child(data_root, "state.toml"),
        actor_path=_safe_child(data_root, "actor.yaml"),
        harness_path=_safe_child(data_root, "harness.yaml"),
        ledger_ref=ledger_ref,
        ledger_data_dir=data_ledger,
        ledger_logs_dir=logs_ledger,
        ledger_indexes_dir=indexes_ledger,
        introductions_dir=_safe_child(data_ledger, "intros"),
        releases_dir=_safe_child(data_ledger, "releases"),
        tasks_dir=_safe_child(data_ledger, "tasks"),
        events_dir=_safe_child(logs_ledger, "events"),
        agent_logs_dir=_safe_child(logs_ledger, "agent-logs"),
        active_task_path=_safe_child(data_ledger, "active-task.yaml"),
        repo_registry_path=_safe_child(data_ledger, "repos.json"),
        task_index_path=_safe_child(indexes_ledger, "tasks.json"),
        sidecar_index_path=_safe_child(indexes_ledger, "task_sidecars.json"),
        active_locks_index_path=_safe_child(indexes_ledger, "active_locks.json"),
        dependencies_index_path=_safe_child(indexes_ledger, "dependencies.json"),
        introductions_index_path=_safe_child(indexes_ledger, "introductions.json"),
    )


def _load_toml(path: Path) -> dict[str, object]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Unable to read Ledger configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"Ledger configuration {path} must contain a TOML table.")
    return cast(dict[str, object], value)


def _legacy_context(project_paths: ProjectPaths) -> TaskledgerProjectContext:
    data_root = project_paths.taskledger_dir
    ledger = load_ledger_config(project_paths.config_path)
    paths = _paths_for_mounts(
        project_paths.workspace_root,
        project_paths.config_path,
        data_root,
        data_root,
        data_root,
        ledger.ref,
    )
    config = merge_project_config(
        load_project_config_document(project_paths.config_path)
    )
    from taskledger.storage.project_identity import (
        load_project_uuid,
        project_name_or_default,
    )

    return TaskledgerProjectContext(
        mode="legacy",
        project_root=project_paths.workspace_root,
        project_uuid=load_project_uuid(project_paths.config_path),
        project_name=project_name_or_default(
            project_paths.config_path, workspace_root=project_paths.workspace_root
        ),
        config_path=project_paths.config_path,
        config=config,
        ledger_state=ledger,
        paths=paths,
        initialization=TaskledgerInitializationState(
            "legacy", "Legacy Taskledger layout detected; run taskledger migrate."
        ),
        layout=None,
        legacy_locator=project_paths,
    )


def _legacy_marker_root(start: Path) -> Path | None:
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        taskledger_dir = candidate / DEFAULT_TASKLEDGER_DIR_NAME
        if (taskledger_dir / "storage.yaml").exists() or (
            taskledger_dir / "ledgers"
        ).is_dir():
            return candidate
    return None


def _validate_registration(layout: Any) -> None:
    if set(layout.mounts) != set(CANONICAL_MOUNT_NAMES):
        raise LaunchError(
            "TASKLEDGER_REGISTRATION_INVALID: Taskledger registration must define "
            "exactly data and indexes mounts."
        )
    if layout.mounts[DATA_MOUNT].storage not in {"project", "external", "user-data"}:
        raise LaunchError(
            "TASKLEDGER_STORAGE_BINDING_INVALID: data must be persistent."
        )
    if layout.mounts[INDEX_MOUNT].storage != "cache":
        raise LaunchError("TASKLEDGER_STORAGE_BINDING_INVALID: indexes must be cache.")


def _context_from_layout(
    start: Path,
    bundle: TaskledgerLedgerLayout,
    *,
    require_initialized: bool,
) -> TaskledgerProjectContext:
    loaded = bundle.loaded_project
    layout = bundle.resolved_layout
    if getattr(loaded.manifest, "schema_version", 3) == 3:
        _validate_registration(layout)
    config_path = layout.tool_config_path
    if config_path is None:
        raise LaunchError(
            "TASKLEDGER_REGISTRATION_INVALID: Taskledger config is missing."
        )
    if config_path.exists():
        config = load_canonical_project_config(config_path)
        init_state = TaskledgerInitializationState("ready")
    else:
        config = ProjectConfig()
        init_state = TaskledgerInitializationState("config_missing", str(config_path))
        if require_initialized:
            raise LaunchError(
                f"Missing Taskledger config {config_path}. Run `taskledger init`."
            )
    data_root = layout.mounts[DATA_MOUNT].path
    indexes_root = layout.mounts[INDEX_MOUNT].path
    ledger = _load_state(data_root / "state.toml")
    paths = _paths_for_mounts(
        layout.project_root, config_path, data_root, data_root, indexes_root, ledger.ref
    )
    if require_initialized:
        if not data_root.exists() or not paths.storage_meta_path.exists():
            raise LaunchError(
                f"Taskledger data mount is not initialized at {data_root}. "
                "Run `taskledger init`.",
            )
        if (
            getattr(loaded.manifest, "schema_version", 3) == 3
            and bundle.validation_report is not None
            and not bundle.validation_report.valid
        ):
            reasons = "; ".join(
                result.reason or "invalid binding"
                for result in bundle.validation_report.results
                if not result.valid
            )
            raise LaunchError(
                f"TASKLEDGER_STORAGE_BINDING_INVALID: {reasons}",
                details={"validation": reasons},
            )
    data_mount = layout.mounts[DATA_MOUNT]
    return TaskledgerProjectContext(
        mode="canonical",
        project_root=layout.project_root,
        project_uuid=layout.project_uuid,
        project_name=loaded.manifest.project_name or layout.project_root.name,
        config_path=config_path,
        config=config,
        ledger_state=ledger,
        paths=paths,
        initialization=init_state,
        layout=layout,
        legacy_locator=None,
        loaded_project=loaded,
        storage_validation=bundle.validation_report,
        local_overrides_present=loaded.locator.local_config_path.exists(),
        store_root=data_mount.root,
        store_marker_path=data_mount.binding_path,
        binding_path=data_mount.binding_path,
        data_mount_source=str(data_mount.source),
    )


def load_project_context(
    start: Path,
    *,
    require_initialized: bool = True,
    allow_legacy: bool = True,
) -> TaskledgerProjectContext:
    """Load Taskledger context without creating or mutating any files."""
    locator = locate_taskledger_project(start)
    if locator is not None and not locator.is_legacy:
        try:
            bundle = load_taskledger_ledger_layout(start)
        except LaunchError:
            raise
        return _context_from_layout(
            start, bundle, require_initialized=require_initialized
        )
    legacy_root = _legacy_marker_root(start)
    if locator is not None and locator.is_legacy:
        legacy_root = locator.project_root
    if not allow_legacy or legacy_root is None:
        raise LaunchError(
            "No canonical Ledger project or readable legacy Taskledger project found."
        )
    legacy = load_project_locator(legacy_root)
    return _legacy_context(
        project_paths_for_root(
            legacy.workspace_root, legacy.taskledger_dir, config_path=legacy.config_path
        )
    )


def require_mutable_project_context(
    start: Path,
    *,
    allow_legacy: bool = True,
) -> TaskledgerProjectContext:
    """Require a real initialized project before any command may write state."""
    context = load_project_context(
        start,
        require_initialized=True,
        allow_legacy=allow_legacy,
    )
    if context.mode == "legacy":
        required = (
            context.paths.project_dir,
            context.paths.tasks_dir,
            context.paths.events_dir,
            context.paths.ledger_indexes_dir,
        )
        missing = [path for path in required if not path.exists()]
        if missing:
            raise LaunchError(
                "Legacy Taskledger project is not initialized. Missing: "
                + ", ".join(str(path) for path in missing)
                + ". Run `taskledger init`."
            )
    return context


def _load_state(path: Path) -> LedgerConfig:
    if not path.exists():
        return LedgerConfig()
    document = _load_toml(path)
    try:
        schema_version = document.get("schema_version", 1)
        if schema_version != 2:
            raise LaunchError(
                f"Canonical ledger state {path} must use schema_version = 2."
            )
        if "ledger_next_task_number" in document:
            raise LaunchError(
                "Canonical ledger state contains forbidden ledger_next_task_number; "
                "run taskledger migrate."
            )
        return LedgerConfig(
            ref=str(document.get("ledger_ref", "main")),
            parent_ref=(str(document.get("ledger_parent_ref")) or None),
            branch_guard=cast(
                Literal["off", "warn", "error"],
                str(document.get("ledger_branch_guard", "off")),
            ),
        )
    except (TypeError, ValueError) as exc:
        raise LaunchError(f"Invalid canonical ledger state {path}: {exc}") from exc


def canonical_mount_specs(
    project_uuid: str | None = None,
) -> dict[str, tuple[str, str | None, str]]:
    """Return the canonical mount specs for sibling-ledger workspace migration."""
    suffix = f"/{project_uuid}" if project_uuid else ""
    return {
        DATA_MOUNT: ("workspace", "project", f"taskledger{suffix}"),
        INDEX_MOUNT: ("cache", "checkout", "taskledger-indexes"),
    }


__all__ = [
    "CANONICAL_CONFIG_VERSION",
    "CANONICAL_LEDGER_CODE",
    "CANONICAL_LEDGER_NAME",
    "CANONICAL_MOUNT_NAMES",
    "CANONICAL_STORAGE_LAYOUT_VERSION",
    "TaskledgerInitializationState",
    "TaskledgerPaths",
    "TaskledgerProjectContext",
    "_paths_for_mounts",
    "load_project_context",
    "require_mutable_project_context",
]

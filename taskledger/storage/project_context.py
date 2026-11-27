"""Taskledger project context built on Ledgercore's resolved layout."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from taskledger.errors import LaunchError
from taskledger.storage.ledger_config import LedgerConfig
from taskledger.storage.ledgercore_backend import (
    DATA_MOUNT,
    INDEX_MOUNT,
    LOGS_MOUNT,
    RUNTIME_MOUNT,
    TaskledgerLedgerLayout,
    load_taskledger_ledger_layout,
    locate_taskledger_project,
)
from taskledger.storage.paths import ProjectPaths, probe_taskledger_project
from taskledger.storage.project_config import (
    ProjectConfig,
    load_canonical_project_config,
)

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover
    tomllib = importlib.import_module("tomli")

ProjectMode = Literal["canonical"]
InitializationStatus = Literal[
    "uninitialized",
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
CANONICAL_STORAGE_LAYOUT_VERSION = 6
CANONICAL_MOUNT_NAMES = (DATA_MOUNT, RUNTIME_MOUNT, LOGS_MOUNT, INDEX_MOUNT)
CANONICAL_DATA_RELATIVE_PATH = Path("data")
CANONICAL_INDEX_RELATIVE_PATH = Path("indexes")


@dataclass(frozen=True, slots=True)
class TaskledgerInitializationState:
    status: InitializationStatus
    message: str | None = None


@dataclass(frozen=True, slots=True)
class TaskledgerPaths:
    workspace_root: Path
    config_path: Path
    data_root: Path
    runtime_root: Path
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
    loaded_project: Any | None = None
    storage_validation: Any | None = None
    cache_recovery: Any | None = None
    local_state_recovery: Any | None = None
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
    runtime_root: Path,
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
        runtime_root=runtime_root,
        logs_root=logs_root,
        indexes_root=indexes_root,
        storage_meta_path=_safe_child(data_root, "storage.yaml"),
        state_path=_safe_child(data_root, "state.toml"),
        actor_path=_safe_child(runtime_root, "actor.yaml"),
        harness_path=_safe_child(runtime_root, "harness.yaml"),
        ledger_ref=ledger_ref,
        ledger_data_dir=data_ledger,
        ledger_logs_dir=logs_ledger,
        ledger_indexes_dir=indexes_ledger,
        introductions_dir=_safe_child(data_ledger, "intros"),
        releases_dir=_safe_child(data_ledger, "releases"),
        tasks_dir=_safe_child(data_ledger, "tasks"),
        events_dir=_safe_child(logs_ledger, "events"),
        agent_logs_dir=_safe_child(logs_ledger, "agent-logs"),
        active_task_path=_safe_child(
            _safe_child(runtime_root, "checkouts", ledger_ref),
            "active-task.yaml",
        ),
        repo_registry_path=_safe_child(data_ledger, "repos.json"),
        task_index_path=_safe_child(indexes_ledger, "tasks.json"),
        sidecar_index_path=_safe_child(indexes_ledger, "task_sidecars.json"),
        active_locks_index_path=_safe_child(indexes_ledger, "active_locks.json"),
        dependencies_index_path=_safe_child(indexes_ledger, "dependencies.json"),
        introductions_index_path=_safe_child(indexes_ledger, "introductions.json"),
    )


def paths_for_ledger_ref(
    context: TaskledgerProjectContext, ledger_ref: str
) -> TaskledgerPaths:
    """Build canonical mount paths for any physical ledger namespace."""
    paths = context.paths
    return _paths_for_mounts(
        context.project_root,
        context.config_path,
        paths.data_root,
        paths.runtime_root,
        paths.logs_root,
        paths.indexes_root,
        ledger_ref,
    )


def _load_toml(path: Path) -> dict[str, object]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Unable to read Ledger configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"Ledger configuration {path} must contain a TOML table.")
    return cast(dict[str, object], value)


def _validate_registration(layout: Any) -> None:
    mount_names = set(layout.mounts)
    if mount_names not in (set(CANONICAL_MOUNT_NAMES), {DATA_MOUNT, INDEX_MOUNT}):
        raise LaunchError(
            "TASKLEDGER_REGISTRATION_INVALID: Taskledger registration must define "
            "data, runtime, logs, and indexes mounts."
        )
    if layout.mounts[DATA_MOUNT].storage not in {"project", "external", "user-data"}:
        raise LaunchError(
            "TASKLEDGER_STORAGE_BINDING_INVALID: data must be persistent."
        )
    runtime_mount = layout.mounts.get(RUNTIME_MOUNT)
    if runtime_mount is not None and runtime_mount.storage != "user-data":
        raise LaunchError(
            "TASKLEDGER_STORAGE_BINDING_INVALID: runtime must use user-data."
        )
    logs_mount = layout.mounts.get(LOGS_MOUNT)
    if logs_mount is not None and logs_mount.storage not in {
        "project",
        "external",
        "user-data",
    }:
        raise LaunchError(
            "TASKLEDGER_STORAGE_BINDING_INVALID: logs must use persistent storage."
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
    runtime_mount = layout.mounts.get(RUNTIME_MOUNT)
    logs_mount = layout.mounts.get(LOGS_MOUNT)
    runtime_root = runtime_mount.path if runtime_mount is not None else data_root
    logs_root = logs_mount.path if logs_mount is not None else data_root
    indexes_root = layout.mounts[INDEX_MOUNT].path
    ledger = _load_state(data_root / "state.toml")
    paths = _paths_for_mounts(
        layout.project_root,
        config_path,
        data_root,
        runtime_root,
        logs_root,
        indexes_root,
        ledger.ref,
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
) -> TaskledgerProjectContext:
    """Load canonical Taskledger context without creating or mutating files."""
    locator = locate_taskledger_project(start)
    if locator is not None and not locator.is_legacy:
        bundle = load_taskledger_ledger_layout(start)
        return _context_from_layout(
            start, bundle, require_initialized=require_initialized
        )

    probe = probe_taskledger_project(start)
    if probe.source == "legacy":
        raise LaunchError(
            "TASKLEDGER_MIGRATION_REQUIRED: Legacy Taskledger state "
            "is migration input. "
            "Run `taskledger migrate plan`, review the plan, then run "
            "`taskledger migrate apply`.",
            code="TASKLEDGER_MIGRATION_REQUIRED",
            remediation=[
                "Run `taskledger migrate plan` and review the result",
                "Run `taskledger migrate apply`",
            ],
            details={
                "project_root": str(probe.project_root),
                "legacy_config": (
                    str(probe.tool_config_path) if probe.tool_config_path else None
                ),
            },
        )
    raise LaunchError(
        "TASKLEDGER_NOT_INITIALIZED: Taskledger is not initialized for this "
        "project. Run `taskledger init`.",
        code="TASKLEDGER_NOT_INITIALIZED",
        remediation=["Run `taskledger init`"],
        details={"project_root": str(start.resolve())},
    )


def require_mutable_project_context(start: Path) -> TaskledgerProjectContext:
    """Require a valid canonical project before any command may write state."""
    context = load_project_context(start, require_initialized=False)
    if context.paths.storage_meta_path.exists():
        from taskledger.storage.migrations import reconcile_storage_layout

        reconciliation = reconcile_storage_layout(start)
        if reconciliation.changed:
            context = load_project_context(start, require_initialized=False)

    from taskledger.storage.index_cache import ensure_indexes_cache_for_mutation
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    local_state_recovery = ensure_local_state_for_mutation(context)
    cache_recovery = ensure_indexes_cache_for_mutation(context)
    context = load_project_context(start, require_initialized=True)
    if local_state_recovery is not None or cache_recovery is not None:
        context = replace(
            context,
            local_state_recovery=local_state_recovery,
            cache_recovery=cache_recovery,
        )
    if cache_recovery is not None and cache_recovery.quarantine_path is not None:
        logging.getLogger(__name__).warning(
            "Taskledger quarantined the unbound indexes cache at %s",
            cache_recovery.quarantine_path,
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
        RUNTIME_MOUNT: ("user-data", "checkout", f"taskledger-runtime{suffix}"),
        LOGS_MOUNT: ("user-data", "checkout", f"taskledger-logs{suffix}"),
        INDEX_MOUNT: ("cache", "checkout", "taskledger-indexes"),
    }


def resolve_project_paths(workspace_root: Path) -> ProjectPaths:
    context = load_project_context(workspace_root, require_initialized=False)
    return ProjectPaths(
        workspace_root=context.project_root,
        project_dir=context.paths.ledger_data_dir,
        taskledger_dir=context.paths.data_root,
        config_path=context.config_path,
        releases_dir=context.paths.releases_dir,
        repos_dir=context.paths.ledger_data_dir,
        repo_index_path=context.paths.repo_registry_path,
    )


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
    "resolve_project_paths",
]

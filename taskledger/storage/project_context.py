"""Shared canonical and legacy project discovery for Taskledger.

Canonical project topology is resolved by Ledgercore.  This module only adds
Taskledger's registration checks, config parsing, legacy marker compatibility,
and the Taskledger-owned subpaths below resolved mounts.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from ledgercore import (
    LedgerLayoutError,
    LedgerProjectLocator,
    ResolvedLedgerLayout,
    locate_ledger_project,
    parse_ledger_local_config,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)
from ledgercore.layout import (
    LedgerLocalConfig,
    LedgerProjectManifest,
)

from taskledger.errors import LaunchError
from taskledger.storage.ledger_config import (
    LedgerConfig,
    load_ledger_config,
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
    "not_registered",
    "invalid_registration",
    "missing_config",
    "missing_local_provider",
    "workspace_root_conflict",
    "workspace_provider_conflict",
    "workspace_environment_override",
    "missing_sibling_store",
    "missing_store_marker",
    "invalid_store_marker",
    "missing_data",
    "missing_binding",
    "binding_mismatch",
    "old_canonical_layout",
    "missing_storage_meta",
    "invalid_state",
    "migration_required",
    "ready",
]

CANONICAL_LEDGER_NAME = "taskledger"
CANONICAL_LEDGER_CODE = "tl"
CANONICAL_SHORT_DIRECTORY = "task"
CANONICAL_CONFIG_RELATIVE_PATH = Path("task") / "config.toml"
CANONICAL_MOUNT_NAMES = ("data", "indexes")
CANONICAL_MOUNT_SPECS = {
    "data": ("workspace", "project", "task/taskledger"),
    "indexes": ("cache", "checkout", "task/taskledger-indexes"),
}
CANONICAL_CONFIG_VERSION = 3
CANONICAL_STORAGE_LAYOUT_VERSION = 5
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
        """Deprecated legacy alias, retained for compatibility adapters."""
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
    layout: ResolvedLedgerLayout | None
    legacy_locator: ProjectPaths | None
    store_root: Path | None = None
    store_marker_path: Path | None = None
    binding_path: Path | None = None
    workspace_provider: Literal["sibling-ledger"] | None = None
    data_mount_source: Literal["local-provider"] | None = None


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


def _legacy_context(
    start: Path, project_paths: ProjectPaths
) -> TaskledgerProjectContext:
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
    document = load_project_config_document(project_paths.config_path)
    config = merge_project_config(document)
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
        if (candidate / DEFAULT_TASKLEDGER_DIR_NAME / "storage.yaml").exists():
            return candidate
    return None


def _distance(start: Path, root: Path) -> int:
    try:
        return len(start.relative_to(root).parts)
    except ValueError:
        return 10_000


def _find_locator(start: Path) -> tuple[LedgerProjectLocator | None, Path | None]:
    resolved = start.expanduser().resolve()
    locator = locate_ledger_project(
        resolved, legacy_tool_filenames=LEGACY_CONFIG_FILENAMES
    )
    marker_root = _legacy_marker_root(resolved)
    if locator is None:
        return None, marker_root
    if marker_root is None:
        return locator, None
    locator_root = locator.project_root
    marker_distance = _distance(
        resolved if resolved.is_dir() else resolved.parent, marker_root
    )
    locator_distance = _distance(
        resolved if resolved.is_dir() else resolved.parent, locator_root
    )
    if marker_distance < locator_distance:
        return None, marker_root
    return locator, marker_root


def _load_toml(path: Path) -> dict[str, object]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Unable to read Ledger configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"Ledger configuration {path} must contain a TOML table.")
    return cast(dict[str, object], value)


def _validate_registration(layout: ResolvedLedgerLayout) -> None:
    if set(layout.mounts) != set(CANONICAL_MOUNT_NAMES):
        raise LaunchError(
            "TASKLEDGER_REGISTRATION_CONFLICT: Taskledger registration must "
            "define exactly data and indexes mounts."
        )
    data = layout.mounts["data"]
    if (
        str(data.storage) != "workspace"
        or str(data.scope) != "project"
        or not str(data.path).replace("\\", "/").endswith("/task/taskledger")
    ):
        raise LaunchError(
            "TASKLEDGER_REGISTRATION_CONFLICT: Taskledger data mount must be "
            "workspace/project task/taskledger."
        )
    indexes = layout.mounts["indexes"]
    if (
        str(indexes.storage) != "cache"
        or str(indexes.scope) != "checkout"
        or str(indexes.path).replace("\\", "/").split("/")[-2:]
        != ["task", "taskledger-indexes"]
    ):
        raise LaunchError(
            "TASKLEDGER_REGISTRATION_CONFLICT: Taskledger indexes mount must be "
            "cache/checkout task/taskledger-indexes."
        )


def _validate_exact_sibling_postcondition(
    project_root: Path, layout: ResolvedLedgerLayout
) -> None:
    expected_root = (project_root / ".." / "ledger").resolve(strict=False)
    data = layout.mounts["data"]
    if str(data.source) != "local-provider":
        raise LaunchError(
            "TASKLEDGER_SIBLING_PROVIDER_REQUIRED: Taskledger data must resolve "
            "through the local sibling-ledger provider."
        )
    if data.scoped_root != expected_root or data.path != expected_root / (
        "task/taskledger"
    ):
        raise LaunchError(
            "TASKLEDGER_DIRECT_PATH_MISMATCH: Taskledger data must resolve to "
            f"{expected_root / 'task/taskledger'}."
        )
    marker = expected_root / ".ledger-store"
    if not marker.exists():
        raise LaunchError(f"TASKLEDGER_SIBLING_ROOT_MISSING: {expected_root}")
    if marker.is_symlink() or not marker.is_file():
        raise LaunchError(f"TASKLEDGER_SIBLING_MARKER_INVALID: {marker}")


def _resolve_taskledger_layout(
    locator: LedgerProjectLocator,
    manifest: LedgerProjectManifest,
    local: LedgerLocalConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> ResolvedLedgerLayout:
    """Resolve the one canonical Taskledger layout through Ledgercore."""
    effective = dict(os.environ if environ is None else environ)
    if effective.get("LEDGER_WORKSPACE_ROOT"):
        raise LaunchError(
            "TASKLEDGER_WORKSPACE_ENV_UNSUPPORTED: Unset LEDGER_WORKSPACE_ROOT "
            "and retry."
        )
    if local.workspace_root is not None:
        raise LaunchError(
            "TASKLEDGER_WORKSPACE_ROOT_CONFLICT: Taskledger authoritative "
            "storage is fixed to the sibling-ledger provider."
        )
    if local.workspace_provider != "sibling-ledger":
        raise LaunchError(
            "TASKLEDGER_SIBLING_PROVIDER_REQUIRED: Set "
            "[storage.workspace].provider = 'sibling-ledger'."
        )
    return resolve_ledger_layout(
        locator,
        manifest,
        CANONICAL_LEDGER_NAME,
        local_config=local,
        environ=effective,
    )


def load_project_context(
    start: Path,
    *,
    require_initialized: bool = True,
    allow_legacy: bool = True,
) -> TaskledgerProjectContext:
    """Resolve Taskledger project identity, config, layout, and owned paths.

    This function is read-only.  It never creates a directory, UUID, config, or
    index.  Initialization belongs to ``taskledger init`` and migration.
    """
    locator, marker_root = _find_locator(start)
    if locator is None or locator.source in {"legacy-tool", "legacy"}:
        legacy_root = marker_root or (
            locator.project_root if locator is not None else None
        )
        if not allow_legacy or legacy_root is None:
            raise LaunchError(
                "No canonical Ledger project or readable legacy Taskledger "
                "project found."
            )
        legacy = load_project_locator(legacy_root)
        return _legacy_context(
            start,
            project_paths_for_root(
                legacy.workspace_root,
                legacy.taskledger_dir,
                config_path=legacy.config_path,
            ),
        )

    if locator.source not in {"canonical", "default"}:
        raise LaunchError(
            f"Unsupported Ledger project discovery source {locator.source!r}."
        )
    manifest_path = locator.manifest_path
    manifest_doc = _load_toml(manifest_path)
    try:
        manifest = parse_ledger_project_manifest(manifest_doc)
        local_doc = (
            _load_toml(locator.local_config_path)
            if locator.local_config_path.exists()
            else {}
        )
        local = parse_ledger_local_config(local_doc, project_root=locator.project_root)
        layout = _resolve_taskledger_layout(
            locator, manifest, local, environ=dict(os.environ)
        )
        _validate_registration(layout)
        _validate_exact_sibling_postcondition(locator.project_root, layout)
    except LedgerLayoutError as exc:
        raise LaunchError(f"Invalid Ledger layout {manifest_path}: {exc}") from exc
    config_path = layout.tool_config_path
    if config_path is None:
        raise LaunchError(
            f"Taskledger registration has no project config path in {manifest_path}."
        )
    if not config_path.exists():
        state = TaskledgerInitializationState(
            "missing_config", f"Missing Taskledger config {config_path}."
        )
        if require_initialized:
            raise LaunchError(
                f"Missing Taskledger config {config_path}. Run `taskledger init`."
            )
        config = ProjectConfig()
    else:
        config = load_canonical_project_config(config_path)
        state = TaskledgerInitializationState("ready")
    data_mount = layout.mounts["data"]
    data_root = data_mount.path
    sibling_root = (locator.project_root / ".." / "ledger").resolve(strict=False)
    marker = sibling_root / ".ledger-store"
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise LaunchError(f"TASKLEDGER_SIBLING_MARKER_INVALID: {marker}")
    ledger = _load_state(data_root / "state.toml")
    paths = _paths_for_mounts(
        locator.project_root,
        config_path,
        data_root,
        data_root,
        layout.mounts["indexes"].path,
        ledger.ref,
    )
    if require_initialized:
        if not data_root.exists() or not paths.storage_meta_path.exists():
            raise LaunchError(
                f"Taskledger data mount is not initialized at {data_root}. "
                "Run `taskledger init`."
            )
        from taskledger.storage.project_binding import validate_project_binding

        validate_project_binding(data_root, project_uuid=layout.project_uuid)
    return TaskledgerProjectContext(
        mode="canonical",
        project_root=locator.project_root,
        project_uuid=layout.project_uuid,
        project_name=manifest.project_name or locator.project_root.name,
        config_path=config_path,
        config=config,
        ledger_state=ledger,
        paths=paths,
        initialization=state,
        layout=layout,
        legacy_locator=None,
        store_root=sibling_root,
        store_marker_path=marker,
        binding_path=data_root / ".ledger-project.toml",
        workspace_provider="sibling-ledger",
        data_mount_source="local-provider",
    )


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
                "Canonical ledger state contains forbidden "
                "ledger_next_task_number; run taskledger migrate."
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


def is_canonical_project(start: Path) -> bool:
    locator, marker = _find_locator(start)
    return (
        locator is not None
        and locator.source == "canonical"
        and not (
            marker is not None
            and _distance(start.resolve(), marker)
            < _distance(start.resolve(), locator.project_root)
        )
    )


__all__ = [
    "CANONICAL_CONFIG_VERSION",
    "CANONICAL_LEDGER_CODE",
    "CANONICAL_LEDGER_NAME",
    "CANONICAL_MOUNT_NAMES",
    "CANONICAL_MOUNT_SPECS",
    "CANONICAL_SHORT_DIRECTORY",
    "CANONICAL_STORAGE_LAYOUT_VERSION",
    "TaskledgerInitializationState",
    "TaskledgerPaths",
    "TaskledgerProjectContext",
    "load_project_context",
]

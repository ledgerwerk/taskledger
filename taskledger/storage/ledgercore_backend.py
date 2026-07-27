"""Taskledger's narrow adapter for Ledgercore storage APIs."""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, TypeVar, cast

import ledgercore
from ledgercore import (
    LedgerCoreError,
    LedgerProjectLocator,
    ResolvedLedgerLayout,
    StorageMigrationPlan,
    StorageMigrationResult,
    StorageValidationReport,
    execute_storage_migration,
    initialize_config_binding,
    initialize_external_store,
    initialize_storage_binding,
    inspect_storage_migration,
    load_ledger_project,
    parse_ledger_local_config,
    parse_ledger_manifest_v3,
    parse_ledger_project_manifest,
    plan_storage_migration,
    read_ledger_manifest,
    recover_storage_migration,
    resolve_ledger_layout,
    validate_ledger_layout_storage,
    write_ledger_local_config,
    write_ledger_manifest,
)
from ledgercore.manifest import (
    LedgerProjectManifest,
    LedgerRegistration,
    MountDefinition,
)
from ledgercore.storage_binding import StorageBindingError, read_storage_binding

TOOL_NAME = "taskledger"
DATA_MOUNT = "data"
INDEX_MOUNT = "indexes"


@dataclass(frozen=True, slots=True)
class TaskledgerLedgerLayout:
    loaded_project: Any
    resolved_layout: Any
    validation_report: Any

    @property
    def layout(self) -> Any:
        return self.resolved_layout

    @property
    def validation(self) -> Any:
        return self.validation_report


def _storage_error(exc: LedgerCoreError) -> Any:
    from taskledger.errors import LaunchError

    return LaunchError(
        str(exc),
        code="TASKLEDGER_LEDGER_PROJECT_INVALID",
        details={
            "ledgercore_code": exc.code,
            "ledgercore_error_type": type(exc).__name__,
        },
    )


T = TypeVar("T")


def _call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except LedgerCoreError as exc:
        raise _storage_error(exc) from exc


def _load_schema2_layout(start: Path) -> TaskledgerLedgerLayout:
    locator = locate_taskledger_project(start)
    if locator is None:
        raise LedgerCoreError(f"No Ledger project found from {start}")
    manifest = _call(lambda: read_ledger_manifest(locator.manifest_path))
    local_document: dict[str, object] = {}
    if locator.local_config_path.exists():
        try:
            tomllib = importlib.import_module("tomllib")
        except ModuleNotFoundError:  # pragma: no cover
            tomllib = importlib.import_module("tomli")
        local_document = tomllib.loads(
            locator.local_config_path.read_text(encoding="utf-8")
        )
    local = _call(
        lambda: parse_ledger_local_config(
            local_document, project_root=locator.project_root
        )
    )
    layout = _call(
        lambda: resolve_ledger_layout(locator, manifest, TOOL_NAME, local_config=local)
    )
    validation = _call(lambda: validate_ledger_layout_storage(layout))
    loaded = SimpleNamespace(
        locator=locator,
        manifest=manifest,
        local_overrides=local,
        effective_ledgers={},
    )
    return TaskledgerLedgerLayout(loaded, layout, validation)


def load_taskledger_ledger_layout(
    start: Path,
    *,
    validate_storage: bool = True,
) -> TaskledgerLedgerLayout:
    locator = locate_taskledger_project(start)
    if locator is not None:
        manifest = _call(lambda: read_ledger_manifest(locator.manifest_path))
        if getattr(manifest, "schema_version", None) == 2:
            bundle = _load_schema2_layout(start)
            if not validate_storage:
                return TaskledgerLedgerLayout(
                    bundle.loaded_project, bundle.resolved_layout, None
                )
            return bundle
        if (
            getattr(manifest, "schema_version", None) == 3
            and TOOL_NAME not in manifest.ledgers
        ):
            from taskledger.errors import TaskledgerRegistrationMissing

            orphan_config = locator.project_root / ".ledger" / TOOL_NAME / "config.toml"
            raise TaskledgerRegistrationMissing(
                project_root=str(locator.project_root),
                manifest_path=str(locator.manifest_path),
                tool_config_path=str(orphan_config),
                orphan_config_present=orphan_config.exists(),
                ledgercore_code="UNKNOWN_LEDGER_REGISTRATION",
            )
    loaded = _call(
        lambda: load_ledger_project(
            start,
            legacy_tool_filenames=(".taskledger.toml", "taskledger.toml"),
        )
    )
    layout = _call(
        lambda: resolve_ledger_layout(
            loaded.locator,
            loaded.manifest,
            TOOL_NAME,
            local_overrides=loaded.local_overrides,
        )
    )
    validation: StorageValidationReport | None = None
    if validate_storage:
        validation = _call(lambda: validate_ledger_layout_storage(layout))
    return TaskledgerLedgerLayout(loaded, layout, validation)


def locate_taskledger_project(start: Path) -> Any:
    """Discover a canonical or legacy Ledger project without parsing it."""
    return ledgercore.locate_ledger_project(
        start, legacy_tool_filenames=(".taskledger.toml", "taskledger.toml")
    )


def build_taskledger_manifest_with_registration(
    manifest: LedgerProjectManifest | None,
    *,
    project_uuid: str,
    project_name: str,
    data_storage: str = "external",
    external_root: str | None = "../ledger",
) -> LedgerProjectManifest:
    """Return a canonical manifest while preserving other ledger registrations."""
    normalized_uuid = str(uuid.UUID(project_uuid))
    if manifest is not None and manifest.project_uuid != normalized_uuid:
        raise ValueError("project UUID conflicts with the existing Ledger manifest")
    if data_storage not in {"project", "external", "user-data"}:
        raise ValueError(f"unsupported Taskledger data storage {data_storage!r}")
    mounts: dict[str, MountDefinition] = {
        DATA_MOUNT: MountDefinition(
            DATA_MOUNT,
            cast(Literal["project", "external", "user-data", "cache"], data_storage),
            external_root if data_storage == "external" else None,
        ),
        INDEX_MOUNT: MountDefinition(INDEX_MOUNT, "cache", None),
    }
    registrations = dict(manifest.ledgers) if manifest is not None else {}
    registrations[TOOL_NAME] = LedgerRegistration(TOOL_NAME, mounts)
    return LedgerProjectManifest(
        schema_version=3,
        project_uuid=normalized_uuid,
        project_name=(manifest.project_name if manifest is not None else None)
        or project_name,
        ledgers=registrations,
    )


def _manifest_with_registration(
    manifest: LedgerProjectManifest,
    *,
    project_name: str,
    data_storage: str,
    external_root: str | None,
) -> LedgerProjectManifest:
    return build_taskledger_manifest_with_registration(
        manifest,
        project_uuid=manifest.project_uuid,
        project_name=project_name,
        data_storage=data_storage,
        external_root=external_root,
    )


def ensure_taskledger_ledger_registration(
    project_root: Path,
    *,
    project_uuid: str,
    project_name: str,
    data_storage: str = "external",
    external_root: str | None = "../ledger",
) -> Any:
    """Add or update only Taskledger's schema-3 registration."""
    root = project_root.expanduser().resolve()
    ledger_dir = root / ".ledger"
    manifest_path = ledger_dir / "ledger.toml"
    if manifest_path.exists():
        loaded = _call(lambda: ledgercore.read_ledger_manifest(manifest_path))
        if loaded.project_uuid != str(uuid.UUID(project_uuid)):
            raise ValueError("project UUID conflicts with the existing Ledger manifest")
        manifest = _manifest_with_registration(
            loaded,
            project_name=project_name,
            data_storage=data_storage,
            external_root=external_root,
        )
    else:
        manifest = parse_ledger_manifest_v3(
            {
                "schema_version": 3,
                "project": {"uuid": str(uuid.UUID(project_uuid)), "name": project_name},
                "ledgers": {
                    TOOL_NAME: {
                        "mounts": {
                            DATA_MOUNT: {
                                "storage": data_storage,
                                **(
                                    {"root": external_root}
                                    if data_storage == "external" and external_root
                                    else {}
                                ),
                            },
                            INDEX_MOUNT: {"storage": "cache"},
                        }
                    }
                },
            }
        )
    ledger_dir.mkdir(parents=True, exist_ok=True)
    _call(lambda: write_ledger_manifest(manifest_path, manifest))
    return manifest


def initialize_taskledger_bindings(
    layout: Any,
    *,
    initialize_config: bool,
    initialize_data: bool,
    initialize_indexes: bool,
) -> Any:
    results: dict[str, Any] = {}
    if initialize_config:
        results["config"] = _call(lambda: initialize_config_binding(layout))
    if initialize_data:
        data_mount = layout.mounts[DATA_MOUNT]
        results[DATA_MOUNT] = _call(
            lambda: initialize_storage_binding(
                data_mount,
                require_empty=not (data_mount.path / ".ledger-project.toml").exists(),
            )
        )
    if initialize_indexes:
        indexes_mount = layout.mounts[INDEX_MOUNT]
        results[INDEX_MOUNT] = _call(
            lambda: initialize_storage_binding(
                indexes_mount,
                require_empty=not (
                    indexes_mount.path / ".ledger-project.toml"
                ).exists(),
            )
        )
    return results


def initialize_taskledger_external_store(layout: Any) -> bool:
    """Initialize an external root only during explicit Taskledger init."""
    mount = layout.mounts[DATA_MOUNT]
    if mount.storage != "external" or mount.root is None:
        return False
    existed = mount.root.exists()
    _call(lambda: initialize_external_store(mount.root))
    return not existed


def set_taskledger_mount_target(
    start: Path,
    *,
    mount: str,
    storage: str,
    external_root: str | None,
    target: str,
) -> Any:
    if mount != DATA_MOUNT:
        raise ValueError("only the data mount is user-changeable")
    if target not in {"local", "project"}:
        raise ValueError("target must be local or project")
    loaded = _call(lambda: load_ledger_project(start))
    if target == "local":
        overrides = ledgercore.set_local_mount_override(
            loaded,
            TOOL_NAME,
            mount,
            storage=storage,
            root=external_root,
        )
        _call(
            lambda: write_ledger_local_config(
                loaded.locator.local_config_path, overrides
            )
        )
        return overrides
    manifest = _manifest_with_registration(
        loaded.manifest,
        project_name=loaded.manifest.project_name or loaded.locator.project_root.name,
        data_storage=storage,
        external_root=external_root,
    )
    _call(lambda: write_ledger_manifest(loaded.locator.manifest_path, manifest))
    if loaded.locator.local_config_path.exists():
        _call(
            lambda: write_ledger_local_config(
                loaded.locator.local_config_path,
                ledgercore.clear_local_mount_override(loaded, TOOL_NAME, mount),
                delete_if_empty=True,
            )
        )
    return manifest


def migrate_taskledger_mount(
    start: Path,
    *,
    mount: str,
    storage: str,
    external_root: str | None,
    target: str,
    mode: str,
    quiescence_check: Callable[[], None],
) -> StorageMigrationResult:
    loaded = _call(lambda: load_ledger_project(start))
    if target == "local":
        overrides = _call(
            lambda: ledgercore.set_local_mount_override(
                loaded, TOOL_NAME, mount, storage=storage, root=external_root
            )
        )
        manifest = loaded.manifest
    elif target == "project":
        overrides = _call(
            lambda: ledgercore.clear_local_mount_override(loaded, TOOL_NAME, mount)
        )
        manifest = _manifest_with_registration(
            loaded.manifest,
            project_name=loaded.manifest.project_name or start.name,
            data_storage=storage,
            external_root=external_root,
        )
    else:
        raise ValueError("target must be local or project")
    plan = plan_taskledger_layout_migration(
        loaded, manifest, overrides, mounts=(mount,)
    )
    return execute_taskledger_layout_migration(
        plan,
        mode=mode,
        quiescence_check=quiescence_check,
        project_root=start.resolve(),
    )


def plan_taskledger_layout_migration(
    current: Any,
    target_manifest: Any,
    target_overrides: Any,
    *,
    mounts: tuple[str, ...] | None = None,
    include_config: bool = False,
    cache_strategy: str = "rebuild",
) -> StorageMigrationPlan:
    return _call(
        lambda: plan_storage_migration(
            current,
            target_manifest,
            target_overrides,
            TOOL_NAME,
            mounts=mounts,
            include_config=include_config,
            cache_strategy=cast(Literal["copy", "rebuild"], cache_strategy),
        )
    )


def execute_taskledger_layout_migration(
    plan: StorageMigrationPlan,
    *,
    mode: str,
    quiescence_check: Callable[[], None],
    project_root: Path,
) -> StorageMigrationResult:
    return _call(
        lambda: execute_storage_migration(
            plan,
            mode=cast(Literal["copy", "move"], mode),
            quiescence_check=quiescence_check,
            project_root=project_root,
        )
    )


def inspect_taskledger_migration(journal_path: Path) -> Any:
    return _call(lambda: inspect_storage_migration(journal_path))


def recover_taskledger_migration(journal_path: Path) -> Any:
    return _call(lambda: recover_storage_migration(journal_path))


__all__ = [
    "DATA_MOUNT",
    "INDEX_MOUNT",
    "TOOL_NAME",
    "TaskledgerLedgerLayout",
    "ensure_taskledger_ledger_registration",
    "execute_taskledger_layout_migration",
    "initialize_taskledger_bindings",
    "load_taskledger_ledger_layout",
    "locate_taskledger_project",
    "initialize_taskledger_external_store",
    "migrate_taskledger_mount",
    "plan_taskledger_layout_migration",
    "LedgerProjectLocator",
    "ResolvedLedgerLayout",
    "parse_ledger_local_config",
    "parse_ledger_project_manifest",
    "resolve_ledger_layout",
    "inspect_taskledger_migration",
    "recover_taskledger_migration",
    "set_taskledger_mount_target",
    "build_taskledger_manifest_with_registration",
    "StorageBindingError",
    "read_storage_binding",
]

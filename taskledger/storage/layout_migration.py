"""Read-only inspection and safe application of Taskledger storage migration."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ledgercore import (
    LedgerProjectLocator,
    ResolvedLedgerLayout,
    parse_ledger_local_config,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)

from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.ledger_manifest import ensure_taskledger_registration
from taskledger.storage.paths import ProjectPaths, find_project_config
from taskledger.storage.project_binding import (
    create_project_binding,
    read_project_binding,
)
from taskledger.storage.project_context import (
    CANONICAL_DATA_RELATIVE_PATH,
    CANONICAL_LEDGER_NAME,
    TaskledgerProjectContext,
    canonical_mount_specs,
    load_project_context,
)
from taskledger.storage.yaml_store import write_yaml_object

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover
    tomllib = importlib.import_module("tomli")

MigrationSourceKind = Literal[
    "uninitialized",
    "legacy-root",
    "legacy-arbitrary-external",
    "canonical-0.3-split-checkout",
    "canonical-repository-local",
    "explicit-root-uuid",
    "ledgercore-namespaced-workspace",
    "direct-sibling-unbound",
    "direct-sibling-old-schema",
    "canonical",
    "partial",
    "invalid",
    "canonical-0.4-sibling",
    "partial-sibling-migration",
]


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    severity: Literal["blocker", "warning", "info"]
    code: str
    message: str
    remediation: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "remediation": list(self.remediation),
        }


@dataclass(frozen=True, slots=True)
class MigrationCopyItem:
    source: Path
    destination: Path
    category: str
    action: str
    verification: str = "sha256"
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "category": self.category,
            "action": self.action,
            "verification": self.verification,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class TaskledgerMigrationInspection:
    project_root: Path
    project_uuid: str | None
    source_kind: MigrationSourceKind
    source_data_root: Path | None
    source_logs_root: Path | None
    source_checkout_id: str | None
    target_data_root: Path
    target_indexes_root: Path | None
    sibling_root: Path
    sibling_marker: Path
    binding_path: Path
    current_registration: Mapping[str, object] | None
    target_registration: Mapping[str, object]
    copy_items: tuple[MigrationCopyItem, ...]
    issues: tuple[MigrationIssue, ...]
    legacy_next_task_number: int | None = None
    derived_next_task_id: str | None = None
    tombstones_required: tuple[str, ...] = ()
    ready: bool = False
    migration_required: bool = True

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            issue.message for issue in self.issues if issue.severity == "blocker"
        )

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(
            issue.message for issue in self.issues if issue.severity == "warning"
        )

    @property
    def items(self) -> tuple[MigrationCopyItem, ...]:
        """Compatibility alias for the former migration plan item list."""
        return self.copy_items

    def to_dict(self) -> dict[str, object]:
        blockers = [
            issue.to_dict() for issue in self.issues if issue.severity == "blocker"
        ]
        warnings = [
            issue.to_dict() for issue in self.issues if issue.severity == "warning"
        ]
        status = (
            "invalid"
            if blockers
            else "migration_needed"
            if self.migration_required
            else "up_to_date"
        )
        return {
            "kind": "taskledger_migration_inspection",
            "schema_version": 1,
            "status": status,
            "project": {"root": str(self.project_root), "uuid": self.project_uuid},
            "source": {
                "kind": self.source_kind,
                "data": str(self.source_data_root) if self.source_data_root else None,
                "logs": str(self.source_logs_root) if self.source_logs_root else None,
                "checkout_id": self.source_checkout_id,
            },
            "target": {
                "sibling_root": str(self.sibling_root),
                "marker": str(self.sibling_marker),
                "data": str(self.target_data_root),
                "indexes": str(self.target_indexes_root)
                if self.target_indexes_root
                else None,
                "binding": str(self.binding_path),
            },
            "task_ids": {
                "legacy_next_task_number": self.legacy_next_task_number,
                "derived_next_task_id": self.derived_next_task_id,
                "tombstones_required": list(self.tombstones_required),
            },
            "counts": {"copy_items": len(self.copy_items)},
            "changes": [item.to_dict() for item in self.copy_items],
            "issues": [issue.to_dict() for issue in self.issues],
            "commands": {
                "apply": (
                    "taskledger migrate apply "
                    f"--sibling-ledger-root {self.sibling_root} --backup"
                )
            },
            "blockers": blockers,
            "warnings": warnings,
            "ready": self.ready,
            "migration_required": self.migration_required,
        }


# Compatibility name retained for callers during the transition release.
TaskledgerLayoutMigrationPlan = TaskledgerMigrationInspection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_task_id_fields(
    source_data: Path | None, project_root: Path
) -> tuple[int | None, str | None, tuple[str, ...]]:
    if source_data is None:
        return None, None, ()
    stored: int | None = None
    for config_path in (
        project_root / "taskledger.toml",
        project_root / ".taskledger.toml",
        source_data / "project.toml",
    ):
        if not config_path.is_file():
            continue
        document = _manifest_document(config_path)
        value = document.get("ledger_next_task_number")
        if value is not None:
            if not isinstance(value, int) or value < 1:
                raise LaunchError(
                    f"Malformed legacy ledger_next_task_number in {config_path}."
                )
            stored = value
            break
    highest = 0
    for ledger_root in (source_data / "ledgers").glob("*"):
        tasks = ledger_root / "tasks"
        tombstones = ledger_root / "tombstones"
        for entry in (*tasks.glob("task-*"), *tombstones.glob("task-*.toml")):
            token = entry.stem if entry.suffix == ".toml" else entry.name
            if token.startswith("task-") and token[5:].isdigit():
                highest = max(highest, int(token[5:]))
    derived_number = highest + 1
    derived = f"task-{derived_number:04d}"
    required: tuple[str, ...] = ()
    if stored is not None and stored > derived_number:
        required = tuple(
            f"task-{number:04d}" for number in range(derived_number, stored)
        )
    return stored, derived, required


def _manifest_document(path: Path) -> dict[str, object]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Invalid Ledger manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"Invalid Ledger manifest {path}.")
    return value


def _target_registration(project_uuid: str | None = None) -> dict[str, object]:
    return {
        "config": {"location": "project", "path": "task/config.toml"},
        "mounts": {
            name: {
                "storage": storage,
                **({"scope": scope} if scope is not None else {}),
                "path": path,
            }
            for name, (storage, scope, path) in canonical_mount_specs(
                project_uuid
            ).items()
        },
    }


def _target_roots(root: Path, sibling_ledger_root: Path | None) -> tuple[Path, Path]:
    """Return the requested migration sibling root and its marker."""
    sibling_root = (
        sibling_ledger_root.expanduser().resolve(strict=False)
        if sibling_ledger_root is not None
        else (root / ".." / "ledger").resolve(strict=False)
    )
    return sibling_root, sibling_root / ".ledger-store"


def _ensure_migration_sibling_store(
    sibling_root: Path,
    *,
    create: bool,
) -> None:
    if sibling_root.is_symlink():
        raise LaunchError(
            f"TASKLEDGER_SIBLING_ROOT_UNMARKED: symlink root {sibling_root}"
        )
    if sibling_root.exists() and not sibling_root.is_dir():
        raise LaunchError(f"TASKLEDGER_SIBLING_ROOT_NOT_DIRECTORY: {sibling_root}")
    if not sibling_root.exists():
        if not create:
            raise LaunchError(
                f"TASKLEDGER_SIBLING_ROOT_MISSING: {sibling_root}. "
                "Use --create-sibling-store to initialize it."
            )
        sibling_root.mkdir(parents=True, exist_ok=False)
    marker = sibling_root / ".ledger-store"
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise LaunchError(f"TASKLEDGER_SIBLING_MARKER_INVALID: {marker}")
    if not marker.exists():
        if not create:
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


def _old_registration(document: Mapping[str, object]) -> Mapping[str, object] | None:
    ledgers = document.get("ledgers")
    if not isinstance(ledgers, Mapping):
        return None
    value = ledgers.get(CANONICAL_LEDGER_NAME)
    return value if isinstance(value, Mapping) else None


def _is_old_registration(registration: Mapping[str, object] | None) -> bool:
    if registration is None:
        return False
    mounts = registration.get("mounts")
    if not isinstance(mounts, Mapping):
        return False
    expected = {
        "data": ("workspace", "checkout", "task/data"),
        "logs": ("workspace", "checkout", "task/logs"),
        "indexes": ("cache", "checkout", "task/indexes"),
    }
    if set(mounts) != set(expected):
        return False
    return all(
        isinstance(mounts[name], Mapping)
        and tuple(mounts[name].get(key) for key in ("storage", "scope", "path"))
        == value
        for name, value in expected.items()
    )


def _locator(root: Path) -> LedgerProjectLocator:
    return LedgerProjectLocator(
        root,
        root / ".ledger",
        root / ".ledger" / "ledger.toml",
        root / ".ledger" / "ledger.local.toml",
        "canonical",
    )


def _resolve_old_layout(
    root: Path,
    document: Mapping[str, object],
    *,
    environ: Mapping[str, str] | None,
) -> ResolvedLedgerLayout:
    manifest = parse_ledger_project_manifest(document)
    local_path = root / ".ledger" / "ledger.local.toml"
    local_doc = _manifest_document(local_path) if local_path.exists() else {}
    local = parse_ledger_local_config(local_doc, project_root=root)
    return resolve_ledger_layout(
        _locator(root),
        manifest,
        CANONICAL_LEDGER_NAME,
        local_config=local,
        environ=environ,
    )


def _resolve_target_layout(
    root: Path, project_uuid: str, environ: Mapping[str, str] | None
) -> ResolvedLedgerLayout:
    manifest_doc: dict[str, object] = {
        "schema_version": 2,
        "project": {"uuid": project_uuid, "name": root.name},
        "ledgers": {CANONICAL_LEDGER_NAME: _target_registration(project_uuid)},
    }
    manifest = parse_ledger_project_manifest(manifest_doc)
    local = parse_ledger_local_config(
        {
            "schema_version": 1,
            "storage": {"workspace": {"provider": "sibling-ledger"}},
        },
        project_root=root,
    )
    effective = dict(environ or {})
    effective.pop("LEDGER_WORKSPACE_ROOT", None)
    return resolve_ledger_layout(
        _locator(root),
        manifest,
        CANONICAL_LEDGER_NAME,
        local_config=local,
        environ=effective,
    )


def _legacy_source(
    start: Path,
) -> tuple[TaskledgerProjectContext, ProjectPaths]:
    context = load_project_context(start, require_initialized=False, allow_legacy=True)
    if context.mode != "legacy" or context.legacy_locator is None:
        raise LaunchError("No legacy Taskledger project was found.")
    return context, context.legacy_locator


def _configured_legacy_source(
    root: Path,
) -> tuple[Path, Path, dict[str, object]] | None:
    config_path = find_project_config(root)
    if config_path is None or config_path.name not in {
        ".taskledger.toml",
        "taskledger.toml",
    }:
        return None
    config_doc = _manifest_document(config_path)
    raw_path = config_doc.get("taskledger_dir")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    source_data = Path(os.path.expandvars(raw_path)).expanduser()
    if not source_data.is_absolute():
        source_data = config_path.parent / source_data
    source_data = source_data.resolve()
    if not source_data.exists():
        return None
    return source_data, config_path, config_doc


def _copy_items(
    source_data: Path | None, source_logs: Path | None, target: Path
) -> list[MigrationCopyItem]:
    items: list[MigrationCopyItem] = []
    seen: set[Path] = set()
    for source_root, category in (
        (source_data, "authoritative-data"),
        (source_logs, "durable-log"),
    ):
        if source_root is None or not source_root.exists():
            continue
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source in seen:
                continue
            seen.add(source)
            relative = source.relative_to(source_root)
            if relative == Path(".ledger-project.toml"):
                continue
            if (
                relative.parts[:2] == ("ledgers", "main", "indexes")
                and relative.name != "repos.json"
            ):
                continue
            destination = target / relative
            if category == "durable-log" and relative.parts[:1] == ("migrations",):
                destination = (
                    target / "migrations" / "legacy" / Path(*relative.parts[1:])
                )
            action = "copy"
            if destination.exists():
                action = (
                    "skip-identical"
                    if _sha256(source) == _sha256(destination)
                    else "conflict"
                )
            items.append(MigrationCopyItem(source, destination, category, action))
    return items


def _issue(
    severity: Literal["blocker", "warning", "info"],
    code: str,
    message: str,
    *remediation: str,
) -> MigrationIssue:
    return MigrationIssue(severity, code, message, tuple(remediation))


def _is_repository_local_registration(
    registration: Mapping[str, object] | None,
) -> bool:
    if registration is None:
        return False
    mounts_value = registration.get("mounts")
    if not isinstance(mounts_value, Mapping):
        return False
    mounts = mounts_value
    data = mounts.get("data")
    indexes = mounts.get("indexes")
    return (
        isinstance(data, Mapping)
        and isinstance(indexes, Mapping)
        and data.get("storage") == "repository"
        and data.get("path") == "task/taskledger"
        and indexes.get("storage") == "cache"
        and indexes.get("scope") == "checkout"
        and indexes.get("path") == "task/taskledger-indexes"
    )


def _is_direct_sibling_registration(
    registration: Mapping[str, object] | None,
    *,
    project_uuid: str | None = None,
) -> bool:
    if registration is None:
        return False
    mounts_value = registration.get("mounts")
    if not isinstance(mounts_value, Mapping):
        return False
    mounts = mounts_value
    data = mounts.get("data")
    indexes = mounts.get("indexes")
    if not isinstance(data, Mapping) or not isinstance(indexes, Mapping):
        return False
    data_path = data.get("path")
    old_uuid_path = (
        f"task/taskledger/{project_uuid}" if project_uuid is not None else None
    )
    return (
        data.get("storage") == "workspace"
        and data.get("scope") == "project"
        and data_path in {"task/taskledger", "taskledger", old_uuid_path}
        and indexes.get("storage") == "cache"
        and indexes.get("scope") == "checkout"
        and indexes.get("path")
        in {
            "task/taskledger-indexes",
            "taskledger-indexes",
        }
    )


def inspect_migration(  # noqa: C901
    start: Path,
    *,
    source_checkout: str | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> TaskledgerMigrationInspection:
    root = start.expanduser().resolve()
    sibling_root, marker = _target_roots(root, sibling_ledger_root)
    target_data = sibling_root / CANONICAL_DATA_RELATIVE_PATH
    target_indexes: Path | None = None
    target_registration = _target_registration()
    issues: list[MigrationIssue] = []
    source_kind: MigrationSourceKind = "uninitialized"
    source_data: Path | None = None
    source_logs: Path | None = None
    selected_uuid: str | None = None
    checkout_id: str | None = source_checkout
    current_registration: Mapping[str, object] | None = None
    legacy_next_task_number: int | None = None
    derived_next_task_id: str | None = None
    tombstones_required: tuple[str, ...] = ()

    if environ is None:
        environ = os.environ
    if environ.get("LEDGER_WORKSPACE_ROOT"):
        issues.append(
            _issue(
                "blocker",
                "WORKSPACE_ENV_OVERRIDE",
                "LEDGER_WORKSPACE_ROOT overrides sibling-ledger resolution.",
                "Unset LEDGER_WORKSPACE_ROOT before applying.",
            )
        )

    locator = None
    try:
        from ledgercore import locate_ledger_project

        locator = locate_ledger_project(
            root, legacy_tool_filenames=(".taskledger.toml", "taskledger.toml")
        )
    except Exception as exc:
        issues.append(_issue("blocker", "DISCOVERY_ERROR", str(exc)))

    if locator is not None and locator.source == "canonical":
        manifest_doc = _manifest_document(locator.manifest_path)
        current_registration = _old_registration(manifest_doc)
        project = manifest_doc.get("project")
        if isinstance(project, Mapping) and isinstance(project.get("uuid"), str):
            selected_uuid = str(uuid.UUID(project["uuid"]))
        if _is_old_registration(current_registration):
            source_kind = "canonical-0.3-split-checkout"
            try:
                old_layout = _resolve_old_layout(root, manifest_doc, environ=environ)
                source_data = old_layout.mounts["data"].path
                source_logs = old_layout.mounts["logs"].path
                checkout_id = old_layout.checkout_id
            except Exception as exc:
                issues.append(_issue("blocker", "OLD_LAYOUT_UNRESOLVED", str(exc)))
        elif _is_repository_local_registration(current_registration):
            configured = _configured_legacy_source(root)
            if configured is not None:
                source_data, _source_config, source_config_doc = configured
                source_kind = (
                    "legacy-arbitrary-external"
                    if not source_data.is_relative_to(root)
                    else "legacy-root"
                )
                source_logs = source_data
                configured_uuid = source_config_doc.get("project_uuid")
                if (
                    isinstance(configured_uuid, str)
                    and selected_uuid is not None
                    and str(uuid.UUID(configured_uuid)) != selected_uuid
                ):
                    issues.append(
                        _issue(
                            "blocker",
                            "PROJECT_UUID_MISMATCH",
                            "Legacy Taskledger config UUID differs from the "
                            "canonical project UUID.",
                        )
                    )
            else:
                source_kind = "canonical-repository-local"
                source_data = root / ".ledger" / "task" / "taskledger"
                source_logs = source_data
        elif _is_direct_sibling_registration(
            current_registration, project_uuid=selected_uuid
        ):
            source_kind = "direct-sibling-old-schema"
            try:
                old_layout = _resolve_old_layout(root, manifest_doc, environ=environ)
                source_data = old_layout.mounts["data"].path
                source_logs = source_data
                checkout_id = old_layout.checkout_id
            except Exception as exc:
                issues.append(_issue("blocker", "OLD_LAYOUT_UNRESOLVED", str(exc)))
        else:
            try:
                context = load_project_context(
                    root, require_initialized=False, allow_legacy=False
                )
                binding = read_project_binding(context.paths.data_root)
                meta = context.paths.storage_meta_path.exists()
                if binding is not None and meta and context.paths.state_path.exists():
                    source_kind = "canonical-0.4-sibling"
                    selected_uuid = context.project_uuid
                else:
                    source_kind = "partial-sibling-migration"
                    issues.append(
                        _issue(
                            "blocker",
                            "PARTIAL_MIGRATION",
                            "Target registration exists but target binding, state, or "
                            "storage metadata is incomplete.",
                        )
                    )
            except Exception as exc:
                source_kind = "partial-sibling-migration"
                issues.append(_issue("blocker", "PARTIAL_MIGRATION", str(exc)))
    elif locator is not None and locator.source in {"legacy-tool", "legacy"}:
        try:
            context, legacy = _legacy_source(root)
            source_kind = "legacy-root"
            source_data = legacy.taskledger_dir
            source_logs = legacy.taskledger_dir
            selected_uuid = context.project_uuid
        except Exception as exc:
            source_kind = "invalid"
            issues.append(_issue("blocker", "LEGACY_SOURCE_INVALID", str(exc)))
    else:
        try:
            context, legacy = _legacy_source(root)
        except LaunchError:
            context = None
        if context is not None:
            source_kind = "legacy-root"
            source_data = legacy.taskledger_dir
            source_logs = legacy.taskledger_dir
            selected_uuid = context.project_uuid

    try:
        (
            legacy_next_task_number,
            derived_next_task_id,
            tombstones_required,
        ) = _legacy_task_id_fields(source_data, root)
    except LaunchError as exc:
        issues.append(_issue("blocker", "MALFORMED_LEGACY_COUNTER", str(exc)))
    if project_uuid is not None:
        try:
            requested_uuid = str(uuid.UUID(project_uuid))
        except ValueError as exc:
            raise LaunchError(
                f"Invalid migration project UUID {project_uuid!r}."
            ) from exc
        if selected_uuid is not None and selected_uuid != requested_uuid:
            issues.append(
                _issue(
                    "blocker",
                    "PROJECT_UUID_MISMATCH",
                    "Requested migration UUID differs from the project UUID.",
                )
            )
        selected_uuid = requested_uuid
    if source_kind == "direct-sibling-old-schema" and source_data is not None:
        source_binding = read_project_binding(source_data)
        if (
            source_binding is not None
            and selected_uuid is not None
            and source_binding.project_uuid != selected_uuid
        ):
            issues.append(
                _issue(
                    "blocker",
                    "BINDING_UUID_MISMATCH",
                    "Direct sibling source binding belongs to "
                    f"{source_binding.project_uuid}, expected {selected_uuid}.",
                )
            )
    if selected_uuid is None and source_kind != "canonical-0.4-sibling":
        selected_uuid = str(uuid.uuid4())
    if selected_uuid is not None:
        target_data = sibling_root / CANONICAL_DATA_RELATIVE_PATH / selected_uuid
        target_registration = _target_registration(selected_uuid)

    if not sibling_root.exists():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_ROOT_MISSING",
                f"Sibling root is missing: {sibling_root}",
                "Use --create-sibling-store when applying.",
            )
        )
    elif not marker.exists():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_ROOT_UNMARKED",
                f"Sibling root exists without required marker {marker}.",
            )
        )
    elif marker.is_symlink() or not marker.is_file():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_MARKER_INVALID",
                f"Sibling marker is not a regular file: {marker}.",
            )
        )
    try:
        if selected_uuid is not None:
            target_layout = _resolve_target_layout(root, selected_uuid, environ)
            target_indexes = target_layout.mounts["indexes"].path
    except Exception as exc:
        target_indexes = None
        if source_kind != "canonical-0.4-sibling":
            issues.append(_issue("warning", "TARGET_UNRESOLVED", str(exc)))

    binding = read_project_binding(target_data) if target_data.exists() else None
    binding_mismatch = (
        binding is not None
        and selected_uuid is not None
        and binding.project_uuid != selected_uuid
    )
    if binding_mismatch:
        assert binding is not None
        issues.append(
            _issue(
                "blocker",
                "BINDING_UUID_MISMATCH",
                "Target binding belongs to "
                f"{binding.project_uuid}, expected {selected_uuid}.",
                "Re-run with --sibling-ledger-root PATH for a separate "
                "migration destination, or keep the existing target unchanged.",
            )
        )
    if (
        target_data.exists()
        and not binding
        and any(target_data.iterdir())
        and source_kind != "canonical-0.4-sibling"
    ):
        issues.append(
            _issue(
                "blocker",
                "BINDING_MISSING",
                "Non-empty target data root has no .ledger-project.toml: "
                f"{target_data}",
            )
        )

    items = (
        [] if binding_mismatch else _copy_items(source_data, source_logs, target_data)
    )
    for item in items:
        if item.action == "conflict":
            issues.append(
                _issue(
                    "blocker",
                    "DESTINATION_CONFLICT",
                    f"Destination differs from source: {item.destination}",
                )
            )
    if (
        source_kind not in {"canonical-0.4-sibling", "partial-sibling-migration"}
        and not items
        and not binding_mismatch
    ):
        issues.append(
            _issue(
                "blocker", "SOURCE_MISSING", "No authoritative source files were found."
            )
        )

    return TaskledgerMigrationInspection(
        project_root=root,
        project_uuid=selected_uuid,
        source_kind=source_kind,
        source_data_root=source_data,
        source_logs_root=source_logs,
        source_checkout_id=checkout_id,
        target_data_root=target_data,
        target_indexes_root=target_indexes,
        sibling_root=sibling_root,
        sibling_marker=marker,
        binding_path=target_data / ".ledger-project.toml",
        current_registration=current_registration,
        target_registration=target_registration,
        copy_items=tuple(items),
        issues=tuple(issues),
        legacy_next_task_number=legacy_next_task_number,
        derived_next_task_id=derived_next_task_id,
        tombstones_required=tombstones_required,
        ready=not any(issue.severity == "blocker" for issue in issues),
        migration_required=source_kind != "canonical-0.4-sibling",
    )


def _backup(inspection: TaskledgerMigrationInspection, backup_dir: Path | None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        backup_dir
        or inspection.project_root / ".ledger" / "backups" / f"taskledger-{timestamp}"
    )
    destination.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, str]] = []
    for source in (inspection.source_data_root, inspection.source_logs_root):
        if (
            source is None
            or not source.exists()
            or source in (inspection.source_data_root, inspection.source_logs_root)
            and source != inspection.source_data_root
        ):
            continue
        target = destination / "source-data"
        shutil.copytree(source, target, dirs_exist_ok=True)
        for path in source.rglob("*"):
            if path.is_file():
                manifest.append({"source": str(path), "sha256": _sha256(path)})
        break
    for source in (
        inspection.project_root / ".ledger" / "ledger.toml",
        inspection.project_root / ".ledger" / "ledger.local.toml",
    ):
        if source.exists():
            shutil.copy2(source, destination / source.name)
            manifest.append({"source": str(source), "sha256": _sha256(source)})
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def _write_tombstones(target: Path, task_ids: tuple[str, ...]) -> None:
    if not task_ids:
        return
    tombstones = target / "ledgers" / "main" / "tombstones"
    tombstones.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    for task_id in task_ids:
        path = tombstones / f"{task_id}.toml"
        if path.exists():
            continue
        path.write_text(
            "schema_version = 1\n"
            'object_type = "task_id_tombstone"\n'
            f'id = "{task_id}"\n'
            'reason = "preserved-from-legacy-next-task-counter"\n'
            f'created_at = "{created_at}"\n',
            encoding="utf-8",
        )


def _write_target_state(target: Path, ref: str = "main") -> None:
    atomic_write_text(
        target / "state.toml",
        "schema_version = 2\n"
        f'ledger_ref = "{ref}"\n'
        'ledger_parent_ref = ""\n'
        'ledger_branch_guard = "off"\n',
    )


def _activate_manifest(
    root: Path,
    project_uuid: str,
    current_registration: Mapping[str, object] | None,
) -> None:
    if current_registration is not None:
        from taskledger.storage.ledger_manifest import upgrade_taskledger_registration

        upgrade_taskledger_registration(root, expected_project_uuid=project_uuid)
    else:
        ensure_taskledger_registration(
            root, project_uuid=project_uuid, project_name=root.name
        )


def apply_migration(
    inspection: TaskledgerMigrationInspection,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    retire_source: bool = False,
) -> dict[str, object]:
    if create_sibling_store:
        _ensure_migration_sibling_store(
            inspection.sibling_root,
            create=True,
        )
    fresh = inspect_migration(
        inspection.project_root,
        source_checkout=inspection.source_checkout_id,
        project_uuid=inspection.project_uuid,
        sibling_ledger_root=inspection.sibling_root,
    )
    if fresh.source_kind == "canonical-0.4-sibling":
        return {
            "kind": "migration_apply",
            "status": "up_to_date",
            "inspection": fresh.to_dict(),
        }
    issues = list(fresh.issues)
    if create_sibling_store and fresh.issues:
        fresh = inspect_migration(
            fresh.project_root,
            source_checkout=fresh.source_checkout_id,
            project_uuid=fresh.project_uuid,
            sibling_ledger_root=fresh.sibling_root,
        )
        issues = list(fresh.issues)
    if issues and any(issue.severity == "blocker" for issue in issues):
        raise LaunchError(
            "Migration preflight blocked:\n"
            + "\n".join(
                "- "
                + issue.code
                + ": "
                + issue.message
                + (
                    "\n  Remedy: " + "; ".join(issue.remediation)
                    if issue.remediation
                    else ""
                )
                for issue in issues
                if issue.severity == "blocker"
            )
        )
    backup_path = _backup(fresh, backup_dir)
    target = fresh.target_data_root
    staging = target.parent / (
        f".taskledger-migration-{fresh.project_uuid}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if target.exists() and read_project_binding(target) is not None:
        staging = target
    else:
        staging.mkdir(parents=True, exist_ok=False)
    create_project_binding(staging, project_uuid=fresh.project_uuid or "")
    for item in fresh.copy_items:
        if item.action == "skip-identical":
            continue
        if item.action == "conflict":
            raise LaunchError(f"Destination conflict: {item.destination}")
        destination = staging / item.destination.relative_to(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source, destination)
    for item in fresh.copy_items:
        destination = staging / item.destination.relative_to(target)
        if not destination.is_file() or _sha256(item.source) != _sha256(destination):
            raise LaunchError(
                f"Migration verification failed: {item.source} -> {destination}"
            )
    staging.mkdir(parents=True, exist_ok=True)
    _write_tombstones(staging, fresh.tombstones_required)
    _write_target_state(staging)
    write_yaml_object(
        staging / "storage.yaml",
        {
            "storage_layout_version": 5,
            "record_schema_version": 1,
            "created_with_taskledger": "migration",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_migrated_with_taskledger": "migration",
            "last_migrated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if staging != target:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(target)

    fixed_sibling_root = (fresh.project_root / ".." / "ledger").resolve(strict=False)
    if fresh.sibling_root != fixed_sibling_root:
        if retire_source:
            raise LaunchError(
                "--retire-source is not supported with a migration-only "
                "sibling destination override."
            )
        migration_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        receipt = target / "migrations" / f"{migration_timestamp}-migration-only.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "inspection": fresh.to_dict(),
                    "backup": str(backup_path),
                    "verified": True,
                    "canonical_activation": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "kind": "migration_apply",
            "status": "applied",
            "inspection": fresh.to_dict(),
            "backup": str(backup_path),
            "receipt": str(receipt),
            "retired": False,
            "canonical_activation": False,
            "warnings": [
                "Migration-only destination override was used; canonical "
                "project activation was not changed."
            ],
        }
    from taskledger.storage.ledger_local_config import (
        ensure_sibling_workspace_provider,
    )
    from taskledger.storage.project_config import render_canonical_taskledger_config

    config_path = fresh.project_root / ".ledger" / "task" / "config.toml"
    if not config_path.exists():
        atomic_write_text(config_path, render_canonical_taskledger_config())
    ensure_sibling_workspace_provider(fresh.project_root)
    _activate_manifest(
        fresh.project_root,
        fresh.project_uuid or "",
        fresh.current_registration,
    )
    context = load_project_context(fresh.project_root)
    from taskledger.storage.indexes import rebuild_v2_indexes
    from taskledger.storage.task_store import resolve_v2_paths

    rebuild_v2_indexes(resolve_v2_paths(fresh.project_root))
    receipt = (
        context.paths.data_root
        / "migrations"
        / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-ledgercore-0.4.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "inspection": fresh.to_dict(),
                "backup": str(backup_path),
                "verified": True,
                "retired": retire_source,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if (
        retire_source
        and fresh.source_data_root is not None
        and fresh.source_data_root.exists()
        and fresh.source_data_root != target
    ):
        fresh.source_data_root.rename(
            fresh.source_data_root.with_name(fresh.source_data_root.name + ".migrated")
        )
    return {
        "kind": "migration_apply",
        "status": "applied",
        "inspection": fresh.to_dict(),
        "backup": str(backup_path),
        "receipt": str(receipt),
        "retired": retire_source,
    }


def build_layout_migration_plan(
    start: Path,
    *,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> TaskledgerMigrationInspection:
    return inspect_migration(
        start,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    )


def apply_layout_migration(
    start: Path,
    *,
    backup: bool = True,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
    create_sibling_store: bool = False,
    dry_run: bool = False,
    retire_legacy: bool = False,
) -> dict[str, object]:
    inspection = inspect_migration(
        start,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    )
    if dry_run:
        return {
            "kind": "migration_inspection",
            "status": "dry_run",
            "inspection": inspection.to_dict(),
        }
    return apply_migration(
        inspection,
        backup=backup,
        create_sibling_store=create_sibling_store,
        retire_source=retire_legacy,
    )


def migration_status(
    start: Path,
    *,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> dict[str, object]:
    return inspect_migration(
        start,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
    ).to_dict()


__all__ = [
    "MigrationCopyItem",
    "MigrationIssue",
    "TaskledgerLayoutMigrationPlan",
    "TaskledgerMigrationInspection",
    "apply_layout_migration",
    "apply_migration",
    "build_layout_migration_plan",
    "inspect_migration",
    "migration_status",
]

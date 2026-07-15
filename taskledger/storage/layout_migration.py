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
from taskledger.storage.paths import ProjectPaths
from taskledger.storage.project_binding import (
    create_project_binding,
    read_project_binding,
)
from taskledger.storage.project_context import (
    CANONICAL_LEDGER_NAME,
    CANONICAL_MOUNT_SPECS,
    TaskledgerProjectContext,
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
    "canonical-0.3-namespaced",
    "canonical-0.4-sibling",
    "partial-sibling-migration",
    "invalid",
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
            },
            "counts": {"copy_items": len(self.copy_items)},
            "changes": [item.to_dict() for item in self.copy_items],
            "issues": [issue.to_dict() for issue in self.issues],
            "commands": {"apply": "taskledger migrate apply --backup"},
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


def _manifest_document(path: Path) -> dict[str, object]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Invalid Ledger manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"Invalid Ledger manifest {path}.")
    return value


def _target_registration() -> dict[str, object]:
    return {
        "config": {"location": "project", "path": "task/config.toml"},
        "mounts": {
            name: {
                "storage": storage,
                **({"scope": scope} if scope is not None else {}),
                "path": path,
            }
            for name, (storage, scope, path) in CANONICAL_MOUNT_SPECS.items()
        },
    }


def _target_roots(root: Path, sibling_ledger_root: Path | None) -> tuple[Path, Path]:
    sibling = (
        sibling_ledger_root.expanduser().resolve()
        if sibling_ledger_root is not None
        else root / ".ledger" / "migration-destination-required"
    )
    return sibling, sibling / ".ledger-store"


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
        "ledgers": {CANONICAL_LEDGER_NAME: _target_registration()},
    }
    manifest = parse_ledger_project_manifest(manifest_doc)
    local = parse_ledger_local_config(
        {"schema_version": 1},
        project_root=root,
    )
    return resolve_ledger_layout(
        _locator(root),
        manifest,
        CANONICAL_LEDGER_NAME,
        local_config=local,
        environ=environ,
    )


def _legacy_source(
    start: Path,
) -> tuple[TaskledgerProjectContext, ProjectPaths]:
    context = load_project_context(start, require_initialized=False, allow_legacy=True)
    if context.mode != "legacy" or context.legacy_locator is None:
        raise LaunchError("No legacy Taskledger project was found.")
    return context, context.legacy_locator


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


def inspect_migration(  # noqa: C901
    start: Path,
    *,
    source_checkout: str | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
) -> TaskledgerMigrationInspection:
    root = start.expanduser().resolve()
    if sibling_ledger_root is None:
        local_path = root / ".ledger" / "ledger.local.toml"
        if local_path.exists():
            local_doc = _manifest_document(local_path)
            local = parse_ledger_local_config(local_doc, project_root=root)
            sibling_ledger_root = local.workspace_root
    sibling_root, marker = _target_roots(root, sibling_ledger_root)
    target_data = sibling_root / "taskledger"
    target_indexes: Path | None = None
    target_registration = _target_registration()
    issues: list[MigrationIssue] = []
    source_kind: MigrationSourceKind = "uninitialized"
    source_data: Path | None = None
    source_logs: Path | None = None
    selected_uuid: str | None = None
    checkout_id: str | None = source_checkout
    current_registration: Mapping[str, object] | None = None

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
            source_kind = "canonical-0.3-namespaced"
            try:
                old_layout = _resolve_old_layout(root, manifest_doc, environ=environ)
                source_data = old_layout.mounts["data"].path
                source_logs = old_layout.mounts["logs"].path
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
    if selected_uuid is None and source_kind != "canonical-0.4-sibling":
        selected_uuid = str(uuid.uuid4())

    if sibling_ledger_root is None:
        issues.append(
            _issue(
                "blocker",
                "DESTINATION_REQUIRED",
                "Migration requires an explicit sibling Ledger destination root.",
                "Use --sibling-ledger-root PATH or configure storage.workspace.root.",
            )
        )
    elif sibling_root.exists() and not marker.exists():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_MARKER_MISSING",
                f"Sibling root exists without required marker {marker}.",
            )
        )
    elif not sibling_root.exists():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_ROOT_MISSING",
                f"Sibling root is missing: {sibling_root}",
                "Use --create-store when applying.",
            )
        )
    elif not marker.is_file():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_MARKER_INVALID",
                f"Sibling marker is not a regular file: {marker}.",
            )
        )

    try:
        if selected_uuid is not None:
            target_data = sibling_root / "taskledger" / selected_uuid
            target_layout = _resolve_target_layout(root, selected_uuid, environ)
            target_indexes = target_layout.mounts["indexes"].path
    except Exception as exc:
        target_indexes = None
        if source_kind != "canonical-0.4-sibling":
            issues.append(_issue("warning", "TARGET_UNRESOLVED", str(exc)))

    binding = read_project_binding(target_data) if target_data.exists() else None
    if (
        binding is not None
        and selected_uuid is not None
        and binding.project_uuid != selected_uuid
    ):
        issues.append(
            _issue(
                "blocker",
                "BINDING_UUID_MISMATCH",
                "Target binding belongs to "
                f"{binding.project_uuid}, expected {selected_uuid}.",
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

    items = _copy_items(source_data, source_logs, target_data)
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
    backup: bool,
    backup_dir: Path | None = None,
    create_store: bool = False,
    replace_workspace_selection: bool = False,
    counter_gap_policy: Literal["preserve", "reuse"] = "preserve",
    retire_source: bool = False,
) -> dict[str, object]:
    fresh = inspect_migration(
        inspection.project_root,
        source_checkout=inspection.source_checkout_id,
        project_uuid=inspection.project_uuid,
        sibling_ledger_root=(
            None
            if inspection.sibling_root.name == "migration-destination-required"
            else inspection.sibling_root
        ),
    )
    if fresh.source_kind == "canonical-0.4-sibling":
        return {
            "kind": "migration_apply",
            "status": "up_to_date",
            "inspection": fresh.to_dict(),
        }
    issues = list(fresh.issues)
    if create_store and not fresh.sibling_root.exists():
        fresh.sibling_root.mkdir(parents=True)
        fresh.sibling_marker.write_text("Ledgercore sibling store\n", encoding="utf-8")
        issues = [issue for issue in issues if issue.code != "SIBLING_ROOT_MISSING"]
    if (
        create_store
        and fresh.sibling_root.exists()
        and not fresh.sibling_marker.exists()
    ):
        if any(entry.name != "task" for entry in fresh.sibling_root.iterdir()):
            issues.append(
                _issue(
                    "blocker",
                    "SIBLING_ROOT_NOT_EMPTY",
                    "Refusing to create marker in non-empty root "
                    f"{fresh.sibling_root}.",
                )
            )
        else:
            fresh.sibling_marker.write_text(
                "Ledgercore sibling store\n", encoding="utf-8"
            )
            issues = [
                issue for issue in issues if issue.code == "SIBLING_MARKER_MISSING"
            ]
    if not backup:
        raise LaunchError("Migration apply requires --backup.")
    if issues and any(issue.severity == "blocker" for issue in issues):
        raise LaunchError(
            "Migration preflight blocked:\n"
            + "\n".join(
                f"- {issue.code}: {issue.message}"
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
    from taskledger.storage.init import _write_local_sibling_root
    from taskledger.storage.project_config import render_canonical_taskledger_config

    config_path = fresh.project_root / ".ledger" / "task" / "config.toml"
    if not config_path.exists():
        atomic_write_text(config_path, render_canonical_taskledger_config())
    _write_local_sibling_root(
        fresh.project_root,
        fresh.sibling_root,
        replace_workspace_selection=replace_workspace_selection,
    )
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
    backup: bool,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
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
    return apply_migration(inspection, backup=backup, retire_source=retire_legacy)


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

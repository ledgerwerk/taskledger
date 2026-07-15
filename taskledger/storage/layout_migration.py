"""Explicit legacy-to-Ledgercore layout migration planning and application."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ledgercore import (
    LedgerProjectLocator,
    ResolvedLedgerLayout,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)

from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.ledger_manifest import ensure_taskledger_registration
from taskledger.storage.project_config import (
    render_canonical_taskledger_config,
)
from taskledger.storage.project_context import (
    CANONICAL_CONFIG_VERSION,
    CANONICAL_LEDGER_NAME,
    CANONICAL_MOUNT_SPECS,
    load_project_context,
)
from taskledger.storage.yaml_store import write_yaml_object

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


@dataclass(frozen=True, slots=True)
class MigrationItem:
    source: Path
    destination: Path
    category: Literal["config", "data", "logs", "cache-skip", "legacy-backup"]
    verification: Literal["sha256", "record-set", "json-semantic", "rebuild"]
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "category": self.category,
            "verification": self.verification,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class TaskledgerLayoutMigrationPlan:
    project_root: Path
    project_uuid: str
    legacy_config_path: Path
    legacy_data_root: Path
    manifest_path: Path
    canonical_config_path: Path
    data_mount: Path
    logs_mount: Path
    indexes_mount: Path
    items: tuple[MigrationItem, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "project_uuid": self.project_uuid,
            "legacy_config_path": str(self.legacy_config_path),
            "legacy_data_root": str(self.legacy_data_root),
            "manifest_path": str(self.manifest_path),
            "canonical_config_path": str(self.canonical_config_path),
            "data_mount": str(self.data_mount),
            "logs_mount": str(self.logs_mount),
            "indexes_mount": str(self.indexes_mount),
            "items": [item.to_dict() for item in self.items],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def _uuid_candidates(root: Path, config_path: Path) -> tuple[str, ...]:
    values: list[str] = []
    candidates = [
        config_path,
        root / ".ledger.toml",
        root / "ledger.toml",
        root / ".taskledger.toml",
        root / "taskledger.toml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        value = raw.get("project_uuid") if isinstance(raw, dict) else None
        if not isinstance(value, str) and isinstance(raw, dict):
            project = raw.get("project")
            value = project.get("uuid") if isinstance(project, dict) else None
        if isinstance(value, str):
            try:
                values.append(str(uuid.UUID(value)))
            except ValueError:
                continue
    return tuple(dict.fromkeys(values))


def _selected_uuid(root: Path, config_path: Path, explicit: str | None) -> str:
    values = _uuid_candidates(root, config_path)
    if explicit is not None:
        try:
            selected = str(uuid.UUID(explicit))
        except ValueError as exc:
            raise LaunchError(f"Invalid migration project UUID {explicit!r}.") from exc
        if values and selected not in values:
            raise LaunchError(
                f"Explicit project UUID {selected} conflicts with legacy UUIDs: {', '.join(values)}"  # noqa: E501
            )
        return selected
    if len(values) > 1:
        raise LaunchError(
            "Distinct legacy project UUIDs found; rerun with --project-uuid. "
            + ", ".join(values)
        )
    return values[0] if values else str(uuid.uuid4())


def _target_layout(root: Path, project_uuid: str) -> ResolvedLedgerLayout:
    locator = LedgerProjectLocator(
        root,
        root / ".ledger",
        root / ".ledger" / "ledger.toml",
        root / ".ledger" / "ledger.local.toml",
        "canonical",
    )
    manifest = parse_ledger_project_manifest(
        {
            "schema_version": 2,
            "project": {"uuid": project_uuid, "name": root.name},
            "storage": {
                "workspace": {
                    "default_provider": "user-data",
                    "namespace": "ledgerwerk",
                },
                "cache": {"default_provider": "user-cache", "namespace": "ledgerwerk"},
            },
            "ledgers": {
                CANONICAL_LEDGER_NAME: {
                    "config": {"location": "project", "path": "task/config.toml"},
                    "mounts": {
                        name: {"storage": storage, "scope": scope, "path": path}
                        for name, (
                            storage,
                            scope,
                            path,
                        ) in CANONICAL_MOUNT_SPECS.items()
                    },
                }
            },
        }
    )
    return resolve_ledger_layout(locator, manifest, CANONICAL_LEDGER_NAME)


def build_layout_migration_plan(
    start: Path, *, project_uuid: str | None = None
) -> TaskledgerLayoutMigrationPlan:
    context = load_project_context(start, require_initialized=False, allow_legacy=True)
    if context.mode == "canonical":
        raise LaunchError("Project is already using the canonical Ledger layout.")
    legacy = context.legacy_locator
    if legacy is None:
        raise LaunchError("No legacy Taskledger project was found.")
    root = context.project_root
    selected_uuid = _selected_uuid(root, context.config_path, project_uuid)
    layout = _target_layout(root, selected_uuid)
    data_mount = layout.mounts["data"].path
    logs_mount = layout.mounts["logs"].path
    indexes_mount = layout.mounts["indexes"].path
    items: list[MigrationItem] = []
    blockers: list[str] = []
    warnings: list[str] = []
    for source in sorted(legacy.taskledger_dir.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(legacy.taskledger_dir)
        if rel.parts[:2] == ("items", "index.json") or rel.parts[:2] == (
            "memories",
            "index.json",
        ):
            blockers.append(f"Unsupported legacy index: {source}")
            continue
        if (
            rel.parts[:2] == ("ledgers", context.ledger_state.ref, "indexes")
            and rel.name != "repos.json"
        ):
            items.append(
                MigrationItem(
                    source,
                    indexes_mount / "ledgers" / context.ledger_state.ref / rel.name,
                    "cache-skip",
                    "rebuild",
                    False,
                )
            )
            continue
        if rel.parts[:3] == ("ledgers", context.ledger_state.ref, "events"):
            destination = (
                logs_mount / "ledgers" / context.ledger_state.ref / Path(*rel.parts[3:])
            )
            items.append(MigrationItem(source, destination, "logs", "sha256"))
        elif rel.parts[:3] == ("ledgers", context.ledger_state.ref, "agent-logs"):
            destination = (
                logs_mount / "ledgers" / context.ledger_state.ref / Path(*rel.parts[3:])
            )
            items.append(MigrationItem(source, destination, "logs", "sha256"))
        elif rel.parts[:2] == ("migrations",):
            items.append(
                MigrationItem(
                    source,
                    logs_mount / "migrations" / "legacy" / Path(*rel.parts[1:]),
                    "logs",
                    "sha256",
                )
            )
        elif rel.parts[-2:] == ("indexes", "repos.json"):
            items.append(
                MigrationItem(
                    source,
                    data_mount / "ledgers" / context.ledger_state.ref / "repos.json",
                    "data",
                    "json-semantic",
                )
            )
        else:
            items.append(MigrationItem(source, data_mount / rel, "data", "sha256"))
    if not items:
        blockers.append(
            f"Legacy data root is empty or missing: {legacy.taskledger_dir}"
        )
    if any(
        item.destination.exists() and item.destination != item.source for item in items
    ):
        warnings.append(
            "Existing canonical destination files will be compared before replacement."
        )
    return TaskledgerLayoutMigrationPlan(
        root,
        selected_uuid,
        context.config_path,
        legacy.taskledger_dir,
        root / ".ledger" / "ledger.toml",
        root / ".ledger" / "task" / "config.toml",
        data_mount,
        logs_mount,
        indexes_mount,
        tuple(items),
        tuple(dict.fromkeys(blockers)),
        tuple(warnings),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup(plan: TaskledgerLayoutMigrationPlan) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = (
        plan.legacy_data_root.parent
        / f"{plan.legacy_data_root.name}.pre-ledger-layout-{timestamp}"
    )
    shutil.copytree(plan.legacy_data_root, backup)
    if (
        plan.legacy_config_path.exists()
        and plan.legacy_config_path.parent == plan.project_root
    ):
        shutil.copy2(plan.legacy_config_path, backup / plan.legacy_config_path.name)
    (backup / "migration-plan.json").write_text(
        json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return backup


def apply_layout_migration(
    start: Path,
    *,
    backup: bool,
    project_uuid: str | None = None,
    dry_run: bool = False,
    retire_legacy: bool = False,
) -> dict[str, object]:
    existing = load_project_context(start, require_initialized=False, allow_legacy=True)
    if existing.mode == "canonical":
        return {
            "kind": "migration_apply",
            "status": "up_to_date",
            "plan": None,
            "backup": None,
            "retired": False,
        }
    if not backup and not dry_run:
        raise LaunchError("Legacy layout migration requires --backup.")
    plan = build_layout_migration_plan(start, project_uuid=project_uuid)
    if plan.blockers:
        raise LaunchError(
            "Migration preflight blocked:\n"
            + "\n".join(f"- {item}" for item in plan.blockers)
        )
    if dry_run:
        return {
            "kind": "migration_plan",
            "status": "dry_run",
            "plan": plan.to_dict(),
            "backup": None,
        }
    backup_path = _backup(plan)
    registration = ensure_taskledger_registration(
        plan.project_root,
        project_uuid=plan.project_uuid,
        project_name=plan.project_root.name,
    )
    plan.canonical_config_path.parent.mkdir(parents=True, exist_ok=True)
    if not plan.canonical_config_path.exists():
        atomic_write_text(
            plan.canonical_config_path, render_canonical_taskledger_config()
        )
    context = load_project_context(
        plan.project_root, require_initialized=False, allow_legacy=False
    )
    paths = context.paths
    for item in plan.items:
        if item.category == "cache-skip":
            continue
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        if item.destination.exists() and _sha256(item.source) == _sha256(
            item.destination
        ):
            continue
        shutil.copy2(item.source, item.destination)
    paths.data_root.mkdir(parents=True, exist_ok=True)
    write_yaml_object(
        paths.storage_meta_path,
        {
            "storage_layout_version": 4,
            "record_schema_version": 1,
            "created_with_taskledger": "migration",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_migrated_with_taskledger": "migration",
            "last_migrated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    atomic_write_text(
        paths.state_path,
        "schema_version = 1\n"
        f"ledger_ref = {context.ledger_state.ref!r}\n"
        f"ledger_parent_ref = {(context.ledger_state.parent_ref or '')!r}\n"
        f"ledger_next_task_number = {context.ledger_state.next_task_number}\n"
        f"ledger_branch_guard = {context.ledger_state.branch_guard!r}\n",
    )
    from taskledger.storage.indexes import rebuild_v2_indexes
    from taskledger.storage.task_store import resolve_v2_paths

    rebuild_v2_indexes(resolve_v2_paths(plan.project_root))
    # Verify every copied file before making the old layout inactive.
    for item in plan.items:
        if item.category == "cache-skip" or item.source.name == "storage.yaml":
            continue
        if _sha256(item.source) != _sha256(item.destination):
            raise LaunchError(
                f"Migration verification failed for {item.source} -> {item.destination}"
            )
    if retire_legacy:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        plan.legacy_data_root.rename(
            plan.legacy_data_root.with_name(
                plan.legacy_data_root.name + f".migrated-{timestamp}"
            )
        )
        if (
            plan.legacy_config_path.exists()
            and plan.legacy_config_path.parent == plan.project_root
        ):
            plan.legacy_config_path.rename(
                plan.legacy_config_path.with_name(
                    plan.legacy_config_path.name + f".migrated-{timestamp}"
                )
            )
    paths.logs_root.mkdir(parents=True, exist_ok=True)
    receipt = (
        paths.logs_root
        / "migrations"
        / f"legacy-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "plan": plan.to_dict(),
                "backup": str(backup_path),
                "registration": registration.to_dict(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "kind": "migration_apply",
        "status": "applied",
        "plan": plan.to_dict(),
        "backup": str(backup_path),
        "receipt": str(receipt),
        "retired": retire_legacy,
    }


def migration_status(
    start: Path, *, project_uuid: str | None = None
) -> dict[str, object]:
    try:
        context = load_project_context(
            start, require_initialized=False, allow_legacy=True
        )
    except LaunchError as exc:
        return {
            "kind": "migration_status",
            "project_layout_status": "invalid",
            "message": str(exc),
        }
    if context.mode == "canonical":
        return {
            "kind": "migration_status",
            "project_mode": "canonical",
            "project_layout_status": "ready",
            "canonical_manifest_path": str(
                context.layout.manifest_path if context.layout else ""
            ),
            "current_config_version": 3,
            "target_config_version": CANONICAL_CONFIG_VERSION,
            "current_storage_layout_version": 4,
            "target_storage_layout_version": 4,
            "pending_record_migrations": 0,
        }
    plan = build_layout_migration_plan(start, project_uuid=project_uuid)
    return {
        "kind": "migration_status",
        "project_mode": "legacy",
        "project_layout_status": "migration_needed",
        "legacy_config_path": str(plan.legacy_config_path),
        "legacy_data_root": str(plan.legacy_data_root),
        "canonical_manifest_path": str(plan.manifest_path),
        "current_config_version": 2,
        "target_config_version": 3,
        "current_storage_layout_version": 3,
        "target_storage_layout_version": 4,
        "pending_record_migrations": len(plan.items),
        "blockers": list(plan.blockers),
    }

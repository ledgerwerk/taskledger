"""Read-only inspection and safe application of Taskledger storage migration."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from ledgercore import StorageBinding, StorageMigrationItem, StorageMigrationPlan
from ledgercore.manifest import parse_ledger_manifest_v3

from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.ledger_manifest import ensure_taskledger_registration
from taskledger.storage.ledgercore_backend import (
    LedgerProjectLocator,
    ResolvedLedgerLayout,
    build_taskledger_manifest_with_registration,
    execute_taskledger_layout_migration,
    initialize_config_binding,
    initialize_taskledger_bindings,
    load_taskledger_ledger_layout,
    parse_ledger_local_config,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)
from taskledger.storage.paths import ProjectPaths, find_project_config
from taskledger.storage.project_binding import (
    read_project_binding,
)
from taskledger.storage.project_context import (
    CANONICAL_LEDGER_NAME,
    DATA_MOUNT,
    INDEX_MOUNT,
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
    "legacy-config-external",
    "legacy-uuid-sibling",
    "explicit-source",
]


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    severity: Literal["blocker", "warning", "info"]
    code: str
    message: str
    remediation: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "remediation": list(self.remediation),
            "details": dict(self.details),
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
    canonical_project_uuid: str | None = None
    legacy_project_uuid: str | None = None
    identity_transition: str = "none"
    source_selection_reason: str | None = None
    source_candidates: tuple[Mapping[str, object], ...] = ()
    target_classification: str = "ABSENT"
    would_create_sibling_store: bool = False
    request_source_data_root: Path | None = None
    request_sibling_ledger_root: Path | None = None
    request_create_sibling_store: bool = False
    request_adopt_sibling_store: bool = False

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

    def _build_commands(self) -> dict[str, object]:
        """Build the apply command with all non-default options."""
        import shlex

        argv: list[str] = ["taskledger"]
        if self.project_root:
            argv.extend(["--root", str(self.project_root)])
        argv.extend(["migrate", "apply"])
        if self.request_sibling_ledger_root is not None:
            argv.extend(
                [
                    "--sibling-ledger-root",
                    str(self.request_sibling_ledger_root),
                ]
            )
        elif self.sibling_root:
            argv.extend(["--sibling-ledger-root", str(self.sibling_root)])
        if self.request_source_data_root is not None:
            argv.extend(["--source-data-root", str(self.request_source_data_root)])
        if self.project_uuid:
            argv.extend(["--project-uuid", self.project_uuid])
        if self.source_checkout_id:
            argv.extend(["--source-checkout-id", self.source_checkout_id])
        if self.request_create_sibling_store:
            argv.append("--create-sibling-store")
        if self.request_adopt_sibling_store:
            argv.append("--adopt-sibling-store")
        shell_cmd = shlex.join(argv)
        return {
            "apply": {
                "argv": argv,
                "shell": shell_cmd,
            }
        }

    def to_dict(self) -> dict[str, object]:
        blockers = [
            issue.to_dict() for issue in self.issues if issue.severity == "blocker"
        ]
        warnings = [
            issue.to_dict() for issue in self.issues if issue.severity == "warning"
        ]
        status = (
            "blocked"
            if blockers
            else "migration_needed"
            if self.migration_required
            else "up_to_date"
        )
        return {
            "kind": "taskledger_migration_inspection",
            "schema_version": 2,
            "status": status,
            "ready": self.ready,
            "migration_required": self.migration_required,
            "would_create_sibling_store": self.would_create_sibling_store,
            "project": {
                "root": str(self.project_root),
                "uuid": self.project_uuid,
                "canonical_uuid": self.canonical_project_uuid or self.project_uuid,
                "legacy_uuid": self.legacy_project_uuid,
                "identity_transition": self.identity_transition,
            },
            "source": {
                "kind": self.source_kind,
                "data": str(self.source_data_root) if self.source_data_root else None,
                "logs": str(self.source_logs_root) if self.source_logs_root else None,
                "checkout_id": self.source_checkout_id,
                "selected_reason": self.source_selection_reason,
                "fingerprint": _tree_fingerprint(self.source_data_root),
                "candidates": [dict(candidate) for candidate in self.source_candidates],
            },
            "target": {
                "sibling_root": str(self.sibling_root),
                "marker": str(self.sibling_marker),
                "data": str(self.target_data_root),
                "indexes": str(self.target_indexes_root)
                if self.target_indexes_root
                else None,
                "binding": str(self.binding_path),
                "registration": "present"
                if self.current_registration is not None
                else "missing; will be added",
                "classification": self.target_classification,
                "fingerprint": _tree_fingerprint(self.target_data_root),
                "authoritative_files": len(_authoritative_files(self.target_data_root)),
            },
            "task_ids": {
                "legacy_next_task_number": self.legacy_next_task_number,
                "derived_next_task_id": self.derived_next_task_id,
                "tombstones_required": list(self.tombstones_required),
            },
            "counts": {
                "copy_items": len(self.copy_items),
                "source_files": _file_count(self.source_data_root),
                "source_tasks": _task_count(self.source_data_root),
            },
            "changes": [item.to_dict() for item in self.copy_items],
            "issues": [issue.to_dict() for issue in self.issues],
            "blockers": blockers,
            "warnings": warnings,
            "commands": self._build_commands() if self.ready else {},
        }


# Compatibility name retained for callers during the transition release.
TaskledgerLayoutMigrationPlan = TaskledgerMigrationInspection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_TARGET_METADATA_NAMES = {".ledger-project.toml", "state.toml", "storage.yaml"}


def _authoritative_files(root: Path | None) -> tuple[Path, ...]:
    if root is None or not root.is_dir():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name not in _TARGET_METADATA_NAMES
        and "indexes" not in path.relative_to(root).parts
        and "migrations" not in path.relative_to(root).parts
    )


def _file_count(root: Path | None) -> int:
    if root is None or not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


def _task_count(root: Path | None) -> int:
    if root is None:
        return 0
    return sum(
        1
        for path in _authoritative_files(root)
        if "tasks" in path.relative_to(root).parts
    )


def _tree_fingerprint(root: Path | None) -> str | None:
    if root is None:
        return None
    files = _authoritative_files(root)
    if not files:
        return None
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _task_fingerprints(root: Path | None) -> dict[str, str]:
    if root is None:
        return {}
    result: dict[str, str] = {}
    for path in _authoritative_files(root):
        relative = path.relative_to(root)
        if "tasks" not in relative.parts:
            continue
        task_id = path.stem if path.suffix else path.name
        result[task_id] = _sha256(path)
    return result


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
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaunchError(f"Invalid Ledger manifest {path}: {exc}") from exc
    value: object | None = None
    try:
        value = tomllib.loads(text)
    except ValueError as exc:
        # Older Windows config writers and hand-authored legacy configs often
        # put a native path in a TOML basic string without escaping ``\\``.
        # Recover that narrow case without making arbitrary malformed TOML
        # acceptable.
        if path.name in {".taskledger.toml", "taskledger.toml"}:
            repaired = re.sub(
                r'(?m)^(\s*taskledger_dir\s*=\s*")([^"\r\n]*)(".*)$',
                lambda match: (
                    f"{match.group(1)}{match.group(2).replace(chr(92), '/')}"
                    f"{match.group(3)}"
                ),
                text,
            )
            if repaired != text:
                try:
                    value = tomllib.loads(repaired)
                except (OSError, ValueError):
                    value = None
        if value is None:
            raise LaunchError(f"Invalid Ledger manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"Invalid Ledger manifest {path}.")
    return value


def _target_registration(project_uuid: str | None = None) -> dict[str, object]:
    # Schema-3 mounts: data is external (sibling-ledger), indexes are cache.
    return {
        "mounts": {
            DATA_MOUNT: {"storage": "external", "root": "../ledger"},
            INDEX_MOUNT: {"storage": "cache"},
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
    adopt: bool = False,
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
        if not create and not adopt:
            raise LaunchError(
                f"TASKLEDGER_SIBLING_ROOT_UNMARKED: {sibling_root}. "
                "Use --create-sibling-store or --adopt-sibling-store to initialize it."
            )
        if adopt:
            # Adoption allows non-empty legacy roots
            if not _is_legacy_sibling_root(sibling_root):
                raise LaunchError(
                    "Refusing to adopt non-legacy unmarked sibling root "
                    f"{sibling_root}. Only roots with recognized legacy "
                    "Taskledger data can be adopted."
                )
        elif any(sibling_root.iterdir()):
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
        "schema_version": 3,
        "project": {"uuid": project_uuid, "name": root.name},
        "ledgers": {CANONICAL_LEDGER_NAME: _target_registration(project_uuid)},
    }
    manifest = parse_ledger_project_manifest(manifest_doc)
    effective = dict(environ or {})
    effective.pop("LEDGER_WORKSPACE_ROOT", None)
    return resolve_ledger_layout(
        _locator(root),
        manifest,
        CANONICAL_LEDGER_NAME,
        local_config=None,
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
    sources_by_destination: dict[Path, Path] = {}
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
            if destination in sources_by_destination:
                action = "conflict"
            elif destination.exists():
                action = (
                    "skip-identical"
                    if relative in {Path("storage.yaml"), Path("state.toml")}
                    or _sha256(source) == _sha256(destination)
                    else "conflict"
                )
            else:
                action = "copy"
            sources_by_destination[destination] = source
            items.append(MigrationCopyItem(source, destination, category, action))
    return items


def _issue(
    severity: Literal["blocker", "warning", "info"],
    code: str,
    message: str,
    *remediation: str,
    details: Mapping[str, object] | None = None,
) -> MigrationIssue:
    return MigrationIssue(severity, code, message, tuple(remediation), details or {})


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
    uuid_path = f"taskledger/{project_uuid}" if project_uuid is not None else None
    return (
        data.get("storage") == "workspace"
        and data.get("scope") == "project"
        and data_path in {"task/taskledger", "taskledger", old_uuid_path, uuid_path}
        and indexes.get("storage") == "cache"
        and indexes.get("scope") == "checkout"
        and indexes.get("path")
        in {
            "task/taskledger-indexes",
            "taskledger-indexes",
        }
    )


def _is_legacy_sibling_root(path: Path) -> bool:
    """Check if a directory contains recognizable legacy Taskledger data."""
    if not path.is_dir():
        return False
    # Check for common legacy patterns:
    # - task/ subdirectory with content
    # - storage.yaml files
    # - ledgers/ directory
    task_dir = path / "task"
    if task_dir.is_dir() and any(task_dir.iterdir()):
        return True
    if (path / "storage.yaml").is_file():
        return True
    ledgers_dir = path / "ledgers"
    if ledgers_dir.is_dir() and any(ledgers_dir.iterdir()):
        return True
    # Check for any directory containing storage.yaml
    for child in path.iterdir():
        if child.is_dir() and (child / "storage.yaml").is_file():
            return True
    return False


def _inspect_migration_phases(  # noqa: C901
    start: Path,
    *,
    source_checkout: str | None = None,
    source_checkout_id: str | None = None,
    source_data_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
    create_sibling_store: bool = False,
    adopt_sibling_store: bool = False,
) -> TaskledgerMigrationInspection:
    root = start.expanduser().resolve()
    sibling_root, marker = _target_roots(root, sibling_ledger_root)
    issues: list[MigrationIssue] = []
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
    checkout_id = source_checkout_id or source_checkout
    if checkout_id is not None and ("/" in checkout_id or "\\\\" in checkout_id):
        raise LaunchError(
            "--source-checkout-id accepts a checkout identifier, not a path.",
            code="EXPLICIT_SOURCE_INVALID",
        )
    manifest_path = root / ".ledger" / "ledger.toml"
    canonical_uuid: str | None = None
    legacy_uuid: str | None = None
    current_registration: Mapping[str, object] | None = None
    manifest_doc: dict[str, object] = {}
    if manifest_path.is_file():
        try:
            manifest_doc = _manifest_document(manifest_path)
            project = manifest_doc.get("project")
            if isinstance(project, Mapping) and isinstance(project.get("uuid"), str):
                canonical_uuid = str(uuid.UUID(project["uuid"]))
            current_registration = _old_registration(manifest_doc)
        except (LaunchError, ValueError) as exc:
            issues.append(
                _issue(
                    "blocker",
                    "CANONICAL_MANIFEST_INVALID",
                    f"Cannot read canonical Ledger manifest {manifest_path}: {exc}",
                    "Repair the canonical manifest before migrating.",
                    details={"path": str(manifest_path)},
                )
            )
    legacy_configs: list[tuple[Path, dict[str, object]]] = []
    for config_path in (root / ".taskledger.toml", root / "taskledger.toml"):
        if not config_path.is_file():
            continue
        try:
            config_doc = _manifest_document(config_path)
        except LaunchError as exc:
            issues.append(_issue("blocker", "LEGACY_CONFIG_INVALID", str(exc)))
            continue
        legacy_configs.append((config_path, config_doc))
        raw_uuid = config_doc.get("project_uuid")
        if legacy_uuid is None and isinstance(raw_uuid, str):
            try:
                legacy_uuid = str(uuid.UUID(raw_uuid))
            except ValueError:
                issues.append(
                    _issue(
                        "blocker",
                        "LEGACY_UUID_INVALID",
                        f"Legacy Taskledger config has an invalid UUID: {config_path}",
                        details={"path": str(config_path)},
                    )
                )
    selected_uuid = canonical_uuid or legacy_uuid
    identity_transition = "none"
    if (
        canonical_uuid is not None
        and legacy_uuid is not None
        and canonical_uuid != legacy_uuid
    ):
        identity_transition = "adopt-canonical"
    elif canonical_uuid is None and legacy_uuid is not None:
        identity_transition = "legacy-only"
    if project_uuid is not None:
        try:
            requested_uuid = str(uuid.UUID(project_uuid))
        except ValueError as exc:
            raise LaunchError(
                f"Invalid migration project UUID {project_uuid!r}.",
                code="EXPLICIT_PROJECT_UUID_CONFLICT",
            ) from exc
        if canonical_uuid is not None and requested_uuid != canonical_uuid:
            issues.append(
                _issue(
                    "blocker",
                    "EXPLICIT_PROJECT_UUID_CONFLICT",
                    "Requested migration UUID differs from the canonical project UUID.",
                    "Use the canonical UUID or repair the manifest explicitly.",
                    details={
                        "canonical_uuid": canonical_uuid,
                        "requested_uuid": requested_uuid,
                    },
                )
            )
        selected_uuid = requested_uuid
        identity_transition = "explicit"
    if selected_uuid is None:
        issues.append(
            _issue(
                "blocker",
                "PROJECT_UUID_MISSING",
                "Legacy Taskledger config has no stable project UUID.",
                "Run `taskledger repair project-identity --apply`.",
                details={
                    "config_paths": [str(path) for path, _ in legacy_configs],
                },
            )
        )
        target_data = sibling_root / "taskledger" / "unresolved" / "data"
        target_indexes = sibling_root / "taskledger" / "unresolved" / "indexes"
        target_registration = _target_registration(None)
    else:
        target_data = sibling_root / "taskledger" / selected_uuid / "data"
        target_indexes = sibling_root / "taskledger" / selected_uuid / "indexes"
        target_registration = _target_registration(selected_uuid)
    if not sibling_root.exists() and create_sibling_store:
        issues.append(
            _issue(
                "info",
                "SIBLING_ROOT_WILL_BE_CREATED",
                f"Sibling root will be created during apply: {sibling_root}",
                "Use --dry-run to inspect without creating it.",
                details={"path": str(sibling_root)},
            )
        )
    elif not sibling_root.exists():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_ROOT_MISSING",
                f"Sibling root is missing: {sibling_root}",
                "Use --create-sibling-store when applying.",
                details={"path": str(sibling_root)},
            )
        )
    elif sibling_root.is_symlink() or not sibling_root.is_dir():
        issues.append(
            _issue(
                "blocker",
                "SIBLING_ROOT_INVALID",
                f"Sibling root is not a regular directory: {sibling_root}",
                details={"path": str(sibling_root)},
            )
        )
    elif not marker.is_file():
        # Check if this is a recognizable legacy sibling root
        is_legacy_adoptable = _is_legacy_sibling_root(sibling_root)
        if is_legacy_adoptable and adopt_sibling_store:
            issues.append(
                _issue(
                    "info",
                    "SIBLING_ROOT_LEGACY_ADOPTABLE",
                    f"Sibling root has legacy data: {sibling_root}",
                    "Marker will be created during apply.",
                    details={"path": str(sibling_root)},
                )
            )
        elif is_legacy_adoptable:
            issues.append(
                _issue(
                    "blocker",
                    "SIBLING_ROOT_LEGACY_ADOPTABLE",
                    f"Sibling root contains legacy data without marker: {sibling_root}",
                    "Use --adopt-sibling-store when applying.",
                    details={"path": str(sibling_root)},
                )
            )
        else:
            issues.append(
                _issue(
                    "blocker",
                    "SIBLING_ROOT_UNMARKED",
                    f"Sibling root exists without required marker {marker}.",
                    "Use --create-sibling-store when applying.",
                    details={"path": str(marker)},
                )
            )
    candidates: list[dict[str, object]] = []
    candidate_paths: set[Path] = set()
    candidate_priority: dict[Path, int] = {}

    def add_candidate(
        kind: str,
        path: Path,
        reason: str,
        candidate_uuid: str | None = None,
        priority: int = 50,
    ) -> None:
        resolved = path.expanduser().resolve(strict=False)
        if (
            resolved == target_data
            or target_data.is_relative_to(resolved)
            or resolved in candidate_paths
        ):
            return
        candidate_paths.add(resolved)
        candidate_priority[resolved] = priority
        exists = resolved.is_dir()
        candidates.append(
            {
                "kind": kind,
                "path": str(resolved),
                "exists": exists,
                "project_uuid": candidate_uuid,
                "binding_status": "unknown",
                "storage_status": "present" if exists else "missing",
                "task_count": _task_count(resolved) if exists else 0,
                "file_count": _file_count(resolved) if exists else 0,
                "fingerprint": _tree_fingerprint(resolved) if exists else None,
                "reason": reason,
                "selected_reason": None,
            }
        )

    if source_data_root is not None:
        add_candidate(
            "explicit-source",
            source_data_root,
            "explicit source-data-root",
            legacy_uuid,
            0,
        )
        if not source_data_root.expanduser().resolve(strict=False).is_dir():
            issues.append(
                _issue(
                    "blocker",
                    "EXPLICIT_SOURCE_INVALID",
                    "Explicit source data root is missing or invalid: "
                    f"{source_data_root}",
                    "Pass an existing Taskledger data root to --source-data-root.",
                    details={"path": str(source_data_root)},
                )
            )
    for config_path, config_doc in legacy_configs:
        raw_path = config_doc.get("taskledger_dir")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        configured = Path(os.path.expandvars(raw_path)).expanduser()
        if not configured.is_absolute():
            configured = config_path.parent / configured
        configured = configured.resolve(strict=False)
        add_candidate(
            "legacy-arbitrary-external"
            if not configured.is_relative_to(root)
            else "legacy-config-external",
            configured,
            "configured legacy source",
            legacy_uuid,
            10,
        )
        if not configured.is_dir():
            issues.append(
                _issue(
                    "warning",
                    "LEGACY_CONFIG_PATH_STALE",
                    f"{config_path} points to missing legacy data: {configured}",
                    "The migration will use a unique UUID-bound source if one exists.",
                    details={"config_path": str(config_path), "path": str(configured)},
                )
            )
    add_candidate(
        "legacy-local", root / ".taskledger", "legacy local storage", legacy_uuid, 30
    )
    if legacy_uuid is not None:
        uuid_data = sibling_root / "taskledger" / legacy_uuid / "data"
        add_candidate(
            "legacy-uuid-sibling",
            uuid_data,
            "legacy UUID sibling store",
            legacy_uuid,
            20,
        )
        if not uuid_data.is_dir():
            add_candidate(
                "legacy-uuid-sibling",
                sibling_root / "taskledger" / legacy_uuid,
                "legacy UUID sibling store",
                legacy_uuid,
                21,
            )
    add_candidate(
        "direct-sibling-old-schema",
        sibling_root / "task" / "taskledger",
        "direct sibling old-schema path",
        legacy_uuid,
        40,
    )
    viable = [
        candidate
        for candidate in candidates
        if candidate["exists"] is True
        and isinstance(candidate["file_count"], int)
        and candidate["file_count"] > 0
    ]
    viable.sort(
        key=lambda candidate: (
            int(candidate_priority[Path(str(candidate["path"]))]),
            str(candidate["path"]),
        )
    )
    selected: dict[str, object] | None = viable[0] if viable else None
    if len(viable) > 1:
        fingerprints = {candidate["fingerprint"] for candidate in viable}
        if len(fingerprints) > 1:
            if source_data_root is not None:
                # Explicit source overrides ambiguity
                issues.append(
                    _issue(
                        "info",
                        "EXPLICIT_SOURCE_OVERRIDES_OTHER_CANDIDATES",
                        "Explicit source-data-root overrides other candidates.",
                        "Other candidates remain visible but are not selected.",
                        details={
                            "selected": str(source_data_root),
                            "candidate_count": len(viable),
                        },
                    )
                )
            else:
                issues.append(
                    _issue(
                        "blocker",
                        "MIGRATION_SOURCE_AMBIGUOUS",
                        "Multiple non-identical source candidates found.",
                        "Use --source-data-root to select one source after ",
                        "inspecting all candidates.",
                        details={"candidates": viable},
                    )
                )
    if selected is not None:
        selected["selected_reason"] = selected["reason"]
    source_data = Path(str(selected["path"])) if selected is not None else None
    source_kind = cast(
        MigrationSourceKind,
        str(selected["kind"]) if selected is not None else "uninitialized",
    )
    source_reason = str(selected["reason"]) if selected is not None else None
    if selected is None and current_registration is None:
        issues.append(
            _issue(
                "blocker",
                "MIGRATION_SOURCE_NOT_FOUND",
                "No legacy Taskledger source data was found.",
                "Pass --source-data-root or restore the legacy source "
                "before migrating.",
                details={"candidates": candidates},
            )
        )
    elif selected is not None and selected["kind"] == "legacy-uuid-sibling":
        for candidate in candidates:
            if (
                candidate["kind"] == "legacy-config-external"
                and not candidate["exists"]
            ):
                break
        else:
            issues.append(
                _issue(
                    "info",
                    "LEGACY_UUID_ADOPTED",
                    "The canonical project UUID will replace the legacy storage UUID.",
                    details={
                        "canonical_uuid": canonical_uuid,
                        "legacy_uuid": legacy_uuid,
                    },
                )
            )
    if (
        canonical_uuid is not None
        and legacy_uuid is not None
        and canonical_uuid != legacy_uuid
    ):
        issues.append(
            _issue(
                "info",
                "LEGACY_UUID_ADOPTED",
                f"Legacy UUID {legacy_uuid} identifies the source; canonical "
                f"UUID {canonical_uuid} remains authoritative.",
                details={"canonical_uuid": canonical_uuid, "legacy_uuid": legacy_uuid},
            )
        )
    if current_registration is None and source_data is not None:
        issues.append(
            _issue(
                "info",
                "TASKLEDGER_REGISTRATION_MISSING",
                "Taskledger is not registered in the canonical manifest; "
                "apply will add it.",
                "Do not add the registration manually; let migration apply it "
                "after verification.",
                details={"manifest": str(manifest_path)},
            )
        )
    if current_registration is not None and current_registration != target_registration:
        issues.append(
            _issue(
                "warning",
                "TASKLEDGER_REGISTRATION_WILL_BE_REPLACED",
                "The existing Taskledger registration will be replaced with "
                "the canonical registration.",
                details={"manifest": str(manifest_path)},
            )
        )
    target_classification = "ABSENT"
    target_binding = None
    if target_data.exists() and not target_data.is_dir():
        target_classification = "INVALID"
        issues.append(
            _issue(
                "blocker",
                "TARGET_DATA_INVALID",
                f"Target data root is not a directory: {target_data}",
                details={"path": str(target_data)},
            )
        )
    elif target_data.is_dir():
        try:
            target_binding = read_project_binding(target_data)
        except LaunchError as exc:
            target_classification = "INVALID"
            issues.append(
                _issue(
                    "blocker",
                    "TARGET_DATA_BINDING_INVALID",
                    str(exc),
                    "Back up the target before repairing its binding.",
                    details={"path": str(target_data)},
                )
            )
        authoritative = _authoritative_files(target_data)
        if target_binding is not None and (
            target_binding.project_uuid != selected_uuid
            or target_binding.ledger != "taskledger"
            or target_binding.mount != "data"
        ):
            target_classification = "FOREIGN_BOUND"
            details = {
                "path": str(target_data),
                "actual_uuid": target_binding.project_uuid,
                "expected_uuid": selected_uuid,
            }
            issues.append(
                _issue(
                    "blocker",
                    "BINDING_UUID_MISMATCH",
                    f"Target binding belongs to {target_binding.project_uuid}; "
                    f"expected {selected_uuid}.",
                    "Use a separate destination or resolve the foreign binding "
                    "explicitly.",
                    details=details,
                )
            )
            issues.append(
                _issue(
                    "blocker",
                    "FOREIGN_TARGET",
                    "The target is bound to a different project or mount.",
                    "Use a separate destination or resolve the foreign binding "
                    "explicitly.",
                    details=details,
                )
            )
        elif (
            source_data is not None
            and target_binding is not None
            and _task_count(source_data) == 0
            and _task_count(target_data) == 0
        ):
            target_classification = "IDENTICAL_SOURCE"
        elif (
            source_data is None
            and target_binding is not None
            and target_binding.project_uuid == selected_uuid
            and target_binding.ledger == "taskledger"
            and target_binding.mount == "data"
            and (target_data / "state.toml").is_file()
            and (target_data / "storage.yaml").is_file()
        ):
            source_kind = "canonical-0.4-sibling"
            target_classification = "COMPLETE_CANONICAL"
        elif authoritative:
            source_tasks = _task_fingerprints(source_data)
            target_tasks = _task_fingerprints(target_data)
            conflicts = sorted(
                task_id
                for task_id in set(source_tasks) & set(target_tasks)
                if source_tasks[task_id] != target_tasks[task_id]
            )
            if conflicts:
                target_classification = "AUTHORITATIVE_DATA_CONFLICT"
                issues.append(
                    _issue(
                        "blocker",
                        "SOURCE_TARGET_SPLIT_BRAIN",
                        "Source and target contain different authoritative "
                        "Taskledger records.",
                        "Back up both datasets and reconcile the conflicting "
                        "records before applying.",
                        details={
                            "conflicting_task_ids": conflicts,
                            "source": str(source_data) if source_data else None,
                            "target": str(target_data),
                        },
                    )
                )
            elif source_data is not None and _tree_fingerprint(
                source_data
            ) == _tree_fingerprint(target_data):
                target_classification = "IDENTICAL_SOURCE"
            else:
                target_classification = "AUTHORITATIVE_DATA_CONFLICT"
                issues.append(
                    _issue(
                        "blocker",
                        "TARGET_AUTHORITATIVE_DATA_PRESENT",
                        "The target contains authoritative Taskledger data that "
                        "is not identical to the source.",
                        "Reconcile the datasets explicitly; migration does not "
                        "merge task trees.",
                        details={
                            "path": str(target_data),
                            "authoritative_files": len(authoritative),
                        },
                    )
                )
        elif any(target_data.iterdir()):
            target_classification = "METADATA_ONLY_REPAIRABLE"
            issues.append(
                _issue(
                    "info",
                    "TARGET_METADATA_ONLY",
                    "The target contains only replaceable migration metadata.",
                    "The target will be backed up and replaced atomically "
                    "during apply.",
                    details={"path": str(target_data)},
                )
            )
        else:
            target_classification = "EMPTY"
        if target_classification in {
            "AUTHORITATIVE_DATA_CONFLICT",
            "FOREIGN_BOUND",
            "INVALID",
        }:
            pass
        elif target_data.exists() and (
            target_binding is not None
            or target_classification == "METADATA_ONLY_REPAIRABLE"
        ):
            for name, code in (
                ("state.toml", "TARGET_STATE_MISSING"),
                ("storage.yaml", "TARGET_STORAGE_META_MISSING"),
            ):
                if not (target_data / name).exists():
                    issues.append(
                        _issue(
                            "warning",
                            code,
                            f"Target data root has no {name}: {target_data}",
                            "The migration will recreate canonical metadata after "
                            "the mount is installed.",
                            details={
                                "target_data_root": str(target_data),
                                "missing_path": str(target_data / name),
                            },
                        )
                    )
    source_logs = source_data
    legacy_next_task_number: int | None = None
    derived_next_task_id: str | None = None
    tombstones_required: tuple[str, ...] = ()
    try:
        legacy_next_task_number, derived_next_task_id, tombstones_required = (
            _legacy_task_id_fields(source_data, root)
        )
    except LaunchError as exc:
        issues.append(_issue("blocker", "MALFORMED_LEGACY_COUNTER", str(exc)))
    items: list[MigrationCopyItem] = []
    if source_data is not None and target_classification not in {
        "AUTHORITATIVE_DATA_CONFLICT",
        "FOREIGN_BOUND",
        "INVALID",
        "IDENTICAL_SOURCE",
    }:
        items = _copy_items(source_data, source_logs, target_data)
    # Check for valid completion receipt
    has_valid_receipt = False
    if target_data is not None and target_data.is_dir():
        migrations_dir = target_data / "migrations"
        if migrations_dir.is_dir():
            receipts = list(migrations_dir.glob("*.json"))
            has_valid_receipt = len(receipts) > 0
    migration_required = not (
        target_classification in {"IDENTICAL_SOURCE", "COMPLETE_CANONICAL"}
        and current_registration is not None
        and has_valid_receipt
    )
    ready = not any(issue.severity == "blocker" for issue in issues) and (
        source_data is not None or target_classification == "COMPLETE_CANONICAL"
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
        ready=ready,
        migration_required=migration_required,
        canonical_project_uuid=canonical_uuid,
        legacy_project_uuid=legacy_uuid,
        identity_transition=identity_transition,
        source_selection_reason=source_reason,
        source_candidates=tuple(candidates),
        target_classification=target_classification,
        would_create_sibling_store=create_sibling_store and not sibling_root.exists(),
        request_source_data_root=source_data_root,
        request_sibling_ledger_root=sibling_ledger_root,
        request_create_sibling_store=create_sibling_store,
        request_adopt_sibling_store=adopt_sibling_store,
    )


def inspect_migration(
    start: Path,
    *,
    source_checkout: str | None = None,
    source_checkout_id: str | None = None,
    source_data_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    project_uuid: str | None = None,
    sibling_ledger_root: Path | None = None,
    create_sibling_store: bool = False,
    adopt_sibling_store: bool = False,
) -> TaskledgerMigrationInspection:
    """Inspect migration state through the phase-based implementation."""
    return _inspect_migration_phases(
        start,
        source_checkout=source_checkout,
        source_checkout_id=source_checkout_id,
        source_data_root=source_data_root,
        environ=environ,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
        create_sibling_store=create_sibling_store,
        adopt_sibling_store=adopt_sibling_store,
    )


def _backup(inspection: TaskledgerMigrationInspection, backup_dir: Path | None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        backup_dir
        or inspection.project_root / ".ledger" / "backups" / f"taskledger-{timestamp}"
    )
    if backup_dir is None:
        suffix = 1
        while destination.exists():
            destination = destination.with_name(
                f"{destination.name.rsplit('-', 1)[0]}-{timestamp}-{suffix}"
            )
            suffix += 1
    destination.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, str]] = []
    copied_roots: set[Path] = set()
    for label, source in (
        ("source-data", inspection.source_data_root),
        ("source-logs", inspection.source_logs_root),
        ("target-data", inspection.target_data_root),
    ):
        if source is None or not source.exists() or source in copied_roots:
            continue
        copied_roots.add(source)
        target = destination / label
        shutil.copytree(source, target, dirs_exist_ok=True)
        for path in source.rglob("*"):
            if path.is_file():
                manifest.append({"source": str(path), "sha256": _sha256(path)})
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


def _ledgercore_migration_plan(
    inspection: TaskledgerMigrationInspection,
) -> StorageMigrationPlan:
    if inspection.project_uuid is None or inspection.source_data_root is None:
        raise LaunchError(
            "Ledgercore migration requires a project UUID and data source."
        )
    existing_manifest = None
    manifest_path = inspection.project_root / ".ledger" / "ledger.toml"
    if manifest_path.is_file():
        document = _manifest_document(manifest_path)
        if document.get("schema_version") == 3:
            existing_manifest = parse_ledger_manifest_v3(document)
    target_manifest = build_taskledger_manifest_with_registration(
        existing_manifest,
        project_uuid=inspection.project_uuid,
        project_name=inspection.project_root.name,
        data_storage="external",
        external_root="../ledger",
    )
    source_binding = StorageBinding(
        1,
        3,
        inspection.project_uuid,
        None,
        CANONICAL_LEDGER_NAME,
        DATA_MOUNT,
        "project",
    )
    destination_binding = StorageBinding(
        1,
        3,
        inspection.project_uuid,
        None,
        CANONICAL_LEDGER_NAME,
        DATA_MOUNT,
        "external",
    )
    strategy: Literal["copy", "noop"] = (
        "noop" if inspection.target_classification == "IDENTICAL_SOURCE" else "copy"
    )
    item = StorageMigrationItem(
        "mount",
        CANONICAL_LEDGER_NAME,
        DATA_MOUNT,
        inspection.source_data_root,
        inspection.target_data_root,
        source_binding,
        destination_binding,
        strategy,
    )
    return StorageMigrationPlan(
        uuid.uuid4().hex,
        inspection.project_uuid,
        (item,),
        target_manifest,
        ("indexes are rebuilt by Taskledger after data migration",),
    )


def _apply_migration_phases(
    inspection: TaskledgerMigrationInspection,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    adopt_sibling_store: bool = False,
    retire_source: bool = False,
) -> dict[str, object]:
    if not inspection.ready:
        raise LaunchError(
            "Migration inspection is not ready to apply. Resolve all blockers first.",
            code="TASKLEDGER_STORAGE_MIGRATION_NOT_READY",
            details={"blockers": list(inspection.blockers)},
        )
    if inspection.project_uuid is None:
        raise LaunchError(
            "Migration requires a stable project UUID. "
            "Run `taskledger repair project-identity --apply` first.",
            code="TASKLEDGER_STORAGE_MIGRATION_NO_PROJECT_UUID",
        )
    initial_source_fingerprint = _tree_fingerprint(inspection.source_data_root)
    initial_target_fingerprint = _tree_fingerprint(inspection.target_data_root)
    if create_sibling_store or adopt_sibling_store:
        _ensure_migration_sibling_store(
            inspection.sibling_root,
            create=create_sibling_store,
            adopt=adopt_sibling_store,
        )
    fresh = inspect_migration(
        inspection.project_root,
        source_checkout=inspection.source_checkout_id,
        source_data_root=inspection.source_data_root,
        project_uuid=inspection.project_uuid,
        sibling_ledger_root=inspection.sibling_root,
    )
    if (
        fresh.source_kind == "canonical-0.4-sibling"
        or fresh.target_classification == "IDENTICAL_SOURCE"
    ):
        receipts = sorted((fresh.target_data_root / "migrations").glob("*.json"))
        return {
            "kind": "migration_apply",
            "status": "applied",
            "inspection": fresh.to_dict(),
            "receipt": str(receipts[-1]) if receipts else None,
            "canonical_activation": True,
            "source_retired": False,
            "next_commands": [
                "taskledger migrate status",
                "taskledger storage validate",
                "taskledger doctor",
            ],
        }
    issues = list(fresh.issues)
    if create_sibling_store and fresh.issues:
        fresh = inspect_migration(
            fresh.project_root,
            source_checkout=fresh.source_checkout_id,
            source_data_root=fresh.source_data_root,
            project_uuid=fresh.project_uuid,
            sibling_ledger_root=fresh.sibling_root,
        )
        issues = list(fresh.issues)
    current_source_fingerprint = _tree_fingerprint(fresh.source_data_root)
    current_target_fingerprint = _tree_fingerprint(fresh.target_data_root)
    if initial_source_fingerprint != current_source_fingerprint:
        raise LaunchError(
            "Migration source changed after inspection; rerun migration plan.",
            code="TASKLEDGER_STORAGE_MIGRATION_BLOCKED",
            details={
                "before": initial_source_fingerprint,
                "after": current_source_fingerprint,
            },
        )
    if initial_target_fingerprint != current_target_fingerprint:
        raise LaunchError(
            "Migration target changed after inspection; rerun migration plan.",
            code="TASKLEDGER_STORAGE_MIGRATION_BLOCKED",
            details={
                "before": initial_target_fingerprint,
                "after": current_target_fingerprint,
            },
        )
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
            ),
            code="TASKLEDGER_STORAGE_MIGRATION_BLOCKED",
            details={"issues": [issue.to_dict() for issue in issues]},
        )
    backup_path = _backup(fresh, backup_dir)
    target = fresh.target_data_root
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = fresh.project_root / ".ledger" / "ledger.toml"
    manifest_before = (
        manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
    )
    (fresh.project_root / ".ledger" / "migrations").mkdir(parents=True, exist_ok=True)
    if fresh.target_classification == "METADATA_ONLY_REPAIRABLE":
        verification = inspect_migration(
            fresh.project_root,
            source_checkout=fresh.source_checkout_id,
            source_data_root=fresh.source_data_root,
            project_uuid=fresh.project_uuid,
            sibling_ledger_root=fresh.sibling_root,
        )
        if verification.target_classification != "METADATA_ONLY_REPAIRABLE":
            raise LaunchError(
                "Target changed while preparing metadata-only replacement.",
                code="TASKLEDGER_STORAGE_MIGRATION_BLOCKED",
            )
        shutil.rmtree(target)
        fresh = inspect_migration(
            fresh.project_root,
            source_checkout=fresh.source_checkout_id,
            source_data_root=fresh.source_data_root,
            project_uuid=fresh.project_uuid,
            sibling_ledger_root=fresh.sibling_root,
        )
    plan = _ledgercore_migration_plan(fresh)
    from taskledger.storage.taskledger_migration import (
        require_no_active_taskledger_locks,
    )

    execute_taskledger_layout_migration(
        plan,
        mode="copy",
        quiescence_check=lambda: require_no_active_taskledger_locks(fresh.project_root),
        project_root=fresh.project_root,
    )
    _write_tombstones(target, fresh.tombstones_required)
    _write_target_state(target)
    write_yaml_object(
        target / "storage.yaml",
        {
            "storage_layout_version": 5,
            "record_schema_version": 1,
            "created_with_taskledger": "migration",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_migrated_with_taskledger": "migration",
            "last_migrated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    verification_report = {
        "target_exists": target.is_dir(),
        "binding": (target / ".ledger-project.toml").is_file(),
        "state": (target / "state.toml").is_file(),
        "storage_metadata": (target / "storage.yaml").is_file(),
        "source_preserved": fresh.source_data_root is not None
        and fresh.source_data_root.exists(),
        "source_fingerprint": _tree_fingerprint(fresh.source_data_root),
        "target_fingerprint": _tree_fingerprint(target),
        "preserved_ledger_registrations": sorted(
            name
            for name in plan.config_changes.ledgers
            if name != CANONICAL_LEDGER_NAME
        ),
    }

    fixed_sibling_root = (fresh.project_root / ".." / "ledger").resolve(strict=False)
    if fresh.sibling_root != fixed_sibling_root:
        if manifest_before is None:
            manifest_path.unlink(missing_ok=True)
        else:
            atomic_write_text(manifest_path, manifest_before)
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
                    "verified": verification_report,
                    "canonical_activation": False,
                    "identity": {
                        "canonical_uuid": fresh.canonical_project_uuid,
                        "legacy_uuid": fresh.legacy_project_uuid,
                    },
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
            "verification": verification_report,
            "canonical_activation": False,
            "source_retired": False,
            "next_commands": [
                "taskledger migrate status",
                "taskledger storage validate",
                "taskledger doctor",
            ],
            "warnings": [
                (
                    "Migration-only destination override was used; canonical "
                    "project activation was not changed."
                )
            ],
        }
    from taskledger.storage.ledger_local_config import (
        ensure_sibling_workspace_provider,
    )
    from taskledger.storage.project_config import render_canonical_taskledger_config

    config_path = fresh.project_root / ".ledger" / "taskledger" / "config.toml"
    if not config_path.exists():
        atomic_write_text(config_path, render_canonical_taskledger_config())
    ensure_sibling_workspace_provider(fresh.project_root)
    local_config_path = fresh.project_root / ".ledger" / "ledger.local.toml"
    if local_config_path.exists():
        local_config_path.unlink()
    layout = load_taskledger_ledger_layout(
        fresh.project_root, validate_storage=False
    ).resolved_layout
    initialize_config_binding(layout)
    initialize_taskledger_bindings(
        layout,
        initialize_config=False,
        initialize_data=False,
        initialize_indexes=True,
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
                "verified": verification_report,
                "identity": {
                    "canonical_uuid": fresh.canonical_project_uuid,
                    "legacy_uuid": fresh.legacy_project_uuid,
                },
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
        "verification": verification_report,
        "canonical_activation": True,
        "source_retired": retire_source,
        "next_commands": [
            "taskledger migrate status",
            "taskledger storage validate",
            "taskledger doctor",
        ],
    }


def apply_migration(
    inspection: TaskledgerMigrationInspection,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    adopt_sibling_store: bool = False,
    retire_source: bool = False,
) -> dict[str, object]:
    """Apply migration through the phase-based implementation."""
    return _apply_migration_phases(
        inspection,
        backup=backup,
        backup_dir=backup_dir,
        create_sibling_store=create_sibling_store,
        adopt_sibling_store=adopt_sibling_store,
        retire_source=retire_source,
    )


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
    adopt_sibling_store: bool = False,
    dry_run: bool = False,
    retire_legacy: bool = False,
) -> dict[str, object]:
    inspection = inspect_migration(
        start,
        project_uuid=project_uuid,
        sibling_ledger_root=sibling_ledger_root,
        create_sibling_store=create_sibling_store,
        adopt_sibling_store=adopt_sibling_store,
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
        adopt_sibling_store=adopt_sibling_store,
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

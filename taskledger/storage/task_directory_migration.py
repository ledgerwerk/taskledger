"""Recoverable layout-5 to layout-6 UUIDv7 task-directory migration."""

from __future__ import annotations

import base64
import importlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from taskledger.domain.models import DependencyRequirement, TaskRecord
from taskledger.errors import LaunchError
from taskledger.ids import TASK_ID_FORMAT
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.frontmatter import (
    read_markdown_front_matter,
    write_markdown_front_matter,
)
from taskledger.storage.task_identity import (
    LEGACY_GAP_CREATED_AT,
    TaskIdentity,
    deterministic_legacy_task_uuid,
    invalidate_task_identity_inventory,
    missing_legacy_task_ids,
    scan_task_identity_inventory,
    task_identity_for_stored_ref,
)
from taskledger.storage.task_store import V2Paths, resolve_v2_paths

_JOURNAL_NAME = "task-directory-migration-v5-to-v6.json"
_LOCK_NAME = ".task-directory-uuidv7-migration.lock"


def migrate_v5_task_directories_to_uuidv7(workspace_root: Path) -> None:
    """Rename numeric task bundles to deterministic UUIDv7 storage paths."""
    paths = resolve_v2_paths(workspace_root)
    journal_path = paths.ledger_dir / _JOURNAL_NAME
    lock_path = paths.ledger_dir / _LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        existing_journal = _read_journal(journal_path)
        if (
            existing_journal is not None
            and existing_journal.get("status") == "complete"
        ):
            _validate_completed_migration(paths, existing_journal)
            return
        if existing_journal is not None:
            _rollback_migration(paths, journal_path, existing_journal)

        _assert_no_unmerged_git_paths(paths.workspace_root)
        _assert_no_active_locks(paths)
        plan = _build_rename_plan(paths)
        journal: dict[str, object] = {
            "schema_version": 1,
            "object_type": "task_directory_migration",
            "from_layout": 5,
            "to_layout": 6,
            "status": "prepared",
            "task_renames": plan["task_renames"],
            "tombstone_renames": plan["tombstone_renames"],
            "reservation_creates": plan["reservation_creates"],
            "relation_backfills": [],
            "relation_backfill_version": 1,
        }
        _write_journal(journal_path, journal)
        try:
            _apply_renames(paths, journal)
            _backfill_task_relationship_uuids(paths, journal_path, journal)
            _mark_and_rebuild_indexes(paths)
            _validate_migrated_storage(paths, require_relation_uuids=True)
            journal["status"] = "complete"
            from taskledger.timeutils import utc_now_iso

            journal["completed_at"] = utc_now_iso()
            _write_journal(journal_path, journal)
        except Exception as exc:
            try:
                _rollback_migration(paths, journal_path, journal)
            except Exception as rollback_exc:  # noqa: BLE001
                raise LaunchError(
                    "UUIDv7 task-directory migration failed; automatic "
                    "rollback also "
                    f"failed: {rollback_exc}. Inspect {journal_path} before retrying."
                ) from exc
            if isinstance(exc, LaunchError):
                raise
            raise LaunchError(f"UUIDv7 task-directory migration failed: {exc}") from exc


def _build_rename_plan(paths: V2Paths) -> dict[str, list[dict[str, object]]]:
    tasks_dir = paths.tasks_dir
    entries = (
        sorted(tasks_dir.iterdir(), key=lambda item: item.name)
        if tasks_dir.exists()
        else []
    )
    numeric_dirs: list[Path] = []
    uuid_dirs: list[Path] = []
    for entry in entries:
        if entry.is_symlink():
            raise LaunchError(f"Task directory migration refuses symlink: {entry}")
        if not entry.is_dir():
            raise LaunchError(
                f"Task directory migration found an unexpected entry: {entry}"
            )
        for nested in entry.rglob("*"):
            if nested.is_symlink():
                raise LaunchError(f"Task directory migration refuses symlink: {nested}")
        if entry.name.startswith("task-"):
            numeric_dirs.append(entry)
        elif _is_uuid_directory_name(entry.name):
            uuid_dirs.append(entry)
        else:
            raise LaunchError(
                f"Task directory migration found an unknown task directory {entry}; "
                "move or repair it explicitly before migrating."
            )
    if numeric_dirs and uuid_dirs:
        raise LaunchError(
            "Mixed numeric and UUID task directories without an active "
            "migration journal; "
            "inspect the store and recover the interrupted migration explicitly."
        )
    if uuid_dirs and not numeric_dirs:
        raise LaunchError(
            "UUID task directories already exist while storage metadata is "
            "still layout 5; "
            "a valid migration journal is required to prove their provenance."
        )

    project_uuid = _project_uuid_for_paths(paths) if numeric_dirs else None
    task_renames: list[dict[str, object]] = []
    used_uuids: set[str] = set()
    used_legacy_ids: set[str] = set()
    for source in numeric_dirs:
        legacy_id, _ = _parse_legacy_id(source.name, source)
        if legacy_id in used_legacy_ids:
            raise LaunchError(f"Duplicate legacy task allocation {legacy_id}.")
        used_legacy_ids.add(legacy_id)
        task_md = source / "task.md"
        if task_md.exists() and not task_md.is_file():
            raise LaunchError(f"Task record path is not a file: {task_md}")
        if task_md.is_file():
            metadata, _ = _read_task_metadata(task_md)
            if metadata.get("object_type") != "task":
                raise LaunchError(f"Task record {task_md} has invalid object_type.")
            if metadata.get("id") != legacy_id:
                raise LaunchError(
                    f"Task record {task_md} id does not match directory {legacy_id}."
                )
            created_at = metadata.get("created_at")
            if isinstance(created_at, datetime):
                created_at = created_at.isoformat()
            if not isinstance(created_at, str) or not created_at.strip():
                raise LaunchError(f"Task record {task_md} has no valid created_at.")
        else:
            created_at = "legacy-reservation"
        assert project_uuid is not None
        task_uuid = deterministic_legacy_task_uuid(
            project_uuid=project_uuid,
            ledger_ref=paths.ledger_ref,
            legacy_task_id=legacy_id,
            created_at=created_at,
        )
        uuid_text = str(task_uuid)
        if uuid_text in used_uuids:
            raise LaunchError(
                f"Multiple legacy allocations map to UUID {uuid_text}; "
                "refusing to merge."
            )
        used_uuids.add(uuid_text)
        destination = tasks_dir / uuid_text
        if destination.exists():
            raise LaunchError(
                f"UUID task destination already exists: {destination}; "
                "refusing to overwrite."
            )
        task_renames.append(
            {
                "old": (Path("tasks") / source.name).as_posix(),
                "new": (Path("tasks") / uuid_text).as_posix(),
                "legacy_task_id": legacy_id,
                "task_uuid": uuid_text,
            }
        )

    tombstone_renames = _plan_tombstones(paths, used_uuids, used_legacy_ids)
    reservation_creates = _plan_legacy_gap_reservations(
        paths, used_legacy_ids, used_uuids
    )
    return {
        "task_renames": task_renames,
        "tombstone_renames": tombstone_renames,
        "reservation_creates": reservation_creates,
    }


def _plan_tombstones(
    paths: V2Paths, used_uuids: set[str], used_legacy_ids: set[str]
) -> list[dict[str, object]]:
    tombstones_dir = paths.ledger_dir / "tombstones"
    if not tombstones_dir.exists():
        return []
    entries = sorted(tombstones_dir.iterdir(), key=lambda item: item.name)
    legacy_entries = [entry for entry in entries if entry.stem.startswith("task-")]
    project_uuid = _project_uuid_for_paths(paths) if legacy_entries else None
    result: list[dict[str, object]] = []
    for source in entries:
        if source.is_symlink() or not source.is_file() or source.suffix != ".toml":
            raise LaunchError(f"Malformed task tombstone during migration: {source}")
        if not source.stem.startswith("task-"):
            raise LaunchError(
                f"Unexpected non-legacy tombstone during layout-5 migration: "
                f"{source.name}"
            )
        legacy_id, _ = _parse_legacy_id(source.stem, source)
        if legacy_id in used_legacy_ids:
            raise LaunchError(f"Duplicate legacy task allocation {legacy_id}.")
        used_legacy_ids.add(legacy_id)
        document = _read_toml(source)
        if (
            document.get("schema_version") != 1
            or document.get("object_type") != "task_id_tombstone"
            or document.get("id") != legacy_id
            or not isinstance(document.get("reason"), str)
            or not isinstance(document.get("created_at"), str)
        ):
            raise LaunchError(f"Legacy task tombstone {source} has invalid schema.")
        assert project_uuid is not None
        task_uuid = deterministic_legacy_task_uuid(
            project_uuid=project_uuid,
            ledger_ref=paths.ledger_ref,
            legacy_task_id=legacy_id,
            created_at=str(document["created_at"]),
        )
        uuid_text = str(task_uuid)
        if uuid_text in used_uuids:
            raise LaunchError(
                f"Duplicate task allocation identity {uuid_text} at {source}; "
                "refusing migration."
            )
        used_uuids.add(uuid_text)
        destination = tombstones_dir / f"{uuid_text}.toml"
        if destination.exists():
            raise LaunchError(
                f"UUID tombstone destination already exists: {destination}; "
                "refusing overwrite."
            )
        result.append(
            {
                "old": (Path("tombstones") / source.name).as_posix(),
                "new": (Path("tombstones") / destination.name).as_posix(),
                "legacy_task_id": legacy_id,
                "task_uuid": uuid_text,
                "original_contents_base64": base64.b64encode(
                    source.read_bytes()
                ).decode("ascii"),
                "document": document,
            }
        )
    return result


def _plan_legacy_gap_reservations(
    paths: V2Paths, existing_ids: set[str], used_uuids: set[str]
) -> list[dict[str, object]]:
    missing_ids = missing_legacy_task_ids(existing_ids)
    if not missing_ids:
        return []
    project_uuid = _project_uuid_for_paths(paths)
    tombstones_dir = paths.ledger_dir / "tombstones"
    reservations: list[dict[str, object]] = []
    for legacy_id in missing_ids:
        task_uuid = deterministic_legacy_task_uuid(
            project_uuid=project_uuid,
            ledger_ref=paths.ledger_ref,
            legacy_task_id=legacy_id,
            created_at=LEGACY_GAP_CREATED_AT,
        )
        uuid_text = str(task_uuid)
        if uuid_text in used_uuids:
            raise LaunchError(
                f"Legacy gap reservation collides with task UUID {uuid_text}."
            )
        used_uuids.add(uuid_text)
        destination = tombstones_dir / f"{uuid_text}.toml"
        if destination.exists():
            raise LaunchError(
                f"Legacy gap reservation destination already exists: {destination}."
            )
        document: dict[str, object] = {
            "schema_version": 2,
            "object_type": "task_identity_tombstone",
            "task_uuid": uuid_text,
            "legacy_task_id": legacy_id,
            "reason": "unrecorded legacy allocation slot preserved during migration",
            "created_at": LEGACY_GAP_CREATED_AT,
        }
        reservations.append(
            {
                "new": (Path("tombstones") / destination.name).as_posix(),
                "legacy_task_id": legacy_id,
                "task_uuid": uuid_text,
                "document": document,
            }
        )
    return reservations


def _apply_renames(paths: V2Paths, journal: dict[str, object]) -> None:
    task_renames = _journal_list(journal, "task_renames")
    for item in task_renames:
        source = paths.ledger_dir / str(item["old"])
        destination = paths.ledger_dir / str(item["new"])
        if destination.exists():
            raise LaunchError(
                f"UUID task destination appeared during migration: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)

    for item in _journal_list(journal, "tombstone_renames"):
        source = paths.ledger_dir / str(item["old"])
        destination = paths.ledger_dir / str(item["new"])
        document = item.get("document")
        if not isinstance(document, dict):
            raise LaunchError(
                "Migration journal contains an invalid tombstone document."
            )
        if destination.exists():
            raise LaunchError(f"UUID tombstone destination appeared: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(destination, _uuid_tombstone_text(item, document))
        source.unlink()
    for item in _journal_list(journal, "reservation_creates"):
        destination = paths.ledger_dir / str(item["new"])
        document = item.get("document")
        if not isinstance(document, dict):
            raise LaunchError("Migration journal contains an invalid gap reservation.")
        if destination.exists():
            raise LaunchError(
                f"Legacy gap tombstone destination appeared: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(destination, _uuid_tombstone_text(item, document))
    invalidate_task_identity_inventory()


def _rollback_migration(
    paths: V2Paths, journal_path: Path, journal: dict[str, object]
) -> None:
    relation_backfills = journal.get("relation_backfills", [])
    if not isinstance(relation_backfills, list):
        raise LaunchError("Migration journal relation backfills are invalid.")
    for item in reversed(relation_backfills):
        if not isinstance(item, dict):
            raise LaunchError("Migration journal relation backfill is invalid.")
        relative_path = item.get("path")
        encoded = item.get("original_contents_base64")
        if not isinstance(relative_path, str) or not isinstance(encoded, str):
            raise LaunchError("Migration journal relation backup is invalid.")
        path = paths.ledger_dir / relative_path
        if not path.is_file():
            raise LaunchError(f"Cannot restore missing relation source {path}.")
        try:
            relation_original = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            raise LaunchError("Migration journal relation backup is corrupt.") from exc
        atomic_write_text(path, relation_original)
    journal["relation_backfills"] = []
    for item in reversed(_journal_list(journal, "task_renames")):
        source = paths.ledger_dir / str(item["old"])
        destination = paths.ledger_dir / str(item["new"])
        if destination.exists() and not source.exists():
            destination.rename(source)
        elif source.exists() and not destination.exists():
            continue
        elif source.exists() and destination.exists():
            raise LaunchError(
                f"Cannot roll back conflicting task paths {source} and {destination}."
            )
        else:
            raise LaunchError(
                f"Cannot recover missing task paths {source} and {destination}."
            )

    for item in reversed(_journal_list(journal, "tombstone_renames")):
        source = paths.ledger_dir / str(item["old"])
        destination = paths.ledger_dir / str(item["new"])
        encoded = item.get("original_contents_base64")
        if not isinstance(encoded, str):
            raise LaunchError("Migration journal cannot restore tombstone contents.")
        tombstone_original = base64.b64decode(encoded)
        if destination.exists():
            current = _read_toml(destination)
            if current.get("task_uuid") != item.get("task_uuid"):
                raise LaunchError(
                    f"Cannot roll back foreign UUID tombstone {destination}."
                )
            destination.unlink()
        if source.exists() and source.read_bytes() != tombstone_original:
            raise LaunchError(f"Cannot restore changed legacy tombstone {source}.")
        if not source.exists():
            atomic_write_text(source, tombstone_original.decode("utf-8"))
    for item in reversed(_journal_list(journal, "reservation_creates")):
        destination = paths.ledger_dir / str(item["new"])
        if not destination.exists():
            continue
        current = _read_toml(destination)
        if current.get("task_uuid") != item.get("task_uuid") or current.get(
            "legacy_task_id"
        ) != item.get("legacy_task_id"):
            raise LaunchError(f"Cannot roll back foreign gap tombstone {destination}.")
        destination.unlink()
    journal["status"] = "rolled_back"
    _write_journal(journal_path, journal)
    invalidate_task_identity_inventory()
    _mark_indexes_dirty(paths)


def _resolve_live_relation(
    paths: V2Paths,
    *,
    source_path: Path,
    field: str,
    task_id: str,
    task_uuid: str | None,
) -> TaskIdentity:
    try:
        identity = task_identity_for_stored_ref(
            paths, task_id=task_id, task_uuid=task_uuid
        )
    except LaunchError as exc:
        raise LaunchError(
            f"Cannot safely resolve relation {field} in {source_path}: {exc}",
            code="TASKLEDGER_RELATION_RESOLUTION_FAILED",
            details={
                "source": str(source_path),
                "field": field,
                "task_id": task_id,
                "task_uuid": task_uuid,
                "cause_code": exc.code,
                "cause": str(exc),
            },
        ) from exc
    if identity.state != "live" or not (identity.path / "task.md").is_file():
        raise LaunchError(
            f"Relation {field} in {source_path} targets non-live task "
            f"{task_id!r} ({identity.state}).",
            code="TASKLEDGER_RELATION_RESOLUTION_FAILED",
            details={
                "source": str(source_path),
                "field": field,
                "task_id": task_id,
                "task_uuid": str(identity.task_uuid),
                "target_state": identity.state,
            },
        )
    return identity


def _prepare_task_relation_backfills(paths: V2Paths) -> list[dict[str, object]]:
    inventory = scan_task_identity_inventory(paths)
    updates: list[dict[str, object]] = []
    for identity in inventory.entries:
        if identity.state != "live" or not (identity.path / "task.md").is_file():
            continue
        task_path = identity.path / "task.md"
        metadata, body = read_markdown_front_matter(task_path)
        task = TaskRecord.from_dict(metadata)
        if task.parent_task_id or task.parent_task_uuid:
            parent = _resolve_live_relation(
                paths,
                source_path=task_path,
                field="parent_task_uuid",
                task_id=task.parent_task_id or "",
                task_uuid=task.parent_task_uuid,
            )
            updated = dict(metadata)
            updated["parent_task_id"] = parent.task_id
            updated["parent_task_uuid"] = str(parent.task_uuid)
            if updated != metadata:
                updates.append(
                    {
                        "path": task_path,
                        "metadata": updated,
                        "body": body,
                        "original_bytes": task_path.read_bytes(),
                        "fields": ["parent_task_uuid"],
                    }
                )

        requirements_dir = identity.path / "requirements"
        for requirement_path in sorted(requirements_dir.glob("req-*.md")):
            requirement_metadata, requirement_body = read_markdown_front_matter(
                requirement_path
            )
            requirement = DependencyRequirement.from_dict(requirement_metadata)
            owner_task_id = requirement.parent_task_id or task.id
            owner_task_uuid = requirement.parent_task_uuid
            if requirement.parent_task_id is None and owner_task_uuid is None:
                owner_task_uuid = str(identity.task_uuid)
            owner = _resolve_live_relation(
                paths,
                source_path=requirement_path,
                field="parent_task_uuid",
                task_id=owner_task_id,
                task_uuid=owner_task_uuid,
            )
            required = _resolve_live_relation(
                paths,
                source_path=requirement_path,
                field="required_task_uuid",
                task_id=requirement.required_task_id or requirement.task_id,
                task_uuid=requirement.required_task_uuid,
            )
            updated_requirement = dict(requirement_metadata)
            updated_requirement["task_id"] = required.task_id
            updated_requirement["required_task_id"] = required.task_id
            updated_requirement["required_task_uuid"] = str(required.task_uuid)
            updated_requirement["parent_task_id"] = owner.task_id
            updated_requirement["parent_task_uuid"] = str(owner.task_uuid)
            if updated_requirement != requirement_metadata:
                updates.append(
                    {
                        "path": requirement_path,
                        "metadata": updated_requirement,
                        "body": requirement_body,
                        "original_bytes": requirement_path.read_bytes(),
                        "fields": ["parent_task_uuid", "required_task_uuid"],
                    }
                )
    return updates


def _backfill_task_relationship_uuids(
    paths: V2Paths, journal_path: Path, journal: dict[str, object]
) -> None:
    updates = _prepare_task_relation_backfills(paths)
    entries = journal.get("relation_backfills", [])
    if not isinstance(entries, list):
        raise LaunchError("Migration journal relation backfills are invalid.")
    snapshots: list[dict[str, object]] = []
    for update in updates:
        path = update["path"]
        original_bytes = update["original_bytes"]
        if not isinstance(path, Path) or not isinstance(original_bytes, bytes):
            raise LaunchError("Migration relation backfill plan is invalid.")
        snapshots.append(
            {
                "path": path.relative_to(paths.ledger_dir).as_posix(),
                "original_contents_base64": base64.b64encode(original_bytes).decode(
                    "ascii"
                ),
                "fields": update["fields"],
            }
        )
    journal["relation_backfills"] = snapshots
    _write_journal(journal_path, journal)
    for update in updates:
        path = update["path"]
        original_bytes = update["original_bytes"]
        metadata = update["metadata"]
        body = update["body"]
        if not isinstance(path, Path) or not isinstance(original_bytes, bytes):
            raise LaunchError("Migration relation backfill plan is invalid.")
        if not isinstance(metadata, dict) or not isinstance(body, str):
            raise LaunchError("Migration relation backfill content is invalid.")
        fields = update["fields"]
        if not isinstance(fields, list) or not all(
            isinstance(field, str) for field in fields
        ):
            raise LaunchError("Migration relation backfill fields are invalid.")
        if path.read_bytes() != original_bytes:
            raise LaunchError(
                f"Relation source changed during migration: {path}.",
                code="TASKLEDGER_RELATION_SOURCE_CHANGED",
                details={"source": str(path), "fields": update["fields"]},
            )
        write_markdown_front_matter(path, metadata, body)
        verified_metadata, _ = read_markdown_front_matter(path)
        if any(verified_metadata.get(field) != metadata.get(field) for field in fields):
            raise LaunchError(
                f"Relation backfill postcondition failed for {path}.",
                code="TASKLEDGER_RELATION_BACKFILL_FAILED",
                details={"source": str(path), "fields": update["fields"]},
            )


def _validate_migrated_storage(
    paths: V2Paths, *, require_relation_uuids: bool = False
) -> None:
    if paths.tasks_dir.exists() and any(
        path.name.startswith("task-") for path in paths.tasks_dir.iterdir()
    ):
        raise LaunchError("Migration left numeric task directories in layout 6.")
    tombstones_dir = paths.ledger_dir / "tombstones"
    if tombstones_dir.exists() and any(
        path.stem.startswith("task-") for path in tombstones_dir.glob("*.toml")
    ):
        raise LaunchError("Migration left numeric task tombstones in layout 6.")
    scan_task_identity_inventory(paths)
    if require_relation_uuids:
        pending_backfills = _prepare_task_relation_backfills(paths)
        if pending_backfills:
            pending = pending_backfills[0]
            path = pending["path"]
            fields = pending["fields"]
            raise LaunchError(
                f"Migration left an unbackfilled task relation in {path}.",
                code="TASKLEDGER_RELATION_BACKFILL_FAILED",
                details={"source": str(path), "fields": fields},
            )
    from taskledger.storage.task_store import list_tasks_from_paths

    list_tasks_from_paths(paths)


def _validate_completed_migration(paths: V2Paths, journal: dict[str, object]) -> None:
    for item in _journal_list(journal, "task_renames"):
        source = paths.ledger_dir / str(item["old"])
        destination = paths.ledger_dir / str(item["new"])
        if source.exists() or not destination.is_dir():
            raise LaunchError(
                f"Completed migration receipt disagrees with task paths: "
                f"{source}, {destination}."
            )
    for item in _journal_list(journal, "tombstone_renames"):
        source = paths.ledger_dir / str(item["old"])
        destination = paths.ledger_dir / str(item["new"])
        if source.exists() or not destination.is_file():
            raise LaunchError(
                "Completed migration receipt disagrees with tombstone paths: "
                f"{source}, "
                f"{destination}."
            )
    for item in _journal_list(journal, "reservation_creates"):
        destination = paths.ledger_dir / str(item["new"])
        if not destination.is_file():
            raise LaunchError(
                f"Completed migration is missing gap tombstone {destination}."
            )
        document = _read_toml(destination)
        if document.get("task_uuid") != item.get("task_uuid") or document.get(
            "legacy_task_id"
        ) != item.get("legacy_task_id"):
            raise LaunchError(
                f"Completed migration receipt disagrees with {destination}."
            )
    _validate_migrated_storage(
        paths, require_relation_uuids=journal.get("relation_backfill_version") == 1
    )


def _mark_indexes_dirty(paths: V2Paths) -> None:
    from taskledger.storage.indexes import mark_index_dirty

    for name in ("task_index", "sidecar_index", "dependencies", "active_locks"):
        mark_index_dirty(paths, name)


def _mark_and_rebuild_indexes(paths: V2Paths) -> None:
    from taskledger.storage.indexes import rebuild_v2_indexes

    _mark_indexes_dirty(paths)
    rebuild_v2_indexes(paths)


def _assert_no_active_locks(paths: V2Paths) -> None:
    from taskledger.services.lock_inventory import (
        build_lock_inventory,
        require_migration_safe_locks,
    )

    inventory = build_lock_inventory(paths)
    require_migration_safe_locks(inventory, project_root=paths.workspace_root)


def _assert_no_unmerged_git_paths(workspace_root: Path) -> None:
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LaunchError(
            "Unable to inspect Git merge state before UUIDv7 migration: "
            f"{result.stderr.strip()}"
        )
    conflicts = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if conflicts:
        rendered = ", ".join(conflicts)
        raise LaunchError(
            "UUIDv7 task-directory migration is blocked by unresolved "
            "Git merge conflicts: "
            f"{rendered}. Resolve the conflicts before the first mutating command."
        )


def _project_uuid_for_paths(paths: V2Paths) -> str:
    from taskledger.storage.project_identity import load_project_uuid

    candidates = (
        paths.workspace_root / ".ledger" / "taskledger" / "config.toml",
        paths.workspace_root / ".taskledger.toml",
        paths.workspace_root / "taskledger.toml",
        paths.taskledger_root / "taskledger.toml",
        paths.taskledger_root / "project.toml",
    )
    for candidate in candidates:
        if candidate.is_file():
            project_uuid = load_project_uuid(candidate)
            if project_uuid is not None:
                return project_uuid
    raise LaunchError(
        "Deterministic UUIDv7 task-directory migration requires a project UUID."
    )


def _parse_legacy_id(value: str, path: Path) -> tuple[str, int]:
    try:
        parts = TASK_ID_FORMAT.parse_parts(value)
    except ValueError as exc:
        raise LaunchError(
            f"Malformed legacy task allocation {path}: {value!r}."
        ) from exc
    canonical = TASK_ID_FORMAT.format(parts.number)
    if canonical != value:
        raise LaunchError(f"Non-canonical legacy task ID {value!r} at {path}.")
    if parts.number < 1:
        raise LaunchError(f"Legacy task ID {value!r} must be positive.")
    return canonical, parts.number


def _read_task_metadata(path: Path) -> tuple[dict[str, object], str]:
    from taskledger.storage.frontmatter import read_markdown_front_matter

    return read_markdown_front_matter(path)


def _read_toml(path: Path) -> dict[str, object]:
    try:
        tomllib = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = importlib.import_module("tomli")
    try:
        result = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Invalid task tombstone {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise LaunchError(f"Invalid task tombstone {path}: expected a TOML table.")
    return result


def _uuid_tombstone_text(item: dict[str, object], document: dict[str, Any]) -> str:
    task_uuid = json.dumps(str(item["task_uuid"]))
    legacy_task_id = json.dumps(str(item["legacy_task_id"]))
    reason = json.dumps(str(document["reason"]))
    created_at = json.dumps(str(document["created_at"]))
    lines = [
        "schema_version = 2",
        'object_type = "task_identity_tombstone"',
        f"task_uuid = {task_uuid}",
        f"legacy_task_id = {legacy_task_id}",
        f"reason = {reason}",
        f"created_at = {created_at}",
    ]
    quarantined_path = document.get("quarantined_path")
    if isinstance(quarantined_path, str):
        lines.append(f"quarantined_path = {json.dumps(quarantined_path)}")
    return "\n".join(lines) + "\n"


def _is_uuid_directory_name(value: str) -> bool:
    if len(value) != 36 or value.count("-") != 4:
        return False
    from taskledger.ids import parse_uuid7

    try:
        return str(parse_uuid7(value)) == value
    except ValueError:
        return False


def _journal_list(journal: dict[str, object], key: str) -> list[dict[str, object]]:
    value = journal.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise LaunchError(f"Migration journal field {key!r} is invalid.")
    return value


def _validate_journal_entries(journal: dict[str, object]) -> None:
    task_entries = _journal_list(journal, "task_renames")
    tombstone_entries = _journal_list(journal, "tombstone_renames")
    legacy_ids: set[str] = set()
    task_uuids: set[str] = set()

    for item in task_entries:
        legacy_id = item.get("legacy_task_id")
        task_uuid = item.get("task_uuid")
        if not isinstance(legacy_id, str) or not isinstance(task_uuid, str):
            raise LaunchError("Migration journal contains an invalid task identity.")
        _parse_legacy_id(legacy_id, Path(legacy_id))
        if not _is_uuid_directory_name(task_uuid):
            raise LaunchError(
                f"Migration journal contains an invalid UUID: {task_uuid!r}."
            )
        if (
            item.get("old") != f"tasks/{legacy_id}"
            or item.get("new") != f"tasks/{task_uuid}"
            or legacy_id in legacy_ids
            or task_uuid in task_uuids
        ):
            raise LaunchError("Migration journal contains conflicting task paths.")
        legacy_ids.add(legacy_id)
        task_uuids.add(task_uuid)

    for item in tombstone_entries:
        legacy_id = item.get("legacy_task_id")
        task_uuid = item.get("task_uuid")
        encoded = item.get("original_contents_base64")
        document = item.get("document")
        if (
            not isinstance(legacy_id, str)
            or not isinstance(task_uuid, str)
            or not isinstance(encoded, str)
            or not isinstance(document, dict)
        ):
            raise LaunchError(
                "Migration journal contains an invalid tombstone identity."
            )
        _parse_legacy_id(legacy_id, Path(legacy_id))
        if not _is_uuid_directory_name(task_uuid):
            raise LaunchError(
                f"Migration journal contains an invalid UUID: {task_uuid!r}."
            )
        if (
            item.get("old") != f"tombstones/{legacy_id}.toml"
            or item.get("new") != f"tombstones/{task_uuid}.toml"
            or legacy_id in legacy_ids
            or task_uuid in task_uuids
            or document.get("schema_version") != 1
            or document.get("object_type") != "task_id_tombstone"
            or document.get("id") != legacy_id
            or not isinstance(document.get("reason"), str)
            or not isinstance(document.get("created_at"), str)
        ):
            raise LaunchError("Migration journal contains conflicting tombstone data.")
        try:
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise LaunchError(
                "Migration journal has invalid tombstone backup data."
            ) from exc
        legacy_ids.add(legacy_id)
        task_uuids.add(task_uuid)
    for item in _journal_list(journal, "reservation_creates"):
        legacy_id = item.get("legacy_task_id")
        task_uuid = item.get("task_uuid")
        document = item.get("document")
        if (
            not isinstance(legacy_id, str)
            or not isinstance(task_uuid, str)
            or not isinstance(document, dict)
        ):
            raise LaunchError("Migration journal contains an invalid gap reservation.")
        _parse_legacy_id(legacy_id, Path(legacy_id))
        if not _is_uuid_directory_name(task_uuid):
            raise LaunchError(
                f"Migration journal contains an invalid UUID: {task_uuid!r}."
            )
        if (
            item.get("new") != f"tombstones/{task_uuid}.toml"
            or legacy_id in legacy_ids
            or task_uuid in task_uuids
            or document.get("schema_version") != 2
            or document.get("object_type") != "task_identity_tombstone"
            or document.get("task_uuid") != task_uuid
            or document.get("legacy_task_id") != legacy_id
            or document.get("created_at") != LEGACY_GAP_CREATED_AT
            or not isinstance(document.get("reason"), str)
        ):
            raise LaunchError(
                "Migration journal contains conflicting gap reservation data."
            )
        legacy_ids.add(legacy_id)
        task_uuids.add(task_uuid)
    if missing_legacy_task_ids(legacy_ids):
        raise LaunchError(
            "Migration journal does not reserve every legacy ordinal gap."
        )
    relation_backfills = journal.get("relation_backfills", [])
    if not isinstance(relation_backfills, list) or not all(
        isinstance(item, dict) for item in relation_backfills
    ):
        raise LaunchError("Migration journal relation backfills are invalid.")
    for item in relation_backfills:
        relative_path = item.get("path")
        encoded = item.get("original_contents_base64")
        fields = item.get("fields")
        path = Path(relative_path) if isinstance(relative_path, str) else Path("/")
        if (
            not isinstance(relative_path, str)
            or path.is_absolute()
            or ".." in path.parts
            or len(path.parts) < 3
            or path.parts[0] != "tasks"
            or path.suffix != ".md"
            or not isinstance(encoded, str)
            or not isinstance(fields, list)
            or not all(
                isinstance(field, str)
                and field in {"parent_task_uuid", "required_task_uuid"}
                for field in fields
            )
        ):
            raise LaunchError(
                "Migration journal contains an invalid relation backfill."
            )
        try:
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise LaunchError(
                "Migration journal has invalid relation backup data."
            ) from exc


def _read_journal(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(
            f"Invalid task-directory migration journal {path}: {exc}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("object_type") != "task_directory_migration"
        or payload.get("from_layout") != 5
        or payload.get("to_layout") != 6
        or payload.get("status") not in {"prepared", "complete", "rolled_back"}
    ):
        raise LaunchError(
            f"Task-directory migration journal {path} has invalid schema."
        )
    _journal_list(payload, "task_renames")
    _journal_list(payload, "tombstone_renames")
    _journal_list(payload, "reservation_creates")
    _validate_journal_entries(payload)
    return payload


def _write_journal(path: Path, journal: dict[str, object]) -> None:
    atomic_write_text(path, json.dumps(journal, indent=2, sort_keys=True) + "\n")

"""Stable UUIDv7 storage identities and derived numeric task aliases."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from filelock import FileLock

from taskledger.errors import LaunchError
from taskledger.ids import TASK_ID_FORMAT, parse_uuid7, uuid7
from taskledger.storage.frontmatter import read_markdown_front_matter

if TYPE_CHECKING:
    from taskledger.storage.task_store import V2Paths

IdentityState = Literal["live", "tombstone", "reserved", "incomplete"]
LEGACY_UUID7_EPOCH_MS = 946_684_800_000  # 2000-01-01T00:00:00Z
AMBIGUOUS_LEGACY_TASK_REF = "TASKLEDGER_AMBIGUOUS_LEGACY_TASK_REF"
LEGACY_GAP_CREATED_AT = "2000-01-01T00:00:00+00:00"
_UUID7_RANDOM_BITS = 74


@dataclass(frozen=True, slots=True)
class TaskIdentity:
    task_uuid: UUID
    task_id: str
    number: int
    path: Path
    state: IdentityState


@dataclass(frozen=True, slots=True)
class TaskIdentityInventory:
    entries: tuple[TaskIdentity, ...]
    by_uuid: Mapping[UUID, TaskIdentity]
    by_task_id: Mapping[str, TaskIdentity]
    next_task_id: str


@dataclass(frozen=True, slots=True)
class TaskAllocation:
    task_uuid: UUID
    task_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class _IdentitySource:
    task_uuid: UUID
    path: Path
    state: IdentityState


def deterministic_legacy_task_uuid(
    *,
    project_uuid: str,
    ledger_ref: str,
    legacy_task_id: str,
    created_at: str,
) -> UUID:
    """Build an order-preserving UUIDv7 for a legacy numeric task allocation.

    This deterministic packing is migration-only. The synthetic timestamp keeps
    legacy task numbers ordered before normal UUIDv7 allocations; stable hash
    entropy distinguishes divergent tasks that reused the same legacy number.
    """
    try:
        project = str(UUID(project_uuid))
        parsed_id = TASK_ID_FORMAT.parse_parts(legacy_task_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise LaunchError(
            "Invalid project UUID or legacy task ID for migration."
        ) from exc
    if TASK_ID_FORMAT.format(parsed_id.number) != legacy_task_id:
        raise LaunchError(f"Non-canonical legacy task ID {legacy_task_id!r}.")
    if parsed_id.number < 1:
        raise LaunchError("Legacy task numbers must be positive.")
    if not ledger_ref.strip() or not created_at.strip():
        raise LaunchError(
            "Legacy task UUID migration requires ledger_ref and created_at."
        )

    timestamp_ms = LEGACY_UUID7_EPOCH_MS + parsed_id.number
    if timestamp_ms >= 1 << 48:
        raise LaunchError("Legacy task number exceeds UUIDv7 timestamp capacity.")
    seed = f"{project}\0{ledger_ref}\0{legacy_task_id}\0{created_at}".encode()
    entropy = int.from_bytes(hashlib.sha256(seed).digest(), "big") & (
        (1 << _UUID7_RANDOM_BITS) - 1
    )
    rand_a = entropy >> 62
    rand_b = entropy & ((1 << 62) - 1)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return parse_uuid7(UUID(int=value))


def missing_legacy_task_ids(existing_ids: Iterable[str]) -> tuple[str, ...]:
    """Return unrepresented numeric slots below the highest legacy allocation."""
    existing_numbers: set[int] = set()
    for task_id in existing_ids:
        try:
            parts = TASK_ID_FORMAT.parse_parts(task_id)
        except ValueError as exc:
            raise LaunchError(f"Invalid legacy task ID {task_id!r}.") from exc
        if parts.number < 1:
            raise LaunchError("Legacy task numbers must be positive.")
        if TASK_ID_FORMAT.format(parts.number) != task_id:
            raise LaunchError(f"Non-canonical legacy task ID {task_id!r}.")
        existing_numbers.add(parts.number)
    if not existing_numbers:
        return ()
    highest_number = max(existing_numbers)
    missing_count = highest_number - len(existing_numbers)
    if missing_count > 10_000:
        raise LaunchError(
            "Legacy task identity inventory has more than 10,000 "
            "unrecorded numeric slots; "
            "repair the allocation history before migration."
        )
    return tuple(
        TASK_ID_FORMAT.format(number)
        for number in range(1, max(existing_numbers) + 1)
        if number not in existing_numbers
    )


def _legacy_id_for_source(paths: V2Paths, source: _IdentitySource) -> str | None:
    if source.path.parent == paths.tasks_dir and source.path.name.startswith("task-"):
        return source.path.name
    tombstones_dir = paths.ledger_dir / "tombstones"
    if (
        source.path.parent == tombstones_dir
        and source.path.suffix == ".toml"
        and source.path.stem.startswith("task-")
    ):
        return source.path.stem
    return None


def scan_task_identity_inventory(paths: V2Paths) -> TaskIdentityInventory:
    """Scan canonical task bundles and identity tombstones once."""
    sources = [*_scan_task_directories(paths), *_scan_identity_tombstones(paths)]
    legacy_ids = {
        task_id
        for source in sources
        if (task_id := _legacy_id_for_source(paths, source)) is not None
    }
    missing_ids = missing_legacy_task_ids(legacy_ids)
    if missing_ids:
        project_uuid = _project_uuid_for_paths(paths)
        tombstones_dir = paths.ledger_dir / "tombstones"
        for task_id in missing_ids:
            task_uuid = deterministic_legacy_task_uuid(
                project_uuid=project_uuid,
                ledger_ref=paths.ledger_ref,
                legacy_task_id=task_id,
                created_at=LEGACY_GAP_CREATED_AT,
            )
            sources.append(
                _IdentitySource(
                    task_uuid,
                    tombstones_dir / f"{task_uuid}.toml",
                    "reserved",
                )
            )
    by_uuid_source: dict[UUID, _IdentitySource] = {}
    for source in sources:
        previous = by_uuid_source.get(source.task_uuid)
        if previous is not None:
            raise LaunchError(
                f"Duplicate task UUID identity {source.task_uuid}: {previous.path} and "
                f"{source.path}."
            )
        by_uuid_source[source.task_uuid] = source

    ordered_sources = sorted(sources, key=lambda item: item.task_uuid.int)
    entries = tuple(
        TaskIdentity(
            task_uuid=source.task_uuid,
            task_id=TASK_ID_FORMAT.format(number),
            number=number,
            path=source.path,
            state=source.state,
        )
        for number, source in enumerate(ordered_sources, start=1)
    )
    by_uuid = {entry.task_uuid: entry for entry in entries}
    by_task_id = {entry.task_id: entry for entry in entries}
    return TaskIdentityInventory(
        entries=entries,
        by_uuid=MappingProxyType(by_uuid),
        by_task_id=MappingProxyType(by_task_id),
        next_task_id=TASK_ID_FORMAT.format(len(entries) + 1),
    )


def _scan_task_directories(paths: V2Paths) -> list[_IdentitySource]:
    if not paths.tasks_dir.exists():
        return []
    entries = sorted(paths.tasks_dir.iterdir(), key=lambda item: item.name)
    for entry in entries:
        if entry.is_symlink():
            raise LaunchError(f"Task identity path is a symlink: {entry}")
    legacy_entries = [entry for entry in entries if entry.name.startswith("task-")]
    project_uuid = _project_uuid_for_paths(paths) if legacy_entries else None
    sources: list[_IdentitySource] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("task-"):
            task_id, source = _legacy_directory_source(entry)
            assert project_uuid is not None
            task_uuid = deterministic_legacy_task_uuid(
                project_uuid=project_uuid,
                ledger_ref=paths.ledger_ref,
                legacy_task_id=task_id,
                created_at=source[1],
            )
            sources.append(_IdentitySource(task_uuid, entry, source[0]))
            continue
        if len(entry.name) == 36 and entry.name.count("-") == 4:
            sources.append(_uuid_directory_source(entry))
    return sources


def _legacy_directory_source(entry: Path) -> tuple[str, tuple[IdentityState, str]]:
    task_id, _ = _parse_legacy_task_id(entry.name, entry)
    task_path = entry / "task.md"
    if not task_path.is_file():
        state: IdentityState = "reserved" if not any(entry.iterdir()) else "incomplete"
        return task_id, (state, "legacy-reservation")
    metadata, _ = read_markdown_front_matter(task_path)
    if metadata.get("object_type") != "task":
        raise LaunchError(f"Task record {task_path} has object_type other than 'task'.")
    if metadata.get("id") != task_id:
        raise LaunchError(
            f"Task record {task_path} id does not match its legacy directory {task_id}."
        )
    created_at = metadata.get("created_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    if not isinstance(created_at, str) or not created_at.strip():
        raise LaunchError(f"Task record {task_path} has no valid created_at.")
    return task_id, ("live", created_at)


def _uuid_directory_source(entry: Path) -> _IdentitySource:
    try:
        task_uuid = parse_uuid7(entry.name)
    except ValueError as exc:
        raise LaunchError(
            f"Malformed task identity directory {entry}: expected canonical UUIDv7."
        ) from exc
    if str(task_uuid) != entry.name:
        raise LaunchError(f"Non-canonical UUIDv7 task directory name: {entry.name!r}.")
    task_path = entry / "task.md"
    if task_path.is_file():
        metadata, _ = read_markdown_front_matter(task_path)
        if metadata.get("object_type") != "task":
            raise LaunchError(
                f"Task record {task_path} has object_type other than 'task'."
            )
        state: IdentityState = "live"
    else:
        state = "reserved" if not any(entry.iterdir()) else "incomplete"
    return _IdentitySource(task_uuid, entry, state)


def _scan_identity_tombstones(paths: V2Paths) -> list[_IdentitySource]:
    tombstones_dir = paths.ledger_dir / "tombstones"
    if not tombstones_dir.exists():
        return []
    entries = sorted(tombstones_dir.iterdir(), key=lambda item: item.name)
    legacy_entries = [entry for entry in entries if entry.stem.startswith("task-")]
    project_uuid = _project_uuid_for_paths(paths) if legacy_entries else None
    sources: list[_IdentitySource] = []
    for entry in entries:
        if not entry.is_file() or entry.suffix != ".toml":
            raise LaunchError(f"Malformed task identity tombstone path: {entry}")
        if entry.stem.startswith("task-"):
            assert project_uuid is not None
            task_uuid = _legacy_tombstone_uuid(entry, paths, project_uuid)
        else:
            task_uuid = _uuid_tombstone_uuid(entry)
        sources.append(_IdentitySource(task_uuid, entry, "tombstone"))
    return sources


def _legacy_tombstone_uuid(entry: Path, paths: V2Paths, project_uuid: str) -> UUID:
    task_id, _ = _parse_legacy_task_id(entry.stem, entry)
    document = _read_toml(entry)
    if (
        document.get("schema_version") != 1
        or document.get("id") != task_id
        or document.get("object_type") != "task_id_tombstone"
    ):
        raise LaunchError(f"Legacy task tombstone {entry} has invalid schema.")
    created_at = document.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise LaunchError(f"Legacy task tombstone {entry} has no created_at.")
    return deterministic_legacy_task_uuid(
        project_uuid=project_uuid,
        ledger_ref=paths.ledger_ref,
        legacy_task_id=task_id,
        created_at=created_at,
    )


def _uuid_tombstone_uuid(entry: Path) -> UUID:
    try:
        task_uuid = parse_uuid7(entry.stem)
    except ValueError as exc:
        raise LaunchError(
            f"Malformed task identity tombstone filename: {entry.name}"
        ) from exc
    if str(task_uuid) != entry.stem:
        raise LaunchError(f"Non-canonical UUIDv7 tombstone filename: {entry.name}.")
    document = _read_toml(entry)
    if (
        document.get("schema_version") != 2
        or document.get("object_type") != "task_identity_tombstone"
        or document.get("task_uuid") != str(task_uuid)
        or not isinstance(document.get("reason"), str)
        or not isinstance(document.get("created_at"), str)
    ):
        raise LaunchError(f"Task identity tombstone {entry} has invalid schema.")
    return task_uuid


def _directory_children_fingerprint(path: Path) -> tuple[tuple[str, int], ...]:
    if not path.is_dir():
        return ()
    return tuple(
        (entry.name, entry.lstat().st_mtime_ns)
        for entry in sorted(path.iterdir(), key=lambda item: item.name)
    )


@lru_cache(maxsize=128)
@lru_cache(maxsize=128)
def _cached_task_identity_inventory(
    paths: V2Paths,
    tasks_fingerprint: tuple[tuple[str, int], ...],
    tombstones_fingerprint: tuple[tuple[str, int], ...],
) -> TaskIdentityInventory:
    del tasks_fingerprint, tombstones_fingerprint
    return scan_task_identity_inventory(paths)


def task_identity_inventory(paths: V2Paths) -> TaskIdentityInventory:
    """Return a cached identity inventory invalidated by canonical changes."""
    tasks_fingerprint = _directory_children_fingerprint(paths.tasks_dir)
    tombstones_fingerprint = _directory_children_fingerprint(
        paths.ledger_dir / "tombstones"
    )
    return _cached_task_identity_inventory(
        paths, tasks_fingerprint, tombstones_fingerprint
    )


def invalidate_task_identity_inventory() -> None:
    """Clear command-process identity caches after an identity-changing write."""
    _cached_task_identity_inventory.cache_clear()


def task_uuid_from_ref(paths: V2Paths, ref: str) -> UUID:
    return task_identity_for_ref(paths, ref).task_uuid


def task_id_for_uuid(paths: V2Paths, task_uuid: UUID | str) -> str:
    parsed = _parse_uuid(task_uuid)
    identity = task_identity_inventory(paths).by_uuid.get(parsed)
    if identity is None:
        raise LaunchError(f"Unknown task UUID {parsed}.")
    return identity.task_id


def task_path_for_uuid(paths: V2Paths, task_uuid: UUID | str) -> Path:
    parsed = _parse_uuid(task_uuid)
    identity = task_identity_inventory(paths).by_uuid.get(parsed)
    return identity.path if identity is not None else paths.tasks_dir / str(parsed)


def task_identity_for_ref(paths: V2Paths, ref: str) -> TaskIdentity:
    inventory = task_identity_inventory(paths)
    try:
        parsed_uuid = parse_uuid7(ref)
    except ValueError:
        identity = inventory.by_task_id.get(ref)
        if identity is None:
            raise LaunchError(f"Unknown task reference {ref!r}.") from None
        return identity
    identity = inventory.by_uuid.get(parsed_uuid)
    if identity is None:
        raise LaunchError(f"Unknown task UUID {parsed_uuid}.")
    return identity


def legacy_task_identity_for_ref(paths: V2Paths, ref: str) -> TaskIdentity:
    """Resolve a stored numeric reference using deterministic migration identity."""
    try:
        parts = TASK_ID_FORMAT.parse_parts(ref)
    except ValueError as exc:
        raise LaunchError(f"Invalid legacy task reference {ref!r}.") from exc
    if TASK_ID_FORMAT.format(parts.number) != ref or parts.number < 1:
        raise LaunchError(f"Non-canonical legacy task reference {ref!r}.")

    inventory = task_identity_inventory(paths)
    legacy_timestamp = LEGACY_UUID7_EPOCH_MS + parts.number
    candidates = tuple(
        identity
        for identity in inventory.entries
        if identity.task_uuid.int >> 80 == legacy_timestamp
    )
    if len(candidates) > 1:
        uuids = ", ".join(str(item.task_uuid) for item in candidates)
        raise LaunchError(
            f"Legacy ref {ref!r} is ambiguous after UUID migration: {uuids}.",
            code=AMBIGUOUS_LEGACY_TASK_REF,
        )
    if candidates:
        return candidates[0]

    identity = inventory.by_task_id.get(ref)
    if identity is None:
        raise LaunchError(f"Unknown task reference {ref!r}.")
    return identity


def task_identity_for_stored_ref(
    paths: V2Paths, *, task_id: str, task_uuid: str | None
) -> TaskIdentity:
    """Resolve a persisted task relationship, preferring its authoritative UUID."""
    if task_uuid is not None:
        return task_identity_for_ref(paths, task_uuid)
    return legacy_task_identity_for_ref(paths, task_id)


def allocate_task_identity(paths: V2Paths, *, max_attempts: int = 32) -> TaskAllocation:
    """Reserve a fresh UUIDv7 task directory and derive its current display ID."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    lock_path = paths.ledger_dir / ".task-identity-allocation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        inventory = scan_task_identity_inventory(paths)
        if any(
            identity.path.name.startswith("task-") for identity in inventory.entries
        ):
            raise LaunchError(
                "Legacy task directories must be migrated before UUID allocation."
            )
        for _ in range(max_attempts):
            task_uuid = parse_uuid7(uuid7())
            task_dir = paths.tasks_dir / str(task_uuid)
            try:
                task_dir.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                continue
            updated = scan_task_identity_inventory(paths)
            identity = updated.by_uuid[task_uuid]
            return TaskAllocation(task_uuid, identity.task_id, task_dir)
    raise LaunchError(
        "Unable to allocate a UUIDv7 task directory after repeated collisions."
    )


def _parse_legacy_task_id(value: str, path: Path) -> tuple[str, int]:
    try:
        parts = TASK_ID_FORMAT.parse_parts(value)
    except ValueError as exc:
        raise LaunchError(
            f"Malformed legacy task allocation path {path}: {value!r}."
        ) from exc
    canonical = TASK_ID_FORMAT.format(parts.number)
    if canonical != value:
        raise LaunchError(f"Non-canonical legacy task ID {value!r} at {path}.")
    if parts.number < 1:
        raise LaunchError(f"Legacy task ID {value!r} must be positive.")
    return canonical, parts.number


def _parse_uuid(value: UUID | str) -> UUID:
    try:
        return parse_uuid7(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise LaunchError(f"Invalid task UUID {value!r}; expected UUIDv7.") from exc


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
    raise LaunchError("Deterministic UUIDv7 migration requires a project UUID.")


def _read_toml(path: Path) -> dict[str, object]:
    try:
        tomllib = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        tomllib = importlib.import_module("tomli")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Invalid task identity tombstone {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LaunchError(
            f"Invalid task identity tombstone {path}: expected a TOML table."
        )
    return data


def write_task_identity_tombstone(
    paths: V2Paths,
    task_uuid: UUID | str,
    *,
    reason: str,
    quarantined_path: str,
) -> Path:
    """Record a quarantined UUID task directory as a durable reservation."""
    import json

    from taskledger.storage.atomic import atomic_write_text
    from taskledger.timeutils import utc_now_iso

    parsed_uuid = _parse_uuid(task_uuid)
    if not reason.strip():
        raise LaunchError("Task identity repair requires a non-empty reason.")
    tombstones_dir = paths.ledger_dir / "tombstones"
    tombstones_dir.mkdir(parents=True, exist_ok=True)
    tombstone_path = tombstones_dir / f"{parsed_uuid}.toml"
    with FileLock(str(paths.ledger_dir / ".task-identity-tombstone.lock")):
        if tombstone_path.exists():
            raise LaunchError(
                f"Task identity tombstone already exists: {tombstone_path}"
            )
        lines = (
            "schema_version = 2",
            'object_type = "task_identity_tombstone"',
            f"task_uuid = {json.dumps(str(parsed_uuid))}",
            f"reason = {json.dumps(reason.strip())}",
            f"created_at = {json.dumps(utc_now_iso())}",
            f"quarantined_path = {json.dumps(quarantined_path)}",
        )
        atomic_write_text(tombstone_path, "\n".join(lines) + "\n")
    invalidate_task_identity_inventory()
    return tombstone_path


__all__ = [
    "AMBIGUOUS_LEGACY_TASK_REF",
    "LEGACY_UUID7_EPOCH_MS",
    "TaskAllocation",
    "TaskIdentity",
    "TaskIdentityInventory",
    "allocate_task_identity",
    "deterministic_legacy_task_uuid",
    "invalidate_task_identity_inventory",
    "legacy_task_identity_for_ref",
    "scan_task_identity_inventory",
    "task_id_for_uuid",
    "task_identity_for_ref",
    "task_identity_for_stored_ref",
    "task_identity_inventory",
    "task_path_for_uuid",
    "task_uuid_from_ref",
    "write_task_identity_tombstone",
]

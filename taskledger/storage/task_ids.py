"""Strict authoritative task-ID inventory and exclusive allocation."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from taskledger.errors import LaunchError
from taskledger.ids import TASK_ID_FORMAT
from taskledger.storage.frontmatter import read_markdown_front_matter
from taskledger.storage.task_store import V2Paths, require_v2_layout


@dataclass(frozen=True, slots=True)
class TaskIdAllocation:
    task_id: str
    number: int
    source: Literal["task", "tombstone"]
    path: Path


@dataclass(frozen=True, slots=True)
class IncompleteTaskAllocation:
    task_id: str
    path: Path
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskIdInventory:
    allocations: tuple[TaskIdAllocation, ...]
    highest_number: int
    next_task_id: str
    empty_reservations: tuple[Path, ...] = ()
    incomplete_allocations: tuple[IncompleteTaskAllocation, ...] = ()


def _parse_canonical_task_id(value: str, *, path: Path) -> tuple[str, int]:
    try:
        parts = TASK_ID_FORMAT.parse_parts(value)
    except ValueError as exc:
        raise LaunchError(f"Malformed task allocation path {path}: {value!r}.") from exc
    normalized = TASK_ID_FORMAT.format(parts.number)
    if value != normalized:
        raise LaunchError(f"Non-canonical task ID {value!r} at {path}.")
    return normalized, parts.number


def _scan_task_allocations(
    paths: V2Paths,
) -> tuple[list[TaskIdAllocation], list[Path], list[IncompleteTaskAllocation]]:
    allocations: list[TaskIdAllocation] = []
    empty_reservations: list[Path] = []
    incomplete_allocations: list[IncompleteTaskAllocation] = []
    if paths.tasks_dir.exists():
        for entry in sorted(paths.tasks_dir.iterdir()):
            if not entry.name.startswith("task-"):
                continue
            if entry.is_symlink():
                raise LaunchError(f"Task allocation path is a symlink: {entry}")
            if not entry.is_dir():
                raise LaunchError(f"Task allocation path is not a directory: {entry}")
            task_id, number = _parse_canonical_task_id(entry.name, path=entry)
            task_path = entry / "task.md"
            if not task_path.is_file():
                files = tuple(sorted(path.name for path in entry.iterdir()))
                if not files:
                    empty_reservations.append(entry)
                else:
                    incomplete_allocations.append(
                        IncompleteTaskAllocation(task_id, entry, files)
                    )
                continue
            metadata, _ = read_markdown_front_matter(task_path)
            if metadata.get("object_type") != "task":
                raise LaunchError(
                    f"Task record {task_path} has object_type other than 'task'."
                )
            if metadata.get("id") != task_id:
                raise LaunchError(
                    f"Task record {task_path} id does not match its directory "
                    f"{task_id}."
                )
            allocations.append(TaskIdAllocation(task_id, number, "task", task_path))
    tombstones_dir = paths.ledger_dir / "tombstones"
    if tombstones_dir.exists():
        for entry in sorted(tombstones_dir.iterdir()):
            if not entry.name.startswith("task-"):
                continue
            if not entry.is_file() or entry.suffix != ".toml":
                raise LaunchError(f"Malformed task tombstone path: {entry}")
            task_id, number = _parse_canonical_task_id(entry.stem, path=entry)
            try:
                tomllib = importlib.import_module("tomllib")
            except ModuleNotFoundError:  # pragma: no cover
                tomllib = importlib.import_module("tomli")
            try:
                document = tomllib.loads(entry.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LaunchError(f"Invalid task tombstone {entry}: {exc}") from exc
            if (
                document.get("schema_version") != 1
                or document.get("id") != task_id
                or document.get("object_type") != "task_id_tombstone"
                or not isinstance(document.get("reason"), str)
                or not isinstance(document.get("created_at"), str)
            ):
                raise LaunchError(
                    f"Task tombstone {entry} has invalid schema or required fields."
                )
            allocations.append(TaskIdAllocation(task_id, number, "tombstone", entry))
    return allocations, empty_reservations, incomplete_allocations


def inspect_task_id_inventory(paths: V2Paths) -> TaskIdInventory:
    allocations, empty_reservations, incomplete_allocations = _scan_task_allocations(
        paths
    )
    by_number: dict[int, TaskIdAllocation] = {}
    for allocation in allocations:
        previous = by_number.get(allocation.number)
        if previous is not None:
            raise LaunchError(
                f"Duplicate task allocation {allocation.task_id}: "
                f"{previous.path} and {allocation.path}."
            )
        by_number[allocation.number] = allocation
    ordered = tuple(sorted(allocations, key=lambda item: item.number))
    reserved_numbers = [
        _parse_canonical_task_id(path.name, path=path)[1] for path in empty_reservations
    ]
    incomplete_numbers = [
        _parse_canonical_task_id(item.path.name, path=item.path)[1]
        for item in incomplete_allocations
    ]
    highest = max(
        (*[item.number for item in ordered], *reserved_numbers, *incomplete_numbers),
        default=0,
    )
    return TaskIdInventory(
        allocations=ordered,
        highest_number=highest,
        next_task_id=TASK_ID_FORMAT.format(highest + 1),
        empty_reservations=tuple(empty_reservations),
        incomplete_allocations=tuple(incomplete_allocations),
    )


def write_task_id_tombstone(
    paths: V2Paths,
    task_id: str,
    *,
    reason: str,
    quarantined_path: Path,
) -> Path:
    _parse_canonical_task_id(task_id, path=paths.tasks_dir / task_id)
    if not reason.strip():
        raise LaunchError("Task allocation repair requires a non-empty reason.")
    tombstone_path = paths.ledger_dir / "tombstones" / f"{task_id}.toml"
    relative_quarantine = quarantined_path.relative_to(
        paths.tasks_dir.parent
    ).as_posix()
    if tombstone_path.exists():
        try:
            tomllib = importlib.import_module("tomllib")
        except ModuleNotFoundError:  # pragma: no cover
            tomllib = importlib.import_module("tomli")
        try:
            existing = tomllib.loads(tombstone_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LaunchError(
                f"Invalid task tombstone {tombstone_path}: {exc}"
            ) from exc
        if (
            existing.get("schema_version") == 1
            and existing.get("object_type") == "task_id_tombstone"
            and existing.get("id") == task_id
            and existing.get("quarantined_path") == relative_quarantine
            and isinstance(existing.get("reason"), str)
            and isinstance(existing.get("created_at"), str)
        ):
            return tombstone_path
        raise LaunchError(f"Task tombstone conflicts with repair: {tombstone_path}")
    from taskledger.storage.atomic import atomic_create_text
    from taskledger.timeutils import utc_now_iso

    document = "\n".join(
        (
            "schema_version = 1",
            'object_type = "task_id_tombstone"',
            f"id = {json.dumps(task_id)}",
            f"reason = {json.dumps(reason.strip())}",
            f"created_at = {json.dumps(utc_now_iso())}",
            f"quarantined_path = {json.dumps(relative_quarantine)}",
            "",
        )
    )
    try:
        atomic_create_text(tombstone_path, document)
    except FileExistsError as exc:
        raise LaunchError(f"Task tombstone already exists: {tombstone_path}") from exc
    return tombstone_path


def scan_task_id_inventory(paths: V2Paths) -> TaskIdInventory:
    inventory = inspect_task_id_inventory(paths)
    if inventory.incomplete_allocations:
        allocation = inventory.incomplete_allocations[0]
        raise LaunchError(f"Task allocation {allocation.path} is missing task.md.")
    return inventory


def next_task_id(paths: V2Paths) -> str:
    return scan_task_id_inventory(paths).next_task_id


def reserve_task_directory(paths: V2Paths, task_id: str) -> Path:
    task_dir = paths.tasks_dir / task_id
    try:
        task_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise
    except OSError as exc:
        raise LaunchError(f"Unable to reserve {task_dir}: {exc}") from exc
    return task_dir


def allocate_task_directory(
    workspace_root: Path,
    *,
    max_attempts: int = 32,
) -> tuple[str, Path]:
    return allocate_task_directory_from_paths(
        require_v2_layout(workspace_root), max_attempts=max_attempts
    )


def allocate_task_directory_from_paths(
    paths: V2Paths,
    *,
    max_attempts: int = 32,
) -> tuple[str, Path]:
    for _ in range(max_attempts):
        candidate = scan_task_id_inventory(paths).next_task_id
        try:
            return candidate, reserve_task_directory(paths, candidate)
        except FileExistsError:
            continue
    raise LaunchError(
        "Unable to allocate a task ID after repeated exclusive-create collisions."
    )


def reserve_task_directories(paths: V2Paths, task_ids: list[str]) -> None:
    """Reserve imported task directories with exclusive creation."""
    reserved: list[Path] = []
    try:
        for task_id in task_ids:
            reserved.append(reserve_task_directory(paths, task_id))
    except FileExistsError as exc:
        for directory in reversed(reserved):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise LaunchError(f"Task allocation already exists: {exc.filename}") from exc


__all__ = [
    "IncompleteTaskAllocation",
    "TaskIdAllocation",
    "TaskIdInventory",
    "allocate_task_directory",
    "allocate_task_directory_from_paths",
    "inspect_task_id_inventory",
    "next_task_id",
    "reserve_task_directories",
    "reserve_task_directory",
    "scan_task_id_inventory",
    "write_task_id_tombstone",
]

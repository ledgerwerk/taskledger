"""Strict authoritative task-ID inventory and exclusive allocation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from taskledger.errors import LaunchError
from taskledger.ids import TASK_ID_FORMAT
from taskledger.storage.frontmatter import read_markdown_front_matter
from taskledger.storage.task_store import V2Paths, ensure_v2_layout


@dataclass(frozen=True, slots=True)
class TaskIdAllocation:
    task_id: str
    number: int
    source: Literal["task", "tombstone"]
    path: Path


@dataclass(frozen=True, slots=True)
class TaskIdInventory:
    allocations: tuple[TaskIdAllocation, ...]
    highest_number: int
    next_task_id: str


def _parse_canonical_task_id(value: str, *, path: Path) -> tuple[str, int]:
    try:
        parts = TASK_ID_FORMAT.parse_parts(value)
    except ValueError as exc:
        raise LaunchError(f"Malformed task allocation path {path}: {value!r}.") from exc
    normalized = TASK_ID_FORMAT.format(parts.number)
    if value != normalized:
        raise LaunchError(f"Non-canonical task ID {value!r} at {path}.")
    return normalized, parts.number


def _scan_task_allocations(paths: V2Paths) -> list[TaskIdAllocation]:
    allocations: list[TaskIdAllocation] = []
    if paths.tasks_dir.exists():
        for entry in sorted(paths.tasks_dir.iterdir()):
            if not entry.name.startswith("task-"):
                continue
            if not entry.is_dir():
                raise LaunchError(f"Task allocation path is not a directory: {entry}")
            task_id, number = _parse_canonical_task_id(entry.name, path=entry)
            task_path = entry / "task.md"
            if not task_path.is_file():
                if not any(entry.iterdir()):
                    # An empty directory is an in-flight exclusive reservation.
                    continue
                raise LaunchError(f"Task allocation {entry} is missing task.md.")
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
            stem = entry.stem
            task_id, number = _parse_canonical_task_id(stem, path=entry)
            try:
                tomllib = importlib.import_module("tomllib")
            except ModuleNotFoundError:  # pragma: no cover
                tomllib = importlib.import_module("tomli")
            try:
                document = tomllib.loads(entry.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LaunchError(f"Invalid task tombstone {entry}: {exc}") from exc
            if document.get("id") != task_id:
                raise LaunchError(
                    f"Task tombstone {entry} id does not match its filename."
                )
            if document.get("object_type") != "task_id_tombstone":
                raise LaunchError(f"Task tombstone {entry} has an invalid object_type.")
            allocations.append(TaskIdAllocation(task_id, number, "tombstone", entry))
    return allocations


def scan_task_id_inventory(paths: V2Paths) -> TaskIdInventory:
    allocations = _scan_task_allocations(paths)
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
    highest = ordered[-1].number if ordered else 0
    return TaskIdInventory(
        allocations=ordered,
        highest_number=highest,
        next_task_id=TASK_ID_FORMAT.format(highest + 1),
    )


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
    paths = ensure_v2_layout(workspace_root)
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
    "TaskIdAllocation",
    "TaskIdInventory",
    "allocate_task_directory",
    "next_task_id",
    "reserve_task_directory",
    "reserve_task_directories",
    "scan_task_id_inventory",
]

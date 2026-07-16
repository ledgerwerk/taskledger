"""Taskledger binding for the direct sibling data mount."""

from __future__ import annotations

import importlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from ledgercore import atomic_create_text

from taskledger.errors import LaunchError

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover
    tomllib = importlib.import_module("tomli")

BINDING_FILENAME = ".ledger-project.toml"


@dataclass(frozen=True, slots=True)
class TaskledgerProjectBinding:
    schema_version: int
    project_uuid: str
    ledger: str
    mount: str


def binding_path(data_root: Path) -> Path:
    return data_root / BINDING_FILENAME


def directory_is_effectively_empty(data_root: Path) -> bool:
    return not data_root.exists() or not any(data_root.iterdir())


def read_project_binding(data_root: Path) -> TaskledgerProjectBinding | None:
    path = binding_path(data_root)
    if not path.exists():
        return None
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Invalid Taskledger project binding {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise LaunchError(f"Invalid Taskledger project binding {path}.")
    schema_version = document.get("schema_version")
    raw_uuid = document.get("project_uuid")
    ledger = document.get("ledger")
    mount = document.get("mount")
    if schema_version != 1:
        raise LaunchError(
            f"Taskledger project binding {path} must use schema_version = 1."
        )
    if (
        not isinstance(raw_uuid, str)
        or not isinstance(ledger, str)
        or not isinstance(mount, str)
    ):
        raise LaunchError(f"Taskledger project binding {path} has invalid fields.")
    try:
        project_uuid = str(uuid.UUID(raw_uuid))
    except ValueError as exc:
        raise LaunchError(
            f"Taskledger project binding {path} has an invalid UUID."
        ) from exc
    return TaskledgerProjectBinding(
        schema_version=1,
        project_uuid=project_uuid,
        ledger=ledger,
        mount=mount,
    )


def validate_project_binding(
    data_root: Path,
    *,
    project_uuid: str,
) -> TaskledgerProjectBinding:
    try:
        expected_uuid = str(uuid.UUID(project_uuid))
    except ValueError as exc:
        raise LaunchError(f"Invalid project UUID {project_uuid!r}.") from exc
    binding = read_project_binding(data_root)
    if binding is None:
        if directory_is_effectively_empty(data_root):
            raise LaunchError(
                f"Taskledger data root {data_root} is not bound to a project. "
                "Run `taskledger init` to create its project binding."
            )
        raise LaunchError(
            f"Taskledger data root {data_root} is non-empty and has no "
            f"{BINDING_FILENAME}; refusing to adopt it."
        )
    if binding.project_uuid != expected_uuid:
        raise LaunchError(
            f"Taskledger project binding UUID mismatch at {binding_path(data_root)}: "
            f"expected {expected_uuid}, found {binding.project_uuid}."
        )
    if binding.ledger != "taskledger":
        raise LaunchError(
            f"Taskledger project binding {binding_path(data_root)} has ledger "
            f"{binding.ledger!r}, expected 'taskledger'."
        )
    if binding.mount != "data":
        raise LaunchError(
            f"Taskledger project binding {binding_path(data_root)} has mount "
            f"{binding.mount!r}, expected 'data'."
        )
    return binding


def create_project_binding(
    data_root: Path,
    *,
    project_uuid: str,
) -> TaskledgerProjectBinding:
    try:
        normalized_uuid = str(uuid.UUID(project_uuid))
    except ValueError as exc:
        raise LaunchError(f"Invalid project UUID {project_uuid!r}.") from exc
    data_root.mkdir(parents=True, exist_ok=True)
    existing = read_project_binding(data_root)
    if existing is not None:
        return validate_project_binding(data_root, project_uuid=normalized_uuid)
    if any(data_root.iterdir()):
        raise LaunchError(
            "Taskledger data root "
            f"{data_root} is non-empty and unbound; refusing to adopt it."
        )
    binding = TaskledgerProjectBinding(1, normalized_uuid, "taskledger", "data")
    contents = (
        "schema_version = 1\n"
        f'project_uuid = "{binding.project_uuid}"\n'
        'ledger = "taskledger"\n'
        'mount = "data"\n'
    )
    try:
        atomic_create_text(binding_path(data_root), contents)
    except FileExistsError:
        pass
    return validate_project_binding(data_root, project_uuid=normalized_uuid)


__all__ = [
    "BINDING_FILENAME",
    "TaskledgerProjectBinding",
    "binding_path",
    "create_project_binding",
    "directory_is_effectively_empty",
    "read_project_binding",
    "validate_project_binding",
]

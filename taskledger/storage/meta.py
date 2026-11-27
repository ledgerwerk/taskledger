"""Read and write Taskledger storage metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from taskledger.domain.states import (
    TASKLEDGER_RECORD_SCHEMA_VERSION,
    TASKLEDGER_STORAGE_LAYOUT_VERSION,
)
from taskledger.errors import LaunchError
from taskledger.storage.paths import resolve_taskledger_root
from taskledger.storage.yaml_store import load_yaml_object, write_yaml_object
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class StorageMeta:
    storage_layout_version: int = TASKLEDGER_STORAGE_LAYOUT_VERSION
    record_schema_version: int = TASKLEDGER_RECORD_SCHEMA_VERSION
    created_with_taskledger: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    last_migrated_with_taskledger: str | None = None
    last_migrated_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "storage_layout_version": self.storage_layout_version,
            "record_schema_version": self.record_schema_version,
            "created_with_taskledger": self.created_with_taskledger,
            "created_at": self.created_at,
            "last_migrated_with_taskledger": self.last_migrated_with_taskledger,
            "last_migrated_at": self.last_migrated_at,
        }


def _storage_yaml_path(workspace_root: Path) -> Path:
    return resolve_taskledger_root(workspace_root) / "storage.yaml"


def read_storage_meta(workspace_root: Path) -> StorageMeta | None:
    path = _storage_yaml_path(workspace_root)
    if not path.exists():
        return None
    payload = load_yaml_object(path, "storage.yaml")
    return StorageMeta(
        storage_layout_version=_int_field(payload, "storage_layout_version"),
        record_schema_version=_int_field(payload, "record_schema_version"),
        created_with_taskledger=_str_field(payload, "created_with_taskledger"),
        created_at=_str_field(payload, "created_at"),
        last_migrated_with_taskledger=_optional_str(
            payload, "last_migrated_with_taskledger"
        ),
        last_migrated_at=_optional_str(payload, "last_migrated_at"),
    )


def write_storage_meta(workspace_root: Path, meta: StorageMeta) -> StorageMeta:
    path = _storage_yaml_path(workspace_root)
    write_yaml_object(path, meta.to_dict())
    return meta


def require_storage_meta(workspace_root: Path) -> StorageMeta:
    meta = read_storage_meta(workspace_root)
    if meta is None:
        raise LaunchError(
            "Missing storage.yaml. Run 'taskledger init' or 'taskledger migrate apply'."
        )
    if meta.storage_layout_version > TASKLEDGER_STORAGE_LAYOUT_VERSION:
        raise LaunchError(
            f"Storage layout version {meta.storage_layout_version} is newer than "
            f"supported {TASKLEDGER_STORAGE_LAYOUT_VERSION}. Upgrade taskledger."
        )
    return meta


def _int_field(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise LaunchError(f"Missing or invalid '{key}' in storage.yaml.")
    return value


def _str_field(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise LaunchError(f"Missing or invalid '{key}' in storage.yaml.")
    return value


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None

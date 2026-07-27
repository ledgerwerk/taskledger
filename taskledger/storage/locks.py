from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from taskledger.domain.models import TaskLock
from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_create_text


def _dump_yaml_text(payload: dict[str, object]) -> str:
    """Render a mapping to YAML text for exclusive-create paths."""
    import yaml

    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def write_lock(path: Path, lock: TaskLock) -> None:
    atomic_create_text(
        path,
        _dump_yaml_text(lock.to_dict()),
    )


def update_lock(path: Path, lock: TaskLock) -> None:
    """Update an existing lock, or create if it doesn't exist."""
    from taskledger.storage.yaml_store import write_yaml_object

    write_yaml_object(path, lock.to_dict())


def read_lock(path: Path) -> TaskLock | None:
    from taskledger.storage.yaml_store import load_yaml_object

    if not path.exists():
        return None
    payload = load_yaml_object(path, f"lock file {path}", missing="empty")
    return TaskLock.from_dict(payload)


def remove_lock(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        raise LaunchError(f"Failed to remove lock {path}: {exc}") from exc


def lock_is_expired(lock: TaskLock, *, now: datetime | None = None) -> bool:
    if lock.expires_at is None:
        return False
    try:
        expires_at = datetime.fromisoformat(lock.expires_at)
    except ValueError as exc:
        raise LaunchError(
            f"Invalid lock expiration on {lock.task_id} "
            f"({lock.lock_id}): {lock.expires_at}"
        ) from exc
    reference = now or datetime.now(timezone.utc)
    return expires_at < reference


def lock_status(lock: TaskLock | None) -> dict[str, object]:
    if lock is None:
        return {
            "present": False,
            "active": False,
            "expired": False,
            "holder": None,
            "stage": None,
            "run_id": None,
            "created_at": None,
            "expires_at": None,
        }
    expired = lock_is_expired(lock)
    return {
        "present": True,
        "active": not expired,
        "expired": expired,
        "holder": lock.holder.to_dict(),
        "stage": lock.stage,
        "run_id": lock.run_id,
        "created_at": lock.created_at,
        "expires_at": lock.expires_at,
    }

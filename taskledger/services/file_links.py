from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from taskledger.domain.models import FileLink, LinkCollection
from taskledger.errors import LaunchError
from taskledger.services import tasks as _tasks
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    resolve_task,
    resolve_v2_paths,
    save_links,
    save_task,
)
from taskledger.timeutils import utc_now_iso


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    target_type: str
    hash: str | None
    size: int | None
    mtime: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "exists": self.exists,
            "target_type": self.target_type,
            "hash": self.hash,
            "size": self.size,
            "mtime": self.mtime,
        }


def _resolve_link_target(workspace_root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return workspace_root / candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _mtime_iso(path: Path) -> str:
    stat = path.stat()
    return datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()


def snapshot_path(path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(
            exists=False,
            target_type="missing",
            hash=None,
            size=None,
            mtime=None,
        )
    stat = path.stat()
    if path.is_file():
        return FileSnapshot(
            exists=True,
            target_type="file",
            hash=_sha256_file(path),
            size=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )
    if path.is_dir():
        return FileSnapshot(
            exists=True,
            target_type="dir",
            hash=None,
            size=None,
            mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )
    return FileSnapshot(
        exists=True,
        target_type="other",
        hash=None,
        size=None,
        mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    )


def with_baseline(link: FileLink, workspace_root: Path) -> FileLink:
    snapshot = snapshot_path(_resolve_link_target(workspace_root, link.path))
    return replace(
        link,
        target_type=snapshot.target_type,
        baseline_hash=snapshot.hash,
        baseline_size=snapshot.size,
        baseline_mtime=snapshot.mtime,
        baseline_exists=snapshot.exists,
        updated_at=utc_now_iso(),
    )


def _baseline_for_link(link: FileLink) -> dict[str, object]:
    return {
        "exists": link.baseline_exists,
        "target_type": link.target_type,
        "hash": link.baseline_hash,
        "size": link.baseline_size,
        "mtime": link.baseline_mtime,
    }


def _status_and_reason(link: FileLink, current: FileSnapshot) -> tuple[str, str]:
    if link.baseline_exists is None:
        return ("unbaselined", "baseline missing")
    if link.baseline_exists is False:
        if current.exists:
            return ("new", "path now exists")
        return ("unchanged", "baseline missing and path still missing")
    if not current.exists:
        return ("deleted", "path deleted")
    if link.target_type != current.target_type:
        return ("modified", "target type changed")
    if current.target_type == "file":
        if link.baseline_hash and current.hash and link.baseline_hash != current.hash:
            return ("modified", "hash changed")
        if (
            link.baseline_hash is None or current.hash is None
        ) and link.baseline_size != current.size:
            return ("modified", "size changed")
        return ("unchanged", "baseline matches current file")
    if current.target_type == "dir":
        return ("unchanged", "directory unchanged")
    return ("unchanged", f"{current.target_type} unchanged")


def status_for_link(link: FileLink, workspace_root: Path) -> dict[str, object]:
    current = snapshot_path(_resolve_link_target(workspace_root, link.path))
    status, reason = _status_and_reason(link, current)
    return {
        "path": link.path,
        "kind": link.kind,
        "label": link.label,
        "required_for_validation": link.required_for_validation,
        "target_type": current.target_type if current.exists else link.target_type,
        "status": status,
        "baseline": _baseline_for_link(link),
        "current": current.to_dict(),
        "reason": reason,
    }


def file_status(workspace_root: Path, task_ref: str) -> dict[str, object]:
    task = _tasks._task_with_sidecars(
        workspace_root,
        resolve_task(workspace_root, task_ref),
    )
    links = [status_for_link(link, workspace_root) for link in task.file_links]
    summary = {
        "new": 0,
        "modified": 0,
        "deleted": 0,
        "unchanged": 0,
        "unbaselined": 0,
    }
    for link in links:
        status = link.get("status")
        if isinstance(status, str) and status in summary:
            summary[status] += 1
    return {
        "kind": "task_file_status",
        "task_id": task.id,
        "summary": summary,
        "links": links,
    }


def refresh_file_baseline(
    workspace_root: Path,
    task_ref: str,
    path: str,
    *,
    reason: str,
) -> dict[str, object]:
    if not reason.strip():
        raise LaunchError("file refresh requires --reason.")
    task = _tasks._task_with_sidecars(
        workspace_root,
        resolve_task(workspace_root, task_ref),
    )
    _tasks._ensure_not_archived(task, operation="refresh file baseline on")
    updated_links: list[FileLink] = []
    refreshed: FileLink | None = None
    for link in task.file_links:
        if link.path == path:
            refreshed = with_baseline(link, workspace_root)
            updated_links.append(refreshed)
            continue
        updated_links.append(link)
    if refreshed is None:
        raise LaunchError(f"File link not found: {path}")
    updated = replace(
        task,
        file_links=tuple(updated_links),
        updated_at=utc_now_iso(),
    )
    save_links(
        workspace_root,
        LinkCollection(task_id=updated.id, links=updated.file_links),
    )
    save_task(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        updated.id,
        "file.baseline_refreshed",
        {
            "path": path,
            "reason": reason.strip(),
            "target_type": refreshed.target_type,
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return {
        "kind": "file_baseline_refreshed",
        "task_id": updated.id,
        "path": path,
        "reason": reason.strip(),
        "link": refreshed.to_dict(),
    }

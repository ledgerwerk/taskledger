from __future__ import annotations

from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.services.storage_locations import (
    build_storage_location_report,
    build_sync_preflight_report,
    build_sync_status_report,
    move_taskledger_storage,
    sync_commit_storage,
)
from taskledger.storage.project_context import load_project_context


def storage_where(workspace_root: Path) -> dict[str, object]:
    return build_storage_location_report(workspace_root).to_dict()


def storage_move(
    workspace_root: Path,
    *,
    target: Path,
    mode: str,
    adopt_existing: bool = False,
    force: bool = False,
) -> dict[str, object]:
    return move_taskledger_storage(
        workspace_root,
        target=target,
        mode=mode,
        adopt_existing=adopt_existing,
        force=force,
    ).to_dict()


def sync_preflight(workspace_root: Path) -> dict[str, object]:
    return build_sync_preflight_report(workspace_root).to_dict()


def sync_status(workspace_root: Path) -> dict[str, object]:
    return build_sync_status_report(workspace_root).to_dict()


def sync_commit(workspace_root: Path, *, message: str) -> dict[str, object]:
    return sync_commit_storage(workspace_root, message=message).to_dict()


__all__ = [
    "storage_where",
    "storage_move",
    "storage_path",
    "sync_preflight",
    "sync_status",
    "sync_commit",
]


def storage_path(workspace_root: Path, mount: str) -> dict[str, object]:
    if mount not in {"data", "logs", "indexes"}:
        raise LaunchError("Unknown mount. Expected one of: data, logs, indexes.")
    context = load_project_context(workspace_root)
    if context.layout is None:
        raise LaunchError(
            "Mount paths are unavailable in legacy mode; "
            "use `taskledger migrate` first."
        )
    resolved = context.layout.mounts["data" if mount == "logs" else mount]
    return {
        "kind": "storage_path",
        "mount": mount,
        "path": str(resolved.path),
        "storage": str(resolved.storage),
        "scope": str(resolved.scope),
        "source": str(resolved.source),
        "initialized": resolved.path.exists(),
        "mode": context.mode,
        "storage_mode": (
            "sibling" if str(resolved.storage) == "workspace" else "repository"
        ),
    }

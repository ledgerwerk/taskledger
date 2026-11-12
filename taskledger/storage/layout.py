"""Read and mutation entry points for V2 Taskledger storage paths."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from taskledger.errors import LaunchError

if TYPE_CHECKING:
    from taskledger.storage.task_store import V2Paths


def require_v2_layout(workspace_root: Path) -> V2Paths:
    """Resolve durable project state without creating directories or indexes."""
    from taskledger.storage.paths import probe_taskledger_project
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    probe = probe_taskledger_project(workspace_root)
    required = (
        (paths.project_dir, paths.tasks_dir)
        if probe.source == "canonical"
        else (paths.project_dir, paths.tasks_dir, paths.events_dir)
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        raise LaunchError(
            "Project state is not initialized. Missing: "
            + ", ".join(str(path) for path in missing)
            + ". Run `taskledger init`."
        )
    return paths


def require_mutable_v2_layout(
    workspace_root: Path,
    *,
    allow_legacy: bool = True,
) -> V2Paths:
    """Prepare mutable project state and return its V2 storage paths."""
    from taskledger.storage.project_context import require_mutable_project_context
    from taskledger.storage.task_store import v2_paths_from_context

    context = require_mutable_project_context(
        workspace_root,
        allow_legacy=allow_legacy,
    )
    if context.mode == "canonical":
        return v2_paths_from_context(context)
    return require_v2_layout(workspace_root)

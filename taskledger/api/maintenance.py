from __future__ import annotations

from pathlib import Path

from taskledger.services.maintenance import GCScope
from taskledger.services.maintenance import garbage_collect as _garbage_collect
from taskledger.storage.task_store import resolve_v2_paths


def garbage_collect(
    workspace_root: Path,
    *,
    scope: GCScope = "all",
    task_id: str | None = None,
    older_than: str | None = None,
    apply: bool = False,
    reason: str = "",
) -> dict[str, object]:
    """Inspect or explicitly collect eligible maintenance files."""
    return _garbage_collect(
        resolve_v2_paths(workspace_root),
        scope=scope,
        task_id=task_id,
        older_than=older_than,
        apply=apply,
        reason=reason,
    )


__all__ = ["garbage_collect"]

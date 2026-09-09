"""Doctor and synchronization checks for oversized artifact files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol


class ArtifactPaths(Protocol):
    @property
    def tasks_dir(self) -> Path: ...

    @property
    def events_dir(self) -> Path: ...

    @property
    def project_dir(self) -> Path: ...


_TASK_ID_RE = re.compile(r"^(task-\d+)$")


def find_oversized_artifacts(
    paths: ArtifactPaths, *, max_bytes: int
) -> list[dict[str, object]]:
    """Return metadata-only diagnostics for artifacts over ``max_bytes``."""
    violations: list[dict[str, object]] = []
    task_root = paths.tasks_dir
    agent_root = paths.events_dir.parent / "agent-logs" / "artifacts"

    for root, kind in ((task_root, "task"), (agent_root, "agent")):
        if not root.exists():
            continue
        for path in root.glob("**/*"):
            if not path.is_file():
                continue
            size_bytes = path.stat().st_size
            if size_bytes <= max_bytes:
                continue
            task_id: str | None = None
            run_id: str | None = None
            if kind == "task":
                try:
                    relative = path.relative_to(task_root)
                except ValueError:
                    relative = Path(path.name)
                if relative.parts:
                    candidate = relative.parts[0]
                    if _TASK_ID_RE.match(candidate):
                        task_id = candidate
                if relative.parts:
                    run_id = relative.name.split("-command-", 1)[0]
                display_path = _relative_path(path, paths.project_dir)
            else:
                display_path = "logs/" + _relative_path(path, paths.events_dir.parent)

            violations.append(
                {
                    "severity": "error",
                    "code": "ARTIFACT_FILE_TOO_LARGE",
                    "path": display_path,
                    "size_bytes": size_bytes,
                    "limit_bytes": max_bytes,
                    "task_id": task_id,
                    "run_id": run_id,
                    "message": (
                        "Artifact exceeds Taskledger's file-size policy: "
                        f"{display_path} ({size_bytes} bytes > {max_bytes} bytes)."
                    ),
                }
            )
    return sorted(violations, key=lambda item: str(item["path"]))


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = ["find_oversized_artifacts"]

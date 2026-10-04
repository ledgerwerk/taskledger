"""Doctor and synchronization checks for oversized artifact files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast


class ArtifactPaths(Protocol):
    @property
    def tasks_dir(self) -> Path: ...

    @property
    def events_dir(self) -> Path: ...

    @property
    def project_dir(self) -> Path: ...


def find_oversized_artifacts(
    paths: ArtifactPaths, *, max_bytes: int
) -> list[dict[str, object]]:
    """Return metadata-only diagnostics for files under artifact roots."""
    violations: list[dict[str, object]] = []
    task_root = paths.tasks_dir
    agent_root = paths.events_dir.parent / "agent-logs" / "artifacts"
    roots: list[tuple[Path, str, str | None, str | None]] = []
    task_identity_resolver: Callable[[str], tuple[str | None, str | None]] | None = None
    if hasattr(paths, "ledger_ref"):
        from taskledger.errors import LaunchError
        from taskledger.storage.task_identity import task_identity_for_ref
        from taskledger.storage.task_store import V2Paths

        resolved_paths = cast(V2Paths, paths)

        def resolve_task_identity(task_ref: str) -> tuple[str | None, str | None]:
            try:
                identity = task_identity_for_ref(resolved_paths, task_ref)
            except LaunchError:
                return None, None
            return identity.task_id, str(identity.task_uuid)

        task_identity_resolver = resolve_task_identity

    for task_dir in task_root.iterdir() if task_root.is_dir() else ():
        if task_dir.is_symlink() or not task_dir.is_dir():
            continue
        artifact_root = task_dir / "artifacts"
        if not artifact_root.is_dir():
            continue
        if task_identity_resolver is not None:
            task_id, task_uuid = task_identity_resolver(task_dir.name)
        elif task_dir.name.startswith("task-"):
            task_id, task_uuid = task_dir.name, None
        else:
            task_id, task_uuid = None, task_dir.name
        roots.append((artifact_root, "task", task_id, task_uuid))
    roots.append((agent_root, "agent", None, None))

    for root, kind, task_id, task_uuid in roots:
        if not root.exists():
            continue
        for path in root.glob("**/*"):
            if not path.is_file():
                continue
            size_bytes = path.stat().st_size
            if size_bytes <= max_bytes:
                continue
            run_id: str | None = None
            if kind == "task":
                run_id = path.name.split("-command-", 1)[0]
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
                    "task_uuid": task_uuid,
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

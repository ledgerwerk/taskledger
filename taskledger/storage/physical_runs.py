"""Read run records by their physical task-bundle location."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from taskledger.domain.models import TaskRunRecord
from taskledger.errors import LaunchError

if TYPE_CHECKING:
    from taskledger.storage.task_store import V2Paths


def list_physical_runs_from_paths(
    paths: V2Paths, task_directory: Path
) -> list[TaskRunRecord]:
    """Read runs from one physical task directory without resolving its identity."""
    if task_directory.parent != paths.tasks_dir:
        raise LaunchError(
            f"Physical task directory is outside the tasks mount: {task_directory}",
            code="TASKLEDGER_RUN_PATH_UNSAFE",
        )
    if paths.tasks_dir.is_symlink() or task_directory.is_symlink():
        raise LaunchError(
            f"Cannot inspect runs through symlinked task path: {task_directory}",
            code="TASKLEDGER_RUN_PATH_UNSAFE",
        )
    if not task_directory.is_dir():
        return []

    runs_directory = task_directory / "runs"
    if runs_directory.is_symlink():
        raise LaunchError(
            f"Cannot inspect symlinked run directory: {runs_directory}",
            code="TASKLEDGER_RUN_PATH_UNSAFE",
        )
    if not runs_directory.is_dir():
        return []

    from taskledger.storage.task_store import _load_run

    runs: list[TaskRunRecord] = []
    for run_path in sorted(runs_directory.glob("*.md"), key=lambda path: path.name):
        if run_path.is_symlink() or not run_path.is_file():
            raise LaunchError(
                f"Cannot inspect non-regular run record: {run_path}",
                code="TASKLEDGER_RUN_PATH_UNSAFE",
            )
        try:
            runs.append(_load_run(run_path))
        except Exception as exc:
            raise LaunchError(
                f"Unable to read physical run record {run_path}: {exc}",
                code="TASKLEDGER_RUN_RECORD_UNREADABLE",
            ) from exc
    runs.sort(key=lambda run: run.run_id)
    return runs

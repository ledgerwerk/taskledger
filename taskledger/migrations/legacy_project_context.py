from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from taskledger.errors import LaunchError
from taskledger.storage.ledger_config import LedgerConfig, load_ledger_config
from taskledger.storage.paths import (
    ProjectPaths,
    load_project_locator,
    probe_taskledger_project,
    project_paths_for_root,
)
from taskledger.storage.project_config import (
    ProjectConfig,
    load_project_config_document,
    merge_project_config,
)
from taskledger.storage.project_identity import (
    load_project_uuid,
    project_name_or_default,
)

if TYPE_CHECKING:
    from taskledger.storage.task_store import TaskledgerStoragePaths


@dataclass(frozen=True, slots=True)
class LegacyProjectContext:
    project_paths: ProjectPaths
    project_uuid: str | None
    project_name: str
    config: ProjectConfig
    ledger_state: LedgerConfig


def load_legacy_project_context(start: Path) -> LegacyProjectContext:
    probe = probe_taskledger_project(start)
    if probe.source != "legacy":
        raise LaunchError(
            "TASKLEDGER_MIGRATION_SOURCE_NOT_FOUND: "
            "No legacy Taskledger project found.",
            code="TASKLEDGER_MIGRATION_SOURCE_NOT_FOUND",
        )
    locator = load_project_locator(start)
    project_paths = project_paths_for_root(
        locator.workspace_root,
        locator.taskledger_dir,
        config_path=locator.config_path,
    )
    return LegacyProjectContext(
        project_paths=project_paths,
        project_uuid=load_project_uuid(project_paths.config_path),
        project_name=project_name_or_default(
            project_paths.config_path, workspace_root=project_paths.workspace_root
        ),
        config=merge_project_config(
            load_project_config_document(project_paths.config_path)
        ),
        ledger_state=load_ledger_config(project_paths.config_path),
    )


def legacy_v2_paths(context: LegacyProjectContext) -> TaskledgerStoragePaths:
    from taskledger.storage.task_store import TaskledgerStoragePaths

    taskledger_root = context.project_paths.taskledger_dir
    ledger_dir = taskledger_root / "ledgers" / context.ledger_state.ref
    indexes_dir = ledger_dir / "indexes"
    return TaskledgerStoragePaths(
        workspace_root=context.project_paths.workspace_root,
        taskledger_root=taskledger_root,
        runtime_root=taskledger_root,
        ledger_ref=context.ledger_state.ref,
        ledger_dir=ledger_dir,
        project_dir=ledger_dir,
        introductions_dir=ledger_dir / "intros",
        releases_dir=ledger_dir / "releases",
        tasks_dir=ledger_dir / "tasks",
        plans_dir=ledger_dir / "plans",
        questions_dir=ledger_dir / "questions",
        runs_dir=ledger_dir / "runs",
        changes_dir=ledger_dir / "changes",
        events_dir=ledger_dir / "events",
        indexes_dir=indexes_dir,
        active_task_path=ledger_dir / "active-task.yaml",
        actor_path=taskledger_root / "actor.yaml",
        harness_path=taskledger_root / "harness.yaml",
        active_locks_index_path=indexes_dir / "active_locks.json",
        dependencies_index_path=indexes_dir / "dependencies.json",
        introductions_index_path=indexes_dir / "introductions.json",
        project_uuid=context.project_uuid,
    )


__all__ = [
    "LegacyProjectContext",
    "legacy_v2_paths",
    "load_legacy_project_context",
]

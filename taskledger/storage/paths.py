from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ledgercore.paths import find_config_upwards

from taskledger.errors import LaunchError
from taskledger.storage.project_config import load_project_config_document

CANONICAL_PROJECT_CONFIG_FILENAME = "taskledger.toml"
PROJECT_CONFIG_FILENAMES = (".taskledger.toml", CANONICAL_PROJECT_CONFIG_FILENAME)
DEFAULT_TASKLEDGER_DIR_NAME = ".taskledger"
LEGACY_PROJECT_CONFIG_FILENAME = "project.toml"


@dataclass(slots=True, frozen=True)
class ProjectLocator:
    workspace_root: Path
    config_path: Path
    taskledger_dir: Path
    source: Literal["explicit", "dotfile", "toml", "legacy", "default", "canonical"]


@dataclass(slots=True, frozen=True)
class TaskledgerProjectProbe:
    """Project-boundary discovery independent of Taskledger mount resolution."""

    project_root: Path
    source: Literal["canonical", "legacy", "none"]
    manifest_path: Path | None
    registration_present: bool
    tool_config_path: Path | None
    orphan_config_present: bool


@dataclass(slots=True, frozen=True)
class ProjectPaths:
    workspace_root: Path
    project_dir: Path
    taskledger_dir: Path
    config_path: Path
    releases_dir: Path
    repos_dir: Path
    repo_index_path: Path


def resolve_taskledger_root(workspace_root: Path) -> Path:
    return load_project_locator(workspace_root).taskledger_dir


def resolve_project_paths(workspace_root: Path) -> ProjectPaths:
    if probe_taskledger_project(workspace_root).source == "none":
        locator = load_project_locator(workspace_root)
        return project_paths_for_root(
            locator.workspace_root,
            locator.taskledger_dir,
            config_path=locator.config_path,
        )
    from taskledger.storage.project_context import load_project_context

    context = load_project_context(workspace_root, require_initialized=False)
    if context is not None and context.mode == "canonical":
        return ProjectPaths(
            workspace_root=context.project_root,
            project_dir=context.paths.ledger_data_dir,
            taskledger_dir=context.paths.data_root,
            config_path=context.config_path,
            releases_dir=context.paths.releases_dir,
            repos_dir=context.paths.ledger_data_dir,
            repo_index_path=context.paths.repo_registry_path,
        )
    locator = load_project_locator(workspace_root)
    return project_paths_for_root(
        locator.workspace_root,
        locator.taskledger_dir,
        config_path=locator.config_path,
    )


def discover_workspace_root(start: Path) -> Path:
    return load_project_locator(start).workspace_root


def find_project_config(start: Path) -> Path | None:
    start_path = start if start.is_dir() else start.parent
    return find_config_upwards(start_path, PROJECT_CONFIG_FILENAMES)


def probe_taskledger_project(start: Path) -> TaskledgerProjectProbe:
    """Find the project boundary without resolving Taskledger storage mounts."""
    start_path = start if start.is_dir() else start.parent
    for current in _search_roots(start_path):
        manifest_path = current / ".ledger" / "ledger.toml"
        if manifest_path.is_file():
            from ledgercore import LedgerCoreError, read_ledger_manifest

            try:
                manifest = read_ledger_manifest(manifest_path)
            except LedgerCoreError as exc:
                raise LaunchError(
                    "CANONICAL_MANIFEST_INVALID: Unable to read "
                    f"{manifest_path}: {exc}",
                    code="CANONICAL_MANIFEST_INVALID",
                    details={"manifest_path": str(manifest_path)},
                ) from exc
            config_path = current / ".ledger" / "taskledger" / "config.toml"
            registration_present = "taskledger" in getattr(manifest, "ledgers", {})
            return TaskledgerProjectProbe(
                project_root=current.resolve(),
                source="canonical",
                manifest_path=manifest_path.resolve(),
                registration_present=registration_present,
                tool_config_path=config_path.resolve(),
                orphan_config_present=(
                    config_path.is_file() and not registration_present
                ),
            )
    legacy_config_path = find_project_config(start_path)
    if legacy_config_path is not None:
        return TaskledgerProjectProbe(
            project_root=legacy_config_path.parent.resolve(),
            source="legacy",
            manifest_path=None,
            registration_present=False,
            tool_config_path=legacy_config_path.resolve(),
            orphan_config_present=False,
        )
    return TaskledgerProjectProbe(
        project_root=start_path.resolve(),
        source="none",
        manifest_path=None,
        registration_present=False,
        tool_config_path=None,
        orphan_config_present=False,
    )


def load_project_locator(
    start: Path,
    *,
    taskledger_dir_override: Path | None = None,
    config_filename: str = CANONICAL_PROJECT_CONFIG_FILENAME,
) -> ProjectLocator:
    start_path = start.expanduser().resolve()
    if taskledger_dir_override is None:
        from ledgercore import locate_ledger_project

        canonical = locate_ledger_project(start_path)
        if canonical is not None and canonical.source == "canonical":
            from ledgercore import read_ledger_manifest

            manifest = read_ledger_manifest(canonical.manifest_path)
            if (
                getattr(manifest, "schema_version", None) == 3
                and "taskledger" not in manifest.ledgers
            ):
                return ProjectLocator(
                    workspace_root=canonical.project_root,
                    config_path=(
                        canonical.project_root
                        / ".ledger"
                        / "taskledger"
                        / "config.toml"
                    ),
                    taskledger_dir=canonical.project_root / ".ledger" / "taskledger",
                    source="canonical",
                )
            from taskledger.storage.project_context import load_project_context

            context = load_project_context(start_path, require_initialized=False)
            return ProjectLocator(
                workspace_root=context.project_root,
                config_path=context.config_path,
                taskledger_dir=context.paths.data_root,
                source="canonical",
            )
    config_path = find_project_config(start_path)
    if config_path is not None:
        workspace_root = config_path.parent
        taskledger_dir = (
            _resolve_path(taskledger_dir_override, workspace_root=workspace_root)
            if taskledger_dir_override is not None
            else _taskledger_dir_from_config(config_path, workspace_root=workspace_root)
        )
        return ProjectLocator(
            workspace_root=workspace_root,
            config_path=config_path,
            taskledger_dir=taskledger_dir,
            source=(
                "explicit"
                if taskledger_dir_override is not None
                else "dotfile"
                if config_path.name.startswith(".")
                else "toml"
            ),
        )

    legacy_workspace_root = _find_legacy_workspace_root(start_path)
    if legacy_workspace_root is not None:
        legacy_config_path = (
            legacy_workspace_root
            / DEFAULT_TASKLEDGER_DIR_NAME
            / LEGACY_PROJECT_CONFIG_FILENAME
        )
        workspace_root = legacy_workspace_root
        return ProjectLocator(
            workspace_root=workspace_root,
            config_path=(
                legacy_config_path
                if legacy_config_path.exists()
                else workspace_root / config_filename
            ),
            taskledger_dir=(
                _resolve_path(taskledger_dir_override, workspace_root=workspace_root)
                if taskledger_dir_override is not None
                else workspace_root / DEFAULT_TASKLEDGER_DIR_NAME
            ),
            source="explicit" if taskledger_dir_override is not None else "legacy",
        )

    workspace_root = start_path
    return ProjectLocator(
        workspace_root=workspace_root,
        config_path=workspace_root / config_filename,
        taskledger_dir=(
            _resolve_path(taskledger_dir_override, workspace_root=workspace_root)
            if taskledger_dir_override is not None
            else workspace_root / DEFAULT_TASKLEDGER_DIR_NAME
        ),
        source="explicit" if taskledger_dir_override is not None else "default",
    )


def project_paths_for_root(
    workspace_root: Path,
    project_dir: Path,
    *,
    config_path: Path | None = None,
    ledger_ref: str = "main",
) -> ProjectPaths:
    from taskledger.storage.ledger_config import load_ledger_config

    if config_path is not None and config_path.exists():
        try:
            ledger = load_ledger_config(config_path)
            ledger_ref = ledger.ref
        except Exception:
            pass
    ledger_dir = project_dir / "ledgers" / ledger_ref
    indexes_dir = ledger_dir / "indexes"
    return ProjectPaths(
        workspace_root=workspace_root,
        project_dir=ledger_dir,
        taskledger_dir=project_dir,
        config_path=config_path or workspace_root / CANONICAL_PROJECT_CONFIG_FILENAME,
        releases_dir=ledger_dir / "releases",
        repos_dir=project_dir / "repos",
        repo_index_path=indexes_dir / "repos.json",
    )


def _search_roots(start: Path) -> tuple[Path, ...]:
    current = start if start.is_dir() else start.parent
    return (current, *current.parents)


def _find_legacy_workspace_root(start: Path) -> Path | None:
    for current in _search_roots(start):
        taskledger_dir = current / DEFAULT_TASKLEDGER_DIR_NAME
        if (taskledger_dir / "storage.yaml").exists() or (
            taskledger_dir / "ledgers"
        ).is_dir():
            return current
    return None


def _taskledger_dir_from_config(config_path: Path, *, workspace_root: Path) -> Path:
    document = load_project_config_document(config_path)
    raw_value = document.get("taskledger_dir")
    if not isinstance(raw_value, str) or not raw_value.strip():
        return workspace_root / DEFAULT_TASKLEDGER_DIR_NAME
    return _resolve_path(raw_value, workspace_root=workspace_root)


def _resolve_path(value: str | Path, *, workspace_root: Path) -> Path:
    raw_value = os.path.expandvars(os.fspath(value))
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve()

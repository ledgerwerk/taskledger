from __future__ import annotations

from pathlib import Path

from taskledger.search import (
    ProjectDependencyInfo,
    ProjectSearchMatch,
)
from taskledger.search import (
    grep_project as _grep_project,
)
from taskledger.search import (
    module_dependencies as _module_dependencies,
)
from taskledger.search import (
    search_project as _search_project,
)
from taskledger.search import (
    symbols_project as _symbols_project,
)
from taskledger.storage.init import ensure_project_exists


def search_workspace(
    workspace_root: Path,
    *,
    query: str,
    repo_refs: tuple[str, ...] = (),
    limit: int = 50,
) -> list[ProjectSearchMatch]:
    return _search_project(
        ensure_project_exists(workspace_root),
        query=query,
        repo_refs=repo_refs,
        limit=limit,
    )


def grep_workspace(
    workspace_root: Path,
    *,
    pattern: str,
    repo_refs: tuple[str, ...] = (),
    limit: int = 100,
) -> list[ProjectSearchMatch]:
    return _grep_project(
        ensure_project_exists(workspace_root),
        pattern=pattern,
        repo_refs=repo_refs,
        limit=limit,
    )


def symbols_workspace(
    workspace_root: Path,
    *,
    query: str,
    repo_refs: tuple[str, ...] = (),
    limit: int = 50,
) -> list[ProjectSearchMatch]:
    return _symbols_project(
        ensure_project_exists(workspace_root),
        query=query,
        repo_refs=repo_refs,
        limit=limit,
    )


def dependencies_for_module(
    workspace_root: Path,
    *,
    repo_ref: str,
    module: str,
) -> ProjectDependencyInfo:
    return _module_dependencies(
        ensure_project_exists(workspace_root),
        repo_ref=repo_ref,
        module=module,
    )


__all__ = [
    "dependencies_for_module",
    "grep_workspace",
    "search_workspace",
    "symbols_workspace",
]

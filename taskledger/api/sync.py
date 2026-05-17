from __future__ import annotations

from pathlib import Path

from taskledger.services.git_sync import (
    git_hooks_status,
    git_sync,
    git_sync_export_local,
    git_sync_import_local,
    git_sync_pull,
    git_sync_push,
    git_sync_status,
    init_git_sync_repo,
    install_git_hooks,
    uninstall_git_hooks,
)


def sync_git_init(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    remote_url: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    project_path: str | None = None,
    adopt_existing: bool = False,
    mode: str = "move",
    install_hooks: bool = False,
    force_hooks: bool = False,
) -> dict[str, object]:
    return init_git_sync_repo(
        workspace_root,
        repo=repo,
        remote_url=remote_url,
        remote=remote,
        branch=branch,
        project_path=project_path,
        adopt_existing=adopt_existing,
        mode=mode,
        install_hooks=install_hooks,
        force_hooks=force_hooks,
    )


def sync_git_status(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    return git_sync_status(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )


def sync_git_import_local(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    return git_sync_import_local(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        dry_run=dry_run,
    )


def sync_git_export_local(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    message: str | None = None,
    allow_dirty: bool = False,
    allow_active_locks: bool = False,
) -> dict[str, object]:
    return git_sync_export_local(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        message=message,
        allow_dirty=allow_dirty,
        allow_active_locks=allow_active_locks,
    )


def sync_git_pull(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    allow_dirty: bool = False,
) -> dict[str, object]:
    return git_sync_pull(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        allow_dirty=allow_dirty,
    )


def sync_git_push(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    message: str | None = None,
    allow_dirty: bool = False,
    allow_active_locks: bool = False,
) -> dict[str, object]:
    return git_sync_push(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        message=message,
        allow_dirty=allow_dirty,
        allow_active_locks=allow_active_locks,
    )


def sync_git_sync(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    message: str | None = None,
    allow_dirty: bool = False,
    allow_active_locks: bool = False,
) -> dict[str, object]:
    return git_sync(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        message=message,
        allow_dirty=allow_dirty,
        allow_active_locks=allow_active_locks,
    )


def sync_git_hooks_install(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> dict[str, object]:
    return install_git_hooks(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        force=force,
        quiet=quiet,
    )


def sync_git_hooks_status(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    return git_hooks_status(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )


def sync_git_hooks_uninstall(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    return uninstall_git_hooks(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )

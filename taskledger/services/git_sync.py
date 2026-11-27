from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from taskledger.errors import LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.doctor_checks.artifact_checks import find_oversized_artifacts
from taskledger.services.git_utils import (
    git_root as _git_root,
)
from taskledger.services.git_utils import (
    run_git as _run_git,
)
from taskledger.services.git_utils import (
    status_path_token as _status_path_token,
)
from taskledger.storage.project_context import load_project_context
from taskledger.storage.task_store import load_active_locks

_HOOK_NAMES = ("post-merge", "post-checkout", "post-rewrite")
_HOOK_MARKER = "# taskledger-managed-hook v1"


@dataclass(frozen=True, slots=True)
class GitSyncConfig:
    repo_path: Path
    project_path: str
    remote: str = "origin"
    branch: str = "main"
    allow_active_locks: bool = False
    hooks: bool = False


def build_git_sync_config(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    allow_uninitialized: bool = False,
) -> GitSyncConfig:
    context = load_project_context(workspace_root, require_initialized=False)
    assert context.layout is not None
    data_path = context.layout.mounts["data"].path.resolve()
    repository = _git_root(data_path)
    if repository is None:
        if not allow_uninitialized:
            raise LaunchError(
                "TASKLEDGER_STORAGE_NOT_GIT_BACKED: resolved data mount is not "
                "inside a Git worktree."
            )
        mount = context.layout.mounts["data"]
        if mount.storage == "external" and mount.root is not None:
            repository = Path(mount.root).resolve()
        elif mount.storage == "project":
            repository = Path(context.project_root).resolve()
        else:
            raise LaunchError(
                "TASKLEDGER_STORAGE_NOT_GIT_BACKED: cannot derive repository "
                f"root for storage type {mount.storage!r}."
            )
    sync_config = context.config.sync_git
    relative = data_path.relative_to(repository).as_posix()
    if (
        (repo is not None and repo.resolve() != repository)
        or (project_path is not None and project_path != relative)
        or sync_config.repo is not None
        or sync_config.project_path is not None
    ):
        raise LaunchError(
            "TASKLEDGER_CANONICAL_SYNC_PATH_FIXED: Git sync selectors must match "
            "the resolved Taskledger data mount."
            f"\nResolved data mount: {data_path}"
            f"\nResolved repository root: {repository}"
        )
    return GitSyncConfig(
        repo_path=repository,
        project_path=relative,
        remote=remote or sync_config.remote,
        branch=branch or sync_config.branch,
        allow_active_locks=sync_config.allow_active_locks,
        hooks=sync_config.hooks,
    )


def git_sync_paths(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    storage_path = _storage_path(config)
    return {
        "kind": "taskledger_sync_git_paths",
        "repo_path": str(config.repo_path),
        "project_path": config.project_path,
        "storage_path": storage_path.as_posix(),
        "branch": config.branch,
        "remote": config.remote,
    }


def git_sync_status(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    context = load_project_context(workspace_root)
    storage_path = _storage_path(config)
    taskledger_dir = context.paths.data_root.resolve()
    taskledger_dir_matches = storage_path.resolve() == taskledger_dir
    active_lock_count = _active_lock_count(context.project_root)
    doctor = inspect_v2_project(context.project_root)
    git_root = _git_root(config.repo_path)
    all_status_lines = _git_status_lines(config.repo_path)
    project_status_lines, outside_status_lines = _split_status_by_project(
        all_status_lines,
        config.project_path,
    )
    ahead, behind = _ahead_behind(config.repo_path)
    warnings: list[str] = []
    if not taskledger_dir_matches:
        warnings.append(
            "Resolved data mount does not match the configured sync project path."
        )
    if active_lock_count:
        warnings.append(f"{active_lock_count} active lock(s) are present.")
    return {
        "kind": "taskledger_sync_git_status",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "storage_path": storage_path.as_posix(),
        "taskledger_dir": taskledger_dir.as_posix(),
        "taskledger_dir_matches": taskledger_dir_matches,
        "branch": _current_branch(config.repo_path),
        "remote": _remote_url(config.repo_path, config.remote),
        "dirty": bool(project_status_lines),
        "ahead": ahead,
        "behind": behind,
        "active_lock_count": active_lock_count,
        "doctor_healthy": bool(doctor["healthy"]),
        "status_lines": project_status_lines,
        "project_dirty": bool(project_status_lines),
        "project_status_lines": project_status_lines,
        "outside_dirty": bool(outside_status_lines),
        "outside_dirty_count": len(outside_status_lines),
        "outside_status_lines": outside_status_lines,
        "warnings": warnings,
        "git_root": git_root.as_posix() if git_root is not None else None,
    }


def init_git_sync_repo(
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
    if mode not in {"move", "copy"}:
        raise LaunchError("mode must be one of: move, copy.")
    if adopt_existing or mode != "move":
        raise LaunchError(
            "TASKLEDGER_STORAGE_TARGET_INVALID: canonical sync git init "
            "does not move or adopt storage."
        )
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
        allow_uninitialized=True,
    )
    context = load_project_context(workspace_root)
    assert context.layout is not None
    data_mount = context.layout.mounts["data"]
    if data_mount.storage == "user-data":
        raise LaunchError(
            "TASKLEDGER_STORAGE_NOT_GIT_BACKED: user-data storage requires "
            "an external Git-backed root."
        )
    target_storage = data_mount.path
    _ensure_git_repo(
        config.repo_path,
        remote_url=None,
        branch=config.branch,
        allow_nonempty=True,
    )
    if remote_url:
        configured_remote = _remote_url(config.repo_path, config.remote)
        if configured_remote is None:
            _run_git(
                config.repo_path,
                "remote",
                "add",
                config.remote,
                remote_url,
            )
        elif configured_remote != remote_url:
            raise LaunchError("Configured Git remote does not match --remote-url.")
    hooks_report = None
    if install_hooks or config.hooks:
        hooks_report = install_git_hooks(
            workspace_root,
            repo=config.repo_path,
            project_path=config.project_path,
            force=force_hooks,
            quiet=True,
        )
    doctor = inspect_v2_project(workspace_root)
    return {
        "kind": "taskledger_sync_git_init",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "storage_path": target_storage.as_posix(),
        "branch": config.branch,
        "remote": config.remote,
        "taskledger_dir_updated": False,
        "doctor_healthy": bool(doctor["healthy"]),
        "hooks": hooks_report,
        "warnings": [],
    }


def git_sync_import_local(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    raise LaunchError(
        "TASKLEDGER_MIGRATION_REQUIRED: Legacy Git storage transitions are no "
        "longer supported by normal runtime. Use `taskledger migrate plan` and "
        "`taskledger migrate apply` instead.",
        code="TASKLEDGER_MIGRATION_REQUIRED",
        remediation=[
            "Run `taskledger migrate plan` and review the result",
            "Run `taskledger migrate apply`",
        ],
    )


def _assert_artifacts_within_policy(workspace_root: Path) -> None:
    context = load_project_context(workspace_root)
    violations = find_oversized_artifacts(
        context.paths, max_bytes=context.config.artifact_max_bytes
    )
    if not violations:
        return
    lines = [
        f"Cannot sync: Taskledger storage contains {len(violations)} "
        + "oversized artifact(s)."
    ]
    for violation in violations:
        lines.append(f"- {violation['path']}: {violation['size_bytes']} bytes")
    lines.extend(
        [
            f"Limit: {context.config.artifact_max_bytes} bytes.",
            (
                "Run `taskledger doctor` for details. Existing Git commits containing "
                + "these blobs may also need to be rewritten before the remote "
                + "accepts the push."
            ),
        ]
    )
    raise LaunchError("\n".join(lines))


def _git_sync_commit_with_config(
    workspace_root: Path,
    config: GitSyncConfig,
    *,
    message: str | None = None,
    allow_active_locks: bool = False,
    require_clean_repo: bool = False,
    include_outside_project: bool = False,
) -> dict[str, object]:
    """Commit using an already-resolved config (no public selector parsing)."""
    context = load_project_context(workspace_root)
    _assert_artifacts_within_policy(workspace_root)
    storage_path = _storage_path(config)
    if context.paths.data_root.resolve() != storage_path.resolve():
        raise LaunchError(
            "Resolved Taskledger data mount must match the sync repo project path."
        )
    doctor = inspect_v2_project(context.project_root)
    if not doctor["healthy"]:
        raise LaunchError(
            "taskledger doctor reported issues:\n"
            + "\n".join(str(item) for item in cast(list[object], doctor["errors"]))
        )
    active_lock_count = _active_lock_count(context.project_root)
    allow_active = allow_active_locks or config.allow_active_locks
    if active_lock_count and not allow_active:
        raise LaunchError(
            f"{active_lock_count} active lock(s) detected. "
            "Use --allow-active-locks to continue."
        )
    if include_outside_project:
        raise LaunchError(
            "TASKLEDGER_CANONICAL_SYNC_PATH_FIXED: canonical Git commits are "
            "limited to the resolved Taskledger project path."
        )
    _ensure_git_repo(config.repo_path, remote_url=None, branch=config.branch)
    warnings: list[str] = []
    outside_dirty = _dirty_paths_outside_project(config.repo_path, config.project_path)
    if outside_dirty:
        if require_clean_repo:
            raise LaunchError(
                "Sync repo has dirty paths outside project_path. "
                "Commit or stash them first."
            )
        warnings.append(
            f"{len(outside_dirty)} dirty path(s) outside project_path were ignored."
        )
    export_paths = (config.project_path,)
    _run_git(config.repo_path, "add", "--all", "--", *export_paths)
    staged = _run_git(
        config.repo_path,
        "diff",
        "--cached",
        "--quiet",
        "--exit-code",
        "--",
        *export_paths,
        check=False,
    )
    committed = staged.returncode != 0
    commit_hash: str | None = None
    commit_message = message or f"Sync taskledger state for {config.project_path}"
    if committed:
        _run_git(config.repo_path, "commit", "-m", commit_message, "--", *export_paths)
        commit_hash = _run_git(config.repo_path, "rev-parse", "HEAD").stdout.strip()
    if active_lock_count and allow_active:
        warnings.append(
            f"{active_lock_count} active lock(s) were synced. "
            "Do not continue the same run on two PCs."
        )
    return {
        "kind": "taskledger_sync_git_commit",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "committed": committed,
        "commit_hash": commit_hash,
        "active_lock_count": active_lock_count,
        "include_outside_project": False,
        "outside_dirty_count": len(outside_dirty),
        "outside_status_lines": outside_dirty,
        "warnings": warnings,
    }


def git_sync_commit(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    message: str | None = None,
    allow_active_locks: bool = False,
    require_clean_repo: bool = False,
    include_outside_project: bool = False,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    return _git_sync_commit_with_config(
        workspace_root,
        config,
        message=message,
        allow_active_locks=allow_active_locks,
        require_clean_repo=require_clean_repo,
        include_outside_project=include_outside_project,
    )


def git_sync_export_local(
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
    raise LaunchError(
        "TASKLEDGER_MIGRATION_REQUIRED: Legacy Git storage transitions are no "
        "longer supported by normal runtime. Use `taskledger migrate plan` and "
        "`taskledger migrate apply` instead.",
        code="TASKLEDGER_MIGRATION_REQUIRED",
        remediation=[
            "Run `taskledger migrate plan` and review the result",
            "Run `taskledger migrate apply`",
        ],
    )


def git_sync_pull(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    allow_dirty: bool = False,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    if _git_status_lines(config.repo_path):
        raise LaunchError(
            "sync git pull updates the whole sync repository and requires a clean "
            "working tree. Commit or stash unrelated project state first. "
            "Canonical sibling-repository pulls do not support --allow-dirty."
        )
    _run_git(config.repo_path, "pull", "--ff-only", config.remote, config.branch)
    doctor = inspect_v2_project(workspace_root)
    refreshed: dict[str, object] = {
        "kind": "taskledger_sync_git_direct",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "storage_path": _storage_path(config).as_posix(),
        "taskledger_dir_updated": False,
        "doctor_healthy": bool(doctor["healthy"]),
        "warnings": [],
    }
    return {
        "kind": "taskledger_sync_git_pull",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "pulled": True,
        "refresh": refreshed,
        "doctor_healthy": refreshed["doctor_healthy"],
        "warnings": [],
    }


def git_sync_push(
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
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    exported = _git_sync_commit_with_config(
        workspace_root,
        config,
        message=message,
        allow_active_locks=allow_active_locks,
    )
    _run_git(config.repo_path, "push", config.remote, config.branch)
    return {
        "kind": "taskledger_sync_git_push",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "committed": exported["committed"],
        "commit_hash": exported["commit_hash"],
        "include_outside_project": exported["include_outside_project"],
        "outside_dirty_count": exported["outside_dirty_count"],
        "outside_status_lines": exported["outside_status_lines"],
        "pushed": True,
        "warnings": list(cast(list[object], exported["warnings"])),
    }


def git_sync(
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
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    # Call pull/push without passing selectors; they build their own config.
    pull_payload = git_sync_pull(
        workspace_root,
        allow_dirty=allow_dirty,
    )
    push_payload = git_sync_push(
        workspace_root,
        message=message,
        allow_dirty=allow_dirty,
        allow_active_locks=allow_active_locks,
    )
    return {
        "kind": "taskledger_sync_git_sync",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "pulled": pull_payload["pulled"],
        "committed": push_payload["committed"],
        "commit_hash": push_payload["commit_hash"],
        "pushed": push_payload["pushed"],
        "warnings": list(cast(list[object], pull_payload["warnings"]))
        + list(cast(list[object], push_payload["warnings"])),
    }


def install_git_hooks(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    hooks_dir = config.repo_path / ".git" / "hooks"
    if not hooks_dir.exists():
        raise LaunchError(f"Git hooks directory does not exist: {hooks_dir}")
    installed: list[str] = []
    skipped: list[str] = []
    samples: list[str] = []
    for hook_name in _HOOK_NAMES:
        hook_path = hooks_dir / hook_name
        desired = _render_hook_script(
            workspace_root=workspace_root,
            repo_path=config.repo_path,
            project_path=config.project_path,
            quiet=quiet,
        )
        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8")
            managed = _HOOK_MARKER in existing
            if (
                managed
                and not force
                and _hook_targets_differ(
                    existing,
                    workspace_root=workspace_root,
                    repo_path=config.repo_path,
                    project_path=config.project_path,
                )
            ):
                raise LaunchError(
                    "Existing taskledger-managed hook targets a different "
                    "workspace or project_path. Shared sync repos are not "
                    "multi-project-safe for single-project hooks without --force."
                )
            if not managed and not force:
                skipped.append(hook_name)
                sample_path = hooks_dir / f"{hook_name}.taskledger.sample"
                sample_path.write_text(desired, encoding="utf-8")
                os.chmod(sample_path, 0o755)
                samples.append(sample_path.as_posix())
                continue
        hook_path.write_text(desired, encoding="utf-8")
        os.chmod(hook_path, 0o755)
        installed.append(hook_name)
    return {
        "kind": "taskledger_sync_git_hooks_install",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "installed": installed,
        "skipped": skipped,
        "samples": samples,
        "warnings": [],
    }


def git_hooks_status(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    hooks_dir = config.repo_path / ".git" / "hooks"
    statuses: list[dict[str, str]] = []
    for hook_name in _HOOK_NAMES:
        hook_path = hooks_dir / hook_name
        if not hook_path.exists():
            statuses.append({"hook": hook_name, "status": "missing"})
            continue
        content = hook_path.read_text(encoding="utf-8")
        statuses.append(
            {
                "hook": hook_name,
                "status": "managed" if _HOOK_MARKER in content else "foreign",
            }
        )
    return {
        "kind": "taskledger_sync_git_hooks_status",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "hooks": statuses,
        "warnings": [],
    }


def uninstall_git_hooks(
    workspace_root: Path,
    *,
    repo: Path | None = None,
    project_path: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    hooks_dir = config.repo_path / ".git" / "hooks"
    removed: list[str] = []
    skipped: list[str] = []
    for hook_name in _HOOK_NAMES:
        hook_path = hooks_dir / hook_name
        if not hook_path.exists():
            continue
        content = hook_path.read_text(encoding="utf-8")
        if _HOOK_MARKER not in content:
            skipped.append(hook_name)
            continue
        hook_path.unlink()
        removed.append(hook_name)
    return {
        "kind": "taskledger_sync_git_hooks_uninstall",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "removed": removed,
        "skipped": skipped,
        "warnings": [],
    }


def _storage_path(config: GitSyncConfig) -> Path:
    return (config.repo_path / config.project_path).resolve()


def _ensure_git_repo(
    repo_path: Path,
    *,
    remote_url: str | None,
    branch: str,
    allow_nonempty: bool = False,
) -> None:
    if remote_url and not repo_path.exists():
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            repo_path.parent,
            "clone",
            "--branch",
            branch,
            remote_url,
            repo_path.name,
        )
    elif remote_url and repo_path.exists() and not (repo_path / ".git").exists():
        raise LaunchError(
            f"Repo path exists but is not a git repo: {repo_path}. "
            "Refuse to clone into non-empty path."
        )
    else:
        repo_path.mkdir(parents=True, exist_ok=True)
        if not (repo_path / ".git").exists():
            if any(repo_path.iterdir()) and not allow_nonempty:
                raise LaunchError(
                    "Repo path exists and is not empty: "
                    f"{repo_path}. Expected git repo."
                )
            _run_git(repo_path, "init")
        _ensure_branch(repo_path, branch)


def _ensure_branch(repo_path: Path, branch: str) -> None:
    current = _run_git(
        repo_path,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        check=False,
        suppress_taskledger_hooks=True,
    )
    if current.returncode == 0 and current.stdout.strip() == branch:
        return

    probe = _run_git(
        repo_path,
        "rev-parse",
        "--verify",
        branch,
        check=False,
        suppress_taskledger_hooks=True,
    )
    if probe.returncode == 0:
        _run_git(
            repo_path,
            "checkout",
            branch,
            suppress_taskledger_hooks=True,
        )
        return
    _run_git(
        repo_path,
        "checkout",
        "-b",
        branch,
        suppress_taskledger_hooks=True,
    )


def _active_lock_count(workspace_root: Path) -> int:
    try:
        return len(load_active_locks(workspace_root))
    except LaunchError:
        return 0


def _git_status_lines(repo_path: Path) -> list[str]:
    if _git_root(repo_path) is None:
        return []
    result = _run_git(repo_path, "status", "--porcelain", check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _split_status_by_project(
    lines: list[str],
    project_path: str,
) -> tuple[list[str], list[str]]:
    prefix = project_path.rstrip("/") + "/"
    project: list[str] = []
    outside: list[str] = []
    for line in lines:
        token = _status_path_token(line)
        if token == project_path or token.startswith(prefix):
            project.append(line)
        else:
            outside.append(line)
    return project, outside


def _current_branch(repo_path: Path) -> str | None:
    result = _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _remote_url(repo_path: Path, remote: str) -> str | None:
    result = _run_git(
        repo_path,
        "config",
        "--get",
        f"remote.{remote}.url",
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _ahead_behind(repo_path: Path) -> tuple[int | None, int | None]:
    upstream = _run_git(
        repo_path,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    )
    if upstream.returncode != 0:
        return (None, None)
    counts = _run_git(
        repo_path,
        "rev-list",
        "--left-right",
        "--count",
        "@{upstream}...HEAD",
        check=False,
    )
    if counts.returncode != 0:
        return (None, None)
    parts = counts.stdout.strip().split()
    if len(parts) != 2:
        return (None, None)
    behind = int(parts[0])
    ahead = int(parts[1])
    return (ahead, behind)


def _dirty_paths_outside_project(repo_path: Path, project_path: str) -> list[str]:
    _, outside_lines = _split_status_by_project(
        _git_status_lines(repo_path),
        project_path,
    )
    return [_status_path_token(line) for line in outside_lines]


def _hook_targets_differ(
    content: str,
    *,
    workspace_root: Path,
    repo_path: Path,
    project_path: str,
) -> bool:
    return any(
        needle not in content
        for needle in (
            f"--root {shlex.quote(workspace_root.as_posix())}",
            f"# taskledger-managed-repo: {repo_path.as_posix()}",
            f"# taskledger-managed-project: {project_path}",
        )
    )


def _render_hook_script(
    *,
    workspace_root: Path,
    repo_path: Path,
    project_path: str,
    quiet: bool,
) -> str:
    quiet_suffix = " >/dev/null 2>&1" if quiet else ""
    return (
        "#!/bin/sh\n"
        f"{_HOOK_MARKER}\n"
        f"# taskledger-managed-repo: {repo_path.as_posix()}\n"
        f"# taskledger-managed-project: {project_path}\n"
        'if [ "${TASKLEDGER_GIT_HOOK:-}" = "1" ]; then\n'
        "  exit 0\n"
        "fi\n"
        "TASKLEDGER_GIT_HOOK=1 exec taskledger "
        f"--root {shlex.quote(workspace_root.as_posix())} repair index{quiet_suffix}\n"
    )

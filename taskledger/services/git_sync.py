from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from taskledger.errors import LaunchError
from taskledger.ids import slugify_project_ref
from taskledger.services.doctor import inspect_v2_project
from taskledger.storage.paths import load_project_locator
from taskledger.storage.project_config import (
    load_project_config_document,
    update_taskledger_dir,
)
from taskledger.storage.project_identity import project_name_or_default
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
) -> GitSyncConfig:
    locator = load_project_locator(workspace_root)
    document = load_project_config_document(locator.config_path)
    sync_table = document.get("sync")
    sync_git_table: dict[str, object] = {}
    if isinstance(sync_table, dict):
        maybe_git = sync_table.get("git")
        if isinstance(maybe_git, dict):
            sync_git_table = maybe_git

    repo_value = (
        repo.as_posix() if repo is not None else _as_str(sync_git_table.get("repo"))
    )
    if repo_value is None:
        repo_path = (locator.workspace_root / ".." / "taskledger-state").resolve()
    else:
        repo_path = _resolve_path(locator.workspace_root, Path(repo_value))

    project_value = project_path or _as_str(sync_git_table.get("project_path"))
    if project_value is None:
        project_name = project_name_or_default(
            locator.config_path,
            workspace_root=locator.workspace_root,
        )
        project_value = slugify_project_ref(project_name, empty="project")
    _validate_project_path(project_value)

    return GitSyncConfig(
        repo_path=repo_path,
        project_path=project_value,
        remote=remote or _as_str(sync_git_table.get("remote")) or "origin",
        branch=branch or _as_str(sync_git_table.get("branch")) or "main",
        allow_active_locks=(
            bool(sync_git_table.get("allow_active_locks"))
            if isinstance(sync_git_table.get("allow_active_locks"), bool)
            else False
        ),
        hooks=(
            bool(sync_git_table.get("hooks"))
            if isinstance(sync_git_table.get("hooks"), bool)
            else False
        ),
    )


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
    locator = load_project_locator(workspace_root)
    storage_path = _storage_path(config)
    taskledger_dir = locator.taskledger_dir.resolve()
    taskledger_dir_matches = storage_path.resolve() == taskledger_dir
    active_lock_count = _active_lock_count(locator.workspace_root)
    doctor = inspect_v2_project(locator.workspace_root)
    git_root = _git_root(config.repo_path)
    status_lines = _project_status_lines(config.repo_path, config.project_path)
    ahead, behind = _ahead_behind(config.repo_path)
    warnings: list[str] = []
    if not taskledger_dir_matches:
        warnings.append(
            "taskledger_dir does not point at the configured sync project path."
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
        "dirty": bool(status_lines),
        "ahead": ahead,
        "behind": behind,
        "active_lock_count": active_lock_count,
        "doctor_healthy": bool(doctor["healthy"]),
        "status_lines": status_lines,
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
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    locator = load_project_locator(workspace_root)
    original_config = locator.config_path.read_text(encoding="utf-8")
    _ensure_git_repo(config.repo_path, remote_url=remote_url, branch=config.branch)
    _write_sync_layout(config.repo_path)
    target_storage = _storage_path(config)
    current_storage = locator.taskledger_dir.resolve()
    warnings: list[str] = []
    if target_storage.exists() and _looks_like_storage_root(target_storage):
        if not adopt_existing and current_storage != target_storage.resolve():
            raise LaunchError(
                "Sync target already has taskledger state. Use --adopt-existing."
            )
    elif target_storage.exists() and any(target_storage.iterdir()):
        raise LaunchError(
            "Sync target exists and is not empty but is not a taskledger storage root."
        )
    elif current_storage != target_storage.resolve():
        target_storage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(current_storage, target_storage)
        if mode == "move":
            backup = _backup_path_for(current_storage)
            current_storage.rename(backup)
            warnings.append(
                f"Original storage was moved to backup: {backup.as_posix()}"
            )

    configured_value = _render_taskledger_dir_value(
        locator.workspace_root,
        target_storage,
    )
    update_taskledger_dir(locator.config_path, configured_value)
    doctor = inspect_v2_project(locator.workspace_root)
    if not doctor["healthy"]:
        from taskledger.storage.atomic import atomic_write_text

        atomic_write_text(locator.config_path, original_config)
        raise LaunchError(
            "taskledger doctor failed after sync init:\n"
            + "\n".join(str(item) for item in cast(list[object], doctor["errors"]))
        )

    hooks_report: dict[str, object] | None = None
    if install_hooks or config.hooks:
        hooks_report = install_git_hooks(
            workspace_root,
            repo=config.repo_path,
            project_path=config.project_path,
            force=force_hooks,
            quiet=True,
        )
    return {
        "kind": "taskledger_sync_git_init",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "storage_path": target_storage.as_posix(),
        "branch": config.branch,
        "remote": config.remote,
        "taskledger_dir_updated": True,
        "doctor_healthy": bool(doctor["healthy"]),
        "hooks": hooks_report,
        "warnings": warnings,
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
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    locator = load_project_locator(workspace_root)
    target_storage = _storage_path(config)
    if not _looks_like_storage_root(target_storage):
        raise LaunchError(
            "Sync target does not look like a taskledger storage root: "
            f"{target_storage}"
        )
    current_storage = locator.taskledger_dir.resolve()
    taskledger_dir_updated = current_storage != target_storage.resolve()
    if dry_run:
        return {
            "kind": "taskledger_sync_git_import_local",
            "repo_path": config.repo_path.as_posix(),
            "project_path": config.project_path,
            "storage_path": target_storage.as_posix(),
            "taskledger_dir_updated": taskledger_dir_updated,
            "dry_run": True,
            "doctor_healthy": None,
            "warnings": [],
        }
    original_config = locator.config_path.read_text(encoding="utf-8")
    if taskledger_dir_updated:
        configured_value = _render_taskledger_dir_value(
            locator.workspace_root, target_storage
        )
        update_taskledger_dir(locator.config_path, configured_value)
    doctor = inspect_v2_project(locator.workspace_root)
    if not doctor["healthy"]:
        from taskledger.storage.atomic import atomic_write_text

        atomic_write_text(locator.config_path, original_config)
        raise LaunchError(
            "taskledger doctor failed after sync import-local:\n"
            + "\n".join(str(item) for item in cast(list[object], doctor["errors"]))
        )
    return {
        "kind": "taskledger_sync_git_import_local",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "storage_path": target_storage.as_posix(),
        "taskledger_dir_updated": taskledger_dir_updated,
        "dry_run": False,
        "doctor_healthy": bool(doctor["healthy"]),
        "warnings": [],
    }


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
    config = build_git_sync_config(
        workspace_root,
        repo=repo,
        project_path=project_path,
        remote=remote,
        branch=branch,
    )
    locator = load_project_locator(workspace_root)
    storage_path = _storage_path(config)
    if locator.taskledger_dir.resolve() != storage_path.resolve():
        raise LaunchError(
            "taskledger_dir must point at sync repo project_path for export-local."
        )
    doctor = inspect_v2_project(locator.workspace_root)
    if not doctor["healthy"]:
        raise LaunchError(
            "taskledger doctor reported issues:\n"
            + "\n".join(str(item) for item in cast(list[object], doctor["errors"]))
        )
    active_lock_count = _active_lock_count(locator.workspace_root)
    allow_active = allow_active_locks or config.allow_active_locks
    if active_lock_count and not allow_active:
        raise LaunchError(
            f"{active_lock_count} active lock(s) detected. "
            "Use --allow-active-locks to continue."
        )
    _ensure_git_repo(config.repo_path, remote_url=None, branch=config.branch)
    if not allow_dirty:
        outside_dirty = _dirty_paths_outside_project(
            config.repo_path,
            config.project_path,
        )
        if outside_dirty:
            raise LaunchError(
                "Sync repo has dirty paths outside project_path. "
                "Use --allow-dirty to continue."
            )
    _run_git(
        config.repo_path,
        "add",
        "--all",
        "--",
        config.project_path,
        "README.md",
        ".gitignore",
        "meta/format.json",
    )
    staged = _run_git(
        config.repo_path,
        "diff",
        "--cached",
        "--quiet",
        "--exit-code",
        check=False,
    )
    committed = staged.returncode != 0
    commit_hash: str | None = None
    if committed:
        _run_git(
            config.repo_path,
            "commit",
            "-m",
            message or "Sync taskledger state",
            "--",
            config.project_path,
            "README.md",
            ".gitignore",
            "meta/format.json",
        )
        commit_hash = _run_git(config.repo_path, "rev-parse", "HEAD").stdout.strip()
    warnings: list[str] = []
    if active_lock_count and allow_active:
        warnings.append(
            f"{active_lock_count} active lock(s) were synced. "
            "Do not continue the same run on two PCs."
        )
    return {
        "kind": "taskledger_sync_git_export_local",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "committed": committed,
        "commit_hash": commit_hash,
        "active_lock_count": active_lock_count,
        "warnings": warnings,
    }


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
    if not allow_dirty and _project_status_lines(config.repo_path, config.project_path):
        raise LaunchError(
            "Sync repo has local changes under project_path. Use --allow-dirty to pull."
        )
    _run_git(config.repo_path, "pull", "--ff-only", config.remote, config.branch)
    imported = git_sync_import_local(
        workspace_root,
        repo=config.repo_path,
        project_path=config.project_path,
        remote=config.remote,
        branch=config.branch,
    )
    return {
        "kind": "taskledger_sync_git_pull",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "pulled": True,
        "import_local": imported,
        "doctor_healthy": imported["doctor_healthy"],
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
    exported = git_sync_export_local(
        workspace_root,
        repo=config.repo_path,
        project_path=config.project_path,
        remote=config.remote,
        branch=config.branch,
        message=message,
        allow_dirty=allow_dirty,
        allow_active_locks=allow_active_locks,
    )
    pushed = False
    if bool(exported["committed"]):
        _run_git(config.repo_path, "push", config.remote, config.branch)
        pushed = True
    return {
        "kind": "taskledger_sync_git_push",
        "repo_path": config.repo_path.as_posix(),
        "project_path": config.project_path,
        "committed": exported["committed"],
        "commit_hash": exported["commit_hash"],
        "pushed": pushed,
        "warnings": exported["warnings"],
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
    pull_payload = git_sync_pull(
        workspace_root,
        repo=config.repo_path,
        project_path=config.project_path,
        remote=config.remote,
        branch=config.branch,
        allow_dirty=allow_dirty,
    )
    push_payload = git_sync_push(
        workspace_root,
        repo=config.repo_path,
        project_path=config.project_path,
        remote=config.remote,
        branch=config.branch,
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
        "warnings": list(cast(list[object], push_payload["warnings"])),
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


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _resolve_path(root: Path, target: Path) -> Path:
    expanded = target.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (root / expanded).resolve()


def _validate_project_path(project_path: str) -> None:
    candidate = Path(project_path)
    if candidate.is_absolute():
        raise LaunchError("sync.git project_path must be relative.")
    if ".." in candidate.parts:
        raise LaunchError("sync.git project_path must not contain '..'.")
    if project_path.strip() in {"", ".", "./"}:
        raise LaunchError("sync.git project_path must not be empty.")


def _ensure_git_repo(repo_path: Path, *, remote_url: str | None, branch: str) -> None:
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
            if any(repo_path.iterdir()):
                raise LaunchError(
                    "Repo path exists and is not empty: "
                    f"{repo_path}. Expected git repo."
                )
            _run_git(repo_path, "init")
    _ensure_branch(repo_path, branch)


def _ensure_branch(repo_path: Path, branch: str) -> None:
    probe = _run_git(repo_path, "rev-parse", "--verify", branch, check=False)
    if probe.returncode == 0:
        _run_git(repo_path, "checkout", branch)
        return
    _run_git(repo_path, "checkout", "-b", branch)


def _write_sync_layout(repo_path: Path) -> None:
    readme = repo_path / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Taskledger sync state repository\n\n"
            "This repository stores external taskledger state.\n",
            encoding="utf-8",
        )
    gitignore = repo_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.tmp\n*.bak\n", encoding="utf-8")
    meta_dir = repo_path / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    format_path = meta_dir / "format.json"
    if not format_path.exists():
        format_path.write_text(
            json.dumps({"kind": "taskledger_sync_repo", "version": 1}, indent=2) + "\n",
            encoding="utf-8",
        )


def _render_taskledger_dir_value(workspace_root: Path, target: Path) -> str:
    try:
        return target.relative_to(workspace_root).as_posix()
    except ValueError:
        return target.as_posix()


def _active_lock_count(workspace_root: Path) -> int:
    try:
        return len(load_active_locks(workspace_root))
    except LaunchError:
        return 0


def _project_status_lines(repo_path: Path, project_path: str) -> list[str]:
    if _git_root(repo_path) is None:
        return []
    result = _run_git(repo_path, "status", "--short", "--", project_path, check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


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


def _git_root(path: Path) -> Path | None:
    candidate = path if path.exists() else path.parent
    result = subprocess.run(
        ["git", "-C", candidate.as_posix(), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _run_git(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise LaunchError(
            f"git {' '.join(args)} failed in {root.as_posix()}: "
            f"{stderr or f'exit {result.returncode}'}"
        )
    return result


def _looks_like_storage_root(path: Path) -> bool:
    return path.exists() and (path / "storage.yaml").exists()


def _backup_path_for(source: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return source.with_name(f"{source.name}.moved-{timestamp}")


def _dirty_paths_outside_project(repo_path: Path, project_path: str) -> list[str]:
    result = _run_git(repo_path, "status", "--porcelain", check=False)
    if result.returncode != 0:
        return []
    normalized_prefix = project_path.rstrip("/") + "/"
    outside: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path_token = line[3:].strip()
        if "->" in path_token:
            path_token = path_token.split("->", 1)[1].strip()
        if path_token == project_path or path_token.startswith(normalized_prefix):
            continue
        outside.append(path_token)
    return outside


def _render_hook_script(
    *,
    workspace_root: Path,
    repo_path: Path,
    project_path: str,
    quiet: bool,
) -> str:
    quiet_flag = " --quiet" if quiet else ""
    return (
        "#!/bin/sh\n"
        f"{_HOOK_MARKER}\n"
        "if [ \"${TASKLEDGER_GIT_HOOK:-}\" = \"1\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "TASKLEDGER_GIT_HOOK=1 exec taskledger "
        f"--root {workspace_root.as_posix()} "
        "sync git import-local "
        f"--repo {repo_path.as_posix()} "
        f"--project-path {project_path}{quiet_flag}\n"
    )

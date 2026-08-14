from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from taskledger.errors import LaunchError


@dataclass(slots=True, frozen=True)
class WorkspaceSnapshot:
    git_commit: str | None = None
    dirty: bool | None = None
    diff_hash: str | None = None
    status_hash: str | None = None
    captured_at: str | None = None


def capture_workspace_snapshot(workspace_root: Path) -> WorkspaceSnapshot:
    """Best-effort capture of the current workspace git state."""
    import hashlib

    from taskledger.timeutils import utc_now_iso

    root = git_root(workspace_root)
    if root is None:
        return WorkspaceSnapshot(captured_at=utc_now_iso())

    commit_result = run_git(root, "rev-parse", "HEAD", check=False)
    git_commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None

    status_result = run_git(root, "status", "--porcelain=v1", check=False)
    status_text = status_result.stdout if status_result.returncode == 0 else ""
    dirty = bool(status_text.strip())
    status_hash = (
        "sha256:" + hashlib.sha256(status_text.encode()).hexdigest()
        if status_text.strip()
        else None
    )

    diff_result = run_git(root, "diff", "--binary", check=False)
    diff_text = diff_result.stdout if diff_result.returncode == 0 else ""
    diff_hash = (
        "sha256:" + hashlib.sha256(diff_text.encode()).hexdigest()
        if diff_text.strip()
        else None
    )

    return WorkspaceSnapshot(
        git_commit=git_commit,
        dirty=dirty,
        diff_hash=diff_hash,
        status_hash=status_hash,
        captured_at=utc_now_iso(),
    )


def run_git(
    root: Path,
    *args: str,
    check: bool = True,
    env: Mapping[str, str] | None = None,
    suppress_taskledger_hooks: bool = False,
) -> subprocess.CompletedProcess[str]:
    command_env = dict(env) if env is not None else None
    if suppress_taskledger_hooks:
        if command_env is None:
            command_env = dict(os.environ)
        command_env["TASKLEDGER_GIT_HOOK"] = "1"
    result = subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        capture_output=True,
        text=True,
        check=False,
        env=command_env,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise LaunchError(
            f"git {' '.join(args)} failed in {root.as_posix()}: "
            f"{stderr or f'exit {result.returncode}'}"
        )
    return result


def git_root(path: Path) -> Path | None:
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


def status_path_token(line: str) -> str:
    token = line[3:].strip()
    if "->" in token:
        token = token.split("->", 1)[1].strip()
    return token.strip('"')


def relative_to_git_root(path: Path, git_root_path: Path) -> str:
    try:
        return path.resolve().relative_to(git_root_path.resolve()).as_posix() or "."
    except ValueError as exc:
        raise LaunchError(
            f"{path.as_posix()} is not inside Git root {git_root_path.as_posix()}."
        ) from exc


def render_relative_or_absolute(workspace_root: Path, target: Path) -> str:
    try:
        return target.relative_to(workspace_root).as_posix()
    except ValueError:
        return target.as_posix()


@dataclass(slots=True, frozen=True)
class GitPathState:
    """Git-aware path state for storage hygiene checks."""

    git_root: Path | None
    inside_git_worktree: bool
    tracked: bool
    ignored: bool
    ignore_source: str | None
    status_lines: tuple[str, ...]


def check_git_path_state(path: Path) -> GitPathState:
    """Check the Git state of a path (tracked, ignored, etc.).

    Uses:
    - git rev-parse --show-toplevel
    - git ls-files --error-unmatch -- <path>
    - git check-ignore -v --no-index -- <path>
    - git status --short -- <path>

    Graceful fallback when Git is not available.
    """
    root = git_root(path)
    if root is None:
        return GitPathState(
            git_root=None,
            inside_git_worktree=False,
            tracked=False,
            ignored=False,
            ignore_source=None,
            status_lines=(),
        )

    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return GitPathState(
            git_root=root,
            inside_git_worktree=False,
            tracked=False,
            ignored=False,
            ignore_source=None,
            status_lines=(),
        )

    # Check if tracked.
    tracked_result = run_git(
        root,
        "ls-files",
        "--error-unmatch",
        "--",
        relative,
        check=False,
    )
    tracked = tracked_result.returncode == 0 and bool(tracked_result.stdout.strip())

    # Check if ignored.
    ignored_result = run_git(
        root,
        "check-ignore",
        "-v",
        "--no-index",
        "--",
        relative,
        check=False,
    )
    ignored = ignored_result.returncode == 0 and bool(ignored_result.stdout.strip())
    ignore_source: str | None = None
    if ignored and ignored_result.stdout.strip():
        # Format is: <source>:<linenum>:<pattern>\t<filename>
        ignore_source = ignored_result.stdout.strip().split("\t", 1)[0].strip()

    # Get status.
    status_result = run_git(root, "status", "--short", "--", relative, check=False)
    status_lines_raw = (
        status_result.stdout.splitlines() if status_result.returncode == 0 else []
    )
    status_lines = tuple(line for line in status_lines_raw if line.strip())

    return GitPathState(
        git_root=root,
        inside_git_worktree=True,
        tracked=tracked,
        ignored=ignored,
        ignore_source=ignore_source,
        status_lines=status_lines,
    )

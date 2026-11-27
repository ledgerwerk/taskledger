from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.git_utils import (
    git_root as _git_root,
)
from taskledger.services.git_utils import (
    relative_to_git_root as _relative_to,
)
from taskledger.services.git_utils import (
    run_git as _run_git,
)
from taskledger.services.lock_inventory import LockInventory, build_lock_inventory
from taskledger.storage.project_context import load_project_context


@dataclass(slots=True, frozen=True)
class StorageIssue:
    """A structured issue surfaced by a storage location report."""

    severity: str  # "info", "warning", "error", "blocker"
    code: str
    message: str
    remediation: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.remediation:
            result["remediation"] = list(self.remediation)
        return result


@dataclass(slots=True, frozen=True)
class StorageLocationReport:
    workspace_root: str
    config_path: str
    taskledger_dir: str
    project_uuid: str | None
    project_name: str
    ledger_ref: str
    inside_workspace: bool
    is_git_repo: bool
    git_root: str | None
    active_lock_count: int
    has_active_locks: bool
    warnings: tuple[str, ...]
    mode: str = "canonical"
    project_root: str | None = None
    project_uuid_source: str | None = None
    manifest_path: str | None = None
    local_config_path: str | None = None
    checkout_id: str | None = None
    mounts: dict[str, dict[str, object]] | None = None
    workspace_provider: str | None = None
    store_root: str | None = None
    store_marker: str | None = None
    binding: str | None = None
    relative_path: str | None = None
    lock_file_count: int | None = None
    expired_lock_count: int | None = None
    stale_lock_count: int | None = None
    malformed_lock_count: int | None = None
    unverifiable_lock_count: int | None = None
    git_tracked: bool | None = None
    git_ignored: bool | None = None
    git_ignore_source: str | None = None
    issues: tuple[StorageIssue, ...] | None = None
    next_commands: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, object]:
        mounts = {
            name: {
                "storage": mount.get("storage"),
                "source": mount.get("source"),
                "root": mount.get("root"),
                "path": mount.get("path"),
                "binding": mount.get("binding", {"status": "unknown"}),
                "initialized": mount.get("initialized", False),
            }
            for name, mount in (self.mounts or {}).items()
        }
        payload: dict[str, object] = {
            "kind": "storage_location_report",
            "schema_version": 2,
            "mode": self.mode,
            "project": {
                "root": self.project_root or self.workspace_root,
                "uuid": self.project_uuid,
                "name": self.project_name,
            },
            "manifest": {"path": self.manifest_path, "schema_version": 3},
            "local_overrides": {
                "path": self.local_config_path,
                "exists": self.local_config_path is not None,
                "active": self.local_config_path is not None,
            },
            "config": {"path": self.config_path, "binding": {"status": "valid"}},
            "mounts": mounts,
            "active_lock_count": self.active_lock_count,
            "warnings": list(self.warnings),
        }
        if self.lock_file_count is not None:
            locks_section: dict[str, object] = {
                "active_count": self.active_lock_count,
                "lock_file_count": self.lock_file_count,
                "status": (
                    "invalid"
                    if self.malformed_lock_count
                    else "attention"
                    if self.active_lock_count or self.expired_lock_count
                    else "clean"
                ),
            }
            payload["lock_file_count"] = self.lock_file_count
            payload["locks"] = locks_section
            if self.expired_lock_count is not None:
                locks_section["expired_count"] = self.expired_lock_count
                payload["expired_lock_count"] = self.expired_lock_count
            if self.stale_lock_count is not None:
                locks_section["stale_count"] = self.stale_lock_count
            if self.malformed_lock_count is not None:
                locks_section["malformed_count"] = self.malformed_lock_count
                payload["malformed_lock_count"] = self.malformed_lock_count
            if self.unverifiable_lock_count is not None:
                locks_section["unverifiable_count"] = self.unverifiable_lock_count
        if self.issues:
            payload["issues"] = [issue.to_dict() for issue in self.issues]
        if self.next_commands:
            payload["next_commands"] = list(self.next_commands)
        return payload


@dataclass(slots=True, frozen=True)
class SyncStatusReport:
    taskledger_dir: str
    git_root: str | None
    relative_path: str | None
    clean: bool
    status_lines: tuple[str, ...]
    active_lock_count: int
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "storage_sync_status",
            "taskledger_dir": self.taskledger_dir,
            "git_root": self.git_root,
            "relative_path": self.relative_path,
            "clean": self.clean,
            "status_lines": list(self.status_lines),
            "active_lock_count": self.active_lock_count,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True, frozen=True)
class SyncPreflightReport:
    location: StorageLocationReport
    taskledger_dir_exists: bool
    doctor_healthy: bool
    doctor_errors: tuple[str, ...]
    doctor_warnings: tuple[str, ...]
    tracked_in_workspace_git: bool
    git_status_lines: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "storage_sync_preflight",
            "location": self.location.to_dict(),
            "taskledger_dir_exists": self.taskledger_dir_exists,
            "doctor_healthy": self.doctor_healthy,
            "doctor_errors": list(self.doctor_errors),
            "doctor_warnings": list(self.doctor_warnings),
            "tracked_in_workspace_git": self.tracked_in_workspace_git,
            "git_status_lines": list(self.git_status_lines),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True, frozen=True)
class StorageMoveReport:
    source: str
    target: str
    mode: str
    config_path: str
    project_uuid: str | None
    project_name: str
    ledger_ref: str
    inside_workspace: bool
    adopted_existing: bool
    backup_path: str | None
    doctor_healthy: bool
    doctor_errors: tuple[str, ...]
    next_commands: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "storage_move",
            "source": self.source,
            "target": self.target,
            "mode": self.mode,
            "config_path": self.config_path,
            "project_uuid": self.project_uuid,
            "project_name": self.project_name,
            "ledger_ref": self.ledger_ref,
            "inside_workspace": self.inside_workspace,
            "adopted_existing": self.adopted_existing,
            "backup_path": self.backup_path,
            "doctor_healthy": self.doctor_healthy,
            "doctor_errors": list(self.doctor_errors),
            "next_commands": list(self.next_commands),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True, frozen=True)
class SyncCommitReport:
    git_root: str
    relative_path: str
    commit: str
    message: str
    active_lock_count: int
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "storage_sync_commit",
            "git_root": self.git_root,
            "relative_path": self.relative_path,
            "commit": self.commit,
            "message": self.message,
            "active_lock_count": self.active_lock_count,
            "warnings": list(self.warnings),
        }


def build_storage_location_report(
    workspace_root: Path, *, require_initialized: bool = True
) -> StorageLocationReport:
    context = load_project_context(
        workspace_root, require_initialized=require_initialized
    )
    assert context.layout is not None
    validation_report = context.storage_validation
    mounts: dict[str, dict[str, object]] = {}
    for name, mount in context.layout.mounts.items():
        validation_result = (
            next(
                (
                    result
                    for result in validation_report.results
                    if result.path == mount.path
                ),
                None,
            )
            if validation_report is not None
            else None
        )
        binding: dict[str, str] = {"status": "unknown"}
        if validation_result is not None:
            binding["status"] = "valid" if validation_result.valid else "invalid"
            if validation_result.reason is not None:
                binding["reason"] = validation_result.reason
        mounts[name] = {
            "storage": str(mount.storage),
            "scope": str(mount.scope),
            "root": str(mount.root) if mount.root is not None else None,
            "path": str(mount.path),
            "binding": binding,
            "source": str(mount.source),
            "initialized": mount.path.exists(),
        }

    active_lock_count = _active_lock_count(workspace_root)
    try:
        inventory = _build_lock_inventory(workspace_root)
        lock_file_count = inventory.lock_file_count
        expired_lock_count = inventory.expired_count
        stale_lock_count = inventory.stale_count
        malformed_lock_count = inventory.malformed_count
        unverifiable_lock_count = inventory.unverifiable_count
    except LaunchError:
        lock_file_count = None
        expired_lock_count = None
        stale_lock_count = None
        malformed_lock_count = None
        unverifiable_lock_count = None

    warnings = (
        [f"{active_lock_count} active lock(s) are present."]
        if active_lock_count
        else []
    )
    data_root = context.paths.data_root
    store_root = context.store_root
    git_root = _git_root(data_root)
    relative_path = _relative_to(data_root, git_root) if git_root is not None else None
    return StorageLocationReport(
        workspace_root=context.project_root.as_posix(),
        config_path=context.config_path.as_posix(),
        taskledger_dir=data_root.as_posix(),
        project_uuid=context.project_uuid,
        project_name=context.project_name,
        ledger_ref=context.ledger_state.ref,
        inside_workspace=_is_within(data_root, context.project_root),
        is_git_repo=git_root is not None,
        git_root=git_root.as_posix() if git_root is not None else None,
        active_lock_count=active_lock_count,
        has_active_locks=active_lock_count > 0,
        warnings=tuple(warnings),
        mode="canonical",
        project_root=context.project_root.as_posix(),
        project_uuid_source="manifest",
        manifest_path=context.layout.manifest_path.as_posix(),
        local_config_path=context.layout.local_config_path.as_posix(),
        checkout_id=context.layout.checkout_id,
        mounts=mounts,
        workspace_provider=context.workspace_provider,
        store_root=store_root.as_posix() if store_root else None,
        store_marker=(
            context.store_marker_path.as_posix() if context.store_marker_path else None
        ),
        binding=context.binding_path.as_posix() if context.binding_path else None,
        relative_path=relative_path,
        lock_file_count=lock_file_count,
        expired_lock_count=expired_lock_count,
        stale_lock_count=stale_lock_count,
        malformed_lock_count=malformed_lock_count,
        unverifiable_lock_count=unverifiable_lock_count,
    )


def build_sync_preflight_report(workspace_root: Path) -> SyncPreflightReport:
    location = build_storage_location_report(workspace_root)
    taskledger_dir = Path(location.taskledger_dir)
    warnings = list(location.warnings)
    doctor_errors: tuple[str, ...]
    doctor_warnings: tuple[str, ...]
    doctor_healthy: bool
    exists = taskledger_dir.exists()
    if exists:
        try:
            doctor = inspect_v2_project(workspace_root)
        except LaunchError as exc:
            doctor_healthy = False
            doctor_errors = (str(exc),)
            doctor_warnings = ()
        else:
            doctor_healthy = bool(doctor["healthy"])
            doctor_errors = tuple(str(item) for item in doctor["errors"])  # type: ignore[attr-defined]
            doctor_warnings = tuple(str(item) for item in doctor["warnings"])  # type: ignore[attr-defined]
    else:
        doctor_healthy = False
        doctor_errors = (
            f"Resolved taskledger_dir does not exist: {taskledger_dir.as_posix()}",
        )
        doctor_warnings = ()
        warnings.append(doctor_errors[0])

    tracked_in_workspace_git = _tracked_in_workspace_git(workspace_root, taskledger_dir)
    if tracked_in_workspace_git:
        warnings.append(
            "Resolved taskledger_dir is inside the source repo and tracked by Git."
        )
    git_status_lines = tuple(_git_status_lines(taskledger_dir))
    return SyncPreflightReport(
        location=location,
        taskledger_dir_exists=exists,
        doctor_healthy=doctor_healthy,
        doctor_errors=doctor_errors,
        doctor_warnings=doctor_warnings,
        tracked_in_workspace_git=tracked_in_workspace_git,
        git_status_lines=git_status_lines,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def move_taskledger_storage(
    workspace_root: Path,
    *,
    target: Path,
    mode: str,
    adopt_existing: bool = False,
    force: bool = False,
) -> StorageMoveReport:
    del target, mode, adopt_existing, force
    load_project_context(workspace_root)
    raise LaunchError(
        "Canonical Taskledger storage has a fixed Ledgercore mount. "
        "Use `taskledger migrate` for legacy storage transitions."
    )


def build_sync_status_report(workspace_root: Path) -> SyncStatusReport:
    location = build_storage_location_report(workspace_root)
    mounts = location.to_dict().get("mounts", {})
    included = [
        Path(str(mounts["data"]["path"]))
        for name in ("data",)
        if isinstance(mounts, dict)
        and isinstance(mounts.get(name), dict)
        and Path(str(mounts[name]["path"])).exists()
    ]
    roots = {_git_root(path) for path in included}
    roots.discard(None)
    git_root = next(iter(roots), None) if len(roots) == 1 else None
    status_lines = tuple(line for path in included for line in _git_status_lines(path))
    warnings = list(location.warnings)
    if len(roots) > 1 or not roots:
        warnings.append(
            "Canonical Taskledger data is not represented by one sync repository."
        )
    return SyncStatusReport(
        taskledger_dir=location.taskledger_dir,
        git_root=git_root.as_posix() if git_root else None,
        relative_path=_relative_to(included[0], git_root)
        if included and git_root
        else None,
        clean=not status_lines,
        status_lines=status_lines,
        active_lock_count=location.active_lock_count,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def sync_commit_storage(workspace_root: Path, *, message: str) -> SyncCommitReport:
    location = build_storage_location_report(workspace_root)
    taskledger_dir = Path(location.taskledger_dir)
    git_root = _git_root(taskledger_dir)
    if git_root is None:
        raise LaunchError("Resolved taskledger_dir is not in a Git repository.")
    relative_path = _relative_to(taskledger_dir, git_root)
    status_lines = _git_status_lines(taskledger_dir)
    if not status_lines:
        raise LaunchError("No local Git changes exist under taskledger_dir.")
    _run_git(git_root, "add", "--all", "--", relative_path)
    _run_git(git_root, "commit", "-m", message, "--", relative_path)
    commit = _run_git(git_root, "rev-parse", "HEAD").stdout.strip()
    warnings: list[str] = []
    if location.active_lock_count:
        warnings.append(f"{location.active_lock_count} active lock(s) were committed.")
    return SyncCommitReport(
        git_root=git_root.as_posix(),
        relative_path=relative_path,
        commit=commit,
        message=message,
        active_lock_count=location.active_lock_count,
        warnings=tuple(warnings),
    )


def _build_lock_inventory(workspace_root: Path) -> LockInventory:
    """Build lock inventory for the given workspace root.

    Raises LaunchError if paths cannot be resolved (no fail-open).
    """
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    return build_lock_inventory(paths)


def _active_lock_count(workspace_root: Path) -> int:
    try:
        inventory = _build_lock_inventory(workspace_root)
        return inventory.active_count
    except LaunchError:
        return 0


def _tracked_in_workspace_git(workspace_root: Path, taskledger_dir: Path) -> bool:
    if not _is_within(taskledger_dir, workspace_root):
        return False
    git_root = _git_root(workspace_root)
    if git_root is None:
        return False
    relative_path = _relative_to(taskledger_dir, git_root)
    result = _run_git(git_root, "ls-files", "--", relative_path, check=False)
    return bool(result.stdout.strip())


def _git_status_lines(path: Path) -> list[str]:
    git_root = _git_root(path)
    if git_root is None:
        return []
    relative_path = _relative_to(path, git_root)
    result = _run_git(git_root, "status", "--short", "--", relative_path)
    return [line for line in result.stdout.splitlines() if line.strip()]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

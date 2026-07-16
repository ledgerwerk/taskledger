from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ledgercore import locate_ledger_project

from taskledger.errors import LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.git_utils import (
    git_root as _git_root,
)
from taskledger.services.git_utils import (
    relative_to_git_root as _relative_to,
)
from taskledger.services.git_utils import (
    render_relative_or_absolute as _render_taskledger_dir_value,
)
from taskledger.services.git_utils import (
    run_git as _run_git,
)
from taskledger.storage.ledger_config import load_ledger_config
from taskledger.storage.paths import DEFAULT_TASKLEDGER_DIR_NAME, load_project_locator
from taskledger.storage.project_config import update_taskledger_dir
from taskledger.storage.project_context import load_project_context
from taskledger.storage.project_identity import (
    load_project_uuid,
    project_name_or_default,
)
from taskledger.storage.task_store import load_active_locks


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
    mode: str = "legacy"
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

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": "storage_location_report",
            "mode": self.mode,
            "workspace_root": self.workspace_root,
            "project_root": self.project_root or self.workspace_root,
            "config_path": self.config_path,
            "project_uuid": self.project_uuid,
            "project_name": self.project_name,
            "ledger_ref": self.ledger_ref,
            "active_lock_count": self.active_lock_count,
            "has_active_locks": self.has_active_locks,
            "warnings": list(self.warnings),
        }
        if self.mode == "legacy":
            payload.update(
                {
                    "taskledger_dir": self.taskledger_dir,
                    "inside_workspace": self.inside_workspace,
                    "is_git_repo": self.is_git_repo,
                    "git_root": self.git_root,
                }
            )
        else:
            payload.update(
                {
                    "workspace_provider": self.workspace_provider,
                    "store_root": self.store_root,
                    "store_marker": self.store_marker,
                    "binding": self.binding,
                    "relative_path": self.relative_path,
                    "taskledger_dir": self.taskledger_dir,
                    "git_root": self.git_root,
                }
            )
            payload.update(
                {
                    "manifest_path": self.manifest_path,
                    "local_config_path": self.local_config_path,
                    "checkout_id": self.checkout_id,
                    "mounts": self.mounts or {},
                }
            )
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


def build_storage_location_report(workspace_root: Path) -> StorageLocationReport:
    try:
        context = load_project_context(workspace_root)
    except LaunchError:
        locator = locate_ledger_project(workspace_root)
        if locator is not None and locator.source == "canonical":
            raise
        context = None
    if (
        context is not None
        and context.mode == "canonical"
        and context.layout is not None
    ):
        mounts = {
            name: {
                "storage": str(mount.storage),
                "scope": str(mount.scope),
                "path": str(mount.path),
                "source": str(mount.source),
                "initialized": mount.path.exists(),
            }
            for name, mount in context.layout.mounts.items()
        }
        active_lock_count = _active_lock_count(workspace_root)
        warnings = (
            [f"{active_lock_count} active lock(s) are present."]
            if active_lock_count
            else []
        )
        store_root = context.store_root
        git_root = _git_root(store_root) if store_root is not None else None
        relative_path = (
            _relative_to(context.paths.data_root, git_root)
            if git_root is not None
            else None
        )
        return StorageLocationReport(
            workspace_root=context.project_root.as_posix(),
            config_path=context.config_path.as_posix(),
            taskledger_dir=context.paths.data_root.as_posix(),
            project_uuid=context.project_uuid,
            project_name=context.project_name,
            ledger_ref=context.ledger_state.ref,
            inside_workspace=False,
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
            store_marker=context.store_marker_path.as_posix()
            if context.store_marker_path
            else None,
            binding=context.binding_path.as_posix() if context.binding_path else None,
            relative_path=relative_path,
        )
    legacy_locator = load_project_locator(workspace_root)
    taskledger_dir = legacy_locator.taskledger_dir
    config_path = legacy_locator.config_path
    project_uuid = load_project_uuid(config_path)
    project_name = project_name_or_default(
        config_path,
        workspace_root=legacy_locator.workspace_root,
    )
    ledger_ref = load_ledger_config(config_path).ref
    inside_workspace = _is_within(taskledger_dir, legacy_locator.workspace_root)
    git_root = _git_root(taskledger_dir)
    active_lock_count = _active_lock_count(legacy_locator.workspace_root)
    legacy_warnings: list[str] = []
    if inside_workspace:
        legacy_warnings.append(
            "Resolved taskledger_dir is inside the workspace. "
            "Keep it ignored in source control."
        )
    if active_lock_count:
        legacy_warnings.append(f"{active_lock_count} active lock(s) are present.")
    return StorageLocationReport(
        workspace_root=legacy_locator.workspace_root.as_posix(),
        config_path=config_path.as_posix(),
        taskledger_dir=taskledger_dir.as_posix(),
        project_uuid=project_uuid,
        project_name=project_name,
        ledger_ref=ledger_ref,
        inside_workspace=inside_workspace,
        is_git_repo=git_root is not None,
        git_root=git_root.as_posix() if git_root is not None else None,
        active_lock_count=active_lock_count,
        has_active_locks=active_lock_count > 0,
        warnings=tuple(legacy_warnings),
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
    try:
        context = load_project_context(workspace_root)
    except LaunchError:
        context = None
    if context is not None and context.mode == "canonical":
        raise LaunchError(
            "Canonical Taskledger storage has one fixed sibling location. "
            "Use `taskledger migrate` to convert a legacy or superseded layout."
        )
    if mode not in {"copy", "move"}:
        raise LaunchError("mode must be one of: copy, move.")
    locator = load_project_locator(workspace_root)
    source = locator.taskledger_dir
    target_path = _resolve_target(locator.workspace_root, target)
    default_source = locator.workspace_root / DEFAULT_TASKLEDGER_DIR_NAME
    if source == target_path:
        raise LaunchError("Source and target taskledger_dir are identical.")
    if not source.exists():
        raise LaunchError(
            "Current taskledger_dir does not exist: "
            f"{source.as_posix()}. Run taskledger init first."
        )
    if source != default_source and not force:
        raise LaunchError(
            "Current config already points to a non-default taskledger_dir. "
            "Use --force to migrate from an existing external location."
        )
    if target_path.exists():
        if any(target_path.iterdir()):
            if not adopt_existing:
                raise LaunchError(
                    "Target exists and is not empty. "
                    "Use --adopt-existing to point at it explicitly."
                )
        else:
            adopt_existing = False
    if adopt_existing:
        _verify_adoptable_target(target_path)
    else:
        shutil.copytree(source, target_path, dirs_exist_ok=target_path.exists())

    original_config_text = locator.config_path.read_text(encoding="utf-8")
    configured_value = _render_taskledger_dir_value(locator.workspace_root, target_path)
    update_taskledger_dir(locator.config_path, configured_value)
    doctor = inspect_v2_project(locator.workspace_root)
    if not doctor["healthy"]:
        from taskledger.storage.atomic import atomic_write_text

        atomic_write_text(locator.config_path, original_config_text)
        raise LaunchError(
            "taskledger doctor failed after updating taskledger_dir:\n"
            + "\n".join(str(item) for item in doctor["errors"])  # type: ignore[attr-defined]
        )

    backup_path: Path | None = None
    warnings: list[str] = []
    if mode == "move":
        backup_path = _backup_path_for(source)
        source.rename(backup_path)
        warnings.append(
            "Original storage was preserved at "
            f"{backup_path.as_posix()} as a recoverable backup."
        )

    target_git_root = _git_root(target_path)
    next_commands = [
        f"git add {locator.config_path.name}",
    ]
    if target_git_root is not None:
        next_commands.append(f"git -C {target_git_root.as_posix()} status --short")
    return StorageMoveReport(
        source=source.as_posix(),
        target=target_path.as_posix(),
        mode=mode,
        config_path=locator.config_path.as_posix(),
        project_uuid=load_project_uuid(locator.config_path),
        project_name=project_name_or_default(
            locator.config_path,
            workspace_root=locator.workspace_root,
        ),
        ledger_ref=load_ledger_config(locator.config_path).ref,
        inside_workspace=_is_within(target_path, locator.workspace_root),
        adopted_existing=adopt_existing,
        backup_path=backup_path.as_posix() if backup_path is not None else None,
        doctor_healthy=bool(doctor["healthy"]),
        doctor_errors=tuple(str(item) for item in doctor["errors"]),  # type: ignore[attr-defined]
        next_commands=tuple(next_commands),
        warnings=tuple(warnings),
    )


def build_sync_status_report(workspace_root: Path) -> SyncStatusReport:
    location = build_storage_location_report(workspace_root)
    if location.mode == "canonical":
        mounts = location.to_dict().get("mounts", {})
        included = [
            Path(str(mounts[name]["path"]))
            for name in ("data",)
            if isinstance(mounts, dict)
            and isinstance(mounts.get(name), dict)
            and Path(str(mounts[name]["path"])).exists()
        ]
        roots = {_git_root(path) for path in included}
        roots.discard(None)
        git_root = next(iter(roots), None) if len(roots) == 1 else None
        status_lines = tuple(
            line for path in included for line in _git_status_lines(path)
        )
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
    taskledger_dir = Path(location.taskledger_dir)
    git_root = _git_root(taskledger_dir)
    status_lines = tuple(_git_status_lines(taskledger_dir))
    warnings = list(location.warnings)
    if git_root is None:
        warnings.append("Resolved taskledger_dir is not in a Git repository.")
    return SyncStatusReport(
        taskledger_dir=location.taskledger_dir,
        git_root=git_root.as_posix() if git_root is not None else None,
        relative_path=_relative_to(taskledger_dir, git_root) if git_root else None,
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


def _active_lock_count(workspace_root: Path) -> int:
    try:
        return len(load_active_locks(workspace_root))
    except LaunchError:
        return 0


def _resolve_target(workspace_root: Path, target: Path) -> Path:
    expanded = target.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (workspace_root / expanded).resolve()


def _verify_adoptable_target(target: Path) -> None:
    if not target.exists():
        raise LaunchError("Cannot adopt a missing target directory.")
    if not (target / "storage.yaml").exists():
        raise LaunchError(
            f"Target {target.as_posix()} does not look like a taskledger storage root."
        )


def _backup_path_for(source: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return source.with_name(f"{source.name}.moved-{timestamp}")


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

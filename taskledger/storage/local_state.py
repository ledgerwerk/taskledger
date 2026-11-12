"""Safe recovery for machine-local Taskledger runtime and logs mounts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock

from taskledger.errors import LaunchError
from taskledger.storage.ledgercore_backend import (
    LOGS_MOUNT,
    RUNTIME_MOUNT,
    initialize_taskledger_mount_bindings,
    validate_taskledger_mount,
)

if TYPE_CHECKING:
    from taskledger.storage.project_context import TaskledgerProjectContext


@dataclass(frozen=True, slots=True)
class LocalMountRecovery:
    mount: str
    action: str
    path: Path


@dataclass(frozen=True, slots=True)
class LocalStateRecoveryResult:
    recoveries: tuple[LocalMountRecovery, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "recoveries": [
                {
                    "mount": recovery.mount,
                    "action": recovery.action,
                    "path": str(recovery.path),
                }
                for recovery in self.recoveries
            ]
        }


def _unsafe_local_mount(name: str, path: Path, reason: str) -> LaunchError:
    remediation = [
        "Inspect the directory and its binding marker.",
        "Move the directory aside if it is stale local state.",
        "Retry the Taskledger command.",
    ]
    return LaunchError(
        f"TASKLEDGER_LOCAL_STATE_RECOVERY_UNSAFE: refusing to initialize the "
        f"{name} mount at {path}: {reason}",
        code="TASKLEDGER_LOCAL_STATE_RECOVERY_UNSAFE",
        details={
            "mount": name,
            "path": str(path),
            "reason": reason,
            "remediation": remediation,
        },
        remediation=remediation,
    )


def _validate_data_mount(layout: Any) -> None:
    mount = layout.mounts["data"]
    validation = validate_taskledger_mount(mount, allow_missing=False)
    if not validation.valid:
        reason = validation.reason or "invalid data binding"
        raise LaunchError(
            f"TASKLEDGER_STORAGE_BINDING_INVALID: durable data mount at "
            f"{mount.path} is invalid: {reason}",
            code="TASKLEDGER_STORAGE_BINDING_INVALID",
            details={
                "mount": "data",
                "path": str(mount.path),
                "reason": reason,
            },
        )


def _mount_needs_initialization(name: str, mount: Any) -> bool:
    root = mount.path
    marker = mount.binding_path

    if root.is_symlink():
        raise _unsafe_local_mount(name, root, "symlinked_mount_root")
    if marker.is_symlink():
        raise _unsafe_local_mount(name, marker, "symlinked_binding_marker")
    if root.exists() and not root.is_dir():
        raise _unsafe_local_mount(name, root, "mount_root_not_directory")

    validation = validate_taskledger_mount(mount, allow_missing=True)
    if marker.exists():
        if not root.is_dir():
            raise _unsafe_local_mount(name, root, "binding_without_mount_directory")
        if not validation.valid:
            raise _unsafe_local_mount(
                name,
                root,
                validation.reason or "binding_invalid",
            )
        return False

    if not root.exists():
        if not validation.valid:
            raise _unsafe_local_mount(
                name,
                root,
                validation.reason or "invalid_mount_metadata",
            )
        return True

    try:
        is_empty = not any(root.iterdir())
    except OSError as exc:
        reason = f"unable_to_inspect_mount: {exc}"
        raise _unsafe_local_mount(name, root, reason) from exc
    if not is_empty:
        raise _unsafe_local_mount(name, root, "non_empty_unbound")
    return True


def ensure_local_state_for_mutation(
    context: TaskledgerProjectContext,
) -> LocalStateRecoveryResult | None:
    """Initialize safe, missing machine-local mounts before a canonical mutation."""
    if context.mode != "canonical" or context.layout is None:
        return None
    manifest = getattr(context.loaded_project, "manifest", None)
    if getattr(manifest, "schema_version", None) != 3:
        return None
    if (
        RUNTIME_MOUNT not in context.layout.mounts
        or LOGS_MOUNT not in context.layout.mounts
    ):
        return None

    layout = context.layout
    _validate_data_mount(layout)

    runtime_root = layout.mounts[RUNTIME_MOUNT].path
    lock_path = runtime_root.with_name(f"{runtime_root.name}.recovery.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(lock_path)):
        _validate_data_mount(layout)
        pending = tuple(
            name
            for name in (RUNTIME_MOUNT, LOGS_MOUNT)
            if _mount_needs_initialization(name, layout.mounts[name])
        )

        initialized: tuple[LocalMountRecovery, ...] = ()
        if pending:
            initialize_taskledger_mount_bindings(layout, mounts=pending)
            initialized = tuple(
                LocalMountRecovery(name, "initialized", layout.mounts[name].path)
                for name in pending
            )

        paths = context.paths
        for directory in (
            paths.runtime_root / "checkouts" / paths.ledger_ref,
            paths.events_dir,
            paths.agent_logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    if not initialized:
        return None
    return LocalStateRecoveryResult(initialized)


__all__ = [
    "LocalMountRecovery",
    "LocalStateRecoveryResult",
    "ensure_local_state_for_mutation",
]

"""Safe recovery for Taskledger's disposable indexes cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from filelock import FileLock

from taskledger.errors import CacheRecoveryFailed, LaunchError
from taskledger.storage.ledgercore_backend import (
    INDEX_MOUNT,
    initialize_taskledger_bindings,
    validate_taskledger_mount,
)

if TYPE_CHECKING:
    from taskledger.storage.project_context import TaskledgerProjectContext


@dataclass(frozen=True, slots=True)
class IndexCacheRecoveryResult:
    """Describe local cache maintenance performed before a mutation."""

    action: Literal["initialized", "rebuilt", "quarantined_rebuilt"]
    cache_root: Path
    quarantine_path: Path | None
    counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "cache_path": str(self.cache_root),
            "quarantine_path": (
                str(self.quarantine_path) if self.quarantine_path is not None else None
            ),
            "counts": dict(self.counts),
        }


def _index_validation_result(
    context: TaskledgerProjectContext, root: Path
) -> Any | None:
    report = context.storage_validation
    if report is None:
        return None
    return next(
        (result for result in report.results if result.path == root),
        None,
    )


def _safe_recovery_candidate(context: TaskledgerProjectContext) -> bool:
    if context.mode != "canonical" or context.layout is None:
        return False
    if context.initialization.status != "ready":
        return False
    manifest = getattr(context.loaded_project, "manifest", None)
    if getattr(manifest, "schema_version", None) != 3:
        return False
    if (
        not context.paths.data_root.is_dir()
        or not context.paths.storage_meta_path.is_file()
    ):
        return False
    index_mount = context.layout.mounts.get(INDEX_MOUNT)
    if index_mount is None or index_mount.storage != "cache":
        return False

    root = index_mount.path
    index_result = _index_validation_result(context, root)
    if index_result is not None and index_result.path != root:
        return False
    report = context.storage_validation
    return not (
        report is not None
        and any(not result.valid and result.path != root for result in report.results)
    )


def _expected_index_files_missing(context: TaskledgerProjectContext) -> bool:
    paths = context.paths
    return any(
        not path.is_file()
        for path in (
            paths.task_index_path,
            paths.active_locks_index_path,
            paths.sidecar_index_path,
            paths.introductions_index_path,
            paths.dependencies_index_path,
        )
    )


def _unique_quarantine_path(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    while True:
        candidate = root.with_name(f"{root.name}.quarantine-{stamp}-{uuid4().hex[:8]}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate


def _recovery_failure(
    root: Path,
    quarantine: Path | None,
    exc: Exception,
) -> CacheRecoveryFailed:
    return CacheRecoveryFailed(
        "TASKLEDGER_CACHE_RECOVERY_FAILED: unable to rebuild indexes cache "
        f"{root}: {exc}",
        details={
            "cache_path": str(root),
            "quarantine_path": str(quarantine) if quarantine is not None else None,
            "operation": "rebuild",
            "cause": str(exc),
        },
        remediation=[
            "Run `taskledger storage validate`.",
            "Run `taskledger repair index`.",
        ],
    )


def ensure_indexes_cache_for_mutation(
    context: TaskledgerProjectContext,
) -> IndexCacheRecoveryResult | None:
    """Prepare the disposable indexes mount before writing derived state.

    This helper is intentionally narrow: it only handles a canonical schema-3
    cache mount after persistent config/data storage has validated successfully.
    """
    if not _safe_recovery_candidate(context):
        return None

    layout = context.layout
    if layout is None:
        return None
    index_mount = layout.mounts[INDEX_MOUNT]
    root = index_mount.path
    root.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(f"{root}.recovery.lock"):
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            return None

        marker = root / ".ledger-project.toml"
        if marker.is_symlink():
            return None

        # Re-check after locking so a concurrent mutation can safely win.
        validation = validate_taskledger_mount(index_mount, allow_missing=True)
        if marker.exists():
            if not validation.valid:
                return None
            if not _expected_index_files_missing(context):
                return None
            try:
                from taskledger.storage.indexes import rebuild_v2_indexes
                from taskledger.storage.task_store import v2_paths_from_context

                counts = rebuild_v2_indexes(v2_paths_from_context(context))
            except (LaunchError, OSError) as exc:
                raise _recovery_failure(root, None, exc) from exc
            return IndexCacheRecoveryResult("rebuilt", root, None, counts)

        quarantine: Path | None = None
        try:
            if root.exists() and any(root.iterdir()):
                quarantine = _unique_quarantine_path(root)
                root.rename(quarantine)

            initialize_taskledger_bindings(
                layout,
                initialize_config=False,
                initialize_data=False,
                initialize_indexes=True,
            )
            from taskledger.storage.indexes import rebuild_v2_indexes
            from taskledger.storage.task_store import v2_paths_from_context

            counts = rebuild_v2_indexes(v2_paths_from_context(context))
        except (LaunchError, OSError) as exc:
            marker = root / ".ledger-project.toml"
            if marker.is_file() and not marker.is_symlink():
                marker.unlink(missing_ok=True)
            raise _recovery_failure(root, quarantine, exc) from exc

        action: Literal["initialized", "quarantined_rebuilt"] = (
            "quarantined_rebuilt" if quarantine is not None else "initialized"
        )
        return IndexCacheRecoveryResult(action, root, quarantine, counts)


__all__ = ["IndexCacheRecoveryResult", "ensure_indexes_cache_for_mutation"]

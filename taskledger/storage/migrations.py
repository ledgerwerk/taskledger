"""Migration framework for taskledger storage layout and record schema changes."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskledger.domain.states import TASKLEDGER_STORAGE_LAYOUT_VERSION
from taskledger.errors import LaunchError
from taskledger.storage.ledger_config import load_ledger_config

Record = dict[str, Any]
MigrationFunc = Callable[[Path], None]
RecordMigrationFunc = Callable[[Record], Record]


@dataclass(frozen=True)
class LayoutMigration:
    from_version: int
    to_version: int
    name: str
    apply: MigrationFunc


@dataclass(frozen=True)
class RecordMigration:
    object_type: str
    from_schema_version: int
    to_schema_version: int
    name: str
    apply: RecordMigrationFunc


@dataclass(frozen=True)
class MigrationNeeded:
    path: Path
    object_type: str
    current_version: int
    target_version: int


@dataclass(frozen=True)
class MigrationScanIssue:
    path: Path
    object_type: str
    message: str


LAYOUT_MIGRATIONS: tuple[LayoutMigration, ...] = (
    LayoutMigration(
        from_version=2,
        to_version=3,
        name="branch-scoped-ledgers",
        apply=lambda workspace_root: (
            _migrate_v2_unscoped_state_to_branch_scoped_ledgers(workspace_root)
        ),
    ),
    LayoutMigration(
        from_version=3,
        to_version=4,
        name="canonical-storage-metadata",
        apply=lambda workspace_root: _migrate_v3_storage_metadata(workspace_root),
    ),
    LayoutMigration(
        from_version=4,
        to_version=5,
        name="canonical-storage-topology",
        apply=lambda workspace_root: None,
    ),
)

RECORD_MIGRATIONS: tuple[RecordMigration, ...] = ()


def required_layout_migrations(current: int, target: int) -> list[LayoutMigration]:
    migrations: list[LayoutMigration] = []
    version = current
    while version < target:
        match = next(
            (
                migration
                for migration in LAYOUT_MIGRATIONS
                if migration.from_version == version
            ),
            None,
        )
        if match is None:
            raise LaunchError(
                f"No migration path from storage layout {version} to {version + 1}."
            )
        migrations.append(match)
        version = match.to_version
    return migrations


def scan_records_for_migration(
    workspace_root: Path,
) -> list[MigrationNeeded]:
    needed, _issues = inspect_records_for_migration(workspace_root)
    return needed


def inspect_records_for_migration(
    workspace_root: Path,
) -> tuple[list[MigrationNeeded], list[MigrationScanIssue]]:
    """Scan all durable records for pending schema migrations.

    Returns records whose schema_version is below the current target and any
    malformed Markdown/frontmatter records encountered during the scan.
    """
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(workspace_root)
    needed: list[MigrationNeeded] = []
    issues: list[MigrationScanIssue] = []
    if not paths.tasks_dir.exists():
        return needed, issues

    for task_dir in sorted(paths.tasks_dir.glob("task-*")):
        if not task_dir.is_dir():
            continue
        _scan_dir(task_dir / "plans", "plan", needed, issues)
        _scan_dir(task_dir / "questions", "question", needed, issues)
        _scan_dir(task_dir / "runs", "run", needed, issues)
        _scan_dir(task_dir / "changes", "change", needed, issues)
        _scan_dir(task_dir / "todos", "todo", needed, issues)
        _scan_dir(task_dir / "links", "link", needed, issues)
        _scan_dir(task_dir / "requirements", "requirement", needed, issues)
        _scan_dir(task_dir / "handoffs", "handoff", needed, issues)

        task_md = task_dir / "task.md"
        if task_md.exists():
            _scan_file(task_md, "task", needed, issues)

    return needed, issues


def apply_layout_migrations(
    workspace_root: Path,
    current_version: int,
    dry_run: bool = False,
) -> list[str]:
    """Apply layout migrations from current_version
    to TASKLEDGER_STORAGE_LAYOUT_VERSION.

    Returns list of migration names that were applied (or would be applied in dry_run).
    """
    from taskledger.storage.meta import read_storage_meta, write_storage_meta

    migrations = required_layout_migrations(
        current_version, TASKLEDGER_STORAGE_LAYOUT_VERSION
    )
    applied: list[str] = []
    for migration in migrations:
        if not dry_run:
            migration.apply(workspace_root)
        applied.append(migration.name)

    if not dry_run and applied:
        meta = read_storage_meta(workspace_root)
        if meta is not None:
            try:
                from taskledger._version import __version__ as tl_version
            except ImportError:
                tl_version = "unknown"
            from taskledger.timeutils import utc_now_iso

            updated = type(meta)(
                storage_layout_version=TASKLEDGER_STORAGE_LAYOUT_VERSION,
                record_schema_version=meta.record_schema_version,
                created_with_taskledger=meta.created_with_taskledger,
                created_at=meta.created_at,
                last_migrated_with_taskledger=tl_version,
                last_migrated_at=utc_now_iso(),
            )
            write_storage_meta(workspace_root, updated)

    return applied


def _scan_dir(
    directory: Path,
    object_type: str,
    needed: list[MigrationNeeded],
    issues: list[MigrationScanIssue],
) -> None:
    if not directory.exists():
        return
    for md_file in sorted(directory.glob("*.md")):
        _scan_file(md_file, object_type, needed, issues)


def _merge_tree_without_overwrite(source: Path, target: Path) -> None:
    """Recursively merge source into target, raising on conflicts.

    Rules:
    1. If target does not exist, move source to target.
    2. If both are directories, recursively merge children.
    3. If both are .ndjson files, append lines from source to target.
    4. If both are active-task.yaml files, keep more recent activation.
    5. If both are other files and byte-identical, delete source.
    6. If both are other files and differ, raise LaunchError.
    7. If file-vs-directory conflict, raise LaunchError.
    8. Only remove source directory if empty after merge.
    """
    if not source.exists():
        return

    if source.is_file():
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            return
        if target.is_file():
            # Special handling for ndjson files: merge by appending
            if source.suffix == ".ndjson" and target.suffix == ".ndjson":
                _merge_ndjson_files(source, target)
                return
            # Special handling for active-task.yaml: keep more recent
            if source.name == "active-task.yaml" and target.name == "active-task.yaml":
                _merge_active_task_files(source, target)
                return
            # For other files, check if identical
            if source.read_bytes() == target.read_bytes():
                source.unlink()
                return
            raise LaunchError(
                f"Migration conflict: cannot merge {source} -> {target} (files differ)"
            )
        raise LaunchError(
            f"Migration conflict: cannot merge {source} -> {target} "
            "(target is directory)"
        )

    if target.exists() and not target.is_dir():
        raise LaunchError(
            f"Migration conflict: cannot merge {source} -> {target} (target is file)"
        )

    target.mkdir(parents=True, exist_ok=True)

    for child in sorted(source.iterdir()):
        _merge_tree_without_overwrite(child, target / child.name)

    if not any(source.iterdir()):
        source.rmdir()


def _max_numeric_task_number(tasks_dir: Path) -> int | None:
    """Find the maximum numeric task ID in format task-NNNN."""
    if not tasks_dir.exists():
        return None

    max_number: int | None = None
    for child in tasks_dir.glob("task-*"):
        if not child.is_dir():
            continue
        match = re.fullmatch(r"task-(\d+)", child.name)
        if match is None:
            continue
        number = int(match.group(1))
        max_number = number if max_number is None else max(max_number, number)
    return max_number


def _get_task_created_at(task_dir: Path) -> Any | None:
    """Extract created_at timestamp from task.md."""
    task_md = task_dir / "task.md"
    if not task_md.exists():
        return None
    try:
        from taskledger.storage.frontmatter import read_markdown_front_matter

        metadata, _ = read_markdown_front_matter(task_md)
        return metadata.get("created_at")
    except Exception:  # noqa: BLE001
        return None


def _find_task_conflicts(
    root_tasks_dir: Path, ledger_tasks_dir: Path
) -> dict[str, tuple[Path, Path]]:
    """Find task IDs that exist in both root and ledger directories.

    Returns mapping of task_id -> (root_path, ledger_path) for all conflicting tasks.
    """
    conflicts: dict[str, tuple[Path, Path]] = {}
    if not root_tasks_dir.exists() or not ledger_tasks_dir.exists():
        return conflicts

    root_ids = {d.name for d in root_tasks_dir.glob("task-*") if d.is_dir()}
    ledger_ids = {d.name for d in ledger_tasks_dir.glob("task-*") if d.is_dir()}

    for task_id in root_ids & ledger_ids:
        conflicts[task_id] = (root_tasks_dir / task_id, ledger_tasks_dir / task_id)
    return conflicts


def _merge_ndjson_files(source: Path, target: Path) -> None:
    """Merge ndjson files by appending lines from source to target.

    Preserves event order: lines from source are appended to target.
    """
    if not source.exists() or not target.exists():
        return

    if source.is_dir() or target.is_dir():
        return

    # Read lines from both files
    source_lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    target_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)

    # Append source lines to target (avoiding duplicates)
    target_set = {line.rstrip() for line in target_lines}
    for line in source_lines:
        if line.rstrip() not in target_set:
            target_lines.append(line if line.endswith("\n") else line + "\n")

    # Write merged content back to target
    target.write_text("".join(target_lines), encoding="utf-8")


def _merge_active_task_files(source: Path, target: Path) -> None:
    """Merge active-task.yaml files by keeping the more recent activation.

    Compares activated_at timestamps and keeps the state with the later timestamp.
    """
    if not source.exists() or not target.exists():
        return

    if source.is_dir() or target.is_dir():
        return

    try:
        import yaml

        from taskledger.domain.models import ActiveTaskState

        # Read both YAML files as pure YAML
        source_data = yaml.safe_load(source.read_text(encoding="utf-8"))
        target_data = yaml.safe_load(target.read_text(encoding="utf-8"))

        # Parse as ActiveTaskState objects
        source_state = ActiveTaskState.from_dict(source_data)
        target_state = ActiveTaskState.from_dict(target_data)

        # Compare timestamps (ISO format strings are comparable)
        if source_state.activated_at > target_state.activated_at:
            # Source is newer, use source state and write to target
            metadata = source_state.to_dict()
            yaml_content = yaml.dump(
                metadata, default_flow_style=False, sort_keys=False
            )
            target.write_text(yaml_content, encoding="utf-8")
        # Otherwise keep target (it's newer or equal)

        source.unlink()
    except Exception as e:
        raise LaunchError(f"Failed to merge active-task.yaml files: {e}") from e


def _renumber_root_task(old_task_dir: Path, new_task_id: str) -> None:
    """Renumber a task directory and update all task_id references within it.

    Args:
        old_task_dir: Current path to the task directory
        new_task_id: New task ID (e.g., 'task-0005')
    """

    old_task_id = old_task_dir.name
    if old_task_id == new_task_id:
        return  # Already correct

    # Rename directory
    new_task_dir = old_task_dir.parent / new_task_id
    old_task_dir.rename(new_task_dir)

    from taskledger.storage.task_store import rewrite_task_refs

    rewrite_task_refs(new_task_dir, old_task_id, new_task_id)


def _renumber_ledger_task(old_task_dir: Path, new_task_id: str) -> None:
    """Renumber a ledger task (newer task gets higher ID).

    Uses same logic as root task renumbering.
    """
    _renumber_root_task(old_task_dir, new_task_id)


def _migrate_v2_unscoped_state_to_branch_scoped_ledgers(workspace_root: Path) -> None:
    """Migrate legacy root-level task state into branch-scoped ledgers (layout v2→v3).

    This migration:
    - Detects task ID conflicts between root and ledger tasks
    - Renumbers older root tasks to next available IDs
    - Moves/merges legacy root tasks/events/intros/releases into ledger namespace
    - Moves active-task.yaml with conflict detection
    - Removes and rebuilds indexes
    - Rebuilds derived indexes after the move
    """
    from taskledger.storage.indexes import rebuild_v2_indexes
    from taskledger.storage.paths import load_project_locator
    from taskledger.storage.task_store import resolve_v2_paths

    locator = load_project_locator(workspace_root)
    root = locator.taskledger_dir
    config = load_ledger_config(locator.config_path)
    ledger_dir = root / "ledgers" / config.ref

    # Ensure target ledger structure exists
    for subdir in ("tasks", "events", "indexes", "intros", "releases"):
        (ledger_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Handle task ID conflicts: keep older root tasks at lower IDs,
    # renumber newer ledger tasks
    root_tasks_dir = root / "tasks"
    ledger_tasks_dir = ledger_dir / "tasks"
    conflicts = _find_task_conflicts(root_tasks_dir, ledger_tasks_dir)

    if conflicts:
        # Get current max task number to determine renumbering for newer ledger tasks
        root_max = _max_numeric_task_number(root_tasks_dir) or 0
        next_available_id = root_max + 1

        # Sort conflicts by task ID number (ascending) so renumbering is predictable
        sorted_conflicts = sorted(
            conflicts.items(), key=lambda x: int(x[0].split("-")[1])
        )

        for _task_id, (root_task_path, ledger_task_path) in sorted_conflicts:
            # Compare timestamps to identify which is older
            root_created_at = _get_task_created_at(root_task_path)
            ledger_created_at = _get_task_created_at(ledger_task_path)

            # If ledger task is newer, renumber it to higher ID
            # (keep older root tasks at lower IDs)
            if (
                root_created_at is not None
                and ledger_created_at is not None
                and ledger_created_at > root_created_at
            ):
                new_task_id = f"task-{next_available_id:04d}"
                # Renumber the newer ledger task
                _renumber_ledger_task(ledger_task_path, new_task_id)
                next_available_id += 1

    # Move/merge canonical legacy directories
    for name in ("tasks", "events", "intros", "releases"):
        source = root / name
        target = ledger_dir / name
        if source.exists():
            _merge_tree_without_overwrite(source, target)

    # Move active task state
    source_active = root / "active-task.yaml"
    target_active = ledger_dir / "active-task.yaml"
    if source_active.exists():
        _merge_tree_without_overwrite(source_active, target_active)

    # Root indexes are derived cache. Remove them after canonical data is moved.
    root_indexes = root / "indexes"
    if root_indexes.exists():
        shutil.rmtree(root_indexes)

    # Rebuild target ledger indexes from canonical records
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))


def _scan_file(
    path: Path,
    default_object_type: str,
    needed: list[MigrationNeeded],
    issues: list[MigrationScanIssue],
) -> None:
    from taskledger.storage.frontmatter import read_markdown_front_matter

    try:
        metadata, _ = read_markdown_front_matter(path)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            MigrationScanIssue(
                path=path,
                object_type=default_object_type,
                message=f"Cannot parse {default_object_type} record {path}: {exc}",
            )
        )
        return
    version = metadata.get("schema_version")
    if not isinstance(version, int):
        return
    if version < 1:
        return  # Legacy/unversioned, not a migration candidate
    from taskledger.domain.states import TASKLEDGER_SCHEMA_VERSION

    if version < TASKLEDGER_SCHEMA_VERSION:
        needed.append(
            MigrationNeeded(
                path=path,
                object_type=str(metadata.get("object_type", default_object_type)),
                current_version=version,
                target_version=TASKLEDGER_SCHEMA_VERSION,
            )
        )


def _migrate_v3_storage_metadata(workspace_root: Path) -> None:
    from taskledger.storage.meta import read_storage_meta, write_storage_meta

    meta = read_storage_meta(workspace_root)
    if meta is None:
        return
    write_storage_meta(
        workspace_root,
        type(meta)(
            storage_layout_version=4,
            record_schema_version=meta.record_schema_version,
            created_with_taskledger=meta.created_with_taskledger,
            created_at=meta.created_at,
            last_migrated_with_taskledger=meta.last_migrated_with_taskledger,
            last_migrated_at=meta.last_migrated_at,
        ),
    )

"""Read-only inspection of canonical task-directory storage layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from taskledger.domain.states import TASKLEDGER_STORAGE_LAYOUT_VERSION
from taskledger.errors import LaunchError

if TYPE_CHECKING:
    from taskledger.storage.project_context import TaskledgerProjectContext
    from taskledger.storage.task_store import TaskledgerStoragePaths

TaskDirectoryLayoutKind = Literal["empty", "legacy", "uuid", "mixed", "invalid"]


@dataclass(frozen=True, slots=True)
class LedgerTaskDirectoryLayout:
    ledger_ref: str
    tasks_dir: Path
    kind: TaskDirectoryLayoutKind
    legacy_dirs: tuple[str, ...] = ()
    uuid_dirs: tuple[str, ...] = ()
    invalid_entries: tuple[str, ...] = ()
    journal_path: Path | None = None
    journal_status: str | None = None

    @property
    def needs_v5_to_v6(self) -> bool:
        return bool(self.legacy_dirs)

    @property
    def is_current(self) -> bool:
        return self.kind in {"empty", "uuid"} and not self.invalid_entries

    @property
    def repairable(self) -> bool:
        if self.kind == "invalid":
            return False
        if self.kind == "mixed":
            return self.journal_status == "prepared"
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "ledger_ref": self.ledger_ref,
            "tasks_dir": str(self.tasks_dir),
            "kind": self.kind,
            "legacy_dirs": list(self.legacy_dirs),
            "uuid_dirs": list(self.uuid_dirs),
            "invalid_entries": list(self.invalid_entries),
            "journal_path": str(self.journal_path) if self.journal_path else None,
            "journal_status": self.journal_status,
            "current": self.is_current,
            "repairable": self.repairable,
        }


@dataclass(frozen=True, slots=True)
class TaskDirectoryLayoutInspection:
    declared_version: int | None
    target_version: int
    ledgers: tuple[LedgerTaskDirectoryLayout, ...]
    legacy_ledgers: tuple[str, ...]
    mixed_ledgers: tuple[str, ...]
    invalid_ledgers: tuple[str, ...]
    current: bool
    repairable: bool

    @property
    def needs_reconciliation(self) -> bool:
        return not self.current

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_version": self.declared_version,
            "expected_version": self.target_version,
            "ledgers": [ledger.to_dict() for ledger in self.ledgers],
            "legacy_ledgers": list(self.legacy_ledgers),
            "mixed_ledgers": list(self.mixed_ledgers),
            "invalid_ledgers": list(self.invalid_ledgers),
            "current": self.current,
            "repairable": self.repairable,
            "requires_reconciliation": self.needs_reconciliation,
        }


def discover_canonical_ledger_refs(
    context: TaskledgerProjectContext,
) -> tuple[str, ...]:
    """Return every physical canonical ledger namespace in deterministic order."""
    ledgers_root = context.paths.data_root / "ledgers"
    if ledgers_root.is_symlink():
        raise LaunchError(f"Canonical ledger directory is a symlink: {ledgers_root}")
    if not ledgers_root.exists():
        return ()
    if not ledgers_root.is_dir():
        raise LaunchError(f"Canonical ledger path is not a directory: {ledgers_root}")

    from taskledger.storage.project_context import paths_for_ledger_ref

    refs: list[str] = []
    for entry in sorted(ledgers_root.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_dir():
            raise LaunchError(f"Invalid canonical ledger directory: {entry}")
        # Use the same single-segment validation as canonical path construction.
        paths_for_ledger_ref(context, entry.name)
        refs.append(entry.name)
    return tuple(refs)


def _inspect_task_directories(
    tasks_dir: Path,
) -> tuple[list[str], list[str], list[str]]:
    from taskledger.storage.task_directory_migration import (
        _is_uuid_directory_name,
        _parse_legacy_id,
    )

    legacy_dirs: list[str] = []
    uuid_dirs: list[str] = []
    invalid_entries: list[str] = []
    if tasks_dir.is_symlink():
        invalid_entries.append(f"symlink: {tasks_dir}")
    elif tasks_dir.exists() and not tasks_dir.is_dir():
        invalid_entries.append(f"not a directory: {tasks_dir}")
    elif tasks_dir.is_dir():
        for entry in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
            if entry.is_symlink():
                invalid_entries.append(f"symlink: {entry}")
                continue
            if not entry.is_dir():
                invalid_entries.append(f"not a task directory: {entry}")
                continue
            invalid_entries.extend(
                f"nested symlink: {nested}"
                for nested in entry.rglob("*")
                if nested.is_symlink()
            )
            if entry.name.startswith("task-"):
                try:
                    _parse_legacy_id(entry.name, entry)
                except LaunchError as exc:
                    invalid_entries.append(str(exc))
                else:
                    legacy_dirs.append(entry.name)
            elif _is_uuid_directory_name(entry.name):
                uuid_dirs.append(entry.name)
            else:
                invalid_entries.append(f"unknown task directory: {entry}")
    return legacy_dirs, uuid_dirs, invalid_entries


def _inspect_migration_journal(
    paths: TaskledgerStoragePaths,
) -> tuple[str | None, Path | None, list[str]]:
    from taskledger.storage.task_directory_migration import (
        _JOURNAL_NAME,
        _read_journal,
        _validate_completed_migration,
    )

    journal_path = paths.ledger_dir / _JOURNAL_NAME
    invalid_entries: list[str] = []
    if journal_path.is_symlink():
        return None, None, [f"migration journal is a symlink: {journal_path}"]
    try:
        journal = _read_journal(journal_path)
    except LaunchError as exc:
        return None, None, [str(exc)]
    if journal is None:
        return None, None, invalid_entries

    journal_status = str(journal["status"])
    if journal_status == "complete":
        try:
            _validate_completed_migration(paths, journal)
        except LaunchError as exc:
            invalid_entries.append(str(exc))
    return journal_status, journal_path, invalid_entries


def _directory_layout_kind(
    legacy_dirs: list[str], uuid_dirs: list[str], invalid_entries: list[str]
) -> TaskDirectoryLayoutKind:
    if invalid_entries:
        return "invalid"
    if legacy_dirs and uuid_dirs:
        return "mixed"
    if legacy_dirs:
        return "legacy"
    if uuid_dirs:
        return "uuid"
    return "empty"


def inspect_ledger_task_directory_layout(
    paths: TaskledgerStoragePaths, *, declared_version: int | None = None
) -> LedgerTaskDirectoryLayout:
    """Inspect one ledger's task directories and migration journal without mutation."""
    legacy_dirs, uuid_dirs, invalid_entries = _inspect_task_directories(paths.tasks_dir)
    journal_status, journal_path, journal_errors = _inspect_migration_journal(paths)
    invalid_entries.extend(journal_errors)
    if (
        declared_version is not None
        and declared_version < TASKLEDGER_STORAGE_LAYOUT_VERSION
        and uuid_dirs
        and not legacy_dirs
        and journal_status != "complete"
    ):
        invalid_entries.append(
            "UUID task directories under an older storage layout require a "
            "complete migration journal."
        )

    return LedgerTaskDirectoryLayout(
        ledger_ref=paths.ledger_ref,
        tasks_dir=paths.tasks_dir,
        kind=_directory_layout_kind(legacy_dirs, uuid_dirs, invalid_entries),
        legacy_dirs=tuple(legacy_dirs),
        uuid_dirs=tuple(uuid_dirs),
        invalid_entries=tuple(invalid_entries),
        journal_path=journal_path,
        journal_status=journal_status,
    )


def inspect_task_directory_layout(
    workspace_root: Path,
) -> TaskDirectoryLayoutInspection:
    """Inspect every canonical ledger's physical task-directory layout."""
    from taskledger.storage.meta import read_storage_meta
    from taskledger.storage.project_context import load_project_context
    from taskledger.storage.task_store import v2_paths_for_ledger_ref

    context = load_project_context(workspace_root, require_initialized=False)
    meta = read_storage_meta(context.project_root)
    declared_version = meta.storage_layout_version if meta is not None else None
    ledger_layouts = tuple(
        inspect_ledger_task_directory_layout(
            v2_paths_for_ledger_ref(context, ledger_ref),
            declared_version=declared_version,
        )
        for ledger_ref in discover_canonical_ledger_refs(context)
    )
    legacy_ledgers = tuple(
        ledger.ledger_ref for ledger in ledger_layouts if ledger.legacy_dirs
    )
    mixed_ledgers = tuple(
        ledger.ledger_ref
        for ledger in ledger_layouts
        if ledger.legacy_dirs and ledger.uuid_dirs
    )
    invalid_ledgers = tuple(
        ledger.ledger_ref for ledger in ledger_layouts if ledger.invalid_entries
    )
    return TaskDirectoryLayoutInspection(
        declared_version=declared_version,
        target_version=TASKLEDGER_STORAGE_LAYOUT_VERSION,
        ledgers=ledger_layouts,
        legacy_ledgers=legacy_ledgers,
        mixed_ledgers=mixed_ledgers,
        invalid_ledgers=invalid_ledgers,
        current=all(ledger.is_current for ledger in ledger_layouts),
        repairable=all(ledger.repairable for ledger in ledger_layouts),
    )

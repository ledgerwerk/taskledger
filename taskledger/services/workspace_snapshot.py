from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from taskledger.domain.models import ActorRef, HarnessRef, TaskRecord, TaskRunRecord
from taskledger.services import tasks as _tasks
from taskledger.services.git_utils import capture_workspace_snapshot, git_root, run_git
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    list_runs,
    resolve_task,
    resolve_v2_paths,
    save_run,
)
from taskledger.timeutils import utc_now_iso

SNAPSHOT_FORMAT = "worktree-content:v1"


@dataclass(slots=True, frozen=True)
class WorktreePathEntry:
    path: str
    status: str
    exists: bool
    kind: str
    size: int | None
    content_hash: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> WorktreePathEntry:
        return cls(
            path=str(data["path"]),
            status=str(data["status"]),
            exists=bool(data["exists"]),
            kind=str(data["kind"]),
            size=data.get("size") if isinstance(data.get("size"), int) else None,
            content_hash=data.get("content_hash")
            if isinstance(data.get("content_hash"), str)
            else None,
        )


@dataclass(slots=True, frozen=True)
class WorkspaceContentSnapshot:
    git_commit: str | None
    dirty: bool | None
    content_hash: str | None
    paths_hash: str | None
    entry_count: int
    entries: tuple[WorktreePathEntry, ...]
    captured_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "format": SNAPSHOT_FORMAT,
            "git_commit": self.git_commit,
            "dirty": self.dirty,
            "content_hash": self.content_hash,
            "paths_hash": self.paths_hash,
            "entry_count": self.entry_count,
            "captured_at": self.captured_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> WorkspaceContentSnapshot:
        entries = tuple(
            WorktreePathEntry.from_dict(item)
            for item in data.get("entries", [])
            if isinstance(item, dict)
        )
        return cls(
            git_commit=data.get("git_commit")
            if isinstance(data.get("git_commit"), str)
            else None,
            dirty=data.get("dirty") if isinstance(data.get("dirty"), bool) else None,
            content_hash=data.get("content_hash")
            if isinstance(data.get("content_hash"), str)
            else None,
            paths_hash=data.get("paths_hash")
            if isinstance(data.get("paths_hash"), str)
            else None,
            entry_count=data.get("entry_count")
            if isinstance(data.get("entry_count"), int)
            else len(entries),
            entries=entries,
            captured_at=data.get("captured_at")
            if isinstance(data.get("captured_at"), str)
            else None,
        )


@dataclass(slots=True, frozen=True)
class ImplementationSnapshotEvaluation:
    ok: bool
    reason_code: str
    message: str
    expected_format: str | None
    current_format: str | None
    expected_commit: str | None
    current_commit: str | None
    expected_content_hash: str | None
    current_content_hash: str | None
    expected_status_hash: str | None
    current_status_hash: str | None
    expected_diff_hash: str | None
    current_diff_hash: str | None
    command_hint: str | None
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _status_from_xy(x: str, y: str) -> str:
    codes = {x, y}
    if "D" in codes:
        return "deleted"
    if "R" in codes:
        return "renamed"
    if "C" in codes:
        return "added"
    if "T" in codes:
        return "typechange"
    if "A" in codes or x == "?":
        return "untracked" if x == "?" else "added"
    return "modified"


def _parse_status_z(data: str) -> list[tuple[str, str]]:
    tokens = data.split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        if len(token) < 4:
            continue
        x = token[0]
        y = token[1]
        path = token[3:]
        if x in {"R", "C"} or y in {"R", "C"}:
            index += 1
        entries.append((path, _status_from_xy(x, y)))
    return entries


def _entry_for_path(root: Path, path: str, status: str) -> WorktreePathEntry:
    absolute = root / path
    if not absolute.exists() and not absolute.is_symlink():
        return WorktreePathEntry(path, status, False, "missing", None, None)
    if absolute.is_symlink():
        target = absolute.readlink().as_posix()
        return WorktreePathEntry(
            path,
            status,
            True,
            "symlink",
            len(target),
            _sha256_text(f"symlink:{target}"),
        )
    if absolute.is_file():
        data = absolute.read_bytes()
        return WorktreePathEntry(
            path, status, True, "file", len(data), _sha256_bytes(data)
        )
    if absolute.is_dir():
        return WorktreePathEntry(path, status, True, "dir", None, None)
    return WorktreePathEntry(path, status, True, "other", None, None)


def _is_taskledger_state_path(path: str) -> bool:
    return path == ".taskledger" or path.startswith(".taskledger/")


def capture_workspace_content_snapshot(
    workspace_root: Path,
) -> WorkspaceContentSnapshot:
    root = git_root(workspace_root)
    if root is None:
        return WorkspaceContentSnapshot(None, None, None, None, 0, (), utc_now_iso())

    commit_result = run_git(root, "rev-parse", "HEAD", check=False)
    git_commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
    status_result = run_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        check=False,
    )
    status_text = status_result.stdout if status_result.returncode == 0 else ""
    status_entries = _parse_status_z(status_text)
    entries = tuple(
        sorted(
            (
                _entry_for_path(root, path, status)
                for path, status in status_entries
                if not _is_taskledger_state_path(path)
            ),
            key=lambda item: item.path,
        )
    )
    manifest = [
        {
            "path": entry.path,
            "state": "missing" if not entry.exists else "present",
            "kind": entry.kind,
            "size": entry.size,
            "content_hash": entry.content_hash,
        }
        for entry in entries
    ]
    paths_manifest = [{"path": entry.path, "status": entry.status} for entry in entries]
    content_hash = (
        _sha256_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
        if entries
        else None
    )
    paths_hash = (
        _sha256_text(json.dumps(paths_manifest, sort_keys=True, separators=(",", ":")))
        if entries
        else None
    )
    return WorkspaceContentSnapshot(
        git_commit=git_commit,
        dirty=bool(entries),
        content_hash=content_hash,
        paths_hash=paths_hash,
        entry_count=len(entries),
        entries=entries,
        captured_at=utc_now_iso(),
    )


def save_workspace_snapshot_manifest(
    workspace_root: Path,
    task_id: str,
    run_id: str,
    snapshot: WorkspaceContentSnapshot,
) -> str:
    paths = resolve_v2_paths(workspace_root)
    path = paths.runs_dir / task_id / f"{run_id}.workspace-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n")
    return f"runs/{task_id}/{path.name}"


def load_workspace_snapshot_manifest(
    workspace_root: Path,
    task_id: str,
    ref: str,
) -> WorkspaceContentSnapshot | None:
    paths = resolve_v2_paths(workspace_root)
    path = paths.ledger_dir / ref
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return None
    return WorkspaceContentSnapshot.from_dict(data)


def _changed_paths(
    expected: WorkspaceContentSnapshot | None,
    current: WorkspaceContentSnapshot,
) -> list[dict[str, object]]:
    if expected is None:
        return []
    expected_by_path = {entry.path: entry for entry in expected.entries}
    current_by_path = {entry.path: entry for entry in current.entries}
    paths = sorted(set(expected_by_path) | set(current_by_path))
    changes: list[dict[str, object]] = []
    for path in paths:
        old = expected_by_path.get(path)
        new = current_by_path.get(path)
        if old == new:
            continue
        changes.append(
            {
                "path": path,
                "expected": old.to_dict() if old else None,
                "current": new.to_dict() if new else None,
            }
        )
    return changes


def _command_hint() -> str:
    return (
        "taskledger implement snapshot refresh --reason "
        '"Accept current workspace as the implementation snapshot."'
    )


def _message(reason_code: str) -> str:
    if reason_code == "legacy_snapshot_mismatch":
        return (
            "Cannot start validation: implementation snapshot mismatch. "
            "Reason: legacy_snapshot_mismatch. Taskledger cannot prove whether "
            "this is staging-only because the implementation run lacks a "
            "content snapshot. "
            f"Next: {_command_hint()}"
        )
    if reason_code == "content_snapshot_mismatch":
        return (
            "Cannot start validation: implementation snapshot mismatch. "
            "Reason: content_snapshot_mismatch. Likely cause: actual file "
            "content changed after implement finish. "
            f"Next: {_command_hint()}"
        )
    if reason_code == "commit_mismatch":
        return (
            "Cannot start validation: implementation snapshot mismatch. "
            "Reason: commit_mismatch. "
            f"Next: {_command_hint()}"
        )
    if reason_code == "missing_snapshot_after_unarchive":
        return (
            "Cannot validate old implementation: implementation snapshot is "
            "missing after unarchive recovery."
        )
    return "Implementation snapshot is current."


def compare_implementation_snapshot(
    workspace_root: Path,
    task: TaskRecord,
    impl_run: TaskRunRecord,
) -> ImplementationSnapshotEvaluation:
    current_legacy = capture_workspace_snapshot(workspace_root)
    current_content = capture_workspace_content_snapshot(workspace_root)
    expected_commit = impl_run.workspace_git_commit
    current_commit = current_content.git_commit or current_legacy.git_commit
    details: dict[str, object] = {"changed_paths": []}

    if expected_commit is None:
        reason = "missing_snapshot"
        ok = True
        if task.notes and any(
            "Unarchived from non-terminal state" in n for n in task.notes
        ):
            reason = "missing_snapshot_after_unarchive"
            ok = False
        return ImplementationSnapshotEvaluation(
            ok,
            reason,
            _message(reason)
            if not ok
            else (
                "Implementation snapshot missing; validation may proceed "
                "for legacy task."
            ),
            impl_run.workspace_snapshot_format,
            SNAPSHOT_FORMAT,
            expected_commit,
            current_commit,
            impl_run.workspace_content_hash,
            current_content.content_hash,
            impl_run.workspace_status_hash,
            current_legacy.status_hash,
            impl_run.workspace_diff_hash,
            current_legacy.diff_hash,
            _command_hint() if not ok else None,
            details,
        )

    if current_commit != expected_commit:
        reason = "commit_mismatch"
        return ImplementationSnapshotEvaluation(
            False,
            reason,
            _message(reason),
            impl_run.workspace_snapshot_format,
            SNAPSHOT_FORMAT,
            expected_commit,
            current_commit,
            impl_run.workspace_content_hash,
            current_content.content_hash,
            impl_run.workspace_status_hash,
            current_legacy.status_hash,
            impl_run.workspace_diff_hash,
            current_legacy.diff_hash,
            _command_hint(),
            details,
        )

    if impl_run.workspace_content_hash is not None:
        expected_manifest = None
        if impl_run.workspace_snapshot_ref:
            expected_manifest = load_workspace_snapshot_manifest(
                workspace_root, task.id, impl_run.workspace_snapshot_ref
            )
        if current_content.content_hash == impl_run.workspace_content_hash:
            reason = "content_snapshot_match"
            return ImplementationSnapshotEvaluation(
                True,
                reason,
                "Implementation content snapshot matches current workspace.",
                impl_run.workspace_snapshot_format,
                SNAPSHOT_FORMAT,
                expected_commit,
                current_commit,
                impl_run.workspace_content_hash,
                current_content.content_hash,
                impl_run.workspace_status_hash,
                current_legacy.status_hash,
                impl_run.workspace_diff_hash,
                current_legacy.diff_hash,
                None,
                details,
            )
        reason = "content_snapshot_mismatch"
        details["changed_paths"] = _changed_paths(expected_manifest, current_content)
        if expected_manifest is None and impl_run.workspace_snapshot_ref:
            details["manifest_missing"] = True
        return ImplementationSnapshotEvaluation(
            False,
            reason,
            _message(reason),
            impl_run.workspace_snapshot_format,
            SNAPSHOT_FORMAT,
            expected_commit,
            current_commit,
            impl_run.workspace_content_hash,
            current_content.content_hash,
            impl_run.workspace_status_hash,
            current_legacy.status_hash,
            impl_run.workspace_diff_hash,
            current_legacy.diff_hash,
            _command_hint(),
            details,
        )

    legacy_match = (
        current_legacy.status_hash == impl_run.workspace_status_hash
        and current_legacy.diff_hash == impl_run.workspace_diff_hash
    )
    reason = "legacy_snapshot_match" if legacy_match else "legacy_snapshot_mismatch"
    return ImplementationSnapshotEvaluation(
        legacy_match,
        reason,
        "Legacy implementation snapshot matches current workspace."
        if legacy_match
        else _message(reason),
        impl_run.workspace_snapshot_format,
        SNAPSHOT_FORMAT,
        expected_commit,
        current_commit,
        None,
        current_content.content_hash,
        impl_run.workspace_status_hash,
        current_legacy.status_hash,
        impl_run.workspace_diff_hash,
        current_legacy.diff_hash,
        None if legacy_match else _command_hint(),
        details,
    )


def refresh_implementation_snapshot(
    workspace_root: Path,
    task_ref: str,
    *,
    reason: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    reason_text = reason.strip()
    if not reason_text:
        raise _tasks._cli_error(
            "Implementation snapshot refresh requires --reason.",
            _tasks.EXIT_CODE_BAD_INPUT,
        )
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="refresh implementation snapshot for")
    if task.status_stage != "implemented":
        raise _tasks._cli_error(
            "Implementation snapshot refresh requires implemented state.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    if _tasks._current_lock(workspace_root, task.id) is not None:
        raise _tasks._cli_error(
            "Implementation snapshot refresh requires no active lock.",
            _tasks.EXIT_CODE_LOCK_CONFLICT,
        )
    impl_run = _tasks._require_run(workspace_root, task, task.latest_implementation_run)
    if impl_run.run_type != "implementation" or impl_run.status != "finished":
        raise _tasks._cli_error(
            "Implementation snapshot refresh requires a finished implementation run.",
            _tasks.EXIT_CODE_INVALID_TRANSITION,
        )
    for run in list_runs(workspace_root, task.id):
        if run.run_type == "validation" and run.status == "running":
            raise _tasks._cli_error(
                "Implementation snapshot refresh requires no running validation run.",
                _tasks.EXIT_CODE_INVALID_TRANSITION,
            )

    old_eval = compare_implementation_snapshot(workspace_root, task, impl_run)
    legacy = capture_workspace_snapshot(workspace_root)
    content = capture_workspace_content_snapshot(workspace_root)
    snapshot_ref = save_workspace_snapshot_manifest(
        workspace_root, task.id, impl_run.run_id, content
    )
    updated = replace(
        impl_run,
        workspace_git_commit=legacy.git_commit,
        workspace_dirty=legacy.dirty,
        workspace_diff_hash=legacy.diff_hash,
        workspace_status_hash=legacy.status_hash,
        workspace_snapshot_at=legacy.captured_at,
        workspace_content_hash=content.content_hash,
        workspace_paths_hash=content.paths_hash,
        workspace_entry_count=content.entry_count,
        workspace_snapshot_format=SNAPSHOT_FORMAT,
        workspace_snapshot_ref=snapshot_ref,
    )
    save_run(workspace_root, updated)
    _tasks._append_event(
        workspace_root,
        task.id,
        "implementation.snapshot.refreshed",
        {
            "run_id": impl_run.run_id,
            "reason": reason_text,
            "actor": actor.to_dict() if actor else None,
            "harness": harness.to_dict() if harness else None,
            "old_snapshot": old_eval.to_dict(),
            "new_snapshot": {
                "git_commit": content.git_commit,
                "content_hash": content.content_hash,
                "paths_hash": content.paths_hash,
                "entry_count": content.entry_count,
            },
            "changed_paths": old_eval.details.get("changed_paths", []),
        },
    )
    rebuild_v2_indexes(resolve_v2_paths(workspace_root))
    return {
        "kind": "implementation_snapshot_refresh",
        "task_id": task.id,
        "run_id": impl_run.run_id,
        "old_snapshot": old_eval.to_dict(),
        "new_snapshot": {
            "git_commit": content.git_commit,
            "content_hash": content.content_hash,
            "paths_hash": content.paths_hash,
            "entry_count": content.entry_count,
            "snapshot_ref": snapshot_ref,
        },
        "changed_paths": old_eval.details.get("changed_paths", []),
        "next_command": "taskledger validate start",
    }

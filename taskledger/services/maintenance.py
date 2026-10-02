from __future__ import annotations

import logging
import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from taskledger.domain.models import (
    AgentCommandLogRecord,
    TaskRecord,
    TaskRunRecord,
)
from taskledger.errors import LaunchError
from taskledger.ids import TASK_ID_FORMAT
from taskledger.services.task_events import append_task_event, default_actor
from taskledger.storage.events import load_events
from taskledger.storage.task_store import V2Paths
from taskledger.storage.yaml_store import write_yaml_object
from taskledger.timeutils import utc_now_iso


class SerializableRecord(Protocol):
    def to_dict(self) -> dict[str, object]: ...


logger = logging.getLogger(__name__)

GCScope = Literal["all", "runtime", "artifacts", "cache"]
CandidateScope = Literal["runtime", "artifacts", "cache"]
DEFAULT_RETENTION_DAYS: dict[CandidateScope, int] = {
    "runtime": 14,
    "artifacts": 30,
    "cache": 7,
}
_DURATION_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[dhm])$")


@dataclass(frozen=True, slots=True)
class GCCandidate:
    path: Path
    safety_root: Path
    scope: CandidateScope
    bytes: int
    file_count: int
    age_days: float
    owner_task_id: str | None
    owner_run_id: str | None
    reason_eligible: str
    reference_status: str
    allowed_name_prefix: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "scope": self.scope,
            "bytes": self.bytes,
            "file_count": self.file_count,
            "age_days": self.age_days,
            "owner_task_id": self.owner_task_id,
            "owner_run_id": self.owner_run_id,
            "reason_eligible": self.reason_eligible,
            "reference_status": self.reference_status,
        }


def _parse_older_than(value: str | None) -> timedelta | None:
    if value is None:
        return None
    match = _DURATION_RE.fullmatch(value.strip().lower())
    if match is None:
        raise LaunchError(
            "--older-than must be a non-negative duration such as 30d, 12h, or 60m."
        )
    amount = int(match.group("amount"))
    unit = match.group("unit")
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def _duration_label(value: timedelta | None) -> str | None:
    if value is None:
        return None
    seconds = int(value.total_seconds())
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}m"


def _valid_task_id(value: str) -> bool:
    try:
        parsed = TASK_ID_FORMAT.parse_parts(value)
    except ValueError:
        return False
    return TASK_ID_FORMAT.format(parsed.number) == value


def _iter_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_strings(child)


def _reference_candidates(paths: V2Paths, reference: str) -> tuple[Path, ...]:
    value = reference.strip().strip("`\"'")
    if not value:
        return ()
    if ": " in value:
        value = value.split(": ", maxsplit=1)[0].strip()
    ref_path = Path(value)
    if ref_path.is_absolute():
        return (ref_path,)
    if value.startswith("runtime/"):
        return (paths.runtime_root / ref_path.relative_to("runtime"),)
    if value.startswith("logs/"):
        return (paths.events_dir.parent / ref_path.relative_to("logs"),)
    return (
        paths.project_dir / ref_path,
        paths.events_dir.parent / ref_path,
        paths.runtime_root / ref_path,
        paths.workspace_root / ref_path,
    )


def _resolve_reference(
    paths: V2Paths,
    reference: str,
    allowed_roots: tuple[Path, ...],
) -> Path | None:
    for candidate in _reference_candidates(paths, reference):
        resolved = candidate.resolve(strict=False)
        for root in allowed_roots:
            resolved_root = root.resolve(strict=False)
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                continue
            return resolved
    return None


def _safe_descendant(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _walk_regular_files(root: Path, unsafe_paths: list[str]) -> list[Path]:
    if root.is_symlink():
        unsafe_paths.append(str(root))
        return []
    if not root.exists():
        return []
    if not root.is_dir():
        unsafe_paths.append(str(root))
        return []
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in tuple(dirnames):
            child = current / name
            if child.is_symlink():
                unsafe_paths.append(str(child))
                dirnames.remove(name)
        for name in filenames:
            child = current / name
            if child.is_symlink() or not child.is_file():
                unsafe_paths.append(str(child))
                continue
            if not _safe_descendant(child, root):
                unsafe_paths.append(str(child))
                continue
            files.append(child)
    return files


def _age_seconds(path: Path, now: datetime) -> tuple[float, float]:
    modified_at = path.stat().st_mtime
    age_seconds = max(0.0, now.timestamp() - modified_at)
    return age_seconds, round(age_seconds / 86400, 2)


def _within_retention(
    path: Path,
    scope: CandidateScope,
    now: datetime,
    override: timedelta | None,
) -> tuple[bool, float]:
    age_seconds, age_days = _age_seconds(path, now)
    retention = (
        override
        if override is not None
        else timedelta(days=DEFAULT_RETENTION_DAYS[scope])
    )
    return age_seconds >= retention.total_seconds(), age_days


def _load_reference_records(
    paths: V2Paths,
    tasks: list[TaskRecord],
    agent_logs: list[AgentCommandLogRecord],
) -> list[SerializableRecord]:

    from taskledger.storage.task_store import (
        list_changes_from_paths,
        list_checks_from_paths,
        list_code_reviews_from_paths,
        list_handoffs_from_paths,
        list_plans_from_paths,
        list_questions_from_paths,
        list_runs_from_paths,
        load_todos_from_paths,
    )

    records: list[SerializableRecord] = list(tasks)
    for task in tasks:
        task_id = task.id
        records.extend(list_plans_from_paths(paths, task_id))
        records.extend(list_questions_from_paths(paths, task_id))
        records.extend(list_runs_from_paths(paths, task_id))
        records.extend(list_changes_from_paths(paths, task_id))
        records.extend(list_checks_from_paths(paths, task_id))
        records.extend(list_code_reviews_from_paths(paths, task_id))
        records.extend(list_handoffs_from_paths(paths, task_id))
        records.extend(load_todos_from_paths(paths, task_id).todos)
    records.extend(agent_logs)
    records.extend(load_events(paths.events_dir))
    return records


def _build_artifact_candidates(
    paths: V2Paths,
    *,
    tasks: list[TaskRecord],
    runs_by_task: dict[str, list[TaskRunRecord]],
    lock_task_ids: set[str],
    active_task_id: str | None,
    incomplete_task_ids: set[str],
    selected_task_id: str | None,
    now: datetime,
    override: timedelta | None,
    unsafe_paths: list[str],
) -> list[GCCandidate]:
    from taskledger.storage.agent_logs import (
        agent_log_artifacts_dir,
        load_agent_command_logs,
    )
    from taskledger.storage.task_store import task_artifacts_dir

    agent_root = agent_log_artifacts_dir(paths)
    logs = load_agent_command_logs(paths.workspace_root)
    roots_by_task = {task.id: task_artifacts_dir(paths, task.id) for task in tasks}
    allowed_roots = (*roots_by_task.values(), agent_root)
    records = _load_reference_records(paths, tasks, logs)
    references: set[Path] = set()
    for record in records:
        record_data = record.to_dict()
        for reference in _iter_strings(record_data):
            resolved = _resolve_reference(paths, reference, allowed_roots)
            if resolved is not None:
                references.add(resolved)

    candidates: list[GCCandidate] = []
    task_by_id = {task.id: task for task in tasks}
    for task_id, root in roots_by_task.items():
        if selected_task_id is not None and task_id != selected_task_id:
            continue
        if task_id in incomplete_task_ids:
            continue
        task = task_by_id[task_id]
        runs = runs_by_task.get(task_id, [])
        if (
            task.status_stage not in {"done", "cancelled"}
            or task_id in lock_task_ids
            or task_id == active_task_id
            or any(run.status == "running" for run in runs)
        ):
            continue
        for path in _walk_regular_files(root, unsafe_paths):
            resolved = path.resolve(strict=True)
            if resolved in references:
                continue
            eligible, age_days = _within_retention(path, "artifacts", now, override)
            if not eligible:
                continue
            candidates.append(
                GCCandidate(
                    path=path,
                    safety_root=root,
                    scope="artifacts",
                    bytes=path.stat().st_size,
                    file_count=1,
                    age_days=age_days,
                    owner_task_id=task_id,
                    owner_run_id=None,
                    reason_eligible="unreferenced artifact older than retention",
                    reference_status="unreferenced",
                )
            )

    logs_by_id = {record.log_id: record for record in logs}

    for path in _walk_regular_files(agent_root, unsafe_paths):
        owner = logs_by_id.get(path.name.split(".", maxsplit=1)[0])
        owner_task_id = owner.task_id if owner is not None else None
        owner_run_id = owner.run_id if owner is not None else None
        if selected_task_id is not None and owner_task_id != selected_task_id:
            continue
        if owner_task_id is not None:
            if (
                owner_task_id not in task_by_id
                or owner_task_id in lock_task_ids
                or owner_task_id == active_task_id
                or task_by_id[owner_task_id].status_stage not in {"done", "cancelled"}
            ):
                continue
            owner_runs = runs_by_task.get(owner_task_id, [])
            if owner_run_id is not None and any(
                run.run_id == owner_run_id and run.status == "running"
                for run in owner_runs
            ):
                continue
        resolved = path.resolve(strict=True)
        if resolved in references:
            continue
        eligible, age_days = _within_retention(path, "artifacts", now, override)
        if not eligible:
            continue
        candidates.append(
            GCCandidate(
                path=path,
                safety_root=agent_root,
                scope="artifacts",
                bytes=path.stat().st_size,
                file_count=1,
                age_days=age_days,
                owner_task_id=owner_task_id,
                owner_run_id=owner_run_id,
                reason_eligible="unreferenced agent-log artifact older than retention",
                reference_status="unreferenced",
            )
        )
    return candidates


def _build_runtime_candidates(
    paths: V2Paths,
    *,
    tasks: list[TaskRecord],
    runs_by_task: dict[str, list[TaskRunRecord]],
    lock_task_ids: set[str],
    active_task_id: str | None,
    selected_task_id: str | None,
    now: datetime,
    override: timedelta | None,
    unsafe_paths: list[str],
) -> list[GCCandidate]:
    snapshot_root = (
        paths.runtime_root / "checkouts" / paths.ledger_ref / "workspace-snapshots"
    )
    if snapshot_root.is_symlink():
        unsafe_paths.append(str(snapshot_root))
        return []
    if not snapshot_root.exists():
        return []
    if not snapshot_root.is_dir():
        unsafe_paths.append(str(snapshot_root))
        return []
    task_by_id = {task.id: task for task in tasks}
    active_snapshot_refs = {
        run.workspace_snapshot_ref
        for runs in runs_by_task.values()
        for run in runs
        if run.status == "running" and run.workspace_snapshot_ref is not None
    }
    candidates: list[GCCandidate] = []
    for task_id, runs in runs_by_task.items():
        if selected_task_id is not None and task_id != selected_task_id:
            continue
        task = task_by_id.get(task_id)
        if (
            task is None
            or task.status_stage not in {"done", "cancelled"}
            or task_id in lock_task_ids
            or task_id == active_task_id
        ):
            continue
        for run in runs:
            reference = run.workspace_snapshot_ref
            if (
                not reference
                or run.status == "running"
                or reference in active_snapshot_refs
                or run.workspace_content_hash is None
                or run.workspace_paths_hash is None
                or run.workspace_snapshot_format is None
            ):
                continue
            expected_reference = (
                f"runtime/checkouts/{paths.ledger_ref}/workspace-snapshots/"
                f"{task_id}/{run.run_id}.workspace-snapshot.json"
            )
            if reference != expected_reference:
                unsafe_paths.append(reference)
                continue
            relative = Path(reference).relative_to("runtime")
            path = paths.runtime_root / relative
            if path.is_symlink() or not _safe_descendant(path, snapshot_root):
                unsafe_paths.append(str(path))
                continue
            if not path.is_file():
                continue
            eligible, age_days = _within_retention(path, "runtime", now, override)
            if not eligible:
                continue
            candidates.append(
                GCCandidate(
                    path=path,
                    safety_root=snapshot_root,
                    scope="runtime",
                    bytes=path.stat().st_size,
                    file_count=1,
                    age_days=age_days,
                    owner_task_id=task_id,
                    owner_run_id=run.run_id,
                    reason_eligible="terminal workspace snapshot older than retention",
                    reference_status="terminal run summary retained",
                )
            )
    return candidates


def _tree_size(path: Path, unsafe_paths: list[str]) -> tuple[int, int]:
    total_bytes = 0
    file_count = 0
    for child in _walk_regular_files(path, unsafe_paths):
        total_bytes += child.stat().st_size
        file_count += 1
    return total_bytes, file_count


def _build_cache_candidates(
    paths: V2Paths,
    *,
    now: datetime,
    override: timedelta | None,
    unsafe_paths: list[str],
) -> list[GCCandidate]:
    parent = paths.indexes_dir.parent
    prefix = f"{paths.indexes_dir.name}.quarantine-"
    if parent.is_symlink():
        unsafe_paths.append(str(parent))
        return []
    if not parent.exists():
        return []
    candidates: list[GCCandidate] = []
    for path in sorted(parent.glob(f"{paths.indexes_dir.name}.quarantine-*")):
        if not path.name.startswith(prefix) or path.parent != parent:
            unsafe_paths.append(str(path))
            continue
        if path.is_symlink() or not path.is_dir():
            unsafe_paths.append(str(path))
            continue
        if not _safe_descendant(path, parent):
            unsafe_paths.append(str(path))
            continue
        eligible, age_days = _within_retention(path, "cache", now, override)
        if not eligible:
            continue
        size_bytes, file_count = _tree_size(path, unsafe_paths)
        candidates.append(
            GCCandidate(
                path=path,
                safety_root=parent,
                scope="cache",
                bytes=size_bytes,
                file_count=file_count,
                age_days=age_days,
                owner_task_id=None,
                owner_run_id=None,
                reason_eligible="quarantined cache generation older than retention",
                reference_status="rebuildable cache quarantine",
                allowed_name_prefix=prefix,
            )
        )
    return candidates


def _validate_candidate(candidate: GCCandidate) -> None:
    path = candidate.path
    if path.is_symlink() or not _safe_descendant(path, candidate.safety_root):
        raise LaunchError(f"Unsafe garbage-collection path: {path}")
    if candidate.scope == "cache":
        if (
            not path.is_dir()
            or path.parent != candidate.safety_root
            or candidate.allowed_name_prefix is None
            or not path.name.startswith(candidate.allowed_name_prefix)
        ):
            raise LaunchError(f"Unsafe garbage-collection path: {path}")
    elif not path.is_file():
        raise LaunchError(f"Garbage-collection candidate is no longer a file: {path}")


def garbage_collect(
    paths: V2Paths,
    *,
    scope: GCScope = "all",
    task_id: str | None = None,
    older_than: str | None = None,
    apply: bool = False,
    reason: str = "",
) -> dict[str, object]:
    if scope not in {"all", "runtime", "artifacts", "cache"}:
        raise LaunchError(f"Unsupported garbage-collection scope: {scope}")
    if task_id is not None and not _valid_task_id(task_id):
        raise LaunchError(f"--task must be a canonical task ID, got {task_id!r}.")
    if task_id is not None and scope == "cache":
        raise LaunchError("--task cannot be combined with --scope cache.")
    override = _parse_older_than(older_than)
    selected_scopes: set[CandidateScope] = (
        {"runtime", "artifacts", "cache"} if scope == "all" else {scope}
    )
    if task_id is not None:
        selected_scopes.discard("cache")

    candidates: list[GCCandidate] = []
    unsafe_paths: list[str] = []
    now = datetime.now(timezone.utc)
    retention_report = {
        candidate_scope: _duration_label(
            override
            if override is not None
            else timedelta(days=DEFAULT_RETENTION_DAYS[candidate_scope])
        )
        for candidate_scope in sorted(selected_scopes)
    }

    if "cache" in selected_scopes:
        candidates.extend(
            _build_cache_candidates(
                paths, now=now, override=override, unsafe_paths=unsafe_paths
            )
        )

    if {"runtime", "artifacts"} & selected_scopes:
        from taskledger.storage.task_ids import inspect_task_id_inventory
        from taskledger.storage.task_store import (
            list_runs_from_paths,
            list_tasks_from_paths,
            load_active_task_state_from_paths,
            load_lock_records_from_paths,
        )

        tasks = list_tasks_from_paths(paths)
        task_by_id = {task.id: task for task in tasks}
        if task_id is not None and task_id not in task_by_id:
            raise LaunchError(f"Task {task_id} does not have a canonical task record.")
        runs_by_task: dict[str, list[TaskRunRecord]] = {
            task.id: list_runs_from_paths(paths, task.id) for task in tasks
        }
        active_state = load_active_task_state_from_paths(paths)
        active_task_id = active_state.task_id if active_state is not None else None
        lock_task_ids = {lock.task_id for lock in load_lock_records_from_paths(paths)}
        incomplete_task_ids = {
            allocation.task_id
            for allocation in inspect_task_id_inventory(paths).incomplete_allocations
        }
        if "runtime" in selected_scopes:
            candidates.extend(
                _build_runtime_candidates(
                    paths,
                    tasks=tasks,
                    runs_by_task=runs_by_task,
                    lock_task_ids=lock_task_ids,
                    active_task_id=active_task_id,
                    selected_task_id=task_id,
                    now=now,
                    override=override,
                    unsafe_paths=unsafe_paths,
                )
            )
        if "artifacts" in selected_scopes:
            candidates.extend(
                _build_artifact_candidates(
                    paths,
                    tasks=tasks,
                    runs_by_task=runs_by_task,
                    lock_task_ids=lock_task_ids,
                    active_task_id=active_task_id,
                    incomplete_task_ids=incomplete_task_ids,
                    selected_task_id=task_id,
                    now=now,
                    override=override,
                    unsafe_paths=unsafe_paths,
                )
            )

    candidates.sort(key=lambda candidate: (candidate.scope, str(candidate.path)))
    planned = [candidate.to_dict() for candidate in candidates]
    bytes_reclaimable = sum(candidate.bytes for candidate in candidates)
    files_reclaimable = sum(candidate.file_count for candidate in candidates)
    result: dict[str, object] = {
        "kind": "maintenance_gc",
        "status": "dry_run" if not apply else "nothing_to_collect",
        "dry_run": not apply,
        "scope": scope,
        "task_id": task_id,
        "older_than": _duration_label(override),
        "retention": retention_report,
        "candidates": planned,
        "files_reclaimable": files_reclaimable,
        "bytes_reclaimable": bytes_reclaimable,
        "files_reclaimed": 0,
        "bytes_reclaimed": 0,
        "unsafe_paths": sorted(set(unsafe_paths)),
    }
    if not apply or not candidates:
        return result
    if unsafe_paths:
        raise LaunchError(
            "Garbage collection refused unsafe paths; no files were removed.",
            details={"unsafe_paths": sorted(set(unsafe_paths))},
        )
    if (
        any(candidate.scope != "cache" for candidate in candidates)
        and not reason.strip()
    ):
        raise LaunchError(
            "Garbage-collection evidence cleanup requires --reason with --apply."
        )

    for candidate in candidates:
        _validate_candidate(candidate)

    report_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_id = f"{report_stamp}-{uuid4().hex[:8]}"
    report_path = paths.ledger_dir / "maintenance" / "gc" / f"gc-{report_id}.yaml"
    report = {
        "schema_version": 1,
        "object_type": "maintenance_gc_report",
        "report_id": report_id,
        "created_at": utc_now_iso(),
        "status": "started",
        "scope": scope,
        "task_id": task_id,
        "older_than": _duration_label(override),
        "retention": retention_report,
        "reason": reason.strip() or None,
        "actor": default_actor().to_dict(),
        "candidates": planned,
        "deleted": [],
        "failures": [],
        "files_reclaimed": 0,
        "bytes_reclaimed": 0,
    }
    write_yaml_object(report_path, report)

    deleted: list[dict[str, object]] = []
    deleted_candidates: list[GCCandidate] = []
    failures: list[dict[str, str]] = []
    for candidate in candidates:
        try:
            _validate_candidate(candidate)
            if candidate.scope == "cache":
                shutil.rmtree(candidate.path)
            else:
                candidate.path.unlink()
            deleted.append(candidate.to_dict())
            deleted_candidates.append(candidate)
        except Exception as exc:  # noqa: BLE001
            failures.append({"path": str(candidate.path), "error": str(exc)})

    files_reclaimed = sum(candidate.file_count for candidate in deleted_candidates)
    bytes_reclaimed = sum(candidate.bytes for candidate in deleted_candidates)
    report.update(
        {
            "status": "partial" if failures else "applied",
            "deleted": deleted,
            "failures": failures,
            "files_reclaimed": files_reclaimed,
            "bytes_reclaimed": bytes_reclaimed,
        }
    )
    write_yaml_object(report_path, report)
    relative_report_path = report_path.relative_to(paths.ledger_dir).as_posix()
    try:
        append_task_event(
            paths.workspace_root,
            "*",
            "maintenance.gc",
            {
                "report_path": relative_report_path,
                "scope": scope,
                "task_id": task_id,
                "files_reclaimed": files_reclaimed,
                "bytes_reclaimed": bytes_reclaimed,
                "reason": reason.strip() or None,
            },
        )
    except Exception:
        logger.warning("Failed to append garbage-collection event", exc_info=True)

    result.update(
        {
            "status": "partial" if failures else "applied",
            "candidates": planned,
            "deleted": deleted,
            "failures": failures,
            "files_reclaimed": files_reclaimed,
            "bytes_reclaimed": bytes_reclaimed,
            "audit_path": relative_report_path,
        }
    )
    return result


__all__ = ["GCCandidate", "garbage_collect"]

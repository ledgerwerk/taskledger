"""Reviewed recovery for active-task pointers that normal resolution cannot load."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from taskledger.domain.active_state import ActiveTaskState
from taskledger.errors import LaunchError
from taskledger.ids import parse_uuid7
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.frontmatter import read_markdown_front_matter
from taskledger.storage.task_identity import (
    LEGACY_UUID7_EPOCH_MS,
    identity_mutation_lock,
    inspect_task_identity_sources,
)
from taskledger.storage.task_ids import allocation_source_fingerprint
from taskledger.storage.task_store import (
    V2Paths,
    active_task_state_from_bytes,
    read_active_task_state_raw,
    resolve_v2_paths,
)
from taskledger.storage.yaml_store import write_yaml_object

_ACTIVE_JOURNAL_SCHEMA_VERSION = 1


def _source_payload(
    matches: list[Any], source_fingerprints: dict[str, str]
) -> list[dict[str, object]]:
    return [
        {
            "task_uuid": str(source.task_uuid),
            "path": str(source.path),
            "state": source.state,
            "source_kind": source.source_kind,
            "legacy_task_id": source.legacy_task_id,
            "source_fingerprint": source_fingerprints.get(str(source.path)),
        }
        for source in sorted(matches, key=lambda item: item.path.as_posix())
    ]


def _classify_uuid_reference(
    ref: str, sources: list[Any], source_fingerprints: dict[str, str]
) -> tuple[list[dict[str, object]], str, list[Any]]:
    try:
        stored_uuid = parse_uuid7(ref)
    except ValueError:
        return (
            [],
            "resolution_blocked",
            [
                {
                    "code": "ACTIVE_TASK_REFERENCE_UNRESOLVED",
                    "error": "Invalid stored task UUID.",
                }
            ],
        )
    matches = [source for source in sources if source.task_uuid == stored_uuid]
    details = _source_payload(matches, source_fingerprints)
    if len(matches) > 1:
        return details, "ambiguous", []
    if matches and matches[0].state == "live":
        return details, "valid", []
    return details, "missing", []


def _classify_legacy_reference(
    state: ActiveTaskState,
    sources: list[Any],
    display_ids: dict[str, list[Any]],
    source_fingerprints: dict[str, str],
) -> tuple[list[dict[str, object]], str, list[Any]]:
    explicit = [source for source in sources if source.legacy_task_id == state.task_id]
    if explicit:
        details = _source_payload(explicit, source_fingerprints)
        if len(explicit) > 1:
            return details, "ambiguous", []
        return details, "valid" if explicit[0].state == "live" else "missing", []

    try:
        number_text = state.task_id.removeprefix("task-")
        number = int(number_text)
        canonical = number > 0 and f"task-{number:04d}" == state.task_id
    except (ValueError, AttributeError):
        canonical = False
        number = 0
    if canonical:
        timestamp = LEGACY_UUID7_EPOCH_MS + number
        migrated = [
            source for source in sources if source.task_uuid.int >> 80 == timestamp
        ]
        if len(migrated) > 1:
            return _source_payload(migrated, source_fingerprints), "ambiguous", []
        if migrated:
            status = "valid" if migrated[0].state == "live" else "missing"
            return _source_payload(migrated, source_fingerprints), status, []

    display_matches = display_ids.get(state.task_id, [])
    details = _source_payload(display_matches, source_fingerprints)
    if len(display_matches) > 1:
        return details, "ambiguous", []
    if display_matches:
        return (
            details,
            "resolution_blocked",
            [
                {
                    "code": "ACTIVE_TASK_REFERENCE_UNRESOLVED",
                    "error": (
                        "The numeric task ID is only a mutable display alias; "
                        "no UUID was stored."
                    ),
                }
            ],
        )
    return [], "missing", []


def _source_details(
    paths: V2Paths, state: ActiveTaskState
) -> tuple[list[dict[str, object]], str, list[Any]]:
    """Classify the raw pointer using validated physical sources only."""
    try:
        sources = list(inspect_task_identity_sources(paths))
    except Exception as exc:  # noqa: BLE001
        return (
            [],
            "resolution_blocked",
            [
                {
                    "code": getattr(exc, "code", "TASK_IDENTITY_SCAN_FAILED"),
                    "error": str(exc),
                }
            ],
        )

    display_ids: dict[str, list[Any]] = {}
    source_fingerprints: dict[str, str] = {}
    try:
        for source in sources:
            if source.state in {"live", "incomplete"} and source.path.is_dir():
                source_fingerprints[str(source.path)] = allocation_source_fingerprint(
                    source.path
                )
            if source.state == "live":
                metadata, _ = read_markdown_front_matter(source.path / "task.md")
                display_id = metadata.get("id")
                if isinstance(display_id, str):
                    display_ids.setdefault(display_id, []).append(source)
    except Exception as exc:  # noqa: BLE001
        return (
            [],
            "resolution_blocked",
            [
                {
                    "code": getattr(exc, "code", "TASK_IDENTITY_SCAN_FAILED"),
                    "error": str(exc),
                }
            ],
        )
    if state.task_uuid is not None:
        return _classify_uuid_reference(state.task_uuid, sources, source_fingerprints)
    try:
        parse_uuid7(state.task_id)
    except ValueError:
        return _classify_legacy_reference(
            state, sources, display_ids, source_fingerprints
        )
    return _classify_uuid_reference(state.task_id, sources, source_fingerprints)


def _protection_state(
    paths: V2Paths,
    state: ActiveTaskState,
    candidates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.task_store import _load_run

    uuids = {str(item["task_uuid"]) for item in candidates if item.get("task_uuid")}
    if state.task_uuid:
        uuids.add(state.task_uuid)
    locks: list[dict[str, object]] = []
    try:
        inventory = build_lock_inventory(paths)
    except Exception as exc:  # noqa: BLE001
        return ([{"error": str(exc), "classification": "unavailable"}], [])
    for entry in inventory.entries:
        lock_uuid = entry.task_uuid
        if entry.lock is not None and entry.lock.task_uuid:
            lock_uuid = entry.lock.task_uuid
        matches = lock_uuid in uuids or (not uuids and entry.task_id == state.task_id)
        if matches:
            locks.append(entry.to_dict())

    runs: list[dict[str, object]] = []
    try:
        for task_dir in sorted(paths.tasks_dir.iterdir()):
            if task_dir.is_symlink():
                raise LaunchError(
                    f"Cannot inspect runs through symlinked task path: {task_dir}"
                )
            if not task_dir.is_dir():
                continue
            run_dir = task_dir / "runs"
            if run_dir.is_symlink():
                raise LaunchError(f"Cannot inspect symlinked run directory: {run_dir}")
            if not run_dir.is_dir():
                continue
            if task_dir.name not in uuids and task_dir.name != state.task_id:
                continue
            for run_path in sorted(run_dir.glob("*.md")):
                run = _load_run(run_path)
                if run.status == "running":
                    runs.append(
                        {
                            "task_path": str(task_dir),
                            "run_path": str(run_path),
                            "run_id": run.run_id,
                            "task_id": run.task_id,
                            "status": run.status,
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        runs.append({"error": str(exc), "classification": "unavailable"})
    return locks, runs


def inspect_active_task_reference(paths: V2Paths) -> dict[str, object]:
    """Inspect active-task YAML independently of strict task resolution."""
    try:
        state = read_active_task_state_raw(paths)
    except LaunchError as exc:
        return {
            "classification": "malformed",
            "code": exc.code,
            "path": str(paths.active_task_path),
            "message": str(exc),
            "details": exc.details,
            "state_present": True,
        }
    if state is None:
        return {
            "classification": "none",
            "path": str(paths.active_task_path),
            "state_present": False,
        }
    candidates, classification, scan_errors = _source_details(paths, state)
    locks, runs = _protection_state(paths, state, candidates)
    protection_blockers: list[dict[str, object]] = list(locks)
    protection_blockers.extend(runs)
    return {
        "classification": classification,
        "state_present": True,
        "task_id": state.task_id,
        "task_uuid": state.task_uuid,
        "previous_task_id": state.previous_task_id,
        "previous_task_uuid": state.previous_task_uuid,
        "path": str(paths.active_task_path),
        "candidates": candidates,
        "scan_errors": scan_errors,
        "locks": locks,
        "running_runs": runs,
        "protected": bool(protection_blockers),
        "protection_blockers": protection_blockers,
        "proof_summary": (
            "The stored UUID has no unique live task record."
            if classification == "missing"
            else "Physical sources do not prove one unambiguous active task."
            if classification in {"ambiguous", "resolution_blocked"}
            else "The stored reference uniquely identifies a live task."
        ),
    }


def _target_task(paths: V2Paths, target_uuid: str) -> tuple[str, Path, str]:
    try:
        parsed_uuid = parse_uuid7(target_uuid)
    except ValueError as exc:
        raise LaunchError(
            "Active-task rebind requires a canonical UUIDv7 target."
        ) from exc
    if str(parsed_uuid) != target_uuid:
        raise LaunchError("Active-task rebind target UUID must be canonical.")
    sources = list(inspect_task_identity_sources(paths))
    matches = [
        source
        for source in sources
        if source.task_uuid == parsed_uuid and source.state == "live"
    ]
    all_matches = [source for source in sources if source.task_uuid == parsed_uuid]
    if len(matches) != 1 or len(all_matches) != 1:
        raise LaunchError(
            "Active-task rebind target must identify exactly one live task record.",
            code="ACTIVE_TASK_REPAIR_TARGET_UNRESOLVED",
            details={
                "target_uuid": target_uuid,
                "candidates": [str(source.path) for source in all_matches],
            },
        )
    source = matches[0]
    metadata, _ = read_markdown_front_matter(source.path / "task.md")
    task_id = metadata.get("id")
    if not isinstance(task_id, str):
        raise LaunchError("Active-task rebind target has no valid display ID.")
    fingerprint = allocation_source_fingerprint(source.path)
    return task_id, source.path, fingerprint


def plan_active_task_repair(
    workspace_root: Path, *, action: str = "clear", target_uuid: str | None = None
) -> dict[str, object]:
    paths = resolve_v2_paths(workspace_root)
    inspection = inspect_active_task_reference(paths)
    raw_bytes: bytes | None = None
    snapshot_error: str | None = None
    try:
        if paths.active_task_path.exists() and not paths.active_task_path.is_symlink():
            raw_bytes = paths.active_task_path.read_bytes()
    except OSError as exc:
        snapshot_error = str(exc)
    raw_fingerprint = (
        hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None
    )
    plan: dict[str, object] = {
        "kind": "active_task_repair",
        "action": action,
        "target_uuid": target_uuid,
        "inspection": inspection,
        "active_task_sha256": raw_fingerprint,
        "apply_safe": False,
        "blocked_reasons": [],
    }
    blockers: list[str] = []
    if snapshot_error is not None:
        blockers.append(f"Unable to snapshot active-task YAML: {snapshot_error}")
    if action not in {"clear", "rebind"}:
        blockers.append("action must be clear or rebind")
    elif not inspection.get("state_present"):
        blockers.append("there is no active-task state to repair")
    elif inspection.get("classification") == "malformed":
        blockers.append(
            "malformed active-task YAML must be preserved and inspected manually"
        )
    elif action == "clear":
        if inspection.get("classification") != "missing":
            blockers.append(
                "clear is permitted only for a proven missing reference, not "
                f"{inspection.get('classification')}"
            )
        if inspection.get("protected"):
            blockers.append(
                "active lock/run or incomplete protection inspection blocks clear"
            )
    else:
        if not target_uuid:
            blockers.append("rebind requires an explicit --target-uuid")
        elif inspection.get("protected"):
            blockers.append("the currently referenced task has an active lock/run")
        else:
            try:
                task_id, target_path, target_fingerprint = _target_task(
                    paths, target_uuid
                )
                plan["target_task_id"] = task_id
                plan["target_path"] = str(target_path)
                plan["target_fingerprint"] = target_fingerprint
            except LaunchError as exc:
                blockers.append(str(exc))
    plan["blocked_reasons"] = blockers
    plan["apply_safe"] = not blockers
    plan_id_payload = {key: value for key, value in plan.items() if key != "plan_id"}
    plan_id = hashlib.sha256(
        json.dumps(plan_id_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    plan["plan_id"] = plan_id
    plan["dry_run"] = True
    plan["status"] = "dry_run"
    plan["next_command"] = (
        f"taskledger repair active-task --action {action} --apply --plan-id {plan_id} "
        f'--reason "Recover the reviewed active-task reference"'
        if plan["apply_safe"]
        else None
    )
    return plan


def _write_active_journal(path: Path, journal: dict[str, object]) -> None:
    atomic_write_text(
        path,
        json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n",
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_active_repair_event(
    workspace_root: Path, paths: V2Paths, journal_path: Path, journal: dict[str, object]
) -> list[str]:
    from taskledger.services.event_logging import event_logging_enabled
    from taskledger.services.task_events import append_task_event
    from taskledger.storage.events import load_events

    transaction_id = str(journal["transaction_id"])
    event_name = str(journal["event_name"])
    if not event_logging_enabled(workspace_root):
        journal["audit_status"] = "disabled"
        journal["audit_errors"] = []
        _write_active_journal(journal_path, journal)
        return []
    try:
        events = load_events(paths.events_dir)
        if not any(
            event.event == event_name
            and event.data.get("transaction_id") == transaction_id
            for event in events
        ):
            state = journal["original_state"]
            assert isinstance(state, dict)
            task_id = str(state.get("task_id", "*"))
            append_task_event(
                workspace_root,
                task_id,
                event_name,
                {
                    "transaction_id": transaction_id,
                    "action": journal["action"],
                    "task_id": state.get("task_id"),
                    "task_uuid": state.get("task_uuid"),
                    "target_uuid": journal.get("target_uuid"),
                    "backup_path": journal["backup_path"],
                    "reason": journal["reason"],
                },
            )
        journal["audit_status"] = "complete"
        journal["audit_errors"] = []
        journal["phase"] = "committed"
    except Exception as exc:  # noqa: BLE001
        journal["audit_status"] = "pending"
        journal["audit_errors"] = [str(exc)]
        journal["phase"] = "audit_pending"
    _write_active_journal(journal_path, journal)
    audit_errors = journal.get("audit_errors", [])
    if not isinstance(audit_errors, list):
        return []
    return [str(error) for error in audit_errors]


def repair_active_task(
    workspace_root: Path,
    *,
    action: str = "clear",
    target_uuid: str | None = None,
    apply: bool = False,
    plan_id: str | None = None,
    reason: str = "",
) -> dict[str, object]:
    paths = resolve_v2_paths(workspace_root)
    planned = plan_active_task_repair(
        workspace_root, action=action, target_uuid=target_uuid
    )
    if not apply:
        return planned
    if not reason.strip():
        raise LaunchError("Active-task recovery requires --reason.")
    if not plan_id:
        raise LaunchError("Active-task recovery requires a reviewed --plan-id.")
    if plan_id != planned["plan_id"]:
        raise LaunchError(
            "Active-task recovery plan changed; inspect a fresh plan.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    if not planned["apply_safe"]:
        raise LaunchError(
            "Active-task recovery is blocked by the reviewed diagnostic.",
            code="ACTIVE_TASK_REPAIR_BLOCKED",
            details={"blocked_reasons": planned["blocked_reasons"]},
        )

    with identity_mutation_lock(paths):
        current = plan_active_task_repair(
            workspace_root, action=action, target_uuid=target_uuid
        )
        if current["plan_id"] != plan_id:
            raise LaunchError(
                "Active-task state or related identity/protection evidence "
                "changed after review.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                details={
                    "reviewed_plan_id": plan_id,
                    "current_plan_id": current["plan_id"],
                },
            )
        active_path = paths.active_task_path
        if active_path.is_symlink() or not active_path.is_file():
            raise LaunchError(
                "Reviewed active-task state path is no longer a regular file.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
            )
        original_bytes = active_path.read_bytes()
        state = active_task_state_from_bytes(paths, original_bytes)
        original_fingerprint = hashlib.sha256(original_bytes).hexdigest()
        if original_fingerprint != planned.get("active_task_sha256"):
            raise LaunchError(
                "Active-task YAML changed after review.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
            )
        transaction_id = str(uuid4())
        recovery_root = paths.ledger_dir / "_recovery"
        active_recovery_root = recovery_root / "active-task-repairs"
        for directory in (recovery_root, active_recovery_root):
            if directory.is_symlink():
                raise LaunchError(
                    f"Active-task recovery path is a symlink: {directory}"
                )
            if directory.exists() and not directory.is_dir():
                raise LaunchError(
                    f"Active-task recovery path is not a directory: {directory}"
                )
            directory.mkdir(exist_ok=True)
        transaction_dir = active_recovery_root / transaction_id
        if transaction_dir.exists() or transaction_dir.is_symlink():
            raise LaunchError(
                "Active-task recovery transaction destination already exists."
            )
        transaction_dir.mkdir(exist_ok=False)
        backup_path = transaction_dir / "active-task-state.json"
        journal_path = transaction_dir / "journal.json"
        original_state = state.to_dict()
        backup: dict[str, object] = {
            "schema_version": _ACTIVE_JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "active_task_path": str(active_path),
            "sha256": hashlib.sha256(original_bytes).hexdigest(),
            "original_bytes_base64": base64.b64encode(original_bytes).decode("ascii"),
        }
        _write_active_journal(backup_path, backup)
        journal: dict[str, object] = {
            "schema_version": _ACTIVE_JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "phase": "prepared",
            "audit_status": "pending",
            "action": action,
            "target_uuid": target_uuid,
            "active_task_path": str(active_path),
            "active_task_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "backup_path": str(backup_path),
            "original_state": original_state,
            "reason": reason.strip(),
            "event_name": (
                "repair.active_task_cleared"
                if action == "clear"
                else "repair.active_task_rebound"
            ),
        }
        _write_active_journal(journal_path, journal)
        if action == "clear":
            if (
                hashlib.sha256(active_path.read_bytes()).hexdigest()
                != journal["active_task_sha256"]
            ):
                raise LaunchError(
                    "Active-task state changed before clear.",
                    code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                )
            active_path.unlink()
            _fsync_directory(active_path.parent)
        else:
            if (
                hashlib.sha256(active_path.read_bytes()).hexdigest()
                != journal["active_task_sha256"]
            ):
                raise LaunchError(
                    "Active-task state changed before rebind.",
                    code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                )
            assert target_uuid is not None
            target_task_id, target_path, target_fingerprint = _target_task(
                paths, target_uuid
            )
            if (
                target_task_id != current.get("target_task_id")
                or str(target_path) != current.get("target_path")
                or target_fingerprint != current.get("target_fingerprint")
            ):
                raise LaunchError(
                    "Rebind target changed after review.",
                    code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                )
            rebound = replace(state, task_id=target_task_id, task_uuid=target_uuid)
            write_yaml_object(active_path, rebound.to_dict())
        journal["phase"] = "committed"
        if action == "rebind":
            journal["new_state"] = rebound.to_dict()
        _write_active_journal(journal_path, journal)
        audit_errors = _append_active_repair_event(
            workspace_root, paths, journal_path, journal
        )
        status = "audit_pending" if audit_errors else "applied"
        return {
            "kind": "active_task_repair",
            "status": status,
            "dry_run": False,
            "action": action,
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "backup_path": str(backup_path),
            "journal_path": str(journal_path),
            "audit_errors": audit_errors,
            "active_task_path": str(active_path),
            "new_state": journal.get("new_state"),
            "next_command": "taskledger --json doctor",
        }

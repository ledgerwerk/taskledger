"""Transactional quarantine and recovery for incomplete task allocations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso

if TYPE_CHECKING:
    from taskledger.domain.models import TaskRunRecord
    from taskledger.storage.task_ids import IncompleteTaskAllocation
    from taskledger.storage.task_store import V2Paths

_JOURNAL_SCHEMA_VERSION = 1
_EVENT_NAME = "repair.task_allocation_quarantined"


def _write_journal(journal_path: Path, journal: dict[str, Any]) -> None:
    from taskledger.storage.atomic import atomic_write_text

    atomic_write_text(
        journal_path,
        json.dumps(journal, indent=2, sort_keys=True) + "\n",
    )


def _load_journal(journal_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(
            f"Unable to read allocation repair journal {journal_path}: {exc}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _JOURNAL_SCHEMA_VERSION
        or not isinstance(payload.get("transaction_id"), str)
        or not isinstance(payload.get("actions"), list)
    ):
        raise LaunchError(f"Invalid allocation repair journal: {journal_path}")
    return payload


def _ensure_ledger_path(paths: V2Paths, path: Path, *, must_exist: bool | None) -> Path:
    ledger_root = paths.ledger_dir.resolve()
    try:
        relative = path.absolute().relative_to(paths.ledger_dir.absolute())
    except ValueError as exc:
        raise LaunchError(
            f"Allocation repair path escapes the ledger root: {path}",
            code="TASKLEDGER_REPAIR_PATH_UNSAFE",
        ) from exc
    candidate = paths.ledger_dir
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise LaunchError(
                f"Allocation repair path is not canonical: {path}",
                code="TASKLEDGER_REPAIR_PATH_UNSAFE",
            )
        candidate = candidate / part
        if candidate.is_symlink():
            raise LaunchError(
                f"Allocation repair path contains a symlink: {candidate}",
                code="TASKLEDGER_REPAIR_PATH_UNSAFE",
            )
        if candidate.exists() and not candidate.resolve().is_relative_to(ledger_root):
            raise LaunchError(
                f"Allocation repair path escapes the ledger root: {candidate}",
                code="TASKLEDGER_REPAIR_PATH_UNSAFE",
            )
    if must_exist is True and not path.exists():
        raise LaunchError(f"Allocation repair source is missing: {path}")
    if must_exist is False and (path.exists() or path.is_symlink()):
        raise LaunchError(f"Allocation repair destination already exists: {path}")
    return path


def _fingerprint(path: Path) -> str:
    from taskledger.storage.task_ids import allocation_source_fingerprint

    return allocation_source_fingerprint(path)


def _plan_action(
    paths: V2Paths,
    allocation: IncompleteTaskAllocation,
    entry: dict[str, object],
    *,
    transaction_id: str,
    reason: str,
) -> dict[str, Any]:
    source = _ensure_ledger_path(paths, allocation.path, must_exist=True)
    quarantine = _ensure_ledger_path(
        paths, Path(str(entry["planned_quarantine"])), must_exist=False
    )
    tombstone_value = entry.get("planned_tombstone")
    tombstone = (
        _ensure_ledger_path(paths, Path(tombstone_value), must_exist=False)
        if isinstance(tombstone_value, str)
        else None
    )
    selected = entry.get("selected_identity")
    if not isinstance(selected, dict):
        raise LaunchError("Allocation repair plan lacks physical identity evidence.")
    survivor = entry.get("surviving_identity")
    selected_uuid = selected.get("task_uuid")
    if not isinstance(selected_uuid, str):
        raise LaunchError("Allocation repair plan lacks a stable physical UUID.")
    return {
        "source_id": str(entry["source_id"]),
        "source_path": str(source),
        "source_relative_path": source.relative_to(paths.ledger_dir).as_posix(),
        "source_fingerprint": str(entry["source_fingerprint"]),
        "task_uuid": selected_uuid,
        "legacy_task_id": selected.get("legacy_task_id"),
        "source_kind": str(entry["source_kind"]),
        "repair_mode": str(entry["repair_mode"]),
        "quarantine_path": str(quarantine),
        "tombstone_path": str(tombstone) if tombstone is not None else None,
        "tombstone_identity": (allocation.legacy_task_id or allocation.task_uuid),
        "tombstone_kind": "legacy" if allocation.legacy_task_id else "uuid",
        "survivor": survivor if isinstance(survivor, dict) else None,
        "transaction_id": transaction_id,
        "reason": reason.strip(),
        "moved": False,
        "tombstone_created": False,
        "status": "prepared",
    }


def _assert_unprotected(paths: V2Paths, actions: list[dict[str, Any]]) -> None:
    from taskledger.domain.models import ActiveTaskState
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.task_store import _load_run
    from taskledger.storage.yaml_store import load_yaml_object

    if paths.active_task_path.exists():
        try:
            active_state = ActiveTaskState.from_dict(
                load_yaml_object(paths.active_task_path, "active task state")
            )
        except Exception as exc:
            raise LaunchError(
                "Cannot safely repair allocations while active-task "
                "state is unreadable.",
                code="TASKLEDGER_ALLOCATION_REPAIR_BLOCKED",
                details={
                    "active_task_path": str(paths.active_task_path),
                    "error": str(exc),
                },
            ) from exc
        for action in actions:
            uuid_match = active_state.task_uuid == action["task_uuid"]
            id_match = (
                active_state.task_id == action["source_id"]
                or active_state.task_id == Path(action["source_path"]).name
            )
            if uuid_match or (active_state.task_uuid is None and id_match):
                raise LaunchError(
                    "Allocation repair is blocked because the selected physical source "
                    "is referenced by active-task state.",
                    code="TASKLEDGER_ALLOCATION_REPAIR_BLOCKED",
                    details={
                        "source_id": action["source_id"],
                        "active_task_id": active_state.task_id,
                        "active_task_uuid": active_state.task_uuid,
                    },
                )

    try:
        inventory = build_lock_inventory(paths)
        runs: list[TaskRunRecord] = []
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
            if run_dir.is_dir():
                runs.extend(
                    _load_run(run_path) for run_path in sorted(run_dir.glob("*.md"))
                )
    except Exception as exc:
        raise LaunchError(
            "Cannot safely inspect lock/run protection before allocation repair.",
            code="TASKLEDGER_ALLOCATION_REPAIR_BLOCKED",
            details={"error": str(exc)},
        ) from exc

    for action in actions:
        source_path = Path(action["source_path"])
        identifiers = {
            str(action["source_id"]),
            source_path.name,
            str(action["task_uuid"]),
        }
        for lock_entry in inventory.entries:
            lock_uuid = (
                lock_entry.lock.task_uuid
                if lock_entry.lock is not None
                else lock_entry.task_uuid
            )
            lock_ids = (
                {str(lock_uuid)}
                if lock_uuid is not None
                else {str(lock_entry.task_id)}
                if lock_entry.task_id is not None
                else set()
            )
            colocated = lock_entry.path == source_path / "lock.yaml"
            if (identifiers & lock_ids or colocated) and (
                lock_entry.is_malformed or lock_entry.is_active
            ):
                raise LaunchError(
                    "Allocation repair is blocked by a task lock.",
                    code="TASKLEDGER_ALLOCATION_REPAIR_BLOCKED",
                    details=lock_entry.to_dict(),
                )
        for run in runs:
            if run.status == "running" and run.task_id in identifiers:
                raise LaunchError(
                    "Allocation repair is blocked by a running task run.",
                    code="TASKLEDGER_ALLOCATION_REPAIR_BLOCKED",
                    details={"source_id": action["source_id"], "run_id": run.run_id},
                )


def _verify_local_action(paths: V2Paths, action: dict[str, Any]) -> None:
    import importlib

    from taskledger.storage.task_identity import inspect_task_identity_sources

    source_path = Path(action["source_path"])
    quarantine_path = Path(action["quarantine_path"])
    if source_path.exists() or source_path.is_symlink() or not quarantine_path.is_dir():
        raise LaunchError(f"Allocation quarantine postcondition failed: {source_path}")
    _ensure_ledger_path(paths, quarantine_path, must_exist=True)
    if _fingerprint(quarantine_path) != action["source_fingerprint"]:
        raise LaunchError(f"Quarantined allocation bytes changed: {quarantine_path}")

    mode = action["repair_mode"]
    if mode == "quarantine_shadowed_legacy_source":
        survivor = action.get("survivor")
        if not isinstance(survivor, dict):
            raise LaunchError("Shadowed allocation has no reviewed live owner.")
        survivor_path = paths.ledger_dir / str(survivor["path"])
        identities = inspect_task_identity_sources(paths)
        matches = tuple(
            identity
            for identity in identities
            if str(identity.task_uuid) == survivor.get("task_uuid")
            and identity.path == survivor_path
            and identity.source_kind == "uuid_task"
            and identity.state == "live"
        )
        if len(matches) != 1 or _fingerprint(survivor_path) != survivor.get(
            "source_fingerprint"
        ):
            raise LaunchError(
                "The reviewed live allocation owner changed during repair."
            )
        if action.get("tombstone_path") is not None:
            raise LaunchError("Shadowed-source quarantine must not create a tombstone.")
        return

    tombstone_value = action.get("tombstone_path")
    if mode != "quarantine_and_tombstone" or not isinstance(tombstone_value, str):
        raise LaunchError("Unsupported allocation repair mode in transaction journal.")
    tombstone_path = Path(tombstone_value)
    _ensure_ledger_path(paths, tombstone_path, must_exist=True)
    try:
        tomllib = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        tomllib = importlib.import_module("tomli")
    try:
        document = tomllib.loads(tombstone_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Unable to verify allocation tombstone: {exc}") from exc
    if (
        document.get("transaction_id") != action["transaction_id"]
        or document.get("quarantined_path")
        != quarantine_path.relative_to(paths.ledger_dir).as_posix()
    ):
        raise LaunchError(
            f"Allocation tombstone is not owned by this transaction: {tombstone_path}"
        )


def _conflict_identity_payload(paths: V2Paths, source: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_uuid": str(source.task_uuid),
        "legacy_task_id": source.legacy_task_id,
        "source_kind": source.source_kind,
        "state": source.state,
        "path": source.path.relative_to(paths.ledger_dir).as_posix(),
    }
    if source.state == "live":
        payload["source_fingerprint"] = _fingerprint(source.path)
    return payload


def _read_conflict_tombstone(path: Path) -> dict[str, object]:
    import importlib

    try:
        tomllib = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        tomllib = importlib.import_module("tomli")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(f"Unable to read identity tombstone {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise LaunchError(f"Invalid identity tombstone {path}: expected a TOML table.")
    return document


def _migration_receipt_evidence(
    paths: V2Paths, legacy_task_id: str, owner: Any
) -> dict[str, object] | None:
    receipt_path = paths.ledger_dir / "task-directory-migration-v5-to-v6.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return None
    try:
        raw = receipt_path.read_bytes()
        receipt = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(receipt, dict):
        return None
    renames = receipt.get("task_renames")
    if not isinstance(renames, list):
        return None
    owner_path = owner.path.relative_to(paths.ledger_dir).as_posix()
    matching = next(
        (
            item
            for item in renames
            if isinstance(item, dict)
            and item.get("legacy_task_id") == legacy_task_id
            and item.get("task_uuid") == str(owner.task_uuid)
            and item.get("new") == owner_path
        ),
        None,
    )
    if not isinstance(matching, dict):
        return None
    return {
        "path": receipt_path.relative_to(paths.ledger_dir).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "task_rename": matching,
    }


def _plan_legacy_conflict_action(
    paths: V2Paths,
    conflict: dict[str, object],
    *,
    allow_unverifiable: bool,
) -> dict[str, object]:
    from taskledger.ids import TASK_ID_FORMAT
    from taskledger.storage.events import load_events
    from taskledger.storage.task_identity import inspect_legacy_identity_claims

    legacy_task_id = str(conflict.get("identity", ""))
    claims = inspect_legacy_identity_claims(paths, legacy_task_id)
    tombstones = tuple(
        source
        for source in claims
        if source.source_kind == "tombstone" and source.state == "tombstone"
    )
    owners = tuple(
        source
        for source in claims
        if source.source_kind == "uuid_task" and source.state == "live"
    )
    if (
        conflict.get("identity_kind") != "legacy_task_id"
        or len(claims) != 2
        or len(tombstones) != 1
        or len(owners) != 1
    ):
        raise LaunchError(
            "Conflict is not exactly one historical tombstone and one live UUID owner."
        )

    tombstone = tombstones[0]
    owner = owners[0]
    expected_tombstone = paths.ledger_dir / "tombstones" / f"{legacy_task_id}.toml"
    if tombstone.path != expected_tombstone:
        raise LaunchError("Conflicting tombstone path does not match its legacy ID.")
    document = _read_conflict_tombstone(tombstone.path)
    if (
        document.get("schema_version") != 1
        or document.get("object_type") != "task_id_tombstone"
        or document.get("id") != legacy_task_id
        or not isinstance(document.get("quarantined_path"), str)
    ):
        raise LaunchError(
            "Conflicting legacy tombstone has invalid schema or identity."
        )

    quarantine_rel = str(document["quarantined_path"])
    quarantine_path = paths.ledger_dir / quarantine_rel
    _ensure_ledger_path(paths, quarantine_path, must_exist=True)
    recovery_root = (
        paths.ledger_dir / "_recovery" / "incomplete-task-allocations"
    ).resolve()
    if (
        not quarantine_path.is_dir()
        or not quarantine_path.resolve().is_relative_to(recovery_root)
        or Path(quarantine_rel).name != legacy_task_id
    ):
        raise LaunchError("Tombstone quarantine path is unsafe or mismatched.")

    tombstone_rel = tombstone.path.relative_to(paths.ledger_dir).as_posix()
    matching_events = tuple(
        event
        for event in load_events(paths.events_dir)
        if event.event == _EVENT_NAME
        and event.data.get("tombstone_path") == tombstone_rel
        and event.data.get("quarantined_path") == quarantine_rel
    )
    if not matching_events:
        raise LaunchError(
            "No historical repair event matches the tombstone and quarantine."
        )

    event_source_ids: set[str] = set()
    for event in matching_events:
        stored_id = event.data.get("legacy_task_id")
        if isinstance(stored_id, str):
            event_source_ids.add(stored_id)
        stored_path = event.data.get("source_path")
        if isinstance(stored_path, str):
            path_id = Path(stored_path).name
            if path_id.startswith("task-"):
                event_source_ids.add(path_id)
    if len(event_source_ids) > 1:
        raise LaunchError(
            "Historical repair events disagree about the physical source ID."
        )

    source_id = next(iter(event_source_ids), None)
    if source_id is not None:
        try:
            source_parts = TASK_ID_FORMAT.parse_parts(source_id)
        except ValueError as exc:
            raise LaunchError(
                "Historical repair event contains an invalid source ID."
            ) from exc

        if TASK_ID_FORMAT.format(source_parts.number) != source_id:
            raise LaunchError(
                "Historical repair event contains a non-canonical source ID."
            )
        if source_id == legacy_task_id:
            raise LaunchError(
                "Historical evidence confirms the tombstone ID; retirement is not safe."
            )
        if inspect_legacy_identity_claims(paths, source_id):
            raise LaunchError("Verified replacement source ID already has claimants.")
        repair_mode = "rehome_tombstone_verified"
        evidence_status = "verified_event"
        requires_override = False
        apply_safe = True
    else:
        source_id = None
        repair_mode = "retire_shadowing_tombstone"
        evidence_status = "unverifiable_physical_source"
        requires_override = True
        apply_safe = allow_unverifiable

    tombstone_hash = hashlib.sha256(tombstone.path.read_bytes()).hexdigest()
    return {
        "kind": "identity_conflict_repair_action",
        "identity_kind": "legacy_task_id",
        "legacy_task_id": legacy_task_id,
        "repair_mode": repair_mode,
        "source_id": source_id,
        "tombstone_path": tombstone.path.as_posix(),
        "tombstone_sha256": tombstone_hash,
        "quarantined_path": quarantine_path.as_posix(),
        "quarantined_relative_path": quarantine_rel,
        "quarantine_fingerprint": _fingerprint(quarantine_path),
        "surviving_identity": _conflict_identity_payload(paths, owner),
        "migration_evidence": _migration_receipt_evidence(paths, legacy_task_id, owner),
        "claimant_signature": [
            _conflict_identity_payload(paths, source) for source in claims
        ],
        "evidence_status": evidence_status,
        "event_ids": sorted(event.event_id for event in matching_events),
        "requires_operator_override": requires_override,
        "operator_override": allow_unverifiable,
        "apply_safe": apply_safe,
        "reason": (
            None if apply_safe else "Requires explicit --allow-unverifiable override."
        ),
        "new_tombstone": (
            str(paths.ledger_dir / "tombstones" / f"{source_id}.toml")
            if source_id is not None
            else None
        ),
    }


def plan_identity_conflict_recovery(
    paths: V2Paths,
    *,
    allow_unverifiable: bool = False,
    tombstone_id: str | None = None,
) -> dict[str, object]:
    """Classify identity conflicts and fingerprint a reviewed repair plan."""
    from uuid import NAMESPACE_URL, uuid5

    from taskledger.storage.task_identity import inspect_task_identity_conflicts

    try:
        conflicts = inspect_task_identity_conflicts(paths)
    except LaunchError as exc:
        conflicts = ()
        actions: list[dict[str, object]] = [
            {
                "kind": "identity_conflict_repair_action",
                "identity_kind": None,
                "legacy_task_id": None,
                "repair_mode": "blocked_identity_conflict",
                "evidence_status": "unverifiable",
                "requires_operator_override": False,
                "operator_override": allow_unverifiable,
                "apply_safe": False,
                "reason": str(exc),
                "next_command": None,
            }
        ]
    else:
        selected_legacy_conflicts = tuple(
            conflict
            for conflict in conflicts
            if conflict.get("identity_kind") == "legacy_task_id"
            and (tombstone_id is None or conflict.get("identity") == tombstone_id)
        )
        selected = tuple(
            conflict
            for conflict in conflicts
            if tombstone_id is None
            or conflict.get("identity") == tombstone_id
            or _identity_uuid_conflict_is_covered(conflict, selected_legacy_conflicts)
        )
        actions = []
        for conflict in selected:
            if _identity_uuid_conflict_is_covered(conflict, selected_legacy_conflicts):
                continue
            try:
                action = _plan_legacy_conflict_action(
                    paths, conflict, allow_unverifiable=allow_unverifiable
                )
            except LaunchError as exc:
                action = {
                    "kind": "identity_conflict_repair_action",
                    "identity_kind": conflict.get("identity_kind"),
                    "legacy_task_id": conflict.get("identity"),
                    "repair_mode": "blocked_identity_conflict",
                    "evidence_status": "blocked",
                    "requires_operator_override": False,
                    "operator_override": allow_unverifiable,
                    "apply_safe": False,
                    "reason": str(exc),
                    "claimant_signature": conflict.get("sources", []),
                }
            actions.append(action)

    base = {
        "allow_unverifiable": allow_unverifiable,
        "tombstone_id": tombstone_id,
        "conflicts": list(conflicts),
        "actions": actions,
    }
    base_fingerprint = hashlib.sha256(
        json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    transaction_number = 0
    while True:
        transaction_id = str(
            uuid5(
                NAMESPACE_URL,
                f"taskledger-allocation-conflict:{base_fingerprint}:{transaction_number}",
            )
        )
        transaction_dir = (
            paths.ledger_dir
            / "_recovery"
            / "allocation-repair-transactions"
            / transaction_id
        )
        if not transaction_dir.exists():
            break
        transaction_number += 1
    for action in actions:
        legacy_id = action.get("legacy_task_id")
        if action.get("repair_mode") in {
            "retire_shadowing_tombstone",
            "rehome_tombstone_verified",
        } and isinstance(legacy_id, str):
            action["preserved_tombstone"] = str(
                paths.ledger_dir
                / "recovery"
                / "misattributed-allocation-tombstones"
                / transaction_id
                / f"{legacy_id}.toml"
            )
    plan_payload = {**base, "transaction_id": transaction_id}
    plan_id = hashlib.sha256(
        json.dumps(plan_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    apply_safe = bool(actions) and all(
        bool(action.get("apply_safe")) for action in actions
    )
    return {
        "kind": "task_allocation_conflict_repair",
        "status": "dry_run" if actions else "nothing_to_repair",
        "dry_run": True,
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "allow_unverifiable": allow_unverifiable,
        "apply_safe": apply_safe,
        "repair_mode": (
            actions[0].get("repair_mode") if len(actions) == 1 else "batch"
        ),
        "actions": actions,
        "identity_conflicts": list(conflicts),
        "ledger_healthy": not conflicts,
    }


def _validate_identity_conflict_action_inputs(
    paths: V2Paths, action: dict[str, Any]
) -> None:
    from taskledger.storage.task_identity import inspect_legacy_identity_claims

    tombstone_path = Path(str(action["tombstone_path"]))
    quarantine_path = Path(str(action["quarantined_path"]))
    preserved_path = Path(str(action["preserved_tombstone"]))
    owner = action.get("surviving_identity")
    _ensure_ledger_path(paths, tombstone_path, must_exist=True)
    _ensure_ledger_path(paths, quarantine_path, must_exist=True)
    _ensure_ledger_path(paths, preserved_path, must_exist=False)
    if hashlib.sha256(tombstone_path.read_bytes()).hexdigest() != action.get(
        "tombstone_sha256"
    ):
        raise LaunchError(
            "Identity conflict tombstone changed after review.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    if _fingerprint(quarantine_path) != action.get("quarantine_fingerprint"):
        raise LaunchError(
            "Identity conflict quarantine changed after review.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    if not isinstance(owner, dict):
        raise LaunchError("Identity conflict plan lacks its reviewed live owner.")
    owner_path = paths.ledger_dir / str(owner.get("path", ""))
    _ensure_ledger_path(paths, owner_path, must_exist=True)
    if _fingerprint(owner_path) != owner.get("source_fingerprint"):
        raise LaunchError(
            "Identity conflict live owner changed after review.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    claims = inspect_legacy_identity_claims(paths, str(action["legacy_task_id"]))
    current_signature = [_conflict_identity_payload(paths, source) for source in claims]
    if current_signature != action.get("claimant_signature"):
        raise LaunchError(
            "Identity conflict claimant set changed after review.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    source_id = action.get("source_id")
    if isinstance(source_id, str) and inspect_legacy_identity_claims(paths, source_id):
        raise LaunchError(
            "Verified replacement source ID acquired a claimant after review.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )


def _verify_identity_conflict_action(paths: V2Paths, action: dict[str, Any]) -> None:
    from taskledger.storage.task_identity import inspect_legacy_identity_claims

    legacy_task_id = str(action["legacy_task_id"])
    tombstone_path = Path(str(action["tombstone_path"]))
    preserved_path = Path(str(action["preserved_tombstone"]))
    quarantine_path = Path(str(action["quarantined_path"]))
    owner = action.get("surviving_identity")
    if not isinstance(owner, dict):
        raise LaunchError("Conflict repair journal lacks the reviewed live owner.")
    for path in (preserved_path, quarantine_path):
        _ensure_ledger_path(paths, path, must_exist=True)
    if tombstone_path.exists() or not preserved_path.is_file():
        raise LaunchError(
            "Original tombstone was not preserved outside the identity set."
        )
    if hashlib.sha256(preserved_path.read_bytes()).hexdigest() != action.get(
        "tombstone_sha256"
    ):
        raise LaunchError("Preserved tombstone bytes differ from the reviewed plan.")
    if _fingerprint(quarantine_path) != action.get("quarantine_fingerprint"):
        raise LaunchError("Reviewed quarantine changed during tombstone recovery.")

    owner_path = paths.ledger_dir / str(owner.get("path", ""))
    _ensure_ledger_path(paths, owner_path, must_exist=True)
    if _fingerprint(owner_path) != owner.get("source_fingerprint"):
        raise LaunchError("Reviewed live UUID owner changed during tombstone recovery.")
    claims = inspect_legacy_identity_claims(paths, legacy_task_id)
    owner_matches = [
        _conflict_identity_payload(paths, source)
        for source in claims
        if source.source_kind == "uuid_task" and source.state == "live"
    ]
    if owner_matches != [owner] or any(
        source.source_kind == "tombstone" for source in claims
    ):
        raise LaunchError(
            "Retired legacy ID is not solely owned by the reviewed live task."
        )

    repair_mode = action.get("repair_mode")
    source_id = action.get("source_id")
    if repair_mode == "retire_shadowing_tombstone":
        if source_id is not None or action.get("new_tombstone") is not None:
            raise LaunchError(
                "Shadow tombstone retirement must not assert a replacement ID."
            )
        return
    if repair_mode != "rehome_tombstone_verified" or not isinstance(source_id, str):
        raise LaunchError("Unsupported identity conflict repair mode in journal.")
    new_tombstone = Path(str(action["new_tombstone"]))
    _ensure_ledger_path(paths, new_tombstone, must_exist=True)
    replacement_claims = inspect_legacy_identity_claims(paths, source_id)
    if (
        len(replacement_claims) != 1
        or replacement_claims[0].source_kind != "tombstone"
        or replacement_claims[0].state != "tombstone"
        or replacement_claims[0].path != new_tombstone
    ):
        raise LaunchError(
            "Verified source ID is not solely owned by its replacement tombstone."
        )
    replacement = _read_conflict_tombstone(new_tombstone)
    if (
        replacement.get("id") != source_id
        or replacement.get("transaction_id") != action.get("transaction_id")
        or replacement.get("quarantined_path")
        != action.get("quarantined_relative_path")
    ):
        raise LaunchError(
            "Replacement tombstone does not match the reviewed transaction."
        )


def _rollback_identity_conflict_transaction(
    paths: V2Paths, journal_path: Path, journal: dict[str, Any]
) -> list[str]:
    import base64

    from taskledger.storage.atomic import atomic_write_text
    from taskledger.storage.task_identity import invalidate_task_identity_inventory

    actions = journal.get("actions", [])
    action_list = actions if isinstance(actions, list) else []
    errors: list[str] = []
    for action in action_list:
        if not isinstance(action, dict):
            errors.append("Conflict repair journal contains an invalid action.")
            continue
        tombstone = Path(str(action["tombstone_path"]))
        preserved = Path(str(action["preserved_tombstone"]))
        replacement_value = action.get("new_tombstone")
        replacement = (
            Path(replacement_value) if isinstance(replacement_value, str) else None
        )
        try:
            _ensure_ledger_path(paths, tombstone, must_exist=None)
            _ensure_ledger_path(paths, preserved, must_exist=None)
            if tombstone.exists() and preserved.exists():
                raise LaunchError(
                    f"Both authoritative and preserved tombstones exist: {tombstone}"
                )
            if preserved.exists() and hashlib.sha256(
                preserved.read_bytes()
            ).hexdigest() != action.get("tombstone_sha256"):
                raise LaunchError(f"Preserved tombstone changed: {preserved}")
            if replacement is not None and replacement.exists():
                document = _read_conflict_tombstone(replacement)
                if document.get("transaction_id") != journal.get("transaction_id"):
                    raise LaunchError(
                        f"Replacement tombstone is not transaction-owned: {replacement}"
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{action.get('legacy_task_id')}: {exc}")

    if errors:
        journal["phase"] = "rollback_incomplete"
        journal["rollback_errors"] = errors
        _write_journal(journal_path, journal)
        return errors

    for action in reversed(action_list):
        if not isinstance(action, dict):
            continue
        tombstone = Path(str(action["tombstone_path"]))
        preserved = Path(str(action["preserved_tombstone"]))
        replacement_value = action.get("new_tombstone")
        replacement = (
            Path(replacement_value) if isinstance(replacement_value, str) else None
        )
        try:
            if replacement is not None and replacement.exists():
                replacement.unlink()
            if preserved.exists():
                tombstone.parent.mkdir(parents=True, exist_ok=True)
                preserved.rename(tombstone)
            elif not tombstone.exists():
                original = base64.b64decode(
                    str(action["tombstone_backup_base64"]), validate=True
                ).decode("utf-8")
                tombstone.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(tombstone, original)
            action["status"] = "rolled_back"
        except Exception as exc:  # noqa: BLE001
            action["status"] = "rollback_incomplete"
            errors.append(f"{action.get('legacy_task_id')}: {exc}")
        try:
            _write_journal(journal_path, journal)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Unable to persist conflict rollback progress: {exc}")
            break

    invalidate_task_identity_inventory()
    journal["phase"] = "rollback_incomplete" if errors else "rolled_back"
    journal["rollback_errors"] = errors
    try:
        _write_journal(journal_path, journal)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Unable to persist final conflict rollback state: {exc}")
    return errors


def _append_identity_conflict_events(
    workspace_root: Path,
    paths: V2Paths,
    journal_path: Path,
    journal: dict[str, Any],
) -> list[str]:
    from taskledger.services.event_logging import event_logging_enabled
    from taskledger.services.task_events import append_task_event
    from taskledger.storage.events import load_events

    if not event_logging_enabled(workspace_root):
        journal["audit_status"] = "disabled"
        journal["audit_errors"] = []
        _write_journal(journal_path, journal)
        return []
    transaction_id = str(journal["transaction_id"])
    try:
        events = load_events(paths.events_dir)
        existing = {
            (event.event, event.data.get("action_index"))
            for event in events
            if event.data.get("transaction_id") == transaction_id
        }
        for index, action in enumerate(journal["actions"]):
            if not isinstance(action, dict):
                continue
            legacy_id = str(action["legacy_task_id"])
            owner = action["surviving_identity"]
            if not isinstance(owner, dict):
                raise LaunchError("Conflict repair journal lost its reviewed owner.")
            repair_mode = str(action["repair_mode"])
            event_name = (
                "repair.task_allocation_shadow_tombstone_retired"
                if repair_mode == "retire_shadowing_tombstone"
                else "repair.task_allocation_tombstone_reconciled"
            )
            if (event_name, index) in existing:
                continue
            common = {
                "transaction_id": transaction_id,
                "action_index": index,
                "legacy_task_id": legacy_id,
                "previous_tombstone_path": Path(str(action["tombstone_path"]))
                .relative_to(paths.ledger_dir)
                .as_posix(),
                "previous_tombstone_sha256": action["tombstone_sha256"],
                "preserved_tombstone": Path(str(action["preserved_tombstone"]))
                .relative_to(paths.ledger_dir)
                .as_posix(),
                "quarantined_path": action["quarantined_relative_path"],
                "quarantine_fingerprint": action["quarantine_fingerprint"],
                "surviving_task_uuid": owner["task_uuid"],
                "surviving_source_path": owner["path"],
                "surviving_source_fingerprint": owner["source_fingerprint"],
                "evidence_status": action["evidence_status"],
                "operator_override": bool(action["requires_operator_override"]),
                "reason": str(journal["reason"]),
            }
            if repair_mode == "rehome_tombstone_verified":
                common["source_id"] = action["source_id"]
                common["new_tombstone"] = (
                    Path(str(action["new_tombstone"]))
                    .relative_to(paths.ledger_dir)
                    .as_posix()
                )
            append_task_event(workspace_root, "*", event_name, common)
            events = load_events(paths.events_dir)
            existing = {
                (event.event, event.data.get("action_index"))
                for event in events
                if event.data.get("transaction_id") == transaction_id
            }
        journal["audit_status"] = "complete"
        journal["audit_errors"] = []
        journal["phase"] = "committed"
        _write_journal(journal_path, journal)
        return []
    except Exception as exc:  # noqa: BLE001
        errors = [str(exc)]
        journal["audit_status"] = "pending"
        journal["audit_errors"] = errors
        journal["phase"] = "audit_pending"
        _write_journal(journal_path, journal)
        return errors


def apply_identity_conflict_repair_batch(
    workspace_root: Path,
    paths: V2Paths,
    *,
    plan_id: str,
    reason: str,
    allow_unverifiable: bool,
    tombstone_id: str | None = None,
) -> dict[str, object]:
    """Apply the reviewed identity-conflict plan as one journaled transaction."""
    import base64

    from taskledger.storage.task_identity import (
        identity_mutation_lock,
        inspect_task_identity_conflicts,
        invalidate_task_identity_inventory,
        scan_task_identity_inventory,
    )

    if not reason.strip():
        raise LaunchError("Identity conflict repair requires --reason when applying.")
    with identity_mutation_lock(paths):
        plan = plan_identity_conflict_recovery(
            paths,
            allow_unverifiable=allow_unverifiable,
            tombstone_id=tombstone_id,
        )
        if plan.get("plan_id") != plan_id:
            raise LaunchError(
                "Identity conflict repair plan changed; inspect a fresh dry-run.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                details={
                    "expected_plan_id": plan_id,
                    "current_plan_id": plan.get("plan_id"),
                },
            )
        actions_raw = plan.get("actions")
        if not isinstance(actions_raw, list) or not actions_raw:
            raise LaunchError("No reviewed identity conflicts are available to repair.")
        if not plan.get("apply_safe"):
            raise LaunchError(
                "Identity conflict plan contains blocked actions or lacks "
                "explicit override.",
                code="TASKLEDGER_ALLOCATION_REPAIR_BLOCKED",
                details={"actions": actions_raw},
            )
        transaction_id = str(plan["transaction_id"])
        txn_dir = (
            paths.ledger_dir
            / "_recovery"
            / "allocation-repair-transactions"
            / transaction_id
        )
        journal_path = txn_dir / "journal.json"
        journal_actions: list[dict[str, Any]] = []
        for entry in actions_raw:
            if not isinstance(entry, dict):
                raise LaunchError("Identity conflict plan contains an invalid action.")
            _validate_identity_conflict_action_inputs(paths, entry)
            tombstone_bytes = Path(str(entry["tombstone_path"])).read_bytes()
            journal_actions.append(
                {
                    **entry,
                    "transaction_id": transaction_id,
                    "status": "prepared",
                    "tombstone_backup_base64": base64.b64encode(tombstone_bytes).decode(
                        "ascii"
                    ),
                    "preserved": False,
                    "replacement_written": False,
                }
            )
        journal: dict[str, Any] = {
            "schema_version": _JOURNAL_SCHEMA_VERSION,
            "transaction_kind": "identity_conflict_repair",
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "scope": (
                "conflicts" if tombstone_id is None else f"conflict:{tombstone_id}"
            ),
            "phase": "prepared",
            "audit_status": "pending",
            "reason": reason.strip(),
            "actions": journal_actions,
            "created_at": utc_now_iso(),
        }
        _ensure_ledger_path(paths, txn_dir, must_exist=False)
        txn_dir.mkdir(parents=True, exist_ok=False)
        _write_journal(journal_path, journal)
        try:
            journal["phase"] = "staging"
            _write_journal(journal_path, journal)
            for action in journal_actions:
                _validate_identity_conflict_action_inputs(paths, action)
                tombstone_path = Path(str(action["tombstone_path"]))
                preserved_path = Path(str(action["preserved_tombstone"]))
                preserved_path.parent.mkdir(parents=True, exist_ok=True)
                tombstone_path.rename(preserved_path)
                action["preserved"] = True
                action["status"] = "old_tombstone_preserved"
                _write_journal(journal_path, journal)
                if action["repair_mode"] == "rehome_tombstone_verified":
                    from taskledger.storage.task_ids import write_task_id_tombstone

                    replacement_path = write_task_id_tombstone(
                        paths,
                        str(action["source_id"]),
                        reason=reason,
                        quarantined_path=Path(str(action["quarantined_path"])),
                        transaction_id=transaction_id,
                    )
                    if replacement_path != Path(str(action["new_tombstone"])):
                        raise LaunchError(
                            "Replacement tombstone differs from reviewed plan."
                        )
                    action["replacement_written"] = True
                    action["status"] = "replacement_written"
                    _write_journal(journal_path, journal)
                _verify_identity_conflict_action(paths, action)
                action["status"] = "locally_verified"
                _write_journal(journal_path, journal)

            invalidate_task_identity_inventory()
            before_raw = plan.get("identity_conflicts", [])
            before_conflicts = (
                tuple(conflict for conflict in before_raw if isinstance(conflict, dict))
                if isinstance(before_raw, list)
                else ()
            )
            removed_tombstones = {
                str(action["tombstone_path"]) for action in journal_actions
            }
            expected_conflicts = _remaining_identity_claim_conflicts(
                before_conflicts, removed_tombstones
            )
            remaining = inspect_task_identity_conflicts(paths)
            if _conflict_signature(remaining) != _conflict_signature(
                expected_conflicts
            ):
                raise LaunchError(
                    "Identity conflict batch produced an unexpected conflict state.",
                    code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                    details={"remaining_conflicts": list(remaining)},
                )
            strict_error: str | None = None
            if not expected_conflicts:
                try:
                    scan_task_identity_inventory(paths)
                except LaunchError as exc:
                    strict_error = str(exc)
                    raise LaunchError(
                        f"Final task identity validation failed: {strict_error}",
                        code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                    ) from exc
            for action in journal_actions:
                action["status"] = "committed"
            journal["phase"] = "committed"
            journal["ledger_healthy"] = strict_error is None and not expected_conflicts
            journal["remaining_conflicts"] = list(remaining)
            _write_journal(journal_path, journal)
        except Exception as exc:  # noqa: BLE001
            journal["failure"] = str(exc)
            rollback_errors = _rollback_identity_conflict_transaction(
                paths, journal_path, journal
            )
            remaining = inspect_task_identity_conflicts(paths)
            failed = [{"source_id": None, "error": str(exc)}]
            return {
                "kind": "task_allocation_conflict_repair",
                "status": "rollback_incomplete" if rollback_errors else "rolled_back",
                "dry_run": False,
                "plan_id": plan_id,
                "transaction_id": transaction_id,
                "attempted_count": len(journal_actions),
                "repaired_count": 0,
                "failed_count": len(failed),
                "repaired": [],
                "failed": failed,
                "rollback_errors": rollback_errors,
                "reason": reason.strip(),
                "ledger_healthy": False,
                "remaining_conflicts": list(remaining),
                "journal_path": str(journal_path),
            }

        audit_errors = _append_identity_conflict_events(
            workspace_root, paths, journal_path, journal
        )
        return {
            "kind": "task_allocation_conflict_repair",
            "status": "audit_pending" if audit_errors else "applied",
            "dry_run": False,
            "plan_id": plan_id,
            "transaction_id": transaction_id,
            "attempted_count": len(journal_actions),
            "repaired_count": len(journal_actions),
            "failed_count": 0,
            "repaired": [
                {
                    "legacy_task_id": action["legacy_task_id"],
                    "repair_mode": action["repair_mode"],
                    "tombstone_path": action["tombstone_path"],
                    "preserved_tombstone": action["preserved_tombstone"],
                    "new_tombstone": action.get("new_tombstone"),
                }
                for action in journal_actions
            ],
            "failed": [],
            "reason": reason.strip(),
            "ledger_healthy": bool(journal.get("ledger_healthy")),
            "remaining_conflicts": list(journal.get("remaining_conflicts", [])),
            "journal_path": str(journal_path),
            "audit_errors": audit_errors,
        }


def _identity_uuid_conflict_is_covered(
    conflict: dict[str, object], legacy_conflicts: tuple[dict[str, object], ...]
) -> bool:
    if conflict.get("identity_kind") != "task_uuid":
        return False
    members = conflict.get("sources")
    if not isinstance(members, list) or len(members) != 2:
        return False
    legacy_ids = {
        member.get("legacy_task_id") for member in members if isinstance(member, dict)
    }
    if len(legacy_ids) != 1:
        return False
    legacy_id = next(iter(legacy_ids))
    if not isinstance(legacy_id, str):
        return False
    matching_legacy = next(
        (
            item
            for item in legacy_conflicts
            if item.get("identity_kind") == "legacy_task_id"
            and item.get("identity") == legacy_id
        ),
        None,
    )
    if matching_legacy is None:
        return False
    legacy_members = matching_legacy.get("sources")
    if not isinstance(legacy_members, list) or len(legacy_members) != 2:
        return False
    paths = {str(member.get("path")) for member in members if isinstance(member, dict)}
    legacy_paths = {
        str(member.get("path")) for member in legacy_members if isinstance(member, dict)
    }
    kinds = {
        (member.get("source_kind"), member.get("state"))
        for member in members
        if isinstance(member, dict)
    }
    return paths == legacy_paths and kinds == {
        ("uuid_task", "live"),
        ("tombstone", "tombstone"),
    }


def _remaining_identity_claim_conflicts(
    before: tuple[dict[str, object], ...], removed_tombstones: set[str]
) -> tuple[dict[str, object], ...]:
    remaining: list[dict[str, object]] = []
    for conflict in before:
        members = conflict.get("sources", [])
        if not isinstance(members, list):
            continue
        kept = [
            member
            for member in members
            if isinstance(member, dict)
            and str(member.get("path")) not in removed_tombstones
        ]
        if len(kept) > 1:
            remaining.append({**conflict, "sources": kept})
    return tuple(remaining)


def _conflict_signature(
    conflicts: tuple[dict[str, object], ...],
) -> set[tuple[str, str, tuple[str, ...]]]:
    signatures: set[tuple[str, str, tuple[str, ...]]] = set()
    for conflict in conflicts:
        sources = conflict.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        source_paths = tuple(
            sorted(
                str(source["path"]) for source in sources if isinstance(source, dict)
            )
        )
        signatures.add(
            (
                str(conflict["identity_kind"]),
                str(conflict["identity"]),
                source_paths,
            )
        )
    return signatures


def _remaining_conflicts(
    before: tuple[dict[str, object], ...], actions: list[dict[str, Any]]
) -> tuple[dict[str, object], ...]:
    selected_paths = {str(action["source_path"]) for action in actions}
    remaining: list[dict[str, object]] = []
    for conflict in before:
        sources = conflict.get("sources", [])
        if not isinstance(sources, list):
            continue
        kept = [
            source
            for source in sources
            if isinstance(source, dict)
            and str(source.get("path")) not in selected_paths
        ]
        if len(kept) > 1:
            remaining.append({**conflict, "sources": kept})
    return tuple(remaining)


def _rollback_transaction(
    paths: V2Paths, journal_path: Path, journal: dict[str, Any]
) -> list[str]:
    import importlib

    from taskledger.storage.task_identity import invalidate_task_identity_inventory

    actions = journal.get("actions", [])
    action_list = actions if isinstance(actions, list) else []
    transaction_id = str(journal["transaction_id"])
    errors: list[str] = []

    # Validate every staged path before rollback begins, so an unexpected file
    # cannot cause us to partially undo otherwise recoverable actions.
    for action in action_list:
        if not isinstance(action, dict):
            errors.append("Transaction journal contains an invalid action entry.")
            continue
        source = Path(str(action["source_path"]))
        quarantine = Path(str(action["quarantine_path"]))
        tombstone_value = action.get("tombstone_path")
        tombstone = Path(tombstone_value) if isinstance(tombstone_value, str) else None
        try:
            _ensure_ledger_path(paths, source, must_exist=None)
            _ensure_ledger_path(paths, quarantine, must_exist=None)
            source_exists = source.exists() or source.is_symlink()
            quarantine_exists = quarantine.exists() or quarantine.is_symlink()
            if source_exists == quarantine_exists:
                raise LaunchError(
                    "Ambiguous source/quarantine state; inspect "
                    f"{source} and {quarantine}."
                )
            present = source if source_exists else quarantine
            if (
                not present.is_dir()
                or _fingerprint(present) != action["source_fingerprint"]
            ):
                raise LaunchError(f"Allocation fingerprint changed: {present}")
            if tombstone is not None:
                _ensure_ledger_path(paths, tombstone, must_exist=None)
                if tombstone.exists():
                    try:
                        tomllib = importlib.import_module("tomllib")
                    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
                        tomllib = importlib.import_module("tomli")
                    document = tomllib.loads(tombstone.read_text(encoding="utf-8"))
                    if document.get("transaction_id") != transaction_id:
                        raise LaunchError(
                            f"Refusing to remove an unowned tombstone: {tombstone}"
                        )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{action.get('source_id')}: {exc}")

    if errors:
        journal["phase"] = "rollback_incomplete"
        journal["rollback_errors"] = errors
        try:
            _write_journal(journal_path, journal)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Unable to persist rollback preflight: {exc}")
        return errors

    for action in reversed(action_list):
        if not isinstance(action, dict):
            continue
        source = Path(str(action["source_path"]))
        quarantine = Path(str(action["quarantine_path"]))
        tombstone_value = action.get("tombstone_path")
        tombstone = Path(tombstone_value) if isinstance(tombstone_value, str) else None
        try:
            if tombstone is not None and tombstone.exists():
                tombstone.unlink()
            if quarantine.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                quarantine.rename(source)
            action["moved"] = False
            action["tombstone_created"] = False
            action["status"] = "rolled_back"
        except Exception as exc:  # noqa: BLE001
            action["status"] = "rollback_incomplete"
            errors.append(f"{action.get('source_id')}: {exc}")
        try:
            _write_journal(journal_path, journal)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Unable to persist rollback progress: {exc}")
            break

    invalidate_task_identity_inventory()
    journal["phase"] = "rollback_incomplete" if errors else "rolled_back"
    journal["rollback_errors"] = errors
    try:
        _write_journal(journal_path, journal)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Unable to persist final rollback state: {exc}")
        journal["phase"] = "rollback_incomplete"
    return errors


def _append_transaction_events(
    workspace_root: Path,
    paths: V2Paths,
    journal_path: Path,
    journal: dict[str, Any],
) -> list[str]:
    from taskledger.services.event_logging import event_logging_enabled
    from taskledger.services.task_events import append_task_event
    from taskledger.storage.events import load_events

    if not event_logging_enabled(workspace_root):
        journal["audit_status"] = "disabled"
        journal["audit_errors"] = []
        _write_journal(journal_path, journal)
        return []

    errors: list[str] = []
    transaction_id = str(journal["transaction_id"])
    try:
        existing = load_events(paths.events_dir)
        existing_actions = {
            event.data.get("action_index")
            for event in existing
            if event.event == _EVENT_NAME
            and event.data.get("transaction_id") == transaction_id
        }
        for index, action in enumerate(journal["actions"]):
            if index in existing_actions:
                continue
            survivor = action.get("survivor")
            append_task_event(
                workspace_root,
                "*",
                _EVENT_NAME,
                {
                    "transaction_id": transaction_id,
                    "action_index": index,
                    "source_kind": action["source_kind"],
                    "source_path": action["source_relative_path"],
                    "legacy_task_id": action.get("legacy_task_id"),
                    "task_uuid": action["task_uuid"],
                    "source_fingerprint": action["source_fingerprint"],
                    "repair_mode": action["repair_mode"],
                    "reason": action["reason"],
                    "quarantined_path": Path(action["quarantine_path"])
                    .relative_to(paths.ledger_dir)
                    .as_posix(),
                    "tombstone_path": Path(action["tombstone_path"])
                    .relative_to(paths.ledger_dir)
                    .as_posix()
                    if isinstance(action.get("tombstone_path"), str)
                    else None,
                    "surviving_task_uuid": (
                        survivor.get("task_uuid")
                        if isinstance(survivor, dict)
                        else None
                    ),
                    "surviving_source_path": (
                        survivor.get("path") if isinstance(survivor, dict) else None
                    ),
                },
            )
            # Re-read after each append so a retry can detect a durable event even
            # if the journal update itself failed.
            existing = load_events(paths.events_dir)
            existing_actions = {
                event.data.get("action_index")
                for event in existing
                if event.event == _EVENT_NAME
                and event.data.get("transaction_id") == transaction_id
            }
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    journal["audit_status"] = "pending" if errors else "complete"
    journal["audit_errors"] = errors
    journal["phase"] = "audit_pending" if errors else "committed"
    try:
        _write_journal(journal_path, journal)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Unable to persist audit completion: {exc}")
        journal["phase"] = "audit_pending"
        journal["audit_status"] = "pending"
    return errors


def _result_from_journal(
    journal_path: Path,
    journal: dict[str, Any],
    *,
    ledger_healthy: bool,
    remaining_conflicts: tuple[dict[str, object], ...],
) -> dict[str, object]:
    actions = journal.get("actions", [])
    repaired = [
        {
            "source_id": action["source_id"],
            "legacy_task_id": action.get("legacy_task_id"),
            "task_uuid": action.get("task_uuid"),
            "repair_mode": action.get("repair_mode"),
            "source_path": action.get("source_path"),
            "quarantined_path": action.get("quarantine_path"),
            "tombstone_path": action.get("tombstone_path"),
            "surviving_task_uuid": (
                action.get("survivor", {}).get("task_uuid")
                if isinstance(action.get("survivor"), dict)
                else None
            ),
            "surviving_source_path": (
                action.get("survivor", {}).get("path")
                if isinstance(action.get("survivor"), dict)
                else None
            ),
        }
        for action in actions
        if isinstance(action, dict) and action.get("status") == "committed"
    ]
    failures = journal.get("rollback_errors", [])
    failed = (
        [{"source_id": None, "error": str(error)} for error in failures]
        if isinstance(failures, list)
        else []
    )
    status = str(journal.get("phase", "failed"))
    if status == "committed":
        status = "applied"
    elif status == "audit_pending":
        status = "audit_pending"
    elif status == "rollback_incomplete":
        status = "rollback_incomplete"
    elif status == "rolled_back":
        status = "rolled_back"
    return {
        "kind": "task_allocation_repair",
        "status": status,
        "dry_run": False,
        "plan_id": journal.get("plan_id"),
        "transaction_id": journal.get("transaction_id"),
        "attempted_count": len(actions),
        "repaired_count": len(repaired),
        "failed_count": len(failed),
        "repaired": repaired,
        "failed": failed,
        "reason": journal.get("reason"),
        "ledger_healthy": ledger_healthy,
        "remaining_conflicts": list(remaining_conflicts),
        "journal_path": str(journal_path),
        "next_commands": [
            "taskledger --json repair allocations --audit",
            "taskledger --json doctor",
        ]
        if status == "applied"
        else [
            f"taskledger repair allocations --recover {journal.get('transaction_id')}",
        ],
    }


def _validate_reviewed_survivor(paths: V2Paths, action: dict[str, Any]) -> None:
    survivor = action.get("survivor")
    if not isinstance(survivor, dict):
        return
    survivor_path = paths.ledger_dir / str(survivor.get("path", ""))
    _ensure_ledger_path(paths, survivor_path, must_exist=True)
    if _fingerprint(survivor_path) != survivor.get("source_fingerprint"):
        raise LaunchError(
            "The reviewed allocation owner changed before apply.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
            details={"survivor_path": str(survivor_path)},
        )


def apply_allocation_repair_batch(
    workspace_root: Path,
    paths: V2Paths,
    allocations: tuple[IncompleteTaskAllocation, ...],
    entries: list[dict[str, object]],
    *,
    plan_id: str,
    reason: str,
    scope: str,
) -> dict[str, object]:
    """Apply the reviewed selection as one journaled filesystem transaction."""
    from taskledger.services.task_events import default_actor, default_harness
    from taskledger.storage.task_identity import (
        identity_mutation_lock,
        inspect_task_identity_conflicts,
        invalidate_task_identity_inventory,
        scan_task_identity_inventory,
    )

    if len(allocations) != len(entries):
        raise LaunchError("Allocation repair plan changed; inspect a fresh dry-run.")
    with identity_mutation_lock(paths):
        transaction_id = str(uuid4())
        actions: list[dict[str, Any]] = []
        destinations: set[str] = set()
        for allocation, entry in zip(allocations, entries, strict=True):
            if not bool(entry.get("apply_safe")):
                raise LaunchError(
                    f"Allocation identity conflict blocks repair: {allocation.path}",
                    code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                    details={"source_path": str(allocation.path)},
                )
            action = _plan_action(
                paths,
                allocation,
                entry,
                transaction_id=transaction_id,
                reason=reason,
            )
            for key in ("quarantine_path", "tombstone_path"):
                value = action.get(key)
                if not isinstance(value, str):
                    continue
                if value in destinations:
                    raise LaunchError(
                        f"Allocation repair actions share a destination: {value}",
                        code="TASKLEDGER_REPAIR_PATH_UNSAFE",
                    )
                destinations.add(value)
            _validate_reviewed_survivor(paths, action)
            actions.append(action)

        _assert_unprotected(paths, actions)
        before_conflicts = inspect_task_identity_conflicts(paths)
        txn_dir = (
            paths.ledger_dir
            / "_recovery"
            / "allocation-repair-transactions"
            / transaction_id
        )
        _ensure_ledger_path(paths, txn_dir, must_exist=False)
        txn_dir.mkdir(parents=True, exist_ok=False)
        journal_path = txn_dir / "journal.json"
        journal: dict[str, Any] = {
            "schema_version": _JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "scope": scope,
            "phase": "prepared",
            "audit_status": "pending",
            "reason": reason.strip(),
            "actor": default_actor().to_dict(),
            "harness": default_harness().to_dict(),
            "actions": actions,
            "created_at": utc_now_iso(),
        }
        _write_journal(journal_path, journal)

        try:
            journal["phase"] = "staging"
            _write_journal(journal_path, journal)
            for action in actions:
                source = Path(action["source_path"])
                quarantine = Path(action["quarantine_path"])
                _ensure_ledger_path(paths, source, must_exist=True)
                _ensure_ledger_path(paths, quarantine, must_exist=False)
                if _fingerprint(source) != action["source_fingerprint"]:
                    raise LaunchError(
                        f"Allocation source changed before move: {source}",
                        code="TASKLEDGER_REPAIR_PLAN_CHANGED",
                    )
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                source.rename(quarantine)
                action["moved"] = True
                action["status"] = "moved"
                _write_journal(journal_path, journal)
                if action["repair_mode"] == "quarantine_and_tombstone":
                    if action["tombstone_kind"] == "legacy":
                        from taskledger.storage.task_ids import write_task_id_tombstone

                        tombstone = write_task_id_tombstone(
                            paths,
                            str(action["tombstone_identity"]),
                            reason=reason,
                            quarantined_path=quarantine,
                            transaction_id=transaction_id,
                        )
                    else:
                        from taskledger.storage.task_identity import (
                            write_task_identity_tombstone,
                        )

                        tombstone = write_task_identity_tombstone(
                            paths,
                            str(action["tombstone_identity"]),
                            reason=reason,
                            quarantined_path=quarantine.relative_to(
                                paths.ledger_dir
                            ).as_posix(),
                            transaction_id=transaction_id,
                        )
                    if tombstone != Path(str(action["tombstone_path"])):
                        raise LaunchError(
                            "Written tombstone differs from reviewed destination."
                        )
                    action["tombstone_created"] = True
                    action["status"] = "staged"
                    _write_journal(journal_path, journal)
                _verify_local_action(paths, action)
                action["status"] = "verified"
                _write_journal(journal_path, journal)

            invalidate_task_identity_inventory()
            strict_error: str | None = None
            try:
                scan_task_identity_inventory(paths)
            except LaunchError as exc:
                strict_error = str(exc)
            after_conflicts = inspect_task_identity_conflicts(paths)
            expected_conflicts = _remaining_conflicts(before_conflicts, actions)
            if _conflict_signature(after_conflicts) != _conflict_signature(
                expected_conflicts
            ):
                raise LaunchError(
                    "Allocation batch produced an unexpected identity-conflict state.",
                    code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                    details={"remaining_conflicts": list(after_conflicts)},
                )
            if strict_error is not None and not expected_conflicts:
                raise LaunchError(
                    f"Final task identity validation failed: {strict_error}",
                    code="TASKLEDGER_TASK_IDENTITY_CONFLICT",
                )
            for action in actions:
                _verify_local_action(paths, action)
                action["status"] = "committed"
            journal["phase"] = "committed"
            journal["ledger_healthy"] = strict_error is None
            journal["remaining_conflicts"] = list(after_conflicts)
            journal["strict_scan_error"] = strict_error
            _write_journal(journal_path, journal)
        except Exception as exc:  # noqa: BLE001
            journal["failure"] = str(exc)
            rollback_errors = _rollback_transaction(paths, journal_path, journal)
            remaining = inspect_task_identity_conflicts(paths)
            result = _result_from_journal(
                journal_path,
                journal,
                ledger_healthy=False,
                remaining_conflicts=remaining,
            )
            failed_items: list[object] = [{"source_id": None, "error": str(exc)}]
            prior_failed = result.get("failed", [])
            if isinstance(prior_failed, list):
                failed_items.extend(prior_failed)
            result["failed"] = failed_items
            result["failed_count"] = len(failed_items)
            result["status"] = (
                "rollback_incomplete" if rollback_errors else "rolled_back"
            )
            result["next_commands"] = [
                f"taskledger repair allocations --recover {transaction_id}"
            ]
            return result

        try:
            audit_errors = _append_transaction_events(
                workspace_root, paths, journal_path, journal
            )
        except Exception as exc:  # noqa: BLE001
            audit_errors = [str(exc)]
            journal["audit_status"] = "pending"
            journal["audit_errors"] = audit_errors
            journal["phase"] = "audit_pending"
            try:
                _write_journal(journal_path, journal)
            except Exception as journal_exc:  # noqa: BLE001
                audit_errors.append(
                    f"Unable to persist audit-pending state: {journal_exc}"
                )
        return _result_from_journal(
            journal_path,
            journal,
            ledger_healthy=bool(journal.get("ledger_healthy")),
            remaining_conflicts=tuple(journal.get("remaining_conflicts", [])),
        ) | ({"audit_errors": audit_errors} if audit_errors else {})


def list_allocation_repair_transactions(paths: V2Paths) -> dict[str, object]:
    txn_root = paths.ledger_dir / "_recovery" / "allocation-repair-transactions"
    transactions: list[dict[str, object]] = []
    if txn_root.exists():
        if txn_root.is_symlink() or not txn_root.is_dir():
            raise LaunchError(f"Invalid allocation repair transaction path: {txn_root}")
        for journal_path in sorted(txn_root.glob("*/journal.json")):
            journal = _load_journal(journal_path)
            transactions.append(
                {
                    "transaction_id": journal["transaction_id"],
                    "phase": journal.get("phase"),
                    "plan_id": journal.get("plan_id"),
                    "journal_path": str(journal_path),
                    "action_count": len(journal.get("actions", [])),
                    "audit_status": journal.get("audit_status"),
                    "errors": journal.get(
                        "rollback_errors", journal.get("audit_errors", [])
                    ),
                }
            )
    return {"kind": "allocation_repair_transactions", "transactions": transactions}


def _plan_identity_conflict_transaction_recovery(
    paths: V2Paths,
    transaction_id: str,
    journal_path: Path,
    journal: dict[str, Any],
) -> dict[str, object]:
    phase = str(journal.get("phase"))
    action = (
        "rollback"
        if phase in {"prepared", "staging", "rollback_incomplete"}
        else "replay_audit"
        if phase == "audit_pending"
        else "none"
    )
    observations: list[dict[str, object]] = []
    for item in journal["actions"]:
        if not isinstance(item, dict):
            raise LaunchError(
                "Invalid identity conflict action in transaction journal."
            )
        observed: dict[str, object] = {
            "legacy_task_id": item.get("legacy_task_id"),
            "status": item.get("status"),
        }
        owner = item.get("surviving_identity")
        owner_path = (
            paths.ledger_dir / str(owner.get("path"))
            if isinstance(owner, dict) and isinstance(owner.get("path"), str)
            else None
        )
        values = {
            "tombstone_path": item.get("tombstone_path"),
            "preserved_tombstone": item.get("preserved_tombstone"),
            "quarantined_path": item.get("quarantined_path"),
            "new_tombstone": item.get("new_tombstone"),
            "surviving_owner": str(owner_path) if owner_path is not None else None,
        }
        for key, value in values.items():
            if not isinstance(value, str):
                continue
            path = Path(value)
            _ensure_ledger_path(paths, path, must_exist=None)
            if path.is_dir():
                observed[key] = _fingerprint(path)
            elif path.is_file():
                observed[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                observed[key] = None
        observations.append(observed)
    state_fingerprint = hashlib.sha256(
        json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    journal_fingerprint = hashlib.sha256(journal_path.read_bytes()).hexdigest()
    recovery_plan_id = hashlib.sha256(
        f"{transaction_id}\\0{phase}\\0{journal_fingerprint}\\0"
        f"{state_fingerprint}\\0{action}".encode()
    ).hexdigest()
    return {
        "kind": "allocation_repair_recovery",
        "transaction_kind": "identity_conflict_repair",
        "transaction_id": transaction_id,
        "phase": phase,
        "action": action,
        "plan_id": recovery_plan_id,
        "state_fingerprint": state_fingerprint,
        "journal_path": str(journal_path),
        "actions": journal.get("actions", []),
        "errors": journal.get("rollback_errors", journal.get("audit_errors", [])),
        "next_command": (
            f"taskledger repair allocations --recover {transaction_id} --apply "
            f'--plan-id {recovery_plan_id} --reason "Recover reviewed '
            'allocation transaction."'
            if action != "none"
            else None
        ),
    }


def plan_allocation_recovery(paths: V2Paths, transaction_id: str) -> dict[str, object]:
    from uuid import UUID

    try:
        parsed_id = UUID(transaction_id)
    except ValueError as exc:
        raise LaunchError("Invalid allocation repair transaction ID.") from exc
    if str(parsed_id) != transaction_id:
        raise LaunchError("Allocation repair transaction ID is not canonical.")
    journal_path = (
        paths.ledger_dir
        / "_recovery"
        / "allocation-repair-transactions"
        / transaction_id
        / "journal.json"
    )
    _ensure_ledger_path(paths, journal_path, must_exist=True)
    journal = _load_journal(journal_path)
    if journal.get("transaction_id") != transaction_id:
        raise LaunchError(
            "Allocation repair transaction ID does not match its journal."
        )
    if journal.get("transaction_kind") == "identity_conflict_repair":
        return _plan_identity_conflict_transaction_recovery(
            paths, transaction_id, journal_path, journal
        )
    phase = str(journal.get("phase"))
    if phase in {"prepared", "staging", "rollback_incomplete"}:
        action = "rollback"
    elif phase == "audit_pending":
        action = "replay_audit"
    else:
        action = "none"

    observations: list[dict[str, object]] = []
    for item in journal["actions"]:
        if not isinstance(item, dict):
            raise LaunchError(
                "Invalid allocation repair action in transaction journal."
            )
        observed: dict[str, object] = {"source_id": item.get("source_id")}
        for key in ("source_path", "quarantine_path", "tombstone_path"):
            value = item.get(key)
            if not isinstance(value, str):
                continue
            path = Path(value)
            _ensure_ledger_path(paths, path, must_exist=None)
            if path.is_dir():
                observed[key] = _fingerprint(path)
            elif path.is_file():
                observed[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                observed[key] = None
        observations.append(observed)
    state_fingerprint = hashlib.sha256(
        json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    journal_fingerprint = hashlib.sha256(journal_path.read_bytes()).hexdigest()
    plan_id = hashlib.sha256(
        f"{transaction_id}\\0{phase}\\0{journal_fingerprint}\\0"
        f"{state_fingerprint}\\0{action}".encode()
    ).hexdigest()
    return {
        "kind": "allocation_repair_recovery",
        "transaction_id": transaction_id,
        "phase": phase,
        "action": action,
        "plan_id": plan_id,
        "state_fingerprint": state_fingerprint,
        "journal_path": str(journal_path),
        "actions": journal.get("actions", []),
        "errors": journal.get("rollback_errors", journal.get("audit_errors", [])),
        "next_command": (
            f"taskledger repair allocations --recover {transaction_id} --apply "
            f'--plan-id {plan_id} --reason "Recover reviewed '
            'allocation transaction."'
            if action != "none"
            else None
        ),
    }


def recover_allocation_repair_transaction(
    workspace_root: Path,
    paths: V2Paths,
    transaction_id: str,
    *,
    apply: bool,
    plan_id: str | None,
    reason: str,
) -> dict[str, object]:
    from taskledger.storage.task_identity import (
        identity_mutation_lock,
        invalidate_task_identity_inventory,
    )

    planned = plan_allocation_recovery(paths, transaction_id)
    if not apply:
        return {**planned, "dry_run": True, "status": "dry_run"}
    if not plan_id or plan_id != planned["plan_id"]:
        raise LaunchError(
            "Allocation transaction recovery plan changed; "
            "inspect a fresh recovery plan.",
            code="TASKLEDGER_REPAIR_PLAN_CHANGED",
        )
    if not reason.strip():
        raise LaunchError("Allocation transaction recovery requires --reason.")

    journal_path = Path(str(planned["journal_path"]))
    with identity_mutation_lock(paths):
        current = plan_allocation_recovery(paths, transaction_id)
        if current["plan_id"] != plan_id:
            raise LaunchError(
                "Allocation transaction changed after recovery review.",
                code="TASKLEDGER_REPAIR_PLAN_CHANGED",
            )
        journal = _load_journal(journal_path)
        if planned["action"] == "rollback":
            if planned.get("transaction_kind") == "identity_conflict_repair":
                errors = _rollback_identity_conflict_transaction(
                    paths, journal_path, journal
                )
            else:
                errors = _rollback_transaction(paths, journal_path, journal)
            return {
                **planned,
                "dry_run": False,
                "status": "rollback_incomplete" if errors else "rolled_back",
                "errors": errors,
                "reason": reason.strip(),
            }
        if planned["action"] == "replay_audit":
            journal["recovery_reason"] = reason.strip()
            if planned.get("transaction_kind") == "identity_conflict_repair":
                audit_errors = _append_identity_conflict_events(
                    workspace_root, paths, journal_path, journal
                )
            else:
                audit_errors = _append_transaction_events(
                    workspace_root, paths, journal_path, journal
                )
            invalidate_task_identity_inventory()
            return {
                **planned,
                "dry_run": False,
                "status": "audit_pending" if audit_errors else "committed",
                "errors": audit_errors,
                "reason": reason.strip(),
            }
        return {**planned, "dry_run": False, "status": "nothing_to_recover"}

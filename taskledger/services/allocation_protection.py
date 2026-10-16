"""Protection checks for physical allocation quarantine sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from taskledger.domain.models import ActiveTaskState, TaskRunRecord
from taskledger.storage.task_store import V2Paths, list_physical_runs_from_paths


def inspect_allocation_protection(
    paths: V2Paths, actions: list[dict[str, Any]]
) -> list[dict[str, object]]:
    """Collect active pointers, locks, and physical running runs blocking repair."""
    from taskledger.services.lock_inventory import build_lock_inventory
    from taskledger.storage.yaml_store import load_yaml_object

    if not actions:
        return []

    blockers: list[dict[str, object]] = []
    if paths.active_task_path.exists():
        try:
            active_state = ActiveTaskState.from_dict(
                load_yaml_object(paths.active_task_path, "active task state")
            )
        except Exception as exc:  # noqa: BLE001
            blockers.append(
                {
                    "kind": "inspection_error",
                    "scope": "active_task_state",
                    "active_task_path": str(paths.active_task_path),
                    "error": str(exc),
                }
            )
        else:
            for action in actions:
                source_path = Path(str(action["source_path"]))
                uuid_match = active_state.task_uuid == action["task_uuid"]
                id_match = (
                    active_state.task_id == action["source_id"]
                    or active_state.task_id == source_path.name
                )
                if uuid_match or (active_state.task_uuid is None and id_match):
                    blockers.append(
                        {
                            "kind": "active_task_pointer",
                            "source_id": action["source_id"],
                            "active_task_id": active_state.task_id,
                            "active_task_uuid": active_state.task_uuid,
                            "active_task_path": str(paths.active_task_path),
                        }
                    )

    try:
        inventory = build_lock_inventory(paths)
        physical_runs: list[tuple[Path, TaskRunRecord]] = []
        for task_dir in sorted(paths.tasks_dir.iterdir()):
            physical_runs.extend(
                (task_dir, run)
                for run in list_physical_runs_from_paths(paths, task_dir)
            )
    except Exception as exc:  # noqa: BLE001
        blockers.append(
            {
                "kind": "inspection_error",
                "scope": "lock_run_inventory",
                "error": str(exc),
            }
        )
        return blockers

    for action in actions:
        source_path = Path(str(action["source_path"]))
        source_id = action["source_id"]
        identifiers = {
            str(source_id),
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
                blockers.append(
                    {
                        "kind": "task_lock",
                        "source_id": source_id,
                        "lock": lock_entry.to_dict(),
                    }
                )
        for physical_task_dir, run in physical_runs:
            if run.status == "running" and physical_task_dir == source_path:
                blockers.append(
                    {
                        "kind": "running_run",
                        "source_id": source_id,
                        "run_id": run.run_id,
                        "run_task_id": run.task_id,
                        "physical_task_directory": str(physical_task_dir),
                    }
                )
    return blockers

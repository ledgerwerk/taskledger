from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.api.repair import repair_allocations, repair_locks
from taskledger.errors import LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.task_lifecycle import activate_task, deactivate_task
from taskledger.services.tasks import create_task, start_planning
from taskledger.storage.events import load_events
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.locks import read_lock
from taskledger.storage.sidecar_index import load_sidecar_index
from taskledger.storage.task_identity import task_identity_inventory
from taskledger.storage.task_store import (
    load_active_task_state,
    resolve_v2_paths,
    task_lock_path,
    task_markdown_path,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_canonical_project_state(workspace, create_sibling_store=True)
    return workspace


def test_recovery_repairs_dangling_active_task_orphan_lock_and_partial_allocation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    task = create_task(
        workspace, title="Interrupted task", description="", slug="interrupted"
    )
    activate_task(workspace, task.id, reason="test setup")
    start_planning(workspace, task.id)
    paths = resolve_v2_paths(workspace)
    lock_path = task_lock_path(paths, task.id)
    assert read_lock(lock_path) is not None

    task_markdown_path(paths, task.id).unlink()

    doctor = inspect_v2_project(workspace)
    assert doctor["healthy"] is False
    assert any(task.id in error for error in doctor["errors"])
    incomplete = doctor["incomplete_task_allocations"]
    assert isinstance(incomplete, list)
    assert incomplete[0]["task_id"] == task.id

    lock_dry_run = repair_locks(workspace)
    assert lock_dry_run["dry_run"] is True
    lock_entries = lock_dry_run["entries"]
    assert isinstance(lock_entries, list)
    assert lock_entries[0]["classification"] == "orphan_missing_task"

    with pytest.raises(LaunchError):
        deactivate_task(workspace, reason="", force=True)
    cleared = deactivate_task(
        workspace, reason="Clear dangling active task after record loss.", force=True
    )
    assert cleared["active"] is False
    assert load_active_task_state(workspace) is None
    events = load_events(paths.events_dir)
    assert any(
        event.event == "repair.active_task_cleared" and event.task_id == task.id
        for event in events
    )
    assert read_lock(lock_path) is not None

    lock_repair = repair_locks(
        workspace,
        apply=True,
        reason="Preserve and remove the orphaned runtime lock.",
    )
    assert lock_repair["orphan_missing_task_repaired"] == [task.id]
    assert read_lock(lock_path) is None
    sidecar_index = load_sidecar_index(paths)
    assert sidecar_index[task.task_uuid]["locks"]["has_lock"] is False
    recovery_locks = paths.ledger_dir / "recovery" / "orphan-locks" / task.id
    audit_files = list(recovery_locks.glob("broken-lock-*.yaml"))
    assert len(audit_files) == 1
    events = load_events(paths.events_dir)
    assert any(event.event == "repair.orphan_lock_broken" for event in events)

    allocation_dry_run = repair_allocations(workspace)
    assert allocation_dry_run["dry_run"] is True
    allocation_entries = allocation_dry_run["incomplete_allocations"]
    assert isinstance(allocation_entries, list)
    assert allocation_entries[0]["task_id"] == task.id
    assert any(
        str(identity.task_uuid) == task.task_uuid and identity.state == "incomplete"
        for identity in task_identity_inventory(paths).entries
    )

    allocation_repair = repair_allocations(
        workspace,
        apply=True,
        reason="Quarantine incomplete task data without reusing its ID.",
    )
    repaired = allocation_repair["repaired"]
    assert isinstance(repaired, list)
    assert repaired[0]["task_id"] == task.id
    quarantined = Path(repaired[0]["quarantined_path"])
    assert (quarantined / "runs").is_dir()
    assert not (paths.tasks_dir / task.task_uuid).exists()
    assert (paths.ledger_dir / "tombstones" / f"{task.task_uuid}.toml").is_file()
    tombstone = next(
        identity
        for identity in task_identity_inventory(paths).entries
        if str(identity.task_uuid) == task.task_uuid
    )
    assert tombstone.state == "tombstone"
    assert tombstone.task_id == task.id
    events = load_events(paths.events_dir)
    assert any(event.event == "repair.task_allocation_quarantined" for event in events)

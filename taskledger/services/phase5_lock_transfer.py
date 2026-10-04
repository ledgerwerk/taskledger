"""Lock transfer operations for handoff."""

from __future__ import annotations

from pathlib import Path

from taskledger.domain.models import ActorRef, HarnessRef, TaskLock
from taskledger.errors import LaunchError
from taskledger.storage.task_store import resolve_lock, save_lock
from taskledger.timeutils import utc_now_iso


def transfer_lock(
    workspace_root: Path,
    task_id: str,
    lock_id: str,
    to_actor: ActorRef,
    to_harness: HarnessRef,
) -> TaskLock:
    """Transfer a lock from current holder to new actor."""
    lock = resolve_lock(workspace_root, task_id)

    if lock is None:
        raise LaunchError(f"Lock not found for task: {task_id}")

    if lock.lock_id != lock_id:
        raise LaunchError(f"Lock ID mismatch: expected {lock_id}, got {lock.lock_id}")

    # Record transfer in history
    from_actor_str = f"{lock.holder.actor_type}:{lock.holder.actor_name}"
    to_actor_str = f"{to_actor.actor_type}:{to_actor.actor_name}"

    new_entry = (lock_id, from_actor_str, to_actor_str)
    new_history = lock.transfer_history + (new_entry,)

    updated = TaskLock(
        lock_id=lock.lock_id,
        task_id=lock.task_id,
        task_uuid=lock.task_uuid,
        stage=lock.stage,
        run_id=lock.run_id,
        created_at=lock.created_at,
        expires_at=lock.expires_at,
        reason=lock.reason,
        holder=to_actor,
        lease_seconds=lock.lease_seconds,
        last_heartbeat_at=lock.last_heartbeat_at,
        broken_at=lock.broken_at,
        broken_by=lock.broken_by,
        broken_reason=lock.broken_reason,
        actor=to_actor,
        harness=to_harness,
        transfer_history=new_history,
        transfer_date=utc_now_iso(),
    )

    save_lock(workspace_root, task_id, updated)
    return updated


def release_lock(
    workspace_root: Path,
    task_id: str,
    lock_id: str,
) -> TaskLock:
    """Release a lock, preparing it for transfer or removal."""
    lock = resolve_lock(workspace_root, task_id)

    if lock is None:
        raise LaunchError(f"Lock not found for task: {task_id}")

    if lock.lock_id != lock_id:
        raise LaunchError(f"Lock ID mismatch: expected {lock_id}, got {lock.lock_id}")

    # Record the release time in transfer_date
    updated = TaskLock(
        lock_id=lock.lock_id,
        task_id=lock.task_id,
        task_uuid=lock.task_uuid,
        stage=lock.stage,
        run_id=lock.run_id,
        created_at=lock.created_at,
        expires_at=lock.expires_at,
        reason=lock.reason,
        holder=lock.holder,
        lease_seconds=lock.lease_seconds,
        last_heartbeat_at=lock.last_heartbeat_at,
        broken_at=lock.broken_at,
        broken_by=lock.broken_by,
        broken_reason=lock.broken_reason,
        actor=lock.actor,
        harness=lock.harness,
        transfer_history=lock.transfer_history,
        transfer_date=utc_now_iso(),
    )

    save_lock(workspace_root, task_id, updated)
    return updated

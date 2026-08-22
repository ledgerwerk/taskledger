"""Handoff lifecycle operations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from taskledger.domain.models import ActorRef, HarnessRef, TaskHandoffRecord
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_effective_identity
from taskledger.storage.task_store import (
    resolve_handoff,
    resolve_lock,
    resolve_task,
    save_handoff,
)
from taskledger.timeutils import utc_now_iso


def claim_handoff(
    workspace_root: Path,
    task_id: str,
    handoff_id: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    new_run_id: str | None = None,
) -> TaskHandoffRecord:
    """Claim a handoff, transitioning from 'open' to 'claimed'."""
    handoff = resolve_handoff(workspace_root, task_id, handoff_id)
    resolved_actor, resolved_harness = resolve_effective_identity(
        workspace_root, actor=actor, harness=harness, cwd=workspace_root
    )

    if handoff.status == "claimed":
        same_session = (
            resolved_actor.session_id
            and handoff.claimed_by is not None
            and handoff.claimed_by.actor_type == resolved_actor.actor_type
            and handoff.claimed_by.actor_name == resolved_actor.actor_name
            and handoff.claimed_by.session_id == resolved_actor.session_id
            and handoff.claimed_in_harness is not None
            and handoff.claimed_in_harness.name == resolved_harness.name
            and handoff.claimed_in_harness.session_id == resolved_harness.session_id
        )
        if same_session:
            return handoff
    if handoff.status != "open":
        owner = handoff.claimed_by.actor_name if handoff.claimed_by else "unknown"
        harness_name = (
            handoff.claimed_in_harness.name if handoff.claimed_in_harness else "unknown"
        )
        session = (
            handoff.claimed_in_harness.session_id
            if handoff.claimed_in_harness
            else "unknown"
        )
        raise LaunchError(
            f"Cannot claim {handoff.handoff_id}: it is already claimed by {owner}; "
            f"harness: {harness_name}; session: {session}. "
            "If this is the same session, the claim is already active. "
            "If that reviewer stopped, release it with an authorized: "
            f'taskledger handoff release {handoff.handoff_id} --reason "..."'
        )

    # Check intent match if specified
    if (
        handoff.intended_actor_type
        and handoff.intended_actor_type != resolved_actor.actor_type
    ):
        raise LaunchError(
            f"Actor type mismatch: handoff intended for {handoff.intended_actor_type}, "
            f"but claiming as {resolved_actor.actor_type}"
        )
    if (
        handoff.intended_actor_name
        and handoff.intended_actor_name != resolved_actor.actor_name
    ):
        raise LaunchError(
            f"Actor name mismatch: handoff intended for {handoff.intended_actor_name}, "
            f"but claiming as {resolved_actor.actor_name}"
        )
    if (
        handoff.intended_harness
        and handoff.intended_harness != "any"
        and handoff.intended_harness != resolved_harness.name
    ):
        raise LaunchError(
            f"Harness mismatch: handoff intended for {handoff.intended_harness}, "
            f"but claiming in {resolved_harness.name}"
        )

    # Create new handoff with claim info
    released_lock_id = handoff.released_lock_id
    updated = replace(
        handoff,
        status="claimed",
        claim_run_id=new_run_id,
        released_lock_id=released_lock_id,
        claimed_at=utc_now_iso(),
        claimed_by=resolved_actor,
        claimed_in_harness=resolved_harness,
    )

    # Handle lock transfer if applicable
    if (
        handoff.mode != "review"
        and handoff.lock_policy == "transfer"
        and handoff.source_run_id
    ):
        task = resolve_task(workspace_root, task_id)
        lock = resolve_lock(workspace_root, task.id)
        if lock and lock.run_id == handoff.source_run_id:
            from taskledger.services.phase5_lock_transfer import transfer_lock

            transfer_lock(
                workspace_root, task.id, lock.lock_id, resolved_actor, resolved_harness
            )
            released_lock_id = lock.lock_id
            updated = replace(updated, released_lock_id=released_lock_id)
    elif (
        handoff.mode != "review"
        and handoff.lock_policy == "release"
        and handoff.source_run_id
    ):
        task = resolve_task(workspace_root, task_id)
        lock = resolve_lock(workspace_root, task.id)
        if lock and lock.run_id == handoff.source_run_id:
            from taskledger.services.phase5_lock_transfer import release_lock

            release_lock(workspace_root, task.id, lock.lock_id)
            released_lock_id = lock.lock_id
            updated = replace(updated, released_lock_id=released_lock_id)

    save_handoff(workspace_root, updated)
    return updated


def close_handoff(
    workspace_root: Path,
    task_id: str,
    handoff_id: str,
    *,
    actor: ActorRef | None = None,
    reason: str | None = None,
) -> TaskHandoffRecord:
    """Close a handoff, transitioning from 'claimed' to 'closed'."""
    handoff = resolve_handoff(workspace_root, task_id, handoff_id)

    if handoff.status not in ("open", "claimed"):
        raise LaunchError(f"Cannot close handoff in status {handoff.status}")

    resolved_actor, _ = resolve_effective_identity(
        workspace_root, actor=actor, cwd=workspace_root
    )
    _ = resolved_actor  # used for actor resolution side-effect

    updated = replace(
        handoff,
        status="closed",
        summary=reason or handoff.summary,
    )

    save_handoff(workspace_root, updated)
    return updated


def cancel_handoff(
    workspace_root: Path,
    task_id: str,
    handoff_id: str,
    *,
    actor: ActorRef | None = None,
    reason: str | None = None,
) -> TaskHandoffRecord:
    """Cancel a handoff, transitioning from 'open' to 'cancelled'."""
    handoff = resolve_handoff(workspace_root, task_id, handoff_id)

    if handoff.status != "open":
        raise LaunchError(f"Cannot cancel handoff in status {handoff.status}")

    resolved_actor, _ = resolve_effective_identity(
        workspace_root, actor=actor, cwd=workspace_root
    )
    _ = resolved_actor  # used for actor resolution side-effect

    updated = replace(
        handoff,
        status="cancelled",
        summary=reason or handoff.summary,
    )

    save_handoff(workspace_root, updated)
    return updated


def release_handoff(
    workspace_root: Path,
    task_id: str,
    handoff_id: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    reason: str,
) -> TaskHandoffRecord:
    """Release a claimed handoff back to open with audit metadata."""
    handoff = resolve_handoff(workspace_root, task_id, handoff_id)
    if handoff.status != "claimed":
        raise LaunchError(f"Cannot release handoff in status {handoff.status}")
    resolved_actor, resolved_harness = resolve_effective_identity(
        workspace_root, actor=actor, harness=harness, cwd=workspace_root
    )
    same_session = (
        resolved_actor.session_id
        and handoff.claimed_by is not None
        and handoff.claimed_by.actor_type == resolved_actor.actor_type
        and handoff.claimed_by.actor_name == resolved_actor.actor_name
        and handoff.claimed_by.session_id == resolved_actor.session_id
        and handoff.claimed_in_harness is not None
        and handoff.claimed_in_harness.name == resolved_harness.name
        and handoff.claimed_in_harness.session_id == resolved_harness.session_id
    )
    authorized_operator = (
        resolved_actor.actor_type == "user" or resolved_actor.role == "operator"
    )
    if not same_session and not authorized_operator:
        raise LaunchError(
            f"Only the claiming session or a user/operator may release {handoff.handoff_id}."  # noqa: E501
        )
    updated = replace(
        handoff,
        status="open",
        released_at=utc_now_iso(),
        released_by=resolved_actor,
        released_in_harness=resolved_harness,
        release_reason=reason,
    )
    save_handoff(workspace_root, updated)
    from taskledger.services.tasks import _append_event

    _append_event(
        workspace_root,
        task_id,
        "handoff.released",
        {
            "handoff_id": handoff.handoff_id,
            "reason": reason,
            "released_by": resolved_actor.to_dict(),
            "released_in_harness": resolved_harness.to_dict(),
        },
    )
    return updated


def retarget_handoff(
    workspace_root: Path,
    task_id: str,
    handoff_id: str,
    *,
    intended_harness: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    reason: str,
) -> TaskHandoffRecord:
    """Retarget an open handoff without changing its frozen context."""
    handoff = resolve_handoff(workspace_root, task_id, handoff_id)
    if handoff.status != "open":
        raise LaunchError(
            f"Cannot retarget handoff in status {handoff.status}; release it first."
        )
    if not intended_harness.strip():
        raise LaunchError("Intended harness must not be empty.")
    resolved_actor, resolved_harness = resolve_effective_identity(
        workspace_root, actor=actor, harness=harness, cwd=workspace_root
    )
    updated = replace(
        handoff,
        intended_harness=intended_harness.strip(),
        retargeted_at=utc_now_iso(),
        retargeted_by=resolved_actor,
        retargeted_in_harness=resolved_harness,
        retarget_reason=reason,
    )
    save_handoff(workspace_root, updated)
    from taskledger.services.tasks import _append_event

    _append_event(
        workspace_root,
        task_id,
        "handoff.retargeted",
        {
            "handoff_id": handoff.handoff_id,
            "intended_harness": updated.intended_harness,
            "reason": reason,
            "retargeted_by": resolved_actor.to_dict(),
        },
    )
    return updated

from pathlib import Path
from typing import cast

from taskledger.domain.models import ActorRef, HarnessRef, TaskHandoffRecord
from taskledger.domain.states import (
    ContextFor,
    ContextScope,
    HandoffMode,
    normalize_actor_type,
)
from taskledger.errors import LaunchError
from taskledger.services.handoff import (
    build_handoff_payload,
    render_handoff,
    render_markdown_handoff,
)
from taskledger.storage.task_store import (
    handoff_markdown_path,
    list_handoffs,
    resolve_handoff,
    resolve_task,
    resolve_v2_paths,
    save_handoff,
)


def _snapshot_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def create_handoff(
    workspace_root: Path,
    task_ref: str,
    *,
    mode: str | None = None,
    context_for: str | None = None,
    worker_step_id: str | None = None,
    scope: str | None = None,
    todo_id: str | None = None,
    focus_run_id: str | None = None,
    intended_actor_type: str | None = None,
    intended_actor_name: str | None = None,
    intended_harness: str | None = None,
    summary: str | None = None,
    next_action: str | None = None,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    """Create and save a handoff record."""
    from taskledger.ids import next_project_id
    from taskledger.services.actors import resolve_effective_identity
    from taskledger.timeutils import utc_now_iso

    task = resolve_task(workspace_root, task_ref)
    resolved_actor, resolved_harness = resolve_effective_identity(
        workspace_root, actor=actor, harness=harness, cwd=workspace_root
    )
    if mode is None and worker_step_id is None:
        raise LaunchError("Handoff creation requires --mode or --worker.")
    payload = build_handoff_payload(
        workspace_root,
        task.id,
        mode=mode,
        context_for=context_for,
        worker_step_id=worker_step_id,
        scope=scope,
        todo_id=todo_id,
        focus_run_id=focus_run_id,
        format_name="markdown",
    )
    context_body = render_markdown_handoff(payload)
    from taskledger.storage.common import content_hash as lc_content_hash

    context_hash = f"sha256:{lc_content_hash(context_body)}"
    snapshot_metadata: dict[str, object] = {}
    if str(payload.get("mode")) == "review":
        try:
            from taskledger.services.code_review import _collect_working_tree_metadata

            snapshot_metadata = _collect_working_tree_metadata(workspace_root)
        except LaunchError:
            snapshot_metadata = {}
    existing_handoffs = list_handoffs(workspace_root, task.id)
    existing_ids = [h.handoff_id for h in existing_handoffs]
    resolved_mode = cast(HandoffMode, str(payload["mode"]))
    resolved_context_for = payload.get("context_for")
    resolved_scope = cast(ContextScope, str(payload["scope"]))
    resolved_context = cast(
        ContextFor | None,
        resolved_context_for if isinstance(resolved_context_for, str) else None,
    )

    handoff_id = next_project_id("handoff", existing_ids)
    handoff = TaskHandoffRecord(
        handoff_id=handoff_id,
        task_id=task.id,
        mode=resolved_mode,
        context_for=resolved_context,
        worker_step_id=worker_step_id,
        scope=resolved_scope,
        todo_id=todo_id,
        focus_run_id=focus_run_id,
        context_format="markdown",
        context_hash=context_hash,
        generated_at=utc_now_iso(),
        status="open",
        lock_policy="retain" if resolved_mode == "review" else "none",
        created_by=resolved_actor,
        created_from_harness=resolved_harness,
        intended_actor_type=(
            normalize_actor_type(intended_actor_type) if intended_actor_type else None
        ),
        intended_actor_name=intended_actor_name,
        intended_harness=intended_harness,
        summary=summary,
        next_action=(
            next_action
            or (
                f"Review implementation run {focus_run_id} using {resolved_context or 'reviewer'}. "  # noqa: E501
                f"Record the review with --handoff {handoff_id} and close the handoff."
                if resolved_mode == "review" and focus_run_id
                else None
            )
        ),
        context_body=context_body,
        git_head=_snapshot_string(snapshot_metadata, "git_head"),
        git_branch=_snapshot_string(snapshot_metadata, "git_branch"),
        git_status_short=_snapshot_string(snapshot_metadata, "git_status_short"),
        git_diff_hash=_snapshot_string(snapshot_metadata, "git_diff_hash"),
    )
    path = save_handoff(workspace_root, handoff)
    result = handoff.to_dict()
    result.pop("context_body", None)
    try:
        result["context_path"] = str(path.relative_to(workspace_root))
    except ValueError:
        result["context_path"] = str(path)
    return result


def list_all_handoffs(workspace_root: Path, task_ref: str) -> list[dict[str, object]]:
    """List all handoffs for a task."""
    task = resolve_task(workspace_root, task_ref)
    handoffs = list_handoffs(workspace_root, task.id)
    return [h.to_dict() for h in handoffs]


def show_handoff(
    workspace_root: Path,
    task_ref: str,
    handoff_ref: str,
    *,
    format_name: str = "text",
) -> str | dict[str, object]:
    """Get a specific handoff."""
    task = resolve_task(workspace_root, task_ref)
    handoff = resolve_handoff(workspace_root, task.id, handoff_ref)
    path = handoff_markdown_path(
        resolve_v2_paths(workspace_root), task.id, handoff.handoff_id
    )
    context_path: str
    try:
        context_path = str(path.relative_to(workspace_root))
    except ValueError:
        context_path = str(path)
    if format_name == "markdown":
        if handoff.context_body.strip():
            body = handoff.context_body
            return body if body.endswith("\n") else body + "\n"
        return cast(
            str,
            render_handoff(
                workspace_root,
                task.id,
                mode=handoff.mode,
                context_for=handoff.context_for,
                worker_step_id=handoff.worker_step_id,
                scope=handoff.scope,
                todo_id=handoff.todo_id,
                focus_run_id=handoff.focus_run_id,
                format_name="markdown",
            ),
        )
    payload = handoff.to_dict()
    payload["context_path"] = context_path
    if format_name == "json":
        return payload
    if format_name != "text":
        raise LaunchError(f"Unsupported handoff format: {format_name}")
    lines = [
        f"Handoff {handoff.handoff_id}",
        f"mode: {handoff.mode}",
        f"context_for: {handoff.context_for or 'none'}",
        f"scope: {handoff.scope}",
        f"status: {handoff.status}",
        f"context_path: {context_path}",
        f"context_hash: {handoff.context_hash or 'none'}",
    ]
    if handoff.worker_step_id:
        lines.append(f"worker_step_id: {handoff.worker_step_id}")
    if handoff.todo_id:
        lines.append(f"todo_id: {handoff.todo_id}")
    if handoff.focus_run_id:
        lines.append(f"focus_run_id: {handoff.focus_run_id}")
    return "\n".join(lines)


def claim_handoff_api(
    workspace_root: Path,
    task_ref: str,
    handoff_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    new_run_id: str | None = None,
) -> dict[str, object]:
    """Claim a handoff, transitioning from 'open' to 'claimed'."""
    from taskledger.services.handoff_lifecycle import claim_handoff

    task = resolve_task(workspace_root, task_ref)
    handoff = claim_handoff(
        workspace_root,
        task.id,
        handoff_ref,
        actor=actor,
        harness=harness,
        new_run_id=new_run_id,
    )
    return handoff.to_dict()


def close_handoff_api(
    workspace_root: Path,
    task_ref: str,
    handoff_ref: str,
    *,
    actor: ActorRef | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Close a handoff, transitioning from 'claimed' to 'closed'."""
    from taskledger.services.handoff_lifecycle import close_handoff

    task = resolve_task(workspace_root, task_ref)
    handoff = close_handoff(
        workspace_root,
        task.id,
        handoff_ref,
        actor=actor,
        reason=reason,
    )
    return handoff.to_dict()


def cancel_handoff_api(
    workspace_root: Path,
    task_ref: str,
    handoff_ref: str,
    *,
    actor: ActorRef | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Cancel a handoff, transitioning from 'open' to 'cancelled'."""
    from taskledger.services.handoff_lifecycle import cancel_handoff

    task = resolve_task(workspace_root, task_ref)
    handoff = cancel_handoff(
        workspace_root,
        task.id,
        handoff_ref,
        actor=actor,
        reason=reason,
    )
    return handoff.to_dict()


def release_handoff_api(
    workspace_root: Path,
    task_ref: str,
    handoff_ref: str,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    reason: str,
) -> dict[str, object]:
    from taskledger.services.handoff_lifecycle import release_handoff

    task = resolve_task(workspace_root, task_ref)
    return release_handoff(
        workspace_root,
        task.id,
        handoff_ref,
        actor=actor,
        harness=harness,
        reason=reason,
    ).to_dict()


def retarget_handoff_api(
    workspace_root: Path,
    task_ref: str,
    handoff_ref: str,
    *,
    intended_harness: str,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    reason: str,
) -> dict[str, object]:
    from taskledger.services.handoff_lifecycle import retarget_handoff

    task = resolve_task(workspace_root, task_ref)
    return retarget_handoff(
        workspace_root,
        task.id,
        handoff_ref,
        intended_harness=intended_harness,
        actor=actor,
        harness=harness,
        reason=reason,
    ).to_dict()


def create_review_handoff(
    workspace_root: Path,
    task_ref: str,
    *,
    run_id: str | None = None,
    kind: str = "general",
    intended_actor_type: str = "agent",
    intended_actor_name: str | None = None,
    intended_harness: str | None = None,
    summary: str | None = None,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    from taskledger.storage.task_store import list_runs

    if run_id is None:
        implementation_runs = [
            r
            for r in list_runs(workspace_root, task.id)
            if r.run_type == "implementation"
        ]
        if len(implementation_runs) != 1:
            if not implementation_runs:
                raise LaunchError(
                    "Review handoff requires an implementation run; none exists."
                )
            raise LaunchError(
                "Review handoff requires --run when multiple implementation runs exist."
            )
        run_id = implementation_runs[0].run_id
    context_for = {
        "code": "code-reviewer",
        "spec": "spec-reviewer",
        "general": "reviewer",
    }.get(kind)
    if context_for is None:
        raise LaunchError("Review kind must be code, spec, or general.")
    return create_handoff(
        workspace_root,
        task.id,
        mode="review",
        context_for=context_for,
        focus_run_id=run_id,
        intended_actor_type=intended_actor_type,
        intended_actor_name=intended_actor_name,
        intended_harness=intended_harness,
        summary=summary,
        actor=actor,
        harness=harness,
    )


__all__ = [
    "cancel_handoff_api",
    "create_review_handoff",
    "claim_handoff_api",
    "close_handoff_api",
    "create_handoff",
    "list_all_handoffs",
    "render_handoff",
    "release_handoff_api",
    "retarget_handoff_api",
    "show_handoff",
]

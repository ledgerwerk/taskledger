"""Actor identity CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from taskledger.cli_common import (
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    resolve_workspace_root,
)
from taskledger.domain.models import ActiveActorState, ActiveHarnessState
from taskledger.domain.states import (
    normalize_actor_role,
    normalize_actor_type,
    normalize_harness_kind,
)
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_actor, resolve_harness
from taskledger.storage.task_store import (
    clear_actor_state,
    clear_harness_state,
    save_actor_state,
    save_harness_state,
)

app = typer.Typer(help="Actor identity commands.")
harness_app = typer.Typer(help="Harness identity commands.")


@app.command(name="whoami")
def whoami_cmd(ctx: typer.Context) -> None:
    """Show current actor and harness identity."""
    state = cli_state_from_context(ctx)
    workspace_root = resolve_workspace_root(state.cwd)

    actor = resolve_actor(workspace_root=workspace_root)
    harness = resolve_harness(workspace_root=workspace_root)

    payload = {
        "kind": "taskledger_actor_identity",
        "actor": actor.to_dict(),
        "harness": harness.to_dict(),
    }

    human_lines = [
        f"Actor: {actor.actor_type}:{actor.actor_name}",
    ]
    if actor.role:
        human_lines.append(f"Role: {actor.role}")
    if actor.tool:
        human_lines.append(f"Tool: {actor.tool}")
    if actor.session_id:
        human_lines.append(f"Session: {actor.session_id}")
    human_lines.extend(
        [
            f"Harness: {harness.name} ({harness.kind})",
        ]
    )
    if harness.session_id:
        human_lines.append(f"Harness Session: {harness.session_id}")

    emit_payload(
        ctx,
        payload,
        human="\n".join(human_lines),
        result_type="actor_identity",
    )


@app.command(name="set")
def actor_set_cmd(
    ctx: typer.Context,
    actor_type: Annotated[
        str,
        typer.Option("--type", help="Actor type: agent, user, or system."),
    ],
    actor_name: Annotated[
        str,
        typer.Option("--name", help="Actor name."),
    ],
    role: Annotated[
        str | None,
        typer.Option("--role", help="Actor role."),
    ] = None,
    tool: Annotated[
        str | None,
        typer.Option("--tool", help="Tool name."),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Session identifier."),
    ] = None,
) -> None:
    """Set the stored actor identity."""
    state = cli_state_from_context(ctx)
    workspace_root = resolve_workspace_root(state.cwd)

    normalized_type = normalize_actor_type(actor_type)
    normalized_role = normalize_actor_role(role) if role else None

    actor_state = ActiveActorState(
        actor_type=normalized_type,
        actor_name=actor_name,
        role=normalized_role,
        tool=tool,
        session_id=session_id,
    )
    try:
        save_actor_state(workspace_root, actor_state)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "kind": "actor_set",
        "actor": actor_state.to_dict(),
    }
    human_lines = [
        f"Actor set: {actor_state.actor_type}:{actor_state.actor_name}",
    ]
    if actor_state.role:
        human_lines.append(f"Role: {actor_state.role}")

    emit_payload(ctx, payload, human="\n".join(human_lines), result_type="actor_set")


@app.command(name="clear")
def actor_clear_cmd(ctx: typer.Context) -> None:
    """Clear the stored actor identity."""
    state = cli_state_from_context(ctx)
    workspace_root = resolve_workspace_root(state.cwd)

    try:
        cleared = clear_actor_state(workspace_root)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "kind": "actor_clear",
        "cleared": cleared.to_dict() if cleared else None,
    }
    human = "Actor cleared." if cleared else "No stored actor to clear."

    emit_payload(ctx, payload, human=human, result_type="actor_clear")


@harness_app.command(name="set")
def harness_set_cmd(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Option("--name", help="Harness name."),
    ],
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Harness kind."),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Session identifier."),
    ] = None,
) -> None:
    """Set the stored harness identity."""
    state = cli_state_from_context(ctx)
    workspace_root = resolve_workspace_root(state.cwd)

    normalized_kind = normalize_harness_kind(kind) if kind else "unknown"

    harness_state = ActiveHarnessState(
        name=name,
        kind=normalized_kind,
        session_id=session_id,
    )
    try:
        save_harness_state(workspace_root, harness_state)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "kind": "harness_set",
        "harness": harness_state.to_dict(),
    }
    human_lines = [
        f"Harness set: {harness_state.name} ({harness_state.kind})",
    ]

    emit_payload(ctx, payload, human="\n".join(human_lines), result_type="harness_set")


@harness_app.command(name="clear")
def harness_clear_cmd(ctx: typer.Context) -> None:
    """Clear the stored harness identity."""
    state = cli_state_from_context(ctx)
    workspace_root = resolve_workspace_root(state.cwd)

    try:
        cleared = clear_harness_state(workspace_root)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "kind": "harness_clear",
        "cleared": cleared.to_dict() if cleared else None,
    }
    human = "Harness cleared." if cleared else "No stored harness to clear."

    emit_payload(ctx, payload, human=human, result_type="harness_clear")

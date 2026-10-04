from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.handoff import (
    cancel_handoff_api,
    claim_handoff_api,
    close_handoff_api,
    create_handoff,
    create_review_handoff,
    list_all_handoffs,
    release_handoff_api,
    retarget_handoff_api,
    show_handoff,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    render_json,
    resolve_cli_task,
)
from taskledger.errors import LaunchError


def register_handoff_v2_commands(app: typer.Typer) -> None:
    @app.command("create")
    def create_command(
        ctx: typer.Context,
        mode: Annotated[str | None, typer.Option("--mode")] = None,
        context_for: Annotated[str | None, typer.Option("--for")] = None,
        worker_step_id: Annotated[
            str | None, typer.Option("--worker", help="Configured worker step id.")
        ] = None,
        scope: Annotated[str | None, typer.Option("--scope")] = None,
        todo_id: Annotated[str | None, typer.Option("--todo")] = None,
        focus_run_id: Annotated[str | None, typer.Option("--run")] = None,
        intended_actor: Annotated[str | None, typer.Option("--intended-actor")] = None,
        intended_harness: Annotated[
            str | None, typer.Option("--intended-harness")
        ] = None,
        summary: Annotated[str | None, typer.Option("--summary")] = None,
        next_action: Annotated[str | None, typer.Option("--next-action")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = create_handoff(
                state.cwd,
                task.id,
                mode=mode,
                context_for=context_for,
                worker_step_id=worker_step_id,
                scope=scope,
                todo_id=todo_id,
                focus_run_id=focus_run_id,
                intended_actor_type=intended_actor,
                intended_harness=intended_harness,
                summary=summary,
                next_action=next_action,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"created handoff {payload['handoff_id']}")

    @app.command("review")
    def review_handoff_command(
        ctx: typer.Context,
        kind: Annotated[
            str, typer.Option("--kind", help="Review kind: code, spec, or general.")
        ] = "general",
        focus_run_id: Annotated[str | None, typer.Option("--run")] = None,
        intended_harness: Annotated[
            str | None, typer.Option("--intended-harness")
        ] = None,
        intended_actor: Annotated[str, typer.Option("--intended-actor")] = "agent",
        intended_actor_name: Annotated[
            str | None, typer.Option("--intended-actor-name")
        ] = None,
        summary: Annotated[str | None, typer.Option("--summary")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = create_review_handoff(
                state.cwd,
                task.id,
                run_id=focus_run_id,
                kind=kind,
                intended_actor_type=intended_actor,
                intended_actor_name=intended_actor_name,
                intended_harness=intended_harness,
                summary=summary,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human=(
                f"created review handoff {payload['handoff_id']} "
                f"run={payload.get('focus_run_id')} context={payload.get('context_for')}"  # noqa: E501
            ),
        )

    @app.command("list")
    def list_handoff_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            handoffs = list_all_handoffs(state.cwd, task.id)
            payload = {"kind": "handoff_list", "task_id": task.id, "handoffs": handoffs}
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human="\n".join(str(h["handoff_id"]) for h in handoffs),
        )

    @app.command("claim")
    def claim_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = claim_handoff_api(state.cwd, task.id, handoff_id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        claim_lines = [f"claimed handoff {payload['handoff_id']}"]
        if payload.get("mode") == "review":
            claim_lines.extend(
                [
                    f"context: {payload.get('context_for') or 'reviewer'}",
                    f"implementation run: {payload.get('focus_run_id') or '(latest)'}",
                    "This is read-only review work; the implementation lock does not need to be acquired or transferred.",  # noqa: E501
                    f"Next: taskledger review record --handoff {payload['handoff_id']} --result pass|fail|blocked ...",  # noqa: E501
                ]
            )
        emit_payload(ctx, payload, human="\n".join(claim_lines))

    @app.command("release")
    def release_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        reason: Annotated[str, typer.Option("--reason")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = release_handoff_api(state.cwd, task.id, handoff_id, reason=reason)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human=f"released handoff {payload['handoff_id']}; it is open for reclaim",
        )

    @app.command("retarget")
    def retarget_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        intended_harness: Annotated[str, typer.Option("--intended-harness")],
        reason: Annotated[str, typer.Option("--reason")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = retarget_handoff_api(
                state.cwd,
                task.id,
                handoff_id,
                intended_harness=intended_harness,
                reason=reason,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human=f"retargeted handoff {payload['handoff_id']} to {payload['intended_harness']}",  # noqa: E501
        )

    @app.command("close")
    def close_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        reason: Annotated[str | None, typer.Option("--reason")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = close_handoff_api(state.cwd, task.id, handoff_id, reason=reason)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"closed handoff {payload['handoff_id']}")

    @app.command("cancel")
    def cancel_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        reason: Annotated[str | None, typer.Option("--reason")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = cancel_handoff_api(state.cwd, task.id, handoff_id, reason=reason)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"cancelled handoff {payload['handoff_id']}")

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        format_name: Annotated[str, typer.Option("--format")] = "text",
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = show_handoff(
                state.cwd, task.id, handoff_id, format_name=format_name
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            payload
            if isinstance(payload, str)
            else render_json(payload)
            if format_name == "json"
            else None
        )
        emit_payload(ctx, payload, human=human)

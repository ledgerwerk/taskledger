from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.tasks import (
    add_requirement,
    remove_requirement,
    waive_requirement,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.storage.task_store import (
    load_requirements,
)


def register_require_v2_commands(app: typer.Typer) -> None:
    @app.command("add")
    def add_command(
        ctx: typer.Context,
        required_task_ref: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = add_requirement(state.cwd, task.id, required_task_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"added requirement on {task.id}")

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            requirements = load_requirements(state.cwd, task.id).requirements
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        refs = [item.task_id for item in requirements]
        emit_payload(
            ctx,
            [item.to_dict() for item in requirements],
            human="\n".join(["REQUIREMENTS", *refs])
            if refs
            else "REQUIREMENTS\n(empty)",
        )

    @app.command("remove")
    def remove_command(
        ctx: typer.Context,
        required_task_ref: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = remove_requirement(state.cwd, task.id, required_task_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"removed requirement on {task.id}")

    @app.command("waive")
    def waive_command(
        ctx: typer.Context,
        required_task_ref: Annotated[str, typer.Argument(...)],
        actor: Annotated[str, typer.Option("--actor")] = "user",
        reason: Annotated[str, typer.Option("--reason")] = "",
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = waive_requirement(
                state.cwd,
                task.id,
                required_task_ref,
                actor_type=actor,
                reason=reason,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"waived requirement on {task.id}")

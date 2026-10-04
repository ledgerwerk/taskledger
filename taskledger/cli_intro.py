from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from taskledger.api.introductions import (
    create_introduction,
    link_introduction,
    list_introductions,
    resolve_introduction,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    read_text_input,
    resolve_cli_task,
)
from taskledger.errors import LaunchError


def register_intro_v2_commands(app: typer.Typer) -> None:
    @app.command("create")
    def create_command(
        ctx: typer.Context,
        title: Annotated[str, typer.Argument(...)],
        text: Annotated[str | None, typer.Option("--text")] = None,
        from_file: Annotated[Path | None, typer.Option("--from-file")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            intro = create_introduction(
                state.cwd,
                title=title,
                body=read_text_input(text=text, from_file=from_file),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, intro.to_dict(), human=f"created intro {intro.id}")

    @app.command("list")
    def list_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        payload = [intro.to_dict() for intro in list_introductions(state.cwd)]
        human = "\n".join(
            ["INTRODUCTIONS", *[f"{intro['id']}  {intro['slug']}" for intro in payload]]
        )
        emit_payload(
            ctx,
            payload,
            human=human if payload else "INTRODUCTIONS\n(empty)",
        )

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        intro_ref: Annotated[str, typer.Argument(...)],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            intro = resolve_introduction(state.cwd, intro_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, intro.to_dict(), human=intro.body)

    @app.command("link")
    def link_command(
        ctx: typer.Context,
        intro_ref: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = link_introduction(state.cwd, task.id, intro_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"linked intro to {task.id}")

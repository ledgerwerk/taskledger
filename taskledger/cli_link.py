from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.tasks import (
    add_file_link,
    list_file_links,
    remove_file_link,
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


def register_link_v2_commands(app: typer.Typer) -> None:
    @app.command("add")
    def add_command(
        ctx: typer.Context,
        url: Annotated[str, typer.Option("--url")],
        label: Annotated[str | None, typer.Option("--label")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        _emit_link_add(
            ctx,
            task_ref,
            path=url,
            kind="other",
            label=label,
            required_for_validation=False,
        )

    @app.command("remove")
    def remove_command(
        ctx: typer.Context,
        link_ref: Annotated[str, typer.Argument(help="Link URL or path.")],
        task_ref: TaskOption = None,
    ) -> None:
        _emit_link_remove(ctx, task_ref, path=link_ref)

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        _emit_link_list(ctx, task_ref)


def _emit_link_add(
    ctx: typer.Context,
    task_ref: str | None,
    *,
    path: str,
    kind: str,
    label: str | None,
    required_for_validation: bool,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        task = add_file_link(
            state.cwd,
            task.id,
            path=path,
            kind=kind,
            label=label,
            required_for_validation=required_for_validation,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, task.to_dict(), human=f"linked file on {task.id}")


def _emit_link_remove(ctx: typer.Context, task_ref: str | None, *, path: str) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        task = remove_file_link(state.cwd, task.id, path=path)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, task.to_dict(), human=f"unlinked file on {task.id}")


def _emit_link_list(ctx: typer.Context, task_ref: str | None) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = list_file_links(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    file_links = payload["file_links"]
    assert isinstance(file_links, list)
    lines = ["FILES"]
    for item in file_links:
        if isinstance(item, dict):
            lines.append(f"@{item.get('path')} [{item.get('kind')}]")
    emit_payload(
        ctx, payload, human="\n".join(lines) if file_links else "FILES\n(empty)"
    )

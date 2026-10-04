from __future__ import annotations

import shutil
import time
from typing import Annotated

import typer

from taskledger.cli_common import (
    CLIState,
    TaskOption,
    TaskRefArgument,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.cli_navigation import _selected_task_ref
from taskledger.errors import LaunchError
from taskledger.services.dashboard import dashboard, render_dashboard_text
from taskledger.services.monitor import monitor_snapshot, render_monitor_text


def view_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = dashboard(state.cwd, ref=task_ref)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human = render_dashboard_text(payload)
    emit_payload(ctx, payload, human=human)


def monitor_command(
    ctx: typer.Context,
    task_arg: TaskRefArgument = None,
    task_ref: Annotated[
        str | None,
        typer.Option("--task"),
    ] = None,
    refresh_seconds: Annotated[
        int,
        typer.Option("--refresh-seconds"),
    ] = 2,
    once: Annotated[bool, typer.Option("--once")] = False,
    max_events: Annotated[int, typer.Option("--max-events")] = 10,
    max_ready: Annotated[int, typer.Option("--max-ready")] = 10,
    activity_scope: Annotated[
        str,
        typer.Option("--activity-scope", help="Activity scope: ledger or task."),
    ] = "ledger",
    plain: Annotated[bool, typer.Option("--plain")] = False,
    no_clear: Annotated[bool, typer.Option("--no-clear")] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        selected_task_ref = _selected_task_ref(
            task_arg,
            task_ref,
            command_name="monitor",
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    normalized_scope = activity_scope.strip().lower()
    if normalized_scope not in {"ledger", "task"}:
        emit_error(
            ctx,
            LaunchError("Invalid --activity-scope value. Use 'ledger' or 'task'."),
        )
        raise typer.Exit(code=2)

    def _snapshot() -> dict[str, object]:
        return monitor_snapshot(
            state.cwd,
            task_ref=selected_task_ref,
            max_events=max_events,
            max_ready=max_ready,
            activity_scope=normalized_scope,
        )

    if state.json_output:
        emit_payload(ctx, _snapshot())
        return

    try:
        while True:
            payload = _snapshot()
            width, height = shutil.get_terminal_size(fallback=(100, 30))
            rendered = render_monitor_text(
                payload,
                width=width,
                height=height,
                plain=plain,
            )
            if not no_clear:
                typer.echo("\x1b[2J\x1b[H", nl=False)
            elif not once:
                typer.echo("")
            typer.echo(rendered)
            if once:
                return
            time.sleep(max(1, refresh_seconds))
    except KeyboardInterrupt:
        raise typer.Exit(code=0) from None


def register_monitor_commands(app: typer.Typer) -> None:
    app.command("view")(view_command)
    app.command("monitor")(monitor_command)

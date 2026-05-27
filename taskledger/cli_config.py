from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.config import config_get, config_list, config_set
from taskledger.cli_common import (
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    render_json,
)
from taskledger.errors import LaunchError


def register_config_commands(app: typer.Typer) -> None:
    @app.command("list")
    def list_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = config_list(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config",
            human=_render_config_list(payload),
        )

    @app.command("show")
    def show_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = config_list(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config",
            human=_render_config_list(payload),
        )

    @app.command("get")
    def get_command(
        ctx: typer.Context,
        key: Annotated[str, typer.Argument(help="Dotted config key path.")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = config_get(state.cwd, key=key)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config_value",
            human=_render_config_get(payload),
        )

    @app.command("set")
    def set_command(
        ctx: typer.Context,
        key: Annotated[str, typer.Argument(help="Dotted config key path.")],
        value: Annotated[
            str,
            typer.Argument(help="New value (TOML literal or string)."),
        ],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = config_set(state.cwd, key=key, value_text=value)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config_updated",
            human=_render_config_set(payload),
        )


def _render_config_list(payload: dict[str, object]) -> str:
    config_path = str(payload.get("config_path", "?"))
    config = payload.get("config")
    rendered = render_json(config) if isinstance(config, dict) else str(config)
    return f"Config: {config_path}\n{rendered.rstrip()}"


def _render_config_get(payload: dict[str, object]) -> str:
    key = str(payload.get("key", "?"))
    value = payload.get("value")
    rendered = render_json(value).rstrip()
    return f"{key} = {rendered}"


def _render_config_set(payload: dict[str, object]) -> str:
    key = str(payload.get("key", "?"))
    previous = render_json(payload.get("previous_value")).rstrip()
    value = render_json(payload.get("value")).rstrip()
    return f"Updated {key}\nPrevious: {previous}\nCurrent: {value}"

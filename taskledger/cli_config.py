from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.config import (
    config_describe,
    config_get,
    config_keys,
    config_list,
    config_set,
)
from taskledger.cli_common import (
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    render_json,
)
from taskledger.errors import LaunchError
from taskledger.storage.project_context import load_project_context


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

    @app.command("keys")
    def keys_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = config_keys(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config_keys",
            human=_render_config_keys(payload),
        )

    @app.command("describe")
    def describe_command(
        ctx: typer.Context,
        key: Annotated[str, typer.Argument(help="Dotted config key path.")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = config_describe(state.cwd, key=key)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config_key_help",
            human=_render_config_describe(payload),
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

    @app.command("path")
    def path_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            context = load_project_context(state.cwd)
            payload = {
                "kind": "config_path",
                "path": str(context.config_path),
                "mode": context.mode,
            }
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx, payload, result_type="config_path", human=str(payload["path"])
        )

    @app.command("validate")
    def validate_command(ctx: typer.Context) -> None:
        """Validate the project configuration.

        Checks that the config file is valid TOML and all keys are recognized.
        """
        state = cli_state_from_context(ctx)
        try:
            from taskledger.storage.project_context import load_project_context

            context = load_project_context(state.cwd)
            payload = {
                "kind": "config_validation",
                "path": str(context.config_path),
                "valid": True,
                "errors": [],
                "warnings": [],
            }
        except LaunchError as exc:
            payload = {
                "kind": "config_validation",
                "valid": False,
                "errors": [str(exc)],
                "warnings": [],
            }
        emit_payload(
            ctx,
            payload,
            result_type="config_validation",
            human=_render_config_validate(payload),
        )

    @app.command("unset")
    def unset_command(
        ctx: typer.Context,
        key: Annotated[str, typer.Argument(help="Configuration key to unset.")],
    ) -> None:
        """Remove a configuration key.

        Removes the key from local overrides if present.
        """
        state = cli_state_from_context(ctx)
        try:
            from taskledger.api.config import config_unset

            payload = config_unset(state.cwd, key=key)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="project_config_updated",
            human=f"Unset: {key}",
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


def _render_config_keys(payload: dict[str, object]) -> str:
    keys = payload.get("keys")
    if not isinstance(keys, list):
        return "No config key help available."
    lines = ["Available config keys:"]
    for item in keys:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "?"))
        value_type = str(item.get("value_type", "unknown"))
        lines.append(f"- {key} ({value_type})")
    lines.append("")
    lines.append(
        "Use `taskledger config describe <key>` for details and allowed values."
    )
    return "\n".join(lines)


def _render_config_describe(payload: dict[str, object]) -> str:
    key = str(payload.get("key", "?"))
    schema_key = str(payload.get("schema_key", key))
    value_type = str(payload.get("value_type", "unknown"))
    description = str(payload.get("description", ""))
    allowed_values = payload.get("allowed_values")
    default_value = payload.get("default_value")
    has_value = bool(payload.get("has_explicit_value"))
    value = payload.get("value")

    lines = [
        f"Key: {key}",
        f"Schema key: {schema_key}",
        f"Type: {value_type}",
        f"Description: {description}",
    ]
    if isinstance(allowed_values, list) and allowed_values:
        values = ", ".join(str(item) for item in allowed_values)
        lines.append(f"Allowed values: {values}")
    else:
        lines.append("Allowed values: any valid value for this type")
    if default_value is not None:
        lines.append(f"Default: {render_json(default_value).rstrip()}")
    if has_value:
        lines.append(f"Current: {render_json(value).rstrip()}")
    else:
        lines.append("Current: not set explicitly")
    return "\n".join(lines)


def _render_config_validate(payload: dict[str, object]) -> str:
    """Render config validation result for human output."""
    valid = payload.get("valid", False)
    errors = payload.get("errors", [])
    warnings = payload.get("warnings", [])
    path = payload.get("path", "?")
    lines = [f"Config validation: {path}"]
    if valid:
        lines.append("Status: valid")
    else:
        lines.append("Status: invalid")
    if isinstance(errors, list) and errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"  - {err}")
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        for warn in warnings:
            lines.append(f"  - {warn}")
    return "\n".join(lines)

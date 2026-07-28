"""Nested help command for Taskledger.

Provides `taskledger help [COMMAND...]` that resolves through the
CommandInventory and renders real Typer/Click help for the target command.
"""

from __future__ import annotations

from typing import Annotated

import typer

from taskledger.cli_common import (
    CLIState,
    cli_state_from_context,
    emit_error,
    emit_payload,
)
from taskledger.command_inventory import COMMAND_METADATA, get_command_family_metadata


def register_help_command(app: typer.Typer) -> None:
    """Register the help command on the main app."""

    @app.command("help", hidden=False)
    def help_command(
        ctx: typer.Context,
        command_path: Annotated[
            list[str] | None,
            typer.Argument(help="Command path to show help for."),
        ] = None,
    ) -> None:
        """Show help for a command or list all commands.

        Examples:
            taskledger help
            taskledger help task
            taskledger help task show
        """
        state = cli_state_from_context(ctx)

        if command_path is None or len(command_path) == 0:
            # Show top-level help
            _show_top_level_help(ctx, state)
            return

        # Resolve the command path
        resolved_path = " ".join(command_path)

        # Check if it's a known command
        if resolved_path in COMMAND_METADATA:
            _show_command_help(ctx, state, resolved_path)
            return

        # Check if it's a group prefix
        matching = [p for p in COMMAND_METADATA if p.startswith(resolved_path)]
        if matching:
            _show_group_help(ctx, state, resolved_path, matching)
            return

        # Unknown command
        emit_error(
            ctx,
            f"Unknown command path: {resolved_path}",
            exit_code=2,
            remediation=[
                "Run `taskledger help` to see all available commands.",
                "Run `taskledger commands` to see the full command inventory.",
            ],
        )
        raise typer.Exit(code=2)


def _show_top_level_help(ctx: typer.Context, state: CLIState) -> None:
    """Show top-level help listing all command groups."""
    if state.json_output:
        payload = {
            "kind": "help",
            "path": "taskledger",
            "commands": list(COMMAND_METADATA.keys()),
            "groups": _get_command_groups(),
        }
        emit_payload(ctx, payload, human=None)
    else:
        # Show the standard Typer help
        root_ctx = ctx.find_root()
        typer.echo(root_ctx.get_help())


def _show_command_help(ctx: typer.Context, state: CLIState, path: str) -> None:
    """Show help for a specific command."""
    meta = get_command_family_metadata(path)
    if not meta:
        emit_error(ctx, f"Command not found: {path}", exit_code=2)
        raise typer.Exit(code=2)

    if state.json_output:
        emit_payload(ctx, meta, human=None)
    else:
        # Try to get the real help from Typer
        _render_command_help_text(ctx, path, meta)


def _show_group_help(
    ctx: typer.Context,
    state: CLIState,
    group: str,
    matching: list[str],
) -> None:
    """Show help for a command group."""
    if state.json_output:
        subcommands = []
        for p in matching:
            sub = p[len(group) :].strip()
            if sub:
                subcommands.append(sub)
        payload = {
            "kind": "help",
            "path": group,
            "subcommands": subcommands,
        }
        emit_payload(ctx, payload, human=None)
    else:
        typer.echo(f"Command group: {group}")
        typer.echo("")
        typer.echo("Available subcommands:")
        for p in sorted(matching):
            sub = p[len(group) :].strip()
            if sub:
                typer.echo(f"  {sub}")
        typer.echo("")
        typer.echo(f"Run `taskledger {group} --help` for more information.")


def _render_command_help_text(
    ctx: typer.Context,
    path: str,
    meta: dict[str, object],
) -> None:
    """Render human-readable help for a command."""
    typer.echo(f"Command: {path}")

    summary = meta.get("summary", "")
    if summary:
        typer.echo(f"Summary: {summary}")

    audience = meta.get("audience", "")
    if audience:
        typer.echo(f"Audience: {audience}")

    stability = meta.get("stability", "")
    if stability:
        typer.echo(f"Stability: {stability}")

    effect = meta.get("effect", "")
    if effect:
        typer.echo(f"Effect: {effect}")

    deprecated = meta.get("deprecated", False)
    if deprecated:
        replacement = meta.get("replacement")
        if replacement:
            typer.echo(f"Deprecated: use {replacement} instead")
        else:
            typer.echo("Deprecated")

    extensions_raw = meta.get("extensions", {})
    extensions = extensions_raw if isinstance(extensions_raw, dict) else {}
    taskledger_ext_raw = extensions.get("taskledger", {})
    taskledger_ext = taskledger_ext_raw if isinstance(taskledger_ext_raw, dict) else {}
    if taskledger_ext:
        typer.echo("")
        typer.echo("Taskledger extensions:")
        for key, value in taskledger_ext.items():
            if value:
                typer.echo(f"  {key}: {value}")

    typer.echo("")
    typer.echo(f"Run `taskledger {path} --help` for command-specific options.")


def _get_command_groups() -> list[str]:
    """Get the list of command groups (first part of multi-word commands)."""
    groups: set[str] = set()
    for path in COMMAND_METADATA:
        parts = path.split()
        if len(parts) > 1:
            groups.add(parts[0])
    return sorted(groups)

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from taskledger.api.storage import (
    storage_clear_override,
    storage_migration_recover,
    storage_migration_status,
    storage_move,
    storage_path,
    storage_set,
    storage_validate,
    storage_where,
)
from taskledger.cli_common import (
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.errors import LaunchError


def _render_storage_where(payload: dict[str, object]) -> str:
    project = payload.get("project", {})
    project = project if isinstance(project, dict) else {}
    config = payload.get("config", {})
    config = config if isinstance(config, dict) else {}
    manifest = payload.get("manifest", {})
    manifest_path = (
        manifest.get("path")
        if isinstance(manifest, dict)
        else payload.get("manifest_path")
    )
    lines = [
        f"Project root: {project.get('root', payload.get('project_root'))}",
        f"Project UUID: {project.get('uuid', payload.get('project_uuid'))}",
        f"Manifest: {manifest_path}",
        f"Config: {config.get('path', payload.get('config_path'))}",
        f"Active locks: {payload.get('active_lock_count', 0)}",
        "Mounts:",
    ]
    mounts = payload.get("mounts", {})
    if isinstance(mounts, dict):
        for name, mount in mounts.items():
            if isinstance(mount, dict):
                lines.extend(
                    [
                        f"  {name}",
                        f"    storage: {mount.get('storage')}",
                        f"    source: {mount.get('source')}",
                        f"    root: {mount.get('root')}",
                        f"    path: {mount.get('path')}",
                        "    initialized: "
                        f"{'yes' if mount.get('initialized') else 'no'}",
                    ]
                )
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    return "\n".join(lines)


def _render_storage_move(payload: dict[str, object]) -> str:
    lines = [
        f"{str(payload['mode']).capitalize()}d storage to {payload['target']}",
        f"Config: {payload['config_path']}",
        f"Source: {payload['source']}",
    ]
    backup_path = payload.get("backup_path")
    if isinstance(backup_path, str) and backup_path:
        lines.append(f"Backup: {backup_path}")
    next_commands = payload.get("next_commands", [])
    if isinstance(next_commands, list) and next_commands:
        lines.append("Next:")
        lines.extend(f"- {item}" for item in next_commands if isinstance(item, str))
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    return "\n".join(lines)


def register_storage_commands(app: typer.Typer) -> None:
    migration_app = typer.Typer(
        add_completion=False, help="Inspect storage migration journals."
    )
    app.add_typer(migration_app, name="migration")

    @migration_app.command("status")
    def migration_status_command(
        ctx: typer.Context,
        journal: Annotated[Path, typer.Argument()],
    ) -> None:
        state = cli_state_from_context(ctx)
        del state
        try:
            payload = storage_migration_status(journal)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx, payload, result_type="storage_migration_status", human=str(payload)
        )

    @migration_app.command("recover")
    def migration_recover_command(
        ctx: typer.Context,
        journal: Annotated[Path, typer.Argument()],
    ) -> None:
        state = cli_state_from_context(ctx)
        del state
        try:
            payload = storage_migration_recover(journal)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx, payload, result_type="storage_migration_recover", human=str(payload)
        )

    @app.command("where")
    def where_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = storage_where(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="storage_where",
            human=_render_storage_where(payload),
        )

    @app.command("path")
    def path_command(
        ctx: typer.Context,
        mount: Annotated[str, typer.Argument(help="Mount name: data or indexes.")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = storage_path(state.cwd, mount)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx, payload, result_type="storage_path", human=str(payload["path"])
        )

    @app.command("validate")
    def validate_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = storage_validate(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, result_type="storage_validate", human=str(payload))

    @app.command("set")
    def set_command(
        ctx: typer.Context,
        mount: Annotated[str, typer.Argument()],
        storage: Annotated[str, typer.Argument()],
        root: Annotated[str | None, typer.Option("--root")] = None,
        project: Annotated[bool, typer.Option("--project")] = False,
        local: Annotated[bool, typer.Option("--local")] = False,
        mode: Annotated[str, typer.Option("--mode")] = "move",
        move: Annotated[bool | None, typer.Option("--move/--copy")] = None,
    ) -> None:
        if project == local:
            raise typer.BadParameter("Specify exactly one of --project or --local")
        state = cli_state_from_context(ctx)
        try:
            payload = storage_set(
                state.cwd,
                mount=mount,
                storage=storage,
                target="project" if project else "local",
                external_root=root,
                mode="move" if move is True else "copy" if move is False else mode,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="storage_set",
            human=_render_storage_where(payload),
        )

    @app.command("clear-override")
    def clear_override_command(
        ctx: typer.Context,
        mount: Annotated[str, typer.Argument()],
        mode: Annotated[str, typer.Option("--mode")] = "move",
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = storage_clear_override(state.cwd, mount=mount, mode=mode)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="storage_clear_override",
            human=_render_storage_where(payload),
        )

    @app.command("move")
    def move_command(
        ctx: typer.Context,
        to: Annotated[str, typer.Option("--to", help="New taskledger_dir target.")],
        mode: Annotated[
            str,
            typer.Option("--mode", help="Migration mode: copy or move."),
        ] = "move",
        adopt_existing: Annotated[
            bool,
            typer.Option("--adopt-existing", help="Adopt a non-empty existing target."),
        ] = False,
        force: Annotated[
            bool,
            typer.Option(
                "--force",
                help="Allow migration from an already external taskledger_dir.",
            ),
        ] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = storage_move(
                state.cwd,
                target=Path(to),
                mode=mode,
                adopt_existing=adopt_existing,
                force=force,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="storage_move",
            human=_render_storage_move(payload),
        )

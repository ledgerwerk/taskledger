"""CLI rendering for the unified Taskledger migration coordinator."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from taskledger.cli_common import (
    CLIState,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.errors import LaunchError
from taskledger.storage.layout_migration import apply_migration, inspect_migration

migrate_app = typer.Typer(
    add_completion=False, help="Inspect and apply storage migrations."
)


def _inspection_human(payload: dict[str, object], *, compact: bool = False) -> str:
    def section(name: str) -> dict[str, object]:
        value = payload.get(name)
        return value if isinstance(value, dict) else {}

    project = section("project")
    source = section("source")
    target = section("target")
    raw_issues = payload.get("issues")
    issues = raw_issues if isinstance(raw_issues, list) else []
    raw_changes = payload.get("changes")
    change_count = len(raw_changes) if isinstance(raw_changes, list) else 0
    lines = [
        "TASKLEDGER MIGRATION",
        "",
        "Project",
        f"  root: {project.get('root')}",
        f"  uuid: {project.get('uuid')}",
        "",
        "Source",
        f"  kind: {source.get('kind')}",
        f"  data: {source.get('data')}",
        f"  logs: {source.get('logs')}",
        "",
        "Target",
        f"  data: {target.get('data')}",
        f"  indexes: {target.get('indexes')}",
        f"  binding: {target.get('binding')}",
        f"  changes: {change_count}",
    ]
    if issues:
        lines.append("Blockers and warnings")
        for issue in issues:
            if isinstance(issue, dict):
                lines.append(
                    "  "
                    f"{issue.get('severity')}: {issue.get('code')}: "
                    f"{issue.get('message')}"
                )
    else:
        lines.extend(["Blockers", "  none"])
    if not compact:
        commands = payload.get("commands")
        apply_command = (
            commands.get("apply")
            if isinstance(commands, dict)
            else "taskledger migrate apply --backup"
        )
        lines.append(f"  apply: {apply_command}")
    return "\n".join(lines)


def _inspect(ctx: typer.Context) -> dict[str, object]:
    state = ctx.obj
    assert isinstance(state, CLIState)
    return inspect_migration(state.cwd).to_dict()


@migrate_app.callback(invoke_without_command=True)
def migrate_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    try:
        payload = _inspect(ctx)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_inspection_human(payload))


@migrate_app.command("inspect")
def migrate_inspect_command(ctx: typer.Context) -> None:
    try:
        payload = _inspect(ctx)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_inspection_human(payload))


@migrate_app.command("status")
def migrate_status_command(ctx: typer.Context) -> None:
    try:
        payload = _inspect(ctx)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_inspection_human(payload, compact=True))


@migrate_app.command("plan")
def migrate_plan_command(ctx: typer.Context) -> None:
    try:
        payload = _inspect(ctx)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_inspection_human(payload))


@migrate_app.command("apply")
def migrate_apply_command(
    ctx: typer.Context,
    backup: Annotated[
        bool,
        typer.Option("--backup/--no-backup", help="Deprecated; backup is automatic."),
    ] = True,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Inspect without writing."),
    ] = False,
    create_sibling_store: Annotated[
        bool,
        typer.Option(
            "--create-sibling-store",
            help="Create the fixed ../ledger sibling store if absent.",
        ),
    ] = False,
    backup_dir: Annotated[Path | None, typer.Option("--backup-dir")] = None,
    source_checkout: Annotated[str | None, typer.Option("--source-checkout")] = None,
    retire_source: Annotated[
        bool, typer.Option("--retire-source", "--retire-legacy")
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    payload: dict[str, object]
    try:
        inspection = inspect_migration(
            state.cwd,
            source_checkout=source_checkout,
        )
        if dry_run:
            payload = {
                "kind": "taskledger_migration_inspection",
                "status": "dry_run",
                "inspection": inspection.to_dict(),
            }
        else:
            payload = apply_migration(
                inspection,
                backup=backup,
                backup_dir=backup_dir,
                create_sibling_store=create_sibling_store,
                retire_source=retire_source,
            )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human_payload = (
        payload.get("inspection")
        if isinstance(payload.get("inspection"), dict)
        else payload
    )
    emit_payload(
        ctx,
        payload,
        human=_inspection_human(human_payload, compact=True)
        if isinstance(human_payload, dict)
        else str(payload),
    )

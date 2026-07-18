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
from taskledger.services.storage_migration import (
    MigrationOptions,
    apply_migration,
    inspect_migration,
)

migrate_app = typer.Typer(
    add_completion=False, help="Inspect and apply storage migrations."
)


def _migration_options(
    *,
    sibling_ledger_root: Path | None = None,
    source_data_root: Path | None = None,
    source_checkout_id: str | None = None,
    project_uuid: str | None = None,
    create_sibling_store: bool = False,
) -> MigrationOptions:
    return MigrationOptions(
        sibling_ledger_root=sibling_ledger_root,
        source_data_root=source_data_root,
        source_checkout_id=source_checkout_id,
        project_uuid=project_uuid,
        create_sibling_store=create_sibling_store,
    )


def _inspection_human(payload: dict[str, object], *, compact: bool = False) -> str:
    def section(name: str) -> dict[str, object]:
        value = payload.get(name)
        return value if isinstance(value, dict) else {}

    project = section("project")
    source = section("source")
    target = section("target")
    issues = payload.get("issues")
    changes = payload.get("changes")
    issue_rows = issues if isinstance(issues, list) else []
    change_count = len(changes) if isinstance(changes, list) else 0
    status = str(payload.get("status", "unknown"))
    ready = "yes" if payload.get("ready") is True else "no"
    lines = [
        "TASKLEDGER MIGRATION",
        "",
        "Status",
        f"  {status}",
        f"  ready: {ready}",
        "",
        "Project identity",
        f"  canonical UUID: {project.get('canonical_uuid')}",
        f"  legacy Taskledger UUID: {project.get('legacy_uuid')}",
        f"  action: {project.get('identity_transition')}",
        "",
        "Source",
        f"  selected: {source.get('data')}",
        f"  reason: {source.get('selected_reason')}",
        f"  tasks: {source.get('task_count', section('counts').get('source_tasks'))}",
        "",
        "Target",
        f"  path: {target.get('data')}",
        f"  registration: {target.get('registration')}",
        f"  classification: {target.get('classification')}",
        f"  changes: {change_count}",
    ]
    if issue_rows:
        lines.extend(["", "Issues"])
        for issue in issue_rows:
            if not isinstance(issue, dict):
                continue
            lines.append(f"  {issue.get('severity')} [{issue.get('code')}]")
            lines.append(f"    {issue.get('message')}")
            details = issue.get("details")
            if isinstance(details, dict):
                for key, value in details.items():
                    lines.append(f"    {key}: {value}")
            remediation = issue.get("remediation")
            if isinstance(remediation, list):
                for index, remedy in enumerate(remediation, start=1):
                    lines.append(f"    remedy {index}: {remedy}")
    else:
        lines.extend(["", "Issues", "  none"])
    if not compact:
        lines.extend(["", "Apply"])
        commands = payload.get("commands")
        apply_command = commands.get("apply") if isinstance(commands, dict) else None
        lines.append(
            f"  {apply_command}"
            if isinstance(apply_command, str)
            else "  unavailable until blockers are resolved"
        )
    return "\n".join(lines)


def _inspect(
    ctx: typer.Context,
    *,
    sibling_ledger_root: Path | None = None,
    source_data_root: Path | None = None,
    source_checkout_id: str | None = None,
    project_uuid: str | None = None,
) -> dict[str, object]:
    state = ctx.obj
    assert isinstance(state, CLIState)
    options = _migration_options(
        sibling_ledger_root=sibling_ledger_root,
        source_data_root=source_data_root,
        source_checkout_id=source_checkout_id,
        project_uuid=project_uuid,
    )
    return inspect_migration(state.cwd, options=options).to_dict()


def _common_options(
    sibling_ledger_root: Path | None,
    source_data_root: Path | None,
    source_checkout_id: str | None,
    project_uuid: str | None,
) -> MigrationOptions:
    return _migration_options(
        sibling_ledger_root=sibling_ledger_root,
        source_data_root=source_data_root,
        source_checkout_id=source_checkout_id,
        project_uuid=project_uuid,
    )


def _emit_inspection(
    ctx: typer.Context,
    payload: dict[str, object],
    *,
    compact: bool = False,
) -> None:
    emit_payload(ctx, payload, human=_inspection_human(payload, compact=compact))


@migrate_app.callback(invoke_without_command=True)
def migrate_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    try:
        payload = _inspect(ctx)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    _emit_inspection(ctx, payload)


@migrate_app.command("inspect")
def migrate_inspect_command(
    ctx: typer.Context,
    sibling_ledger_root: Annotated[
        Path | None, typer.Option("--sibling-ledger-root")
    ] = None,
    source_data_root: Annotated[Path | None, typer.Option("--source-data-root")] = None,
    source_checkout_id: Annotated[
        str | None,
        typer.Option("--source-checkout-id", "--source-checkout"),
    ] = None,
    project_uuid: Annotated[str | None, typer.Option("--project-uuid")] = None,
) -> None:
    try:
        payload = _inspect(
            ctx,
            sibling_ledger_root=sibling_ledger_root,
            source_data_root=source_data_root,
            source_checkout_id=source_checkout_id,
            project_uuid=project_uuid,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    _emit_inspection(ctx, payload)


@migrate_app.command("status")
def migrate_status_command(
    ctx: typer.Context,
    sibling_ledger_root: Annotated[
        Path | None, typer.Option("--sibling-ledger-root")
    ] = None,
    source_data_root: Annotated[Path | None, typer.Option("--source-data-root")] = None,
    source_checkout_id: Annotated[
        str | None,
        typer.Option("--source-checkout-id", "--source-checkout"),
    ] = None,
    project_uuid: Annotated[str | None, typer.Option("--project-uuid")] = None,
) -> None:
    try:
        payload = _inspect(
            ctx,
            sibling_ledger_root=sibling_ledger_root,
            source_data_root=source_data_root,
            source_checkout_id=source_checkout_id,
            project_uuid=project_uuid,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    _emit_inspection(ctx, payload, compact=True)


@migrate_app.command("plan")
def migrate_plan_command(
    ctx: typer.Context,
    sibling_ledger_root: Annotated[
        Path | None, typer.Option("--sibling-ledger-root")
    ] = None,
    source_data_root: Annotated[Path | None, typer.Option("--source-data-root")] = None,
    source_checkout_id: Annotated[
        str | None,
        typer.Option("--source-checkout-id", "--source-checkout"),
    ] = None,
    project_uuid: Annotated[str | None, typer.Option("--project-uuid")] = None,
) -> None:
    try:
        payload = _inspect(
            ctx,
            sibling_ledger_root=sibling_ledger_root,
            source_data_root=source_data_root,
            source_checkout_id=source_checkout_id,
            project_uuid=project_uuid,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    _emit_inspection(ctx, payload)


@migrate_app.command("apply")
def migrate_apply_command(
    ctx: typer.Context,
    backup: Annotated[
        bool,
        typer.Option("--backup/--no-backup", help="Deprecated; backup is automatic."),
    ] = True,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    create_sibling_store: Annotated[
        bool,
        typer.Option(
            "--create-sibling-store",
            help=(
                "Initialize the sibling root and marker only; "
                "it does not repair target metadata."
            ),
        ),
    ] = False,
    sibling_ledger_root: Annotated[
        Path | None, typer.Option("--sibling-ledger-root")
    ] = None,
    source_data_root: Annotated[Path | None, typer.Option("--source-data-root")] = None,
    source_checkout_id: Annotated[
        str | None,
        typer.Option("--source-checkout-id", "--source-checkout"),
    ] = None,
    project_uuid: Annotated[str | None, typer.Option("--project-uuid")] = None,
    backup_dir: Annotated[Path | None, typer.Option("--backup-dir")] = None,
    retire_source: Annotated[
        bool, typer.Option("--retire-source", "--retire-legacy")
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    options = _common_options(
        sibling_ledger_root,
        source_data_root,
        source_checkout_id,
        project_uuid,
    )
    try:
        payload = apply_migration(
            state.cwd,
            options=MigrationOptions(
                sibling_ledger_root=options.sibling_ledger_root,
                source_data_root=options.source_data_root,
                source_checkout_id=options.source_checkout_id,
                project_uuid=options.project_uuid,
                create_sibling_store=create_sibling_store,
            ),
            backup=backup,
            backup_dir=backup_dir,
            dry_run=dry_run,
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
    if isinstance(human_payload, dict):
        _emit_inspection(ctx, human_payload, compact=True)
    else:
        emit_payload(ctx, payload, human=str(payload))

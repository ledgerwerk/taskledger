from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import typer

from taskledger.api.project import (
    init_project,
    project_snapshot,
    project_status,
    project_status_summary,
    project_tree,
)
from taskledger.cli_common import (
    CLIState,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.errors import LaunchError


def init_command(
    ctx: typer.Context,
    create_sibling_store: Annotated[
        bool,
        typer.Option(
            "--create-sibling-store",
            help="Create the fixed ../ledger sibling store if needed.",
        ),
    ] = False,
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            help="Human-readable project name used in reports.",
        ),
    ] = None,
    data_storage: Annotated[
        str,
        typer.Option(
            "--data-storage",
            help="Persistent data storage: external, user-data, or project.",
        ),
    ] = "external",
    external_root: Annotated[
        str,
        typer.Option("--external-root", help="External storage root."),
    ] = "../ledger",
    local_storage_override: Annotated[
        bool,
        typer.Option(
            "--local-storage-override",
            help="Write the selected data storage as a local override.",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = init_project(
            state.cwd,
            create_sibling_store=create_sibling_store,
            project_name=project_name,
            data_storage=data_storage,
            external_root=external_root,
            local_storage_override=local_storage_override,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human="\n".join(
            [
                (
                    "initialized taskledger: "
                    f"{payload.get('root', payload.get('project_root', '?'))}"
                ),
                f"project name: {payload['project_name']}",
                *[f"- {item}" for item in cast(list[str], payload["created"])],
            ]
        ),
    )


def status_command(
    ctx: typer.Context,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Run doctor health check (slower, not done by default).",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = project_status_summary(state.cwd, check_health=check)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=_status_human(payload) if isinstance(payload, dict) else None,
    )


def info_command(
    ctx: typer.Context,
) -> None:
    """Show detailed project information and inventory."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = project_status(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=_status_human(payload) if isinstance(payload, dict) else None,
    )


def tree_command(
    ctx: typer.Context,
    task_ref: Annotated[
        str | None,
        typer.Option(
            "--task", help="Render one task subtree instead of the full ledger."
        ),
    ] = None,
    all_ledgers: Annotated[
        bool,
        typer.Option("--all-ledgers", help="Include every local ledger namespace."),
    ] = False,
    details: Annotated[
        bool,
        typer.Option("--details", help="Show compact per-task counts."),
    ] = False,
    include_archived: Annotated[
        bool,
        typer.Option("--include-archived", help="Include archived tasks."),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Use ASCII tree glyphs."),
    ] = False,
) -> None:
    from taskledger.services.tree import render_tree_text

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = project_tree(
            state.cwd,
            task_ref=task_ref,
            include_all_ledgers=all_ledgers,
            details=details,
            include_archived=include_archived,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=render_tree_text(payload, plain=plain),
    )


def _status_human(payload: dict[str, Any]) -> str:
    if payload.get("mode") == "canonical-unregistered":
        lines = [
            "Taskledger status",
            f"PROJECT root: {payload.get('workspace_root')}",
            "Mode: canonical-unregistered",
            f"Manifest: {payload.get('manifest_path')}",
            "Registration: missing",
            f"Config: {payload.get('config_path')}",
        ]
        if payload.get("orphan_config"):
            lines.append(f"Orphan config: {payload.get('orphan_config')}")
        lines.append("Next: taskledger init")
        return "\n".join(lines)
    workspace = payload.get("workspace_root", "?")
    config_path = payload.get("config_path", "?")
    ledger_ref = payload.get("ledger_ref", "?")
    project_uuid = payload.get("project_uuid")
    project_name = payload.get("project_name")
    active_task = payload.get("active_task")
    counts = payload.get("counts")
    health = payload.get("health")

    lines = ["Taskledger status", f"Workspace: {workspace}", f"Config: {config_path}"]
    if isinstance(project_name, str) and project_name.strip():
        if isinstance(project_uuid, str) and project_uuid.strip():
            lines.append(f"Project: {project_name} ({project_uuid})")
        else:
            lines.append(f"Project: {project_name}")
    elif isinstance(project_uuid, str) and project_uuid.strip():
        lines.append(f"Project UUID: {project_uuid}")
    lines.append(f"Ledger: {ledger_ref}")
    if isinstance(active_task, dict):
        task_id = active_task.get("task_id", "?")
        slug = active_task.get("slug", "?")
        stage = active_task.get("status_stage", "?")
        lines.append(f"Active task: {task_id} {slug} ({stage})")
    else:
        lines.append("Active task: none")
    if isinstance(counts, dict):
        summary = " ".join(
            f"{key}={value}"
            for key, value in sorted(counts.items())
            if value is not None
        )
        lines.append(f"Counts: {summary}")
    if isinstance(health, dict):
        checked = bool(health.get("checked"))
        healthy = health.get("healthy")
        if checked:
            lines.append(f"Health: {'healthy' if healthy else 'issues found'}")
        else:
            lines.append("Health: not checked (use --check)")
    lines.append("Next: taskledger next-action")
    return "\n".join(lines)


def snapshot_command(
    ctx: typer.Context,
    output_dir: Annotated[Path, typer.Argument(..., file_okay=False, dir_okay=True)],
    include_bodies: Annotated[
        bool,
        typer.Option(
            "--include-bodies",
            help="Include Markdown bodies in the snapshot export.",
        ),
    ] = False,
    include_run_artifacts: Annotated[
        bool,
        typer.Option(
            "--include-run-artifacts",
            help="Include run artifact files in the snapshot export.",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = project_snapshot(
            state.cwd,
            output_dir=output_dir,
            include_bodies=include_bodies,
            include_run_artifacts=include_run_artifacts,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"wrote snapshot to {payload['snapshot_dir']}")


def register_project_commands(app: typer.Typer) -> None:
    app.command("init")(init_command)
    app.command("status")(status_command)
    app.command("info")(info_command)
    app.command("tree")(tree_command)
    app.command("snapshot")(snapshot_command)

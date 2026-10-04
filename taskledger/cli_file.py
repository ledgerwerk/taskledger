from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.tasks import (
    add_file_link,
    list_file_links,
    remove_file_link,
)
from taskledger.api.tasks import (
    file_status as file_status_api,
)
from taskledger.api.tasks import (
    refresh_file_baseline as refresh_file_baseline_api,
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


def register_file_v2_commands(app: typer.Typer) -> None:  # noqa: C901
    def _resolve_snapshot_option(snapshot: bool, no_snapshot: bool) -> bool | None:
        if snapshot and no_snapshot:
            raise LaunchError(
                "Use either --snapshot or --no-snapshot, not both.",
                code="USAGE_ERROR",
                exit_code=2,
            )
        if snapshot:
            return True
        if no_snapshot:
            return False
        return None

    @app.command("add")
    def add_command(
        ctx: typer.Context,
        path: Annotated[str, typer.Option("--path")],
        kind: Annotated[str, typer.Option("--kind")] = "code",
        label: Annotated[str | None, typer.Option("--label")] = None,
        required_for_validation: Annotated[
            bool,
            typer.Option("--required-for-validation"),
        ] = False,
        snapshot: Annotated[bool, typer.Option("--snapshot")] = False,
        no_snapshot: Annotated[bool, typer.Option("--no-snapshot")] = False,
        task_ref: TaskOption = None,
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
                snapshot=_resolve_snapshot_option(snapshot, no_snapshot),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"linked file on {task.id}")

    @app.command("link")
    def link_command(
        ctx: typer.Context,
        task_ref_arg: Annotated[str, typer.Argument(help="Task ref.")],
        path: Annotated[str, typer.Argument(help="Linked file path.")],
        kind: Annotated[str, typer.Option("--kind")] = "code",
        label: Annotated[str | None, typer.Option("--label")] = None,
        required_for_validation: Annotated[
            bool,
            typer.Option("--required-for-validation"),
        ] = False,
        snapshot: Annotated[bool, typer.Option("--snapshot")] = False,
        no_snapshot: Annotated[bool, typer.Option("--no-snapshot")] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = add_file_link(
                state.cwd,
                task_ref_arg,
                path=path,
                kind=kind,
                label=label,
                required_for_validation=required_for_validation,
                snapshot=_resolve_snapshot_option(snapshot, no_snapshot),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"linked {path} on {task.id}")

    @app.command("remove")
    def remove_command(
        ctx: typer.Context,
        path: Annotated[str, typer.Option("--path")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = remove_file_link(state.cwd, task.id, path=path)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"unlinked file on {task.id}")

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
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

    @app.command("status")
    def status_command(
        ctx: typer.Context,
        task_ref_arg: Annotated[str, typer.Argument(help="Task ref.")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = file_status_api(state.cwd, task_ref_arg)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        links = payload.get("links", [])
        lines = [f"FILES {payload['task_id']}"]
        if isinstance(links, list) and links:
            for item in links:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").ljust(10)
                path = str(item.get("path") or "")
                kind = str(item.get("kind") or "")
                reason = str(item.get("reason") or "")
                current = item.get("current")
                hash_text = ""
                if isinstance(current, dict):
                    hash_value = current.get("hash")
                    if isinstance(hash_value, str) and hash_value:
                        hash_text = f" {hash_value[:16]}..."
                detail = reason if status.strip() != "unchanged" else hash_text.strip()
                lines.append(
                    f"  {status} {path} [{kind}]" + (f" {detail}" if detail else "")
                )
        else:
            lines.append("  (empty)")
        emit_payload(ctx, payload, human="\n".join(lines))

    @app.command("refresh")
    def refresh_command(
        ctx: typer.Context,
        task_ref_arg: Annotated[str, typer.Argument(help="Task ref.")],
        path: Annotated[str, typer.Argument(help="Linked file path.")],
        reason: Annotated[str, typer.Option("--reason")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = refresh_file_baseline_api(
                state.cwd,
                task_ref_arg,
                path=path,
                reason=reason,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human=f"refreshed baseline for {path} on {payload['task_id']}",
        )

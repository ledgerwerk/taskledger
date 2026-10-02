from __future__ import annotations

from typing import Annotated, Literal

import typer

from taskledger.cli_common import (
    CLIState,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.errors import LaunchError

app = typer.Typer(add_completion=False, help="Maintain safe Taskledger storage.")


@app.command("gc")
def garbage_collect_command(
    ctx: typer.Context,
    scope: Annotated[
        Literal["all", "runtime", "artifacts", "cache"],
        typer.Option(
            "--scope",
            help="Collection scope: all, runtime, artifacts, or cache.",
        ),
    ] = "all",
    task_id: Annotated[
        str | None,
        typer.Option("--task", help="Limit runtime/artifact cleanup to a task ID."),
    ] = None,
    older_than: Annotated[
        str | None,
        typer.Option("--older-than", help="Minimum age, for example 30d, 12h, or 60m."),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Delete eligible files. Default is dry-run."),
    ] = False,
    reason: Annotated[
        str,
        typer.Option("--reason", help="Reason for deleting evidence or runtime files."),
    ] = "",
) -> None:
    from taskledger.api.maintenance import garbage_collect

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = garbage_collect(
            state.cwd,
            scope=scope,
            task_id=task_id,
            older_than=older_than,
            apply=apply,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    candidates_raw = payload.get("candidates", [])
    candidates = candidates_raw if isinstance(candidates_raw, list) else []
    status = str(payload.get("status", "unknown"))
    bytes_value = payload.get("bytes_reclaimed" if apply else "bytes_reclaimable", 0)
    files_value = payload.get("files_reclaimed" if apply else "files_reclaimable", 0)
    lines = [
        (
            f"MAINTENANCE GC ({status}): {len(candidates)} candidate(s), "
            f"{files_value} file(s), {bytes_value} byte(s)"
        )
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        lines.append(
            f"  {candidate.get('scope')} {candidate.get('bytes')} B "
            f"{candidate.get('path')} ({candidate.get('reason_eligible')})"
        )
    audit_path = payload.get("audit_path")
    if audit_path:
        lines.append(f"Audit: {audit_path}")
    unsafe_paths = payload.get("unsafe_paths", [])
    if isinstance(unsafe_paths, list):
        for path in unsafe_paths:
            lines.append(f"  unsafe: {path}")
    emit_payload(ctx, payload, human="\n".join(lines))


__all__ = ["app"]

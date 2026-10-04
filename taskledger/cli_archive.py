from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

import typer

from taskledger.api.project import (
    project_export_archive,
    project_import,
    project_import_archive,
)
from taskledger.cli_common import (
    CLIState,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    resolve_cli_task,
)
from taskledger.errors import LaunchError


@dataclass(frozen=True)
class ArchiveExportRequest:
    target_or_output: str | None
    task_ref: str | None
    output: Path | None
    include_bodies: bool
    include_run_artifacts: bool
    overwrite: bool
    command_prefix: str


@dataclass(frozen=True)
class ArchiveImportRequest:
    source: Path
    replace: bool
    dry_run: bool
    lock_policy: str
    id_policy: str


def looks_like_archive_output_target(value: str) -> bool:
    candidate = value.strip()
    lowered = candidate.lower()
    if lowered.endswith((".tar.gz", ".tgz", ".json")):
        return True
    path = Path(candidate)
    if path.is_absolute():
        return True
    if "/" in candidate or "\\" in candidate:
        return True
    return path.parent != Path(".")


def resolve_archive_export_request(
    state: CLIState,
    request: ArchiveExportRequest,
) -> tuple[Path | None, list[str]]:
    resolved_output = request.output
    task_refs: list[str] = []
    if request.task_ref is not None:
        task_refs = [resolve_cli_task(state.cwd, request.task_ref).id]
        if request.target_or_output is not None:
            if request.output is not None:
                raise LaunchError(
                    "export received both positional output and --output. Use one. "
                    f"Example: {request.command_prefix} -o OUT.tar.gz",
                    exit_code=2,
                )
            resolved_output = Path(request.target_or_output)
    elif request.target_or_output is not None:
        if looks_like_archive_output_target(request.target_or_output):
            if request.output is not None:
                raise LaunchError(
                    "export received both positional output and --output. Use one. "
                    f"Example: {request.command_prefix} -o OUT.tar.gz",
                    exit_code=2,
                )
            resolved_output = Path(request.target_or_output)
        else:
            try:
                task_refs = [resolve_cli_task(state.cwd, request.target_or_output).id]
            except LaunchError as exc:
                raise LaunchError(
                    f"No task found for '{request.target_or_output}'. To write an "
                    "archive "
                    f"to that filename, use: {request.command_prefix} -o "
                    f"{request.target_or_output}.tar.gz",
                    exit_code=launch_error_exit_code(exc),
                ) from exc
    if (
        resolved_output is not None
        and resolved_output.exists()
        and not request.overwrite
    ):
        raise LaunchError(
            "Output file already exists: "
            f"{resolved_output}. Use --overwrite to replace.",
        )
    return resolved_output, task_refs


def run_archive_export(
    state: CLIState,
    request: ArchiveExportRequest,
) -> dict[str, object]:
    resolved_output, task_refs = resolve_archive_export_request(state, request)
    return project_export_archive(
        state.cwd,
        output_path=resolved_output,
        include_bodies=request.include_bodies,
        include_run_artifacts=request.include_run_artifacts,
        task_refs=task_refs,
        overwrite=request.overwrite,
    )


def run_archive_import(
    state: CLIState,
    request: ArchiveImportRequest,
    *,
    is_json_content: Callable[[Path], bool],
) -> tuple[dict[str, object], str]:
    source = request.source
    if source.suffix == ".json" or is_json_content(source):
        text = source.read_text(encoding="utf-8")
        return (
            project_import(
                state.cwd,
                text=text,
                replace=request.replace,
                dry_run=request.dry_run,
                lock_policy=request.lock_policy,
            ),
            "json",
        )
    return (
        project_import_archive(
            state.cwd,
            source_path=source,
            replace=request.replace,
            dry_run=request.dry_run,
            lock_policy=request.lock_policy,
            id_policy=request.id_policy,
        ),
        "archive",
    )


def render_archive_export_human(payload: dict[str, object]) -> str:
    counts = cast(dict[str, object], payload.get("counts", {}))
    project_name = cast(str | None, payload.get("project_name"))
    project_uuid = payload["project_uuid"]
    project_label = (
        f"{project_name} ({project_uuid})"
        if isinstance(project_name, str) and project_name.strip()
        else str(project_uuid)
    )
    return (
        f"exported taskledger archive: {payload['path']}\n"
        f"project: {project_label}\n"
        f"ledger: {payload['ledger_ref']}\n"
        f"scope: {payload.get('archive_scope', 'ledger')}\n"
        f"tasks: {counts.get('tasks', 0)}"
    )


def export_command(
    ctx: typer.Context,
    target_or_output: Annotated[
        str | None,
        typer.Argument(
            help="Task ref convenience selector or output archive path (.tar.gz)."
        ),
    ] = None,
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref to export as task-scoped archive."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output archive path (.tar.gz)."),
    ] = None,
    include_bodies: Annotated[
        bool,
        typer.Option(
            "--include-bodies/--no-include-bodies",
            help="Include Markdown bodies in the export.",
        ),
    ] = True,
    include_run_artifacts: Annotated[
        bool,
        typer.Option(
            "--include-run-artifacts",
            help="Include run artifact files in the export payload.",
        ),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Allow overwriting an existing output file."),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = run_archive_export(
            state,
            ArchiveExportRequest(
                target_or_output=target_or_output,
                task_ref=task_ref,
                output=output,
                include_bodies=include_bodies,
                include_run_artifacts=include_run_artifacts,
                overwrite=overwrite,
                command_prefix="taskledger export",
            ),
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=render_archive_export_human(payload))


def import_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(..., exists=True, readable=True)],
    replace: Annotated[
        bool,
        typer.Option("--replace", help="Replace existing taskledger state."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate archive without importing."),
    ] = False,
    lock_policy: Annotated[
        str,
        typer.Option(
            "--lock-policy",
            help="How imported live locks are handled: drop, quarantine, keep.",
        ),
    ] = "quarantine",
    id_policy: Annotated[
        str,
        typer.Option(
            "--id-policy",
            help=(
                "Task ID conflict policy for task archives: "
                "preserve, renumber-on-conflict, fail-on-conflict."
            ),
        ),
    ] = "preserve",
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload, import_kind = run_archive_import(
            state,
            ArchiveImportRequest(
                source=source,
                replace=replace,
                dry_run=dry_run,
                lock_policy=lock_policy,
                id_policy=id_policy,
            ),
            is_json_content=_is_json_content,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    if import_kind == "json":
        if dry_run:
            json_project = payload.get("project_name") or payload.get(
                "project_uuid", "(unknown)"
            )
            human = (
                f"dry-run JSON import: {source}\n"
                f"project: {json_project}\n"
                f"replace: {payload['replace']}\n"
                f"counts: {payload.get('counts', {})}"
            )
        else:
            human = "imported taskledger state"
        emit_payload(ctx, payload, human=human)
        return
    project_name = cast(str | None, payload.get("project_name"))
    project_uuid = payload["project_uuid"]
    project_label = (
        f"{project_name} ({project_uuid})"
        if isinstance(project_name, str) and project_name.strip()
        else str(project_uuid)
    )
    if dry_run:
        human = (
            f"dry-run archive import: {source}\n"
            f"project: {project_label}\n"
            f"ledger: {payload['ledger_ref']}\n"
            f"replace: {payload['replace']}\n"
            f"counts: {payload.get('imported', {})}"
        )
    else:
        human = (
            f"imported taskledger archive: {source}\n"
            f"project: {project_label}\n"
            f"ledger: {payload['ledger_ref']}\n"
            f"replace: {payload['replace']}\n"
            f"scope: {payload.get('archive_scope', 'ledger')}"
        )
    task_id_map = payload.get("task_id_map")
    if isinstance(task_id_map, dict) and task_id_map:
        id_lines = ["id map:"]
        for source_id, target_id in sorted(task_id_map.items()):
            if source_id == target_id:
                id_lines.append(f"  {source_id} -> {target_id}")
            else:
                id_lines.append(f"  {source_id} -> {target_id}  renumbered")
        human = f"{human}\n" + "\n".join(id_lines)
    if isinstance(payload.get("next_command"), str):
        human = f"{human}\nnext: {payload['next_command']}"
    emit_payload(ctx, payload, human=human)


def _is_json_content(path: Path) -> bool:
    """Return True if file appears to contain JSON (starts with '{')."""
    try:
        with path.open("rb") as f:
            return f.read(1) == b"{"
    except OSError:
        return False


def register_archive_commands(app: typer.Typer) -> None:
    app.command("export")(export_command)
    app.command("import")(import_command)

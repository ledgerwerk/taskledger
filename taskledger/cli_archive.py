from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from taskledger.api.project import (
    project_export_archive,
    project_import,
    project_import_archive,
)
from taskledger.cli_common import CLIState, launch_error_exit_code, resolve_cli_task
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

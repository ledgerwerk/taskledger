from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

from taskledger.api.project import (
    project_export_archive,
    project_import,
    project_import_archive,
)
from taskledger.api.storage import sync_commit, sync_preflight, sync_status
from taskledger.api.sync import (
    sync_git_export_local,
    sync_git_hooks_install,
    sync_git_hooks_status,
    sync_git_hooks_uninstall,
    sync_git_import_local,
    sync_git_init,
    sync_git_pull,
    sync_git_push,
    sync_git_status,
    sync_git_sync,
)
from taskledger.cli_common import (
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.errors import LaunchError


def _render_sync_preflight(payload: dict[str, object]) -> str:
    location = payload["location"]
    assert isinstance(location, dict)
    lines = [
        f"Storage: {location['taskledger_dir']}",
        f"Exists: {'yes' if payload['taskledger_dir_exists'] else 'no'}",
        f"Doctor: {'healthy' if payload['doctor_healthy'] else 'issues found'}",
        f"Active locks: {location['active_lock_count']}",
        (
            "Tracked in workspace Git: "
            f"{'yes' if payload['tracked_in_workspace_git'] else 'no'}"
        ),
    ]
    git_status_lines = payload.get("git_status_lines", [])
    if isinstance(git_status_lines, list) and git_status_lines:
        lines.append("Git status:")
        lines.extend(str(item) for item in git_status_lines)
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    return "\n".join(lines)


def _render_sync_status(payload: dict[str, object]) -> str:
    lines = [
        f"Storage: {payload['taskledger_dir']}",
        f"Git repo: {payload['git_root'] or 'no'}",
        f"Active locks: {payload['active_lock_count']}",
    ]
    status_lines = payload.get("status_lines", [])
    if isinstance(status_lines, list) and status_lines:
        lines.append("Git status:")
        lines.extend(str(item) for item in status_lines)
    else:
        lines.append("Git status: clean")
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    return "\n".join(lines)


def _render_sync_commit(payload: dict[str, object]) -> str:
    lines = [
        f"Committed storage repo at {payload['git_root']}",
        f"Commit: {payload['commit']}",
        f"Path: {payload['relative_path']}",
    ]
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    return "\n".join(lines)


def _looks_like_archive_output_target(value: str) -> bool:
    candidate = value.strip()
    lowered = candidate.lower()
    if (
        lowered.endswith(".tar.gz")
        or lowered.endswith(".tgz")
        or lowered.endswith(".json")
    ):
        return True
    path = Path(candidate)
    if path.is_absolute():
        return True
    if "/" in candidate or "\\" in candidate:
        return True
    return path.parent != Path(".")


def _is_json_content(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(1) == b"{"
    except OSError:
        return False


def register_sync_commands(app: typer.Typer) -> None:  # noqa: C901
    sync_git_app = typer.Typer(
        add_completion=False,
        help="Sync taskledger state through a Git repository.",
    )
    sync_git_hooks_app = typer.Typer(
        add_completion=False,
        help="Manage taskledger-managed Git hooks.",
    )
    app.add_typer(sync_git_app, name="git")
    sync_git_app.add_typer(sync_git_hooks_app, name="hooks")

    @app.command("preflight")
    def preflight_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_preflight(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="sync_preflight",
            human=_render_sync_preflight(payload),
        )

    @app.command("status")
    def status_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_status(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="sync_status",
            human=_render_sync_status(payload),
        )

    @app.command("commit")
    def commit_command(
        ctx: typer.Context,
        message: Annotated[
            str,
            typer.Option(
                "--message",
                help="Commit message for storage state.",
            ),
        ],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_commit(state.cwd, message=message)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            result_type="sync_commit",
            human=_render_sync_commit(payload),
        )

    @app.command("export")
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
            typer.Option(
                "--overwrite",
                help="Allow overwriting an existing output file.",
            ),
        ] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        resolved_output = output
        task_refs: list[str] = []
        if task_ref is not None:
            from taskledger.cli_common import resolve_cli_task

            task_refs = [resolve_cli_task(state.cwd, task_ref).id]
            if target_or_output is not None:
                if output is not None:
                    emit_error(
                        ctx,
                        LaunchError(
                            "export received both positional output and --output. "
                            "Use one."
                        ),
                    )
                    raise typer.Exit(code=2)
                resolved_output = Path(target_or_output)
        elif target_or_output is not None:
            if _looks_like_archive_output_target(target_or_output):
                if output is not None:
                    emit_error(
                        ctx,
                        LaunchError(
                            "export received both positional output and --output. "
                            "Use one."
                        ),
                    )
                    raise typer.Exit(code=2)
                resolved_output = Path(target_or_output)
            else:
                from taskledger.cli_common import resolve_cli_task

                try:
                    task_refs = [resolve_cli_task(state.cwd, target_or_output).id]
                except LaunchError as exc:
                    emit_error(
                        ctx,
                        LaunchError(
                            f"No task found for '{target_or_output}'. To write "
                            "an archive "
                            "to that filename, use: taskledger sync export -o "
                            f"{target_or_output}.tar.gz"
                        ),
                    )
                    raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        if resolved_output is not None and resolved_output.exists() and not overwrite:
            emit_error(
                ctx,
                LaunchError(
                    "Output file already exists: "
                    f"{resolved_output}. Use --overwrite to replace."
                ),
            )
            raise typer.Exit(code=1)
        try:
            payload = project_export_archive(
                state.cwd,
                output_path=resolved_output,
                include_bodies=include_bodies,
                include_run_artifacts=include_run_artifacts,
                task_refs=task_refs,
                overwrite=overwrite,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        counts = cast(dict[str, object], payload.get("counts", {}))
        project_name = cast(str | None, payload.get("project_name"))
        project_uuid = payload["project_uuid"]
        project_label = (
            f"{project_name} ({project_uuid})"
            if isinstance(project_name, str) and project_name.strip()
            else str(project_uuid)
        )
        human = (
            f"exported taskledger archive: {payload['path']}\n"
            f"project: {project_label}\n"
            f"ledger: {payload['ledger_ref']}\n"
            f"scope: {payload.get('archive_scope', 'ledger')}\n"
            f"tasks: {counts.get('tasks', 0)}"
        )
        emit_payload(ctx, payload, human=human)

    @app.command("import")
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
        state = cli_state_from_context(ctx)
        if source.suffix == ".json" or _is_json_content(source):
            text = source.read_text(encoding="utf-8")
            try:
                payload = project_import(
                    state.cwd,
                    text=text,
                    replace=replace,
                    dry_run=dry_run,
                    lock_policy=lock_policy,
                )
            except LaunchError as exc:
                emit_error(ctx, exc)
                raise typer.Exit(code=launch_error_exit_code(exc)) from exc
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
        try:
            payload = project_import_archive(
                state.cwd,
                source_path=source,
                replace=replace,
                dry_run=dry_run,
                lock_policy=lock_policy,
                id_policy=id_policy,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        project_name = cast(str | None, payload.get("project_name"))
        project_uuid = payload["project_uuid"]
        project_label = (
            f"{project_name} ({project_uuid})"
            if isinstance(project_name, str) and project_name.strip()
            else str(project_uuid)
        )
        human = (
            ("validated archive import" if dry_run else "imported taskledger archive")
            + f": {source}\n"
            + f"project: {project_label}\n"
            + f"ledger: {payload.get('ledger_ref', '(unknown)')}\n"
            + f"scope: {payload.get('archive_scope', 'ledger')}\n"
            + f"replace: {payload['replace']}\n"
            + f"id policy: {payload.get('id_policy', id_policy)}\n"
            + f"lock policy: {payload.get('lock_policy', lock_policy)}\n"
            + f"summary: {payload.get('summary', '')}"
        )
        emit_payload(ctx, payload, human=human)

    @sync_git_app.command("init")
    def git_init_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        remote_url: Annotated[str | None, typer.Option("--remote-url")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        adopt_existing: Annotated[bool, typer.Option("--adopt-existing")] = False,
        mode: Annotated[str, typer.Option("--mode", help="move or copy")] = "move",
        hooks: Annotated[bool, typer.Option("--hooks/--no-hooks")] = False,
        force_hooks: Annotated[bool, typer.Option("--force-hooks")] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_init(
                state.cwd,
                repo=repo,
                remote_url=remote_url,
                remote=remote,
                branch=branch,
                project_path=project_path,
                adopt_existing=adopt_existing,
                mode=mode,
                install_hooks=hooks,
                force_hooks=force_hooks,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Git sync repository initialized:\n"
            f"  repo: {payload['repo_path']}\n"
            f"  project path: {payload['project_path']}\n"
            f"  storage: {payload['storage_path']}\n"
            f"  branch: {payload['branch']}\n"
            f"  remote: {payload['remote']}\n"
            "  taskledger_dir updated: "
            f"{'yes' if payload['taskledger_dir_updated'] else 'no'}"
        )
        emit_payload(ctx, payload, result_type="sync_git_init", human=human)

    @sync_git_app.command("status")
    def git_status_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_status(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Git sync status:\n"
            f"  repo: {payload['repo_path']}\n"
            f"  project path: {payload['project_path']}\n"
            f"  dirty: {'yes' if payload['dirty'] else 'no'}\n"
            f"  ahead: {payload['ahead']}\n"
            f"  behind: {payload['behind']}\n"
            f"  active locks: {payload['active_lock_count']}"
        )
        emit_payload(ctx, payload, result_type="sync_git_status", human=human)

    @sync_git_app.command("import-local")
    def git_import_local_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        quiet: Annotated[bool, typer.Option("--quiet")] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_import_local(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Local import:\n"
            f"  repo: {payload['repo_path']}\n"
            f"  project path: {payload['project_path']}\n"
            "  taskledger_dir updated: "
            f"{'yes' if payload['taskledger_dir_updated'] else 'no'}\n"
            f"  doctor: {'healthy' if payload['doctor_healthy'] else 'issues'}"
        )
        emit_payload(
            ctx,
            payload,
            result_type="sync_git_import_local",
            human="" if quiet else human,
        )

    @sync_git_app.command("export-local")
    def git_export_local_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        message: Annotated[str | None, typer.Option("--message")] = None,
        allow_dirty: Annotated[bool, typer.Option("--allow-dirty")] = False,
        allow_active_locks: Annotated[
            bool, typer.Option("--allow-active-locks")
        ] = False,
        quiet: Annotated[bool, typer.Option("--quiet")] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_export_local(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
                message=message,
                allow_dirty=allow_dirty,
                allow_active_locks=allow_active_locks,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Git export (local only):\n"
            f"  repo: {payload['repo_path']}\n"
            f"  project path: {payload['project_path']}\n"
            f"  committed: {'yes' if payload['committed'] else 'no'}\n"
            f"  commit: {payload['commit_hash'] or '-'}"
        )
        emit_payload(
            ctx,
            payload,
            result_type="sync_git_export_local",
            human="" if quiet else human,
        )

    @sync_git_app.command("pull")
    def git_pull_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        allow_dirty: Annotated[bool, typer.Option("--allow-dirty")] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_pull(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
                allow_dirty=allow_dirty,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Git pull/import:\n"
            f"  repo: {payload['repo_path']}\n"
            f"  project path: {payload['project_path']}\n"
            f"  pulled: {'yes' if payload['pulled'] else 'no'}\n"
            f"  doctor: {'healthy' if payload['doctor_healthy'] else 'issues'}"
        )
        emit_payload(ctx, payload, result_type="sync_git_pull", human=human)

    @sync_git_app.command("push")
    def git_push_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        message: Annotated[str | None, typer.Option("--message")] = None,
        allow_dirty: Annotated[bool, typer.Option("--allow-dirty")] = False,
        allow_active_locks: Annotated[
            bool, typer.Option("--allow-active-locks")
        ] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_push(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
                message=message,
                allow_dirty=allow_dirty,
                allow_active_locks=allow_active_locks,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Git push/export:\n"
            f"  repo: {payload['repo_path']}\n"
            f"  project path: {payload['project_path']}\n"
            f"  committed: {'yes' if payload['committed'] else 'no'}\n"
            f"  commit: {payload['commit_hash'] or '-'}\n"
            f"  pushed: {'yes' if payload['pushed'] else 'no'}"
        )
        emit_payload(ctx, payload, result_type="sync_git_push", human=human)

    @sync_git_app.command("sync")
    def git_sync_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        message: Annotated[str | None, typer.Option("--message")] = None,
        allow_dirty: Annotated[bool, typer.Option("--allow-dirty")] = False,
        allow_active_locks: Annotated[
            bool, typer.Option("--allow-active-locks")
        ] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_sync(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
                message=message,
                allow_dirty=allow_dirty,
                allow_active_locks=allow_active_locks,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Git sync:\n"
            f"  repo: {payload['repo_path']}\n"
            f"  pulled: {'yes' if payload['pulled'] else 'no'}\n"
            f"  committed: {'yes' if payload['committed'] else 'no'}\n"
            f"  pushed: {'yes' if payload['pushed'] else 'no'}"
        )
        emit_payload(ctx, payload, result_type="sync_git_sync", human=human)

    @sync_git_hooks_app.command("install")
    def hooks_install_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
        force: Annotated[bool, typer.Option("--force")] = False,
        quiet: Annotated[bool, typer.Option("--quiet")] = True,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_hooks_install(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
                force=force,
                quiet=quiet,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Installed hooks: "
            + ", ".join(cast(list[str], payload["installed"]) or ["none"])
            + "\nSkipped hooks: "
            + ", ".join(cast(list[str], payload["skipped"]) or ["none"])
        )
        emit_payload(ctx, payload, result_type="sync_git_hooks_install", human=human)

    @sync_git_hooks_app.command("status")
    def hooks_status_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_hooks_status(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = "\n".join(
            f"{item['hook']}: {item['status']}"
            for item in cast(list[dict[str, str]], payload["hooks"])
        )
        emit_payload(ctx, payload, result_type="sync_git_hooks_status", human=human)

    @sync_git_hooks_app.command("uninstall")
    def hooks_uninstall_command(
        ctx: typer.Context,
        repo: Annotated[Path | None, typer.Option("--repo")] = None,
        project_path: Annotated[str | None, typer.Option("--project-path")] = None,
        remote: Annotated[str | None, typer.Option("--remote")] = None,
        branch: Annotated[str | None, typer.Option("--branch")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = sync_git_hooks_uninstall(
                state.cwd,
                repo=repo,
                project_path=project_path,
                remote=remote,
                branch=branch,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            "Removed hooks: "
            + ", ".join(cast(list[str], payload["removed"]) or ["none"])
            + "\nSkipped hooks: "
            + ", ".join(cast(list[str], payload["skipped"]) or ["none"])
        )
        emit_payload(ctx, payload, result_type="sync_git_hooks_uninstall", human=human)

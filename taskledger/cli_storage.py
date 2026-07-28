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


def _render_lock_breakdown(payload: dict[str, object]) -> list[str]:
    """Render the lock breakdown section."""
    lines: list[str] = []
    locks = payload.get("locks")
    if isinstance(locks, dict):
        lock_file_count = locks.get("lock_file_count")
        active = locks.get("active_count", 0)
        expired = locks.get("expired_count")
        stale = locks.get("stale_count")
        malformed = locks.get("malformed_count")
        unverifiable = locks.get("unverifiable_count")
        parts = [f"{active} active"]
        if expired:
            parts.append(f"{expired} expired")
        if stale:
            parts.append(f"{stale} stale")
        if malformed:
            parts.append(f"{malformed} malformed")
        if unverifiable:
            parts.append(f"{unverifiable} unverifiable")
        if lock_file_count is not None:
            lines.append(f"Locks: {lock_file_count} file(s): {', '.join(parts)}")
        else:
            lines.append(f"Active locks: {active}")
    else:
        lines.append(f"Active locks: {payload.get('active_lock_count', 0)}")
    return lines


def _render_issues_and_next(payload: dict[str, object]) -> list[str]:
    """Render issues and next commands sections."""
    lines: list[str] = []
    issues = payload.get("issues")
    if isinstance(issues, list) and issues:
        lines.append("")
        lines.append("Issues:")
        for issue in issues:
            if isinstance(issue, dict):
                severity = issue.get("severity", "info")
                code = issue.get("code", "")
                message = issue.get("message", "")
                lines.append(f"- [{severity}:{code}] {message}")
                for rem in issue.get("remediation", []):
                    if isinstance(rem, str):
                        lines.append(f"  remedy: {rem}")
    next_commands = payload.get("next_commands")
    if isinstance(next_commands, list) and next_commands:
        lines.append("")
        lines.append("Next:")
        for idx, cmd in enumerate(next_commands, 1):
            if isinstance(cmd, str):
                lines.append(f"{idx}. {cmd}")
    return lines


def _render_legacy_storage_where(payload: dict[str, object]) -> str:
    """Render storage where for legacy layout."""
    lines = [
        "Mode: legacy",
        f"Workspace: {payload.get('workspace_root')}",
        f"Config: {payload.get('config_path')}",
        f"Storage: {payload.get('taskledger_dir')}",
        f"Project: {payload.get('project_name')} "
        f"[{payload.get('project_uuid') or 'no UUID'}]",
        f"Ledger: {payload.get('ledger_ref')}",
        f"Inside workspace: {payload.get('inside_workspace')}",
    ]
    git = payload.get("git")
    if isinstance(git, dict):
        tracked = git.get("tracked")
        ignored = git.get("ignored")
        git_root = git.get("root")
        if git_root:
            lines.append(f"Git repo: {git_root}")
        if tracked is not None:
            lines.append(f"Git tracked: {tracked}")
        if ignored is not None:
            lines.append(f"Git ignored: {ignored}")
    else:
        lines.append(f"Git repo: {payload.get('git_root')}")
    lines.extend(_render_lock_breakdown(payload))
    # Backward-compat warnings.
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    lines.extend(_render_issues_and_next(payload))
    # Migration guidance for legacy mode
    lines.append("")
    lines.append("Migration required: yes")
    lines.append("")
    lines.append("Next:")
    lines.append("1. taskledger migrate plan")
    lines.append("2. taskledger migrate apply")
    return "\n".join(lines)


def _render_canonical_storage_where(payload: dict[str, object]) -> str:
    """Render storage where for canonical layout."""
    project = payload.get("project", {})
    project = project if isinstance(project, dict) else {}
    config = payload.get("config", {})
    config = config if isinstance(config, dict) else {}
    lines = [
        f"Project root: {project.get('root', payload.get('project_root'))}",
        f"Project UUID: {project.get('uuid', payload.get('project_uuid'))}",
    ]
    manifest = payload.get("manifest", {})
    manifest_path = (
        manifest.get("path")
        if isinstance(manifest, dict)
        else payload.get("manifest_path")
    )
    if manifest_path:
        lines.append(f"Manifest: {manifest_path}")
    lines.append(f"Config: {config.get('path', payload.get('config_path'))}")
    lines.extend(_render_lock_breakdown(payload))
    mounts = payload.get("mounts", {})
    if isinstance(mounts, dict) and mounts:
        lines.append("Mounts:")
        for name, mount in mounts.items():
            if isinstance(mount, dict):
                initialized = "yes" if mount.get("initialized") else "no"
                lines.extend(
                    [
                        f"  {name}",
                        f"    storage: {mount.get('storage')}",
                        f"    source: {mount.get('source')}",
                        f"    root: {mount.get('root')}",
                        f"    path: {mount.get('path')}",
                        f"    initialized: {initialized}",
                    ]
                )
    # Backward-compat warnings.
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings if isinstance(item, str))
    lines.extend(_render_issues_and_next(payload))
    return "\n".join(lines)


def _render_storage_where(payload: dict[str, object]) -> str:
    mode = payload.get("mode", "legacy")
    if mode == "canonical":
        return _render_canonical_storage_where(payload)
    return _render_legacy_storage_where(payload)


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
    def validate_command(
        ctx: typer.Context,
        strict: Annotated[
            bool,
            typer.Option(
                "--strict",
                help="Run strict validation with additional checks.",
            ),
        ] = False,
    ) -> None:
        """Validate storage configuration.

        Checks that storage paths are valid and accessible.
        Use --strict for additional binding and fingerprint checks.
        """
        state = cli_state_from_context(ctx)
        try:
            payload = storage_validate(state.cwd, strict=strict)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, result_type="storage_validate", human=str(payload))

    @app.command("set")
    def set_command(
        ctx: typer.Context,
        mount: Annotated[str, typer.Argument(help="Mount name (e.g., data, indexes).")],
        storage: Annotated[
            str,
            typer.Argument(
                help="Storage kind: project, external, user-data, or cache."
            ),
        ],
        storage_root: Annotated[
            str | None,
            typer.Option(
                "--storage-root",
                help="External storage root path (for external storage).",
            ),
        ] = None,
        scope: Annotated[
            str | None,
            typer.Option(
                "--scope",
                help="Configuration scope: project or local.",
            ),
        ] = None,
        # Deprecated aliases
        root: Annotated[
            str | None,
            typer.Option(
                "--root",
                help="Deprecated: use --storage-root instead.",
                hidden=True,
            ),
        ] = None,
        project: Annotated[
            bool,
            typer.Option(
                "--project",
                help="Deprecated: use --scope project instead.",
                hidden=True,
            ),
        ] = False,
        local: Annotated[
            bool,
            typer.Option(
                "--local",
                help="Deprecated: use --scope local instead.",
                hidden=True,
            ),
        ] = False,
    ) -> None:
        """Set storage topology for a mount.

        This command changes configuration only. It does NOT copy, move, or
        delete data. If data relocation is needed, use `taskledger migrate`.
        """
        state = cli_state_from_context(ctx)

        # Resolve scope from deprecated options if not provided
        if scope is None:
            if project and not local:
                scope = "project"
            elif local and not project:
                scope = "local"
            else:
                scope = "project"  # default

        # Resolve storage_root from deprecated --root if not provided
        resolved_root = storage_root or root

        try:
            payload = storage_set(
                state.cwd,
                mount=mount,
                storage=storage,
                target=scope,
                external_root=resolved_root,
                mode="copy",  # Topology-only, no data movement
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
        mode: Annotated[str, typer.Option("--mode")] = "copy",
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

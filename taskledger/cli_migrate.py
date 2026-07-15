"""CLI commands for taskledger migrate: status, plan, apply."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

from taskledger.cli_common import (
    CLIState,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.domain.states import TASKLEDGER_STORAGE_LAYOUT_VERSION
from taskledger.errors import LaunchError
from taskledger.storage.layout_migration import (
    apply_layout_migration,
    build_layout_migration_plan,
    migration_status,
)
from taskledger.storage.migrations import (
    apply_layout_migrations,
    required_layout_migrations,
    scan_records_for_migration,
)

migrate_app = typer.Typer(
    add_completion=False,
    help="Inspect and apply storage migrations.",
)


@migrate_app.command("status")
def migrate_status_command(ctx: typer.Context) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        layout_status = migration_status(state.cwd)
    except LaunchError:
        layout_status = None
    if isinstance(layout_status, dict) and layout_status.get("project_mode") in {
        "legacy",
        "canonical",
    }:
        emit_payload(
            ctx,
            layout_status,
            human="MIGRATE STATUS\n"
            + "\n".join(
                f"  {key}: {value}"
                for key, value in layout_status.items()
                if key != "kind"
            ),
        )
        return
    try:
        from taskledger.storage.meta import read_storage_meta

        meta = read_storage_meta(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    if meta is None:
        payload = {
            "ok": True,
            "status": "no_storage_meta",
            "message": (
                "No storage.yaml found."
                " Run 'taskledger init' or 'taskledger migrate apply'."
            ),
            "current_layout_version": None,
            "target_layout_version": TASKLEDGER_STORAGE_LAYOUT_VERSION,
            "pending_migrations": [],
            "records_needing_migration": 0,
        }
        human = (
            "MIGRATE STATUS\n"
            "  No storage.yaml found.\n"
            "  Run 'taskledger init' or 'taskledger migrate apply'."
        )
        emit_payload(ctx, payload, human=human)
        return

    try:
        pending = required_layout_migrations(
            meta.storage_layout_version, TASKLEDGER_STORAGE_LAYOUT_VERSION
        )
    except LaunchError as exc:
        payload = {
            "ok": False,
            "status": "migration_unavailable",
            "message": str(exc),
            "current_layout_version": meta.storage_layout_version,
            "target_layout_version": TASKLEDGER_STORAGE_LAYOUT_VERSION,
        }
        emit_error(ctx, exc)
        emit_payload(ctx, payload, human=f"MIGRATE STATUS\n  Error: {exc}")
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    try:
        records = scan_records_for_migration(state.cwd)
    except LaunchError:
        records = []

    needs_migration = len(pending) > 0 or len(records) > 0
    payload = {
        "ok": True,
        "status": "migration_needed" if needs_migration else "up_to_date",
        "current_layout_version": meta.storage_layout_version,
        "target_layout_version": TASKLEDGER_STORAGE_LAYOUT_VERSION,
        "pending_migrations": [
            {"from": m.from_version, "to": m.to_version, "name": m.name}
            for m in pending
        ],
        "records_needing_migration": len(records),
    }
    if needs_migration:
        human_lines = [
            "MIGRATE STATUS",
            f"  Layout version: {meta.storage_layout_version}"
            f" -> {TASKLEDGER_STORAGE_LAYOUT_VERSION}",
            f"  Pending layout migrations: {len(pending)}",
            f"  Records needing migration: {len(records)}",
        ]
    else:
        human_lines = [
            "MIGRATE STATUS",
            f"  Layout version: {meta.storage_layout_version} (up to date)",
            "  No migrations needed.",
        ]
    emit_payload(ctx, payload, human="\n".join(human_lines))


@migrate_app.command("plan")
def migrate_plan_command(ctx: typer.Context) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    payload: dict[str, object]
    try:
        layout_status = migration_status(state.cwd)
    except LaunchError:
        layout_status = None
    if isinstance(layout_status, dict) and layout_status.get("project_mode") in {
        "legacy",
        "canonical",
    }:
        if layout_status.get("project_mode") == "canonical":
            payload = {"kind": "migration_plan", "status": "up_to_date", "plan": {}}
            emit_payload(
                ctx,
                payload,
                human="MIGRATE PLAN\n  Canonical layout is already active.",
            )
            return
        try:
            plan = build_layout_migration_plan(state.cwd)
            payload = {
                "kind": "migration_plan",
                "status": "ready",
                "plan": plan.to_dict(),
            }
            plan_payload = cast(dict[str, object], payload["plan"])
            human = "MIGRATE PLAN\n" + "\n".join(
                f"  {key}: {value}"
                for key, value in plan_payload.items()
                if key != "items"
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=human)
        return
    try:
        from taskledger.storage.meta import read_storage_meta

        meta = read_storage_meta(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    if meta is None:
        payload = {
            "ok": True,
            "status": "no_storage_meta",
            "message": "No storage.yaml found. Nothing to plan.",
            "migrations": [],
            "records": [],
        }
        emit_payload(ctx, payload, human="MIGRATE PLAN\n  No storage.yaml found.")
        return

    try:
        pending = required_layout_migrations(
            meta.storage_layout_version, TASKLEDGER_STORAGE_LAYOUT_VERSION
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    try:
        records = scan_records_for_migration(state.cwd)
    except LaunchError:
        records = []

    payload = {
        "ok": True,
        "current_layout_version": meta.storage_layout_version,
        "target_layout_version": TASKLEDGER_STORAGE_LAYOUT_VERSION,
        "migrations": [
            {"from": m.from_version, "to": m.to_version, "name": m.name}
            for m in pending
        ],
        "records": [
            {
                "path": str(r.path),
                "object_type": r.object_type,
                "current_version": r.current_version,
                "target_version": r.target_version,
            }
            for r in records
        ],
    }
    human_lines = [
        "MIGRATE PLAN",
        f"  Layout: {meta.storage_layout_version}"
        f" -> {TASKLEDGER_STORAGE_LAYOUT_VERSION}",
        f"  Layout migrations: {len(pending)}",
        f"  Records to migrate: {len(records)}",
    ]
    for m in pending:
        human_lines.append(
            f"    - {m.name} (layout {m.from_version} -> {m.to_version})"
        )
    for r in records:
        human_lines.append(
            f"    - {r.path.name} ({r.object_type}:"
            f" {r.current_version} -> {r.target_version})"
        )
    emit_payload(ctx, payload, human="\n".join(human_lines))


@migrate_app.command("apply")
def migrate_apply_command(
    ctx: typer.Context,
    backup: Annotated[
        bool,
        typer.Option("--backup", help="Create a snapshot before applying migrations."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be done without writing."),
    ] = False,
    project_uuid: Annotated[str | None, typer.Option("--project-uuid")] = None,
    retire_legacy: Annotated[
        bool,
        typer.Option(
            "--retire-legacy", help="Rename verified legacy files after migration."
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        layout_context = migration_status(state.cwd, project_uuid=project_uuid)
    except LaunchError:
        layout_context = None
    if (
        isinstance(layout_context, dict)
        and layout_context.get("project_mode") == "legacy"
    ):
        try:
            payload = apply_layout_migration(
                state.cwd,
                backup=backup,
                project_uuid=project_uuid,
                dry_run=dry_run,
                retire_legacy=retire_legacy,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human=(
                f"MIGRATE APPLY{' (dry run)' if dry_run else ''}\n"
                f"  status: {payload.get('status')}"
            ),
        )
        return
    try:
        from taskledger.storage.meta import read_storage_meta

        meta = read_storage_meta(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    if meta is None:
        payload = {
            "ok": False,
            "status": "no_storage_meta",
            "message": "No storage.yaml found. Run 'taskledger init' first.",
        }
        emit_error(ctx, LaunchError(str(payload["message"])))
        raise typer.Exit(code=2)

    if meta.storage_layout_version > TASKLEDGER_STORAGE_LAYOUT_VERSION:
        too_new = LaunchError(
            f"Storage layout {meta.storage_layout_version} is newer than "
            f"supported {TASKLEDGER_STORAGE_LAYOUT_VERSION}."
            " Upgrade taskledger."
        )
        emit_error(ctx, too_new)
        raise typer.Exit(code=launch_error_exit_code(too_new)) from too_new

    if meta.storage_layout_version == TASKLEDGER_STORAGE_LAYOUT_VERSION:
        payload = {
            "ok": True,
            "status": "up_to_date",
            "message": "No migrations needed.",
            "applied_migrations": [],
        }
        emit_payload(ctx, payload, human="MIGRATE APPLY\n  Already up to date.")
        return

    # Create backup if requested
    snapshot_dir: str | None = None
    if backup and not dry_run:
        from taskledger.api.project import project_snapshot

        snapshot_path = Path.cwd() / ".taskledger" / "snapshots"
        result = project_snapshot(
            state.cwd,
            output_dir=snapshot_path,
        )
        snapshot_dir = str(result.get("snapshot_dir", "")) or None

    # Apply migrations
    try:
        applied = apply_layout_migrations(
            state.cwd,
            meta.storage_layout_version,
            dry_run=dry_run,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    # Write audit record
    if not dry_run and applied:
        _write_migration_audit(state.cwd, meta.storage_layout_version, applied)

    # Rebuild indexes
    if not dry_run and applied:
        try:
            from taskledger.storage.indexes import rebuild_v2_indexes
            from taskledger.storage.task_store import resolve_v2_paths

            v2_paths = resolve_v2_paths(state.cwd)
            rebuild_v2_indexes(v2_paths)
        except LaunchError:
            pass  # Index rebuild is best-effort after migration

    payload = {
        "ok": True,
        "status": "dry_run" if dry_run else "applied",
        "from_layout_version": meta.storage_layout_version,
        "to_layout_version": TASKLEDGER_STORAGE_LAYOUT_VERSION,
        "applied_migrations": applied,
        "snapshot_dir": snapshot_dir,
    }
    human_lines = [
        "MIGRATE APPLY" + (" (dry run)" if dry_run else ""),
        f"  Layout: {meta.storage_layout_version}"
        f" -> {TASKLEDGER_STORAGE_LAYOUT_VERSION}",
        f"  Applied migrations: {len(applied)}",
    ]
    for name in applied:
        human_lines.append(f"    - {name}")
    if snapshot_dir:
        human_lines.append(f"  Backup: {snapshot_dir}")
    emit_payload(ctx, payload, human="\n".join(human_lines))


def _write_migration_audit(
    workspace_root: Path,
    from_version: int,
    applied_names: list[str],
) -> None:
    """Write a migration audit record to .taskledger/migrations/."""
    from taskledger.storage.paths import resolve_taskledger_root
    from taskledger.timeutils import utc_now_iso

    project_dir = resolve_taskledger_root(workspace_root)
    migrations_dir = project_dir / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    timestamp = utc_now_iso().replace(":", "").replace("-", "").replace("+", "")
    audit_path = migrations_dir / (
        f"{timestamp[:15]}-layout-{from_version}"
        f"-to-{TASKLEDGER_STORAGE_LAYOUT_VERSION}.md"
    )

    try:
        from taskledger._version import __version__ as tl_version
    except ImportError:
        tl_version = "unknown"

    front_matter = (
        "---\n"
        f"schema_version: 1\n"
        f"object_type: migration_audit\n"
        f"from_layout_version: {from_version}\n"
        f"to_layout_version: {TASKLEDGER_STORAGE_LAYOUT_VERSION}\n"
        f"taskledger_version: {tl_version}\n"
        f'created_at: "{utc_now_iso()}"\n'
        "---\n\n"
    )
    body = (
        f"# Migration layout {from_version} -> {TASKLEDGER_STORAGE_LAYOUT_VERSION}\n\n"
    )
    body += "## Applied migrations\n\n"
    for name in applied_names:
        body += f"- {name}\n"
    body += "\n"

    audit_path.write_text(front_matter + body, encoding="utf-8")

"""CLI commands for taskledger ledger: status, list, fork, switch, adopt, doctor."""

from __future__ import annotations

from typing import Annotated

import typer

from taskledger.cli_common import (
    CLIState,
    emit_error,
    emit_payload,
    launch_error_exit_code,
)
from taskledger.errors import LaunchError

ledger_app = typer.Typer(
    add_completion=False,
    help="Manage branch-scoped ledger namespaces.",
)


@ledger_app.command("status")
def ledger_status_command(ctx: typer.Context) -> None:
    """Show the current ledger ref, parent, next task, and storage path."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.refs import global_ref_for_local_id
        from taskledger.storage.ledger_config import (
            load_ledger_config,
            load_ledger_identity,
        )
        from taskledger.storage.paths import load_project_locator
        from taskledger.storage.task_store import list_tasks, resolve_v2_paths

        locator = load_project_locator(state.cwd)
        config = load_ledger_config(locator.config_path)
        identity = load_ledger_identity(locator.config_path)
        paths = resolve_v2_paths(state.cwd)
        tasks = list_tasks(state.cwd)
        from taskledger.storage.task_store import load_active_task_state

        active = load_active_task_state(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    task_count = len(tasks)
    active_task_id = active.task_id if active else None
    from taskledger.storage.task_ids import scan_task_id_inventory

    next_task_id = scan_task_id_inventory(paths).next_task_id
    next_task_ref = global_ref_for_local_id(state.cwd, next_task_id)
    payload = {
        "ok": True,
        "kind": "ledger_status",
        "ledger_code": identity.code,
        "ledger_name": identity.name,
        "ledger_ref": config.ref,
        "ledger_parent_ref": config.parent_ref,
        "ledger_dir": str(paths.ledger_dir),
        "task_count": task_count,
        "active_task_id": active_task_id,
        "next_task_id": next_task_id,
        "next_task_ref": next_task_ref,
    }
    parent_display = config.parent_ref or "none"
    active_display = active_task_id or "none"
    human_lines = [
        "LEDGER STATUS",
        f"  Ledger code: {identity.code}",
        f"  Ledger ref:  {config.ref}",
        f"  Parent ref:  {parent_display}",
        f"  Next task:   {next_task_id}",
        f"  Next ref:    {next_task_ref}",
        f"  Storage:     {paths.ledger_dir}",
        f"  Tasks:       {task_count}",
        f"  Active task: {active_display}",
    ]
    emit_payload(ctx, payload, human="\n".join(human_lines))


@ledger_app.command("list")
def ledger_list_command(ctx: typer.Context) -> None:
    """List local ledger namespaces."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.storage.ledger_config import load_ledger_config
        from taskledger.storage.paths import (
            load_project_locator,
            resolve_taskledger_root,
        )

        locator = load_project_locator(state.cwd)
        config = load_ledger_config(locator.config_path)
        root = resolve_taskledger_root(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    ledgers_dir = root / "ledgers"
    entries: list[dict[str, object]] = []
    if ledgers_dir.exists():
        for d in sorted(ledgers_dir.iterdir()):
            if d.is_dir():
                tasks = (
                    list((d / "tasks").glob("task-*/task.md"))
                    if (d / "tasks").exists()
                    else []
                )
                from taskledger.storage.yaml_store import load_yaml_object

                active_yaml = d / "active-task.yaml"
                active_data = None
                if active_yaml.exists():
                    try:
                        active_data = load_yaml_object(
                            active_yaml, "active task state", missing="empty"
                        )
                    except Exception:
                        pass
                active_id = active_data.get("task_id") if active_data else None
                entries.append(
                    {
                        "ref": d.name,
                        "task_count": len(tasks),
                        "active_task_id": active_id,
                        "is_current": d.name == config.ref,
                    }
                )

    payload = {
        "ok": True,
        "kind": "ledger_list",
        "current_ref": config.ref,
        "ledgers": entries,
    }
    human_lines = ["LEDGER LIST"]
    for entry in entries:
        marker = " (current)" if entry["is_current"] else ""
        active = entry["active_task_id"] or "none"
        human_lines.append(
            f"  {entry['ref']}{marker}  tasks={entry['task_count']}  active={active}"
        )
    if not entries:
        human_lines.append("  (no ledgers)")
    emit_payload(ctx, payload, human="\n".join(human_lines))


@ledger_app.command("fork")
def ledger_fork_command(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="New ledger ref name.")],
    copy_open: Annotated[
        bool,
        typer.Option("--copy-open", help="Copy open tasks to the new ledger."),
    ] = False,
) -> None:
    """Create a new ledger namespace from the current ledger."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.storage.ledger_config import (
            LedgerConfigPatch,
            load_ledger_config,
            update_ledger_config,
            validate_ledger_ref,
        )
        from taskledger.storage.paths import (
            load_project_locator,
            resolve_taskledger_root,
        )

        validate_ledger_ref(ref)
        locator = load_project_locator(state.cwd)
        config = load_ledger_config(locator.config_path)

        if ref == config.ref:
            raise LaunchError(f"Cannot fork ledger '{ref}' onto itself.")

        root = resolve_taskledger_root(state.cwd)
        new_ledger_dir = root / "ledgers" / ref

        if new_ledger_dir.exists():
            raise LaunchError(
                f"Ledger '{ref}' already exists. Use 'taskledger ledger switch {ref}'."
            )

        # Create the new ledger directory structure
        for subdir in ("tasks", "events", "indexes", "intros", "releases"):
            (new_ledger_dir / subdir).mkdir(parents=True, exist_ok=True)

        # Write empty index files
        from taskledger.storage.atomic import atomic_write_text

        for index_file in (
            "active_locks.json",
            "dependencies.json",
            "introductions.json",
        ):
            atomic_write_text(new_ledger_dir / "indexes" / index_file, "[]\n")

        # Update config to point to the new ledger
        previous_ref = config.ref
        updated = update_ledger_config(
            locator.config_path,
            LedgerConfigPatch(
                ref=ref,
                parent_ref=previous_ref,
            ),
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "ok": True,
        "kind": "ledger_forked",
        "previous_ledger_ref": previous_ref,
        "ledger_ref": updated.ref,
        "ledger_parent_ref": updated.parent_ref,
        "config_path": str(locator.config_path),
    }
    human_lines = [
        "LEDGER FORK",
        f"  forked ledger {previous_ref} -> {ref}",
        f"  config updated: {locator.config_path}",
    ]
    emit_payload(ctx, payload, human="\n".join(human_lines))


@ledger_app.command("switch")
def ledger_switch_command(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="Existing ledger ref to switch to.")],
    create: Annotated[
        bool,
        typer.Option("--create", help="Create the ledger if it does not exist."),
    ] = False,
) -> None:
    """Switch to an existing local ledger namespace."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.storage.ledger_config import (
            LedgerConfigPatch,
            load_ledger_config,
            update_ledger_config,
            validate_ledger_ref,
        )
        from taskledger.storage.paths import (
            load_project_locator,
            resolve_taskledger_root,
        )

        validate_ledger_ref(ref)
        locator = load_project_locator(state.cwd)
        config = load_ledger_config(locator.config_path)
        root = resolve_taskledger_root(state.cwd)
        target_dir = root / "ledgers" / ref

        if not target_dir.exists():
            if create:
                for subdir in ("tasks", "events", "indexes", "intros", "releases"):
                    (target_dir / subdir).mkdir(parents=True, exist_ok=True)
                from taskledger.storage.atomic import atomic_write_text

                for index_file in (
                    "active_locks.json",
                    "dependencies.json",
                    "introductions.json",
                ):
                    atomic_write_text(target_dir / "indexes" / index_file, "[]\n")
            else:
                raise LaunchError(
                    f"Ledger '{ref}' does not exist."
                    f" Use --create or 'taskledger ledger fork {ref}'."
                )

        previous_ref = config.ref
        updated = update_ledger_config(
            locator.config_path,
            LedgerConfigPatch(ref=ref),
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "ok": True,
        "kind": "ledger_switched",
        "previous_ledger_ref": previous_ref,
        "ledger_ref": updated.ref,
        "config_path": str(locator.config_path),
    }
    human_lines = [
        "LEDGER SWITCH",
        f"  switched {previous_ref} -> {ref}",
        f"  config updated: {locator.config_path}",
    ]
    emit_payload(ctx, payload, human="\n".join(human_lines))


@ledger_app.command("adopt")
def ledger_adopt_command(
    ctx: typer.Context,
    task_ref: Annotated[str, typer.Argument(help="Task ID to adopt (e.g. task-0030).")],
    from_ledger: Annotated[
        str,
        typer.Option("--from", help="Source ledger ref to adopt from."),
    ],
) -> None:
    """Adopt a task from another local ledger into the current ledger."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.storage.ledger_config import (
            load_ledger_config,
        )
        from taskledger.storage.paths import (
            load_project_locator,
            resolve_taskledger_root,
        )
        from taskledger.storage.task_store import list_tasks

        locator = load_project_locator(state.cwd)
        config = load_ledger_config(locator.config_path)
        root = resolve_taskledger_root(state.cwd)
        source_dir = root / "ledgers" / from_ledger
        if not source_dir.exists():
            raise LaunchError(f"Source ledger '{from_ledger}' does not exist.")

        source_task_dir = source_dir / "tasks" / task_ref
        if not source_task_dir.exists():
            raise LaunchError(f"Task '{task_ref}' not found in ledger '{from_ledger}'.")

        # Determine target task ID
        current_tasks = list_tasks(state.cwd)
        current_ids = [t.id for t in current_tasks]
        if task_ref in current_ids:
            # Renumber only the imported bundle using the shared allocator.
            from taskledger.storage.task_ids import allocate_task_directory

            new_task_id, reserved_dir = allocate_task_directory(state.cwd)
        else:
            new_task_id = task_ref
            reserved_dir = None

        # Copy task directory
        import shutil

        target_task_dir = reserved_dir or (
            root / "ledgers" / config.ref / "tasks" / new_task_id
        )
        if reserved_dir is None and target_task_dir.exists():
            raise LaunchError(f"Target task directory already exists: {new_task_id}")
        if reserved_dir is not None:
            shutil.copytree(source_task_dir, target_task_dir, dirs_exist_ok=True)
        else:
            shutil.copytree(source_task_dir, target_task_dir)

        # Rewrite task.md with adopted metadata
        task_md = target_task_dir / "task.md"
        if task_md.exists():
            from taskledger.storage.frontmatter import (
                read_markdown_front_matter,
                write_markdown_front_matter,
            )

            metadata, body = read_markdown_front_matter(task_md)
            metadata["id"] = new_task_id
            metadata["adopted_from_ledger"] = from_ledger
            metadata["adopted_from_task_id"] = task_ref
            write_markdown_front_matter(task_md, metadata, body)

            # Rewrite child records if renumbered
            from taskledger.storage.task_store import rewrite_task_refs

            rewrite_task_refs(target_task_dir, task_ref, new_task_id)

    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    payload = {
        "ok": True,
        "kind": "ledger_adopt",
        "from_ledger": from_ledger,
        "from_task_id": task_ref,
        "to_ledger": config.ref,
        "to_task_id": new_task_id,
        "renumbered": new_task_id != task_ref,
    }
    verb = "adopted" if new_task_id == task_ref else "adopted and renumbered"
    human_lines = [
        "LEDGER ADOPT",
        f"  {verb} {from_ledger}/{task_ref} as {config.ref}/{new_task_id}",
    ]
    emit_payload(ctx, payload, human="\n".join(human_lines))


@ledger_app.command("doctor")
def ledger_doctor_command(ctx: typer.Context) -> None:
    """Check branch-scoped ledger consistency."""
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.storage.ledger_config import load_ledger_config
        from taskledger.storage.paths import (
            load_project_locator,
            resolve_taskledger_root,
        )
        from taskledger.storage.task_store import list_tasks

        locator = load_project_locator(state.cwd)
        config = load_ledger_config(locator.config_path)
        root = resolve_taskledger_root(state.cwd)
        ledger_dir = root / "ledgers" / config.ref
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    issues: list[dict[str, object]] = []

    # Check ledger dir exists
    if not ledger_dir.exists():
        issues.append(
            {
                "check": "ledger_dir_exists",
                "status": "fail",
                "message": f"Ledger directory missing: {ledger_dir}",
            }
        )

    # Check active task points to existing task
    try:
        from taskledger.storage.task_store import load_active_task_state

        active = load_active_task_state(state.cwd)
        if active:
            tasks = list_tasks(state.cwd)
            task_ids = [t.id for t in tasks]
            if active.task_id not in task_ids:
                issues.append(
                    {
                        "check": "active_task_exists",
                        "status": "fail",
                        "message": (
                            f"Active task '{active.task_id}' not found "
                            "in current ledger."
                        ),
                    }
                )
    except Exception as exc:
        issues.append(
            {"check": "active_task_check", "status": "warn", "message": str(exc)}
        )

    # Check for legacy unscoped state
    legacy_paths = [
        root / "tasks",
        root / "events",
        root / "indexes",
        root / "intros",
        root / "releases",
        root / "active-task.yaml",
    ]
    for lp in legacy_paths:
        if lp.exists():
            issues.append(
                {
                    "check": "legacy_unscoped_state",
                    "status": "warn",
                    "message": (
                        f"Legacy unscoped path exists: {lp.relative_to(root)}. "
                        "Run: taskledger migrate status && "
                        "taskledger migrate apply --backup"
                    ),
                }
            )

    healthy = not any(i["status"] == "fail" for i in issues)
    payload = {
        "ok": True,
        "kind": "ledger_doctor",
        "healthy": healthy,
        "ledger_ref": config.ref,
        "issues": issues,
    }
    human_lines = [
        "LEDGER DOCTOR",
        f"  Ledger ref: {config.ref}",
        f"  Healthy: {'yes' if healthy else 'no'}",
    ]
    if issues:
        human_lines.append(f"  Issues: {len(issues)}")
        for issue in issues:
            human_lines.append(f"    [{issue['status']}] {issue['message']}")
    else:
        human_lines.append("  No issues found.")
    emit_payload(ctx, payload, human="\n".join(human_lines))

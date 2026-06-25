from __future__ import annotations

from typing import Annotated, cast

import typer

from taskledger.api.task_runs import (
    add_change,
    add_implementation_artifact,
    add_implementation_deviation,
    finish_implementation,
    log_implementation,
    refresh_implementation_snapshot,
    restart_implementation,
    resume_implementation,
    run_implementation_command,
    scan_changes,
    show_task_run,
    start_implementation,
)
from taskledger.api.tasks import todo_status
from taskledger.cli_common import (
    TaskOption,
    TaskRefArgument,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    reject_workflow_positional_task_ref,
    resolve_cli_actor_harness,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.storage.task_store import load_todos


def start_command(
    ctx: typer.Context,
    task_arg: TaskRefArgument = None,
    task_ref: TaskOption = None,
    actor: Annotated[
        str | None,
        typer.Option("--actor", help="Actor type: user, agent, or system."),
    ] = None,
    actor_name: Annotated[
        str | None,
        typer.Option("--actor-name", help="Actor name."),
    ] = None,
    actor_role: Annotated[
        str | None,
        typer.Option("--actor-role", help="Actor role in task lifecycle."),
    ] = None,
    harness: Annotated[
        str | None,
        typer.Option("--harness", help="Harness name."),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Session identifier."),
    ] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        if task_arg:
            reject_workflow_positional_task_ref("implement start", task_arg)
        task = resolve_cli_task(state.cwd, task_ref)
        resolved_actor, resolved_harness = resolve_cli_actor_harness(
            actor=actor,
            actor_name=actor_name,
            actor_role=actor_role,
            harness=harness,
            session_id=session_id,
            workspace_root=state.cwd,
        )
        payload = start_implementation(
            state.cwd,
            task.id,
            actor=resolved_actor,
            harness=resolved_harness,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"started implementation {payload['run_id']}",
    )


def restart_command(
    ctx: typer.Context,
    summary: Annotated[str, typer.Option("--summary")],
    task_ref: TaskOption = None,
    actor: Annotated[
        str | None,
        typer.Option("--actor", help="Actor type: user, agent, or system."),
    ] = None,
    actor_name: Annotated[
        str | None,
        typer.Option("--actor-name", help="Actor name."),
    ] = None,
    actor_role: Annotated[
        str | None,
        typer.Option("--actor-role", help="Actor role in task lifecycle."),
    ] = None,
    harness: Annotated[
        str | None,
        typer.Option("--harness", help="Harness name."),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Session identifier."),
    ] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        resolved_actor, resolved_harness = resolve_cli_actor_harness(
            actor=actor,
            actor_name=actor_name,
            actor_role=actor_role,
            harness=harness,
            session_id=session_id,
            workspace_root=state.cwd,
        )
        payload = restart_implementation(
            state.cwd,
            task.id,
            summary=summary,
            actor=resolved_actor,
            harness=resolved_harness,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"restarted implementation {payload['run_id']}",
    )


def resume_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    run_id: Annotated[
        str | None,
        typer.Option("--run", help="Existing implementation run to resume."),
    ] = None,
    task_ref: TaskOption = None,
    actor: Annotated[
        str | None,
        typer.Option("--actor", help="Actor type: user, agent, or system."),
    ] = None,
    actor_name: Annotated[
        str | None,
        typer.Option("--actor-name", help="Actor name."),
    ] = None,
    actor_role: Annotated[
        str | None,
        typer.Option("--actor-role", help="Actor role in task lifecycle."),
    ] = None,
    harness: Annotated[
        str | None,
        typer.Option("--harness", help="Harness name."),
    ] = None,
    repair_expired_lock: Annotated[
        bool,
        typer.Option(
            "--repair-expired-lock",
            help="Release expired implementation lock and acquire new one.",
        ),
    ] = False,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Session identifier."),
    ] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        resolved_actor, resolved_harness = resolve_cli_actor_harness(
            actor=actor,
            actor_name=actor_name,
            actor_role=actor_role,
            harness=harness,
            session_id=session_id,
            workspace_root=state.cwd,
        )
        payload = resume_implementation(
            state.cwd,
            task.id,
            run_id=run_id,
            reason=reason,
            actor=resolved_actor,
            harness=resolved_harness,
            repair_expired_lock=repair_expired_lock,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"resumed implementation {payload['run_id']}",
    )


def log_command(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Option("--message")] = None,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        if message is None:
            payload = show_task_run(
                state.cwd,
                task.id,
                run_id=None,
                run_type="implementation",
            )
            emit_payload(ctx, payload, human=str(payload["run"]))
            return
        run = log_implementation(state.cwd, task.id, message=message)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, run.to_dict(), human=f"logged implementation {run.run_id}")


def _emit_change_command(
    ctx: typer.Context,
    path: Annotated[str, typer.Option("--path")],
    kind: Annotated[str, typer.Option("--kind")] = "edit",
    summary: Annotated[str, typer.Option("--summary")] = "",
    command: Annotated[str | None, typer.Option("--command")] = None,
    git_diff_stat: Annotated[str | None, typer.Option("--git-diff-stat")] = None,
    task_ref: str | None = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        change = add_change(
            state.cwd,
            task.id,
            path=path,
            kind=kind,
            summary=summary,
            command=command,
            git_diff_stat=git_diff_stat,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, change.to_dict(), human=f"logged change {change.change_id}")


def change_command(
    ctx: typer.Context,
    path: Annotated[str, typer.Option("--path")],
    kind: Annotated[str, typer.Option("--kind")] = "edit",
    summary: Annotated[str, typer.Option("--summary")] = "",
    command: Annotated[str | None, typer.Option("--command")] = None,
    git_diff_stat: Annotated[str | None, typer.Option("--git-diff-stat")] = None,
    task_ref: TaskOption = None,
) -> None:
    _emit_change_command(ctx, path, kind, summary, command, git_diff_stat, task_ref)


def scan_changes_command(
    ctx: typer.Context,
    from_git: Annotated[bool, typer.Option("--from-git")] = False,
    summary: Annotated[str, typer.Option("--summary")] = "",
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        change = scan_changes(
            state.cwd,
            task.id,
            from_git=from_git,
            summary=summary,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, change.to_dict(), human=f"logged change {change.change_id}")


def command_command(
    ctx: typer.Context,
    allow_failure: Annotated[bool, typer.Option("--allow-failure")] = False,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    argv = tuple(ctx.args)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = run_implementation_command(
            state.cwd,
            task.id,
            argv=argv,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    check_data: dict[str, object] = payload.get("check") or {}  # type: ignore[assignment]
    emit_payload(
        ctx,
        payload,
        human=(
            f"recorded check {check_data.get('check_id', '?')}"
            f" exit={payload['exit_code']}"
        ),
    )
    raw_exit_code = payload.get("exit_code", 0)
    if isinstance(raw_exit_code, int):
        exit_code = raw_exit_code
    elif isinstance(raw_exit_code, str) and raw_exit_code.isdigit():
        exit_code = int(raw_exit_code)
    else:
        exit_code = 0
    if exit_code != 0 and not allow_failure:
        from taskledger.services.agent_logging import note_error

        note_error("implementation command failed", exit_code=exit_code)
        raise typer.Exit(code=exit_code)


def deviation_command(
    ctx: typer.Context,
    message: Annotated[str, typer.Option("--message")],
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        run = add_implementation_deviation(state.cwd, task.id, message=message)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, run.to_dict(), human=f"logged deviation on {run.run_id}")


def artifact_command(
    ctx: typer.Context,
    path: Annotated[str, typer.Option("--path")],
    summary: Annotated[str, typer.Option("--summary")],
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        run = add_implementation_artifact(
            state.cwd,
            task.id,
            path=path,
            summary=summary,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, run.to_dict(), human=f"logged artifact on {run.run_id}")


def finish_command(
    ctx: typer.Context,
    summary: Annotated[str, typer.Option("--summary")],
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = finish_implementation(state.cwd, task.id, summary=summary)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    compact = {
        "kind": "task_lifecycle",
        "command": "implement finish",
        "task_id": payload.get("task_id"),
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "status_stage": payload.get("status"),
        "active_stage": payload.get("active_stage"),
        "changed": payload.get("changed"),
        "warnings": payload.get("warnings", []),
        "next_command": "taskledger validate check --criterion CRITERION",
    }
    emit_payload(
        ctx,
        compact,
        result_type="task_lifecycle",
        human=(
            f"finished implementation {compact['run_id']}"
            f"  task {compact['task_id']} -> {compact['status']}"
        ),
    )


def show_command(
    ctx: typer.Context,
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = show_task_run(
            state.cwd,
            task.id,
            run_id=run_id,
            run_type="implementation",
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    run = payload["run"]
    assert isinstance(run, dict)
    emit_payload(ctx, payload, human=f"{run['run_id']}  {run['status']}")


def status_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = todo_status(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    # Build human-readable output
    total = payload.get("total", 0)
    done = payload.get("done", 0)
    can_finish = payload.get("can_finish_implementation", False)
    lines = [f"IMPLEMENTATION STATUS {payload['task_id']}  {done}/{total} todos done"]

    todos = load_todos(state.cwd, task.id).todos
    for todo in todos:
        status_mark = "[x]" if todo.done else "[ ]"
        lines.append(f"{status_mark} {todo.id}  {todo.text}")

    if can_finish:
        lines.append(
            "\nReady: All todos done. "
            "Run 'taskledger implement finish --summary \"...\"'"
        )
    else:
        lines.append(f"\nBlocked: {cast(int, total) - cast(int, done)} todos not done.")

    emit_payload(ctx, payload, human="\n".join(lines))


def checklist_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = todo_status(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    # Build human-readable checklist output
    total = cast(int, payload.get("total", 0))
    done = cast(int, payload.get("done", 0))
    can_finish = payload.get("can_finish_implementation", False)
    lines = [f"TODO CHECKLIST: {done}/{total} done"]

    todos = load_todos(state.cwd, task.id).todos
    for todo in todos:
        status_mark = "[x]" if todo.done else "[ ]"
        lines.append(f"{status_mark} {todo.id}  {todo.text}")

    if can_finish:
        lines.append("\n✓ All todos done!")
    else:
        lines.append(f"\n{total - done} todos remaining")

    emit_payload(ctx, payload, human="\n".join(lines))


def snapshot_refresh_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    task_ref: TaskOption = None,
    actor: Annotated[
        str | None,
        typer.Option("--actor", help="Actor type: user, agent, or system."),
    ] = None,
    actor_name: Annotated[
        str | None,
        typer.Option("--actor-name", help="Actor name."),
    ] = None,
    actor_role: Annotated[
        str | None,
        typer.Option("--actor-role", help="Actor role in task lifecycle."),
    ] = None,
    harness: Annotated[
        str | None,
        typer.Option("--harness", help="Harness name."),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Session identifier."),
    ] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        resolved_actor, resolved_harness = resolve_cli_actor_harness(
            actor=actor,
            actor_name=actor_name,
            actor_role=actor_role,
            harness=harness,
            session_id=session_id,
            workspace_root=state.cwd,
        )
        payload = refresh_implementation_snapshot(
            state.cwd,
            task.id,
            reason=reason,
            actor=resolved_actor,
            harness=resolved_harness,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"refreshed implementation snapshot for {payload['run_id']}",
    )


def register_implement_v2_commands(app: typer.Typer) -> None:
    command_context_settings = {
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    }
    app.command("start")(start_command)
    app.command("restart")(restart_command)
    app.command("resume")(resume_command)
    app.command("log")(log_command)
    app.command("change")(change_command)
    app.command("scan-changes")(scan_changes_command)
    app.command(
        "command",
        context_settings=command_context_settings,
    )(command_command)
    app.command("deviation")(deviation_command)
    app.command("artifact")(artifact_command)
    app.command("finish")(finish_command)
    app.command("show")(show_command)
    app.command("status")(status_command)
    app.command("checklist")(checklist_command)
    snapshot_app = typer.Typer(no_args_is_help=True)
    snapshot_app.command("refresh")(snapshot_refresh_command)
    app.add_typer(snapshot_app, name="snapshot")

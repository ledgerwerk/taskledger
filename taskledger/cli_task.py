from __future__ import annotations

import getpass
from pathlib import Path
from typing import Annotated, cast

import typer

from taskledger.api.tasks import (
    activate_task,
    cancel_task,
    close_task,
    create_follow_up_task,
    create_task,
    deactivate_task,
    edit_task,
    list_task_summaries,
    record_completed_task,
    show_active_task,
    show_task,
    task_dossier,
    uncancel_task,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    read_text_input,
    render_json,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_actor
from taskledger.services.agent_transcripts import (
    render_task_transcript as _render_task_transcript,
)
from taskledger.services.task_reports import (
    ReportPreset,
    TaskReportOptions,
)
from taskledger.services.task_reports import (
    render_task_report as _render_task_report,
)
from taskledger.services.tasks import list_events as _list_events


def create_command(
    ctx: typer.Context,
    title_arg: Annotated[str, typer.Argument(..., help="Task title.")],
    description: Annotated[
        str | None,
        typer.Option("--description", help="Task description."),
    ] = None,
    slug: Annotated[str | None, typer.Option("--slug")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = create_task(
            state.cwd,
            title=title_arg,
            description=read_text_input(
                text=description or title_arg,
                text_label="--description",
            ),
            slug=slug or title_arg,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        task.to_dict(),
        human=f"created task {task.slug} ({task.id})",
    )


def record_command(
    ctx: typer.Context,
    title_arg: Annotated[str, typer.Argument(..., help="Title of the completed task.")],
    description: Annotated[
        str | None,
        typer.Option("--description", help="Task description."),
    ] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="Read description from a file."),
    ] = None,
    summary: Annotated[
        str | None,
        typer.Option(
            "--summary",
            help="Implementation summary of what was done.",
        ),
    ] = None,
    change: Annotated[
        list[str] | None,
        typer.Option(
            "--change",
            help=("Recorded code change in PATH:KIND:SUMMARY format. Repeatable."),
        ),
    ] = None,
    evidence: Annotated[
        list[str] | None,
        typer.Option(
            "--evidence",
            help="Validation evidence (repeatable).",
        ),
    ] = None,
    label: Annotated[
        list[str] | None, typer.Option("--label", help="Task label.")
    ] = None,
    slug: Annotated[str | None, typer.Option("--slug", help="Task slug.")] = None,
    owner: Annotated[str | None, typer.Option("--owner", help="Task owner.")] = None,
    completed_by: Annotated[
        str | None,
        typer.Option(
            "--completed-by",
            help="Actor type: user, agent, or system.",
        ),
    ] = None,
    completed_by_name: Annotated[
        str | None,
        typer.Option(
            "--completed-by-name",
            help="Name of the actor who completed the work.",
        ),
    ] = None,
    allow_empty_record: Annotated[
        bool,
        typer.Option(
            "--allow-empty-record",
            help="Allow recording without changes or evidence.",
        ),
    ] = False,
    reason: Annotated[
        str | None,
        typer.Option(
            "--reason",
            help="Reason for --allow-empty-record.",
        ),
    ] = None,
) -> None:
    state = cli_state_from_context(ctx)
    desc_text = read_text_input(text=description, from_file=from_file)
    # Parse --change inputs
    parsed_changes: list[tuple[str, str, str]] = []
    for raw in change or []:
        parts = raw.split(":", 2)
        if len(parts) != 3:
            emit_error(
                ctx,
                LaunchError(
                    f"Invalid --change format: {raw!r}. Expected PATH:KIND:SUMMARY."
                ),
            )
            raise typer.Exit(code=2)
        parsed_changes.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    resolved_completed_by = None
    if completed_by is not None or completed_by_name is not None:
        from taskledger.domain.models import ActorRef

        resolved_completed_by = ActorRef(
            actor_type=completed_by or "user",  # type: ignore[arg-type]
            actor_name=completed_by_name or (getpass.getuser() or "user")
            if completed_by == "user"
            else "taskledger",
        )
    try:
        payload = record_completed_task(
            state.cwd,
            title=title_arg,
            description=desc_text,
            summary=summary or title_arg,
            slug=slug,
            labels=tuple(label or ()),
            owner=owner,
            changes=tuple(parsed_changes),
            evidence=tuple(evidence or ()),
            completed_by=resolved_completed_by,
            allow_empty_record=allow_empty_record,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    task_id = payload["task_id"]
    slug_val = payload["slug"]
    assert isinstance(task_id, str)
    assert isinstance(slug_val, str)
    human = (
        f"recorded completed task {task_id} ({slug_val})\nstatus: done\ntype: recorded"
    )
    emit_payload(ctx, payload, human=human)


def follow_up_command(
    ctx: typer.Context,
    parent_ref: Annotated[
        str,
        typer.Argument(..., help="Completed parent task ref."),
    ],
    title: Annotated[
        str,
        typer.Argument(..., help="Follow-up task title."),
    ],
    description: Annotated[
        str | None,
        typer.Option("--description", help="Follow-up task description."),
    ] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="Read description from a file."),
    ] = None,
    slug: Annotated[str | None, typer.Option("--slug")] = None,
    activate: Annotated[bool, typer.Option("--activate/--no-activate")] = False,
    copy_files: Annotated[bool, typer.Option("--copy-files/--no-copy-files")] = False,
    copy_links: Annotated[bool, typer.Option("--copy-links/--no-copy-links")] = False,
    label: Annotated[list[str] | None, typer.Option("--label")] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        payload = create_follow_up_task(
            state.cwd,
            parent_ref,
            title=title,
            description=(
                read_text_input(text=description, from_file=from_file)
                if description is not None or from_file is not None
                else None
            ),
            slug=slug,
            labels=tuple(label or ()),
            activate=activate,
            copy_files=copy_files,
            copy_links=copy_links,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    task_id = payload["task_id"]
    parent_task_id = payload["parent_task_id"]
    next_command = payload["next_command"]
    assert isinstance(task_id, str)
    assert isinstance(parent_task_id, str)
    assert isinstance(next_command, str)
    lead = (
        f"created and activated follow-up task {task_id} for {parent_task_id}"
        if payload["activated"]
        else f"created follow-up task {task_id} for {parent_task_id}"
    )
    emit_payload(ctx, payload, human=f"{lead}\nnext: {next_command}")


def list_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    payload = {"kind": "task_list", "tasks": list_task_summaries(state.cwd)}
    human_lines = ["TASKS"]
    if not payload["tasks"]:
        human_lines.append("(empty)")
    else:
        for task in cast(list[dict[str, object]], payload["tasks"]):
            active = task.get("active_stage")
            stage = (
                f"{task['status_stage']} [{active}]"
                if active
                else str(task["status_stage"])
            )
            human_lines.append(f"{task['slug']}  {task['id']}  {stage}")
    emit_payload(ctx, payload, human="\n".join(human_lines))


def active_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    try:
        payload = show_active_task(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"{payload['slug']} ({payload['task_id']})",
    )


def activate_command(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(..., help="Task ref.")],
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        payload = activate_task(state.cwd, ref, reason=reason, force=force)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    changed = "activated" if payload["changed"] else "already active"
    emit_payload(ctx, payload, human=f"{changed} {payload['task_id']}")


def deactivate_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        payload = deactivate_task(state.cwd, reason=reason, force=force)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"deactivated {payload['task_id']}")


def show_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        resolved = resolve_cli_task(state.cwd, task_ref)
        payload = show_task(state.cwd, resolved.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    task = payload["task"]
    assert isinstance(task, dict)
    human_lines = [
        f"{task['title']} ({task['id']})",
        f"status: {task['status_stage']}",
        f"active_stage: {task.get('active_stage') or 'none'}",
        f"slug: {task['slug']}",
    ]
    parent_task = payload.get("parent_task")
    if isinstance(parent_task, dict):
        human_lines.append(
            f"follow-up of: {parent_task['task_id']} {parent_task['title']}"
        )
    follow_up_tasks = payload.get("follow_up_tasks")
    if isinstance(follow_up_tasks, list) and follow_up_tasks:
        rendered = ", ".join(
            f"{item['task_id']} {item['title']}"
            for item in follow_up_tasks
            if isinstance(item, dict)
        )
        if rendered:
            human_lines.append(f"follow-ups: {rendered}")
    emit_payload(
        ctx,
        payload,
        human="\n".join(human_lines),
    )


def edit_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    title: Annotated[str | None, typer.Option("--title")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    from_file: Annotated[Path | None, typer.Option("--from-file")] = None,
    priority: Annotated[str | None, typer.Option("--priority")] = None,
    owner: Annotated[str | None, typer.Option("--owner")] = None,
    add_label: Annotated[list[str] | None, typer.Option("--add-label")] = None,
    remove_label: Annotated[
        list[str] | None,
        typer.Option("--remove-label"),
    ] = None,
    add_note: Annotated[list[str] | None, typer.Option("--add-note")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        task = edit_task(
            state.cwd,
            task.id,
            title=title,
            description=(
                read_text_input(text=description, from_file=from_file)
                if description is not None or from_file is not None
                else None
            ),
            priority=priority,
            owner=owner,
            add_labels=tuple(add_label or ()),
            remove_labels=tuple(remove_label or ()),
            add_notes=tuple(add_note or ()),
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, task.to_dict(), human=f"updated task {task.id}")


def cancel_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = cancel_task(state.cwd, task.id, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"cancelled task {payload['task_id']}")


def uncancel_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    reason: Annotated[str, typer.Option("--reason")] = "",
    target_stage: Annotated[
        str | None,
        typer.Option("--to", help="Target durable stage to restore."),
    ] = None,
    actor: Annotated[
        str | None,
        typer.Option("--actor", help="Actor type: user or agent."),
    ] = None,
    actor_name: Annotated[
        str | None,
        typer.Option("--actor-name", help="Actor name."),
    ] = None,
    allow_agent_uncancel: Annotated[
        bool,
        typer.Option(
            "--allow-agent-uncancel",
            help="Allow an agent actor to uncancel after explicit user direction.",
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
        if actor is None and actor_name is None and session_id is None:
            resolved_actor = resolve_actor(
                workspace_root=state.cwd,
                session_id=session_id,
            )
        else:
            resolved_actor = resolve_actor(
                actor_type=actor or "agent",
                actor_name=actor_name
                or ((getpass.getuser() or "user") if actor == "user" else "taskledger"),
                session_id=session_id,
                workspace_root=state.cwd,
            )
        payload = uncancel_task(
            state.cwd,
            task.id,
            target_stage=target_stage,
            reason=reason,
            actor=resolved_actor,
            allow_agent_uncancel=allow_agent_uncancel,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"uncancelled task {payload['task_id']}")


def close_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = close_task(state.cwd, task.id, note=note)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"closed task {payload['task_id']}")


def events_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    all_tasks: Annotated[
        bool, typer.Option("--all", help="Show events for all tasks.")
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Max events to show.")] = 50,
) -> None:
    state = cli_state_from_context(ctx)
    events = _list_events(state.cwd)
    if not all_tasks:
        try:
            resolved = resolve_cli_task(state.cwd, task_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        events = [e for e in events if e.get("task_id") == resolved.id]
    events = events[-limit:]
    payload = {"kind": "event_list", "items": events}
    from taskledger.cli_common import render_events_human

    human = render_events_human(events)
    emit_payload(ctx, payload, human=human, result_type="event_list")


def dossier_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = task_dossier(state.cwd, task.id, format_name=format_name)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=payload if isinstance(payload, str) else None)


def transcript_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Write transcript to file."),
    ] = None,
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
    include_output: Annotated[
        bool,
        typer.Option("--include-output/--no-include-output"),
    ] = False,
    review: Annotated[bool, typer.Option("--review")] = False,
    failures: Annotated[bool, typer.Option("--failures")] = False,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        if review and failures:
            raise LaunchError("Use either --review or --failures, not both.")
        mode = "table"
        if review:
            mode = "review"
        elif failures:
            mode = "failures"
        task = resolve_cli_task(state.cwd, task_ref)
        payload = _render_task_transcript(
            state.cwd,
            task.id,
            format_name=format_name,
            include_output=include_output,
            mode=mode,
            limit=limit,
        )
        human: str | None
        if output is not None:
            from taskledger.cli_common import write_text_output

            if format_name == "markdown":
                content = payload.get("content")
                if not isinstance(content, str):
                    raise LaunchError("Task transcript content is not text.")
                written = write_text_output(output, content)
            else:
                written = write_text_output(output, render_json(payload))
            payload = dict(payload)
            payload["output_path"] = str(written)
            human = f"wrote task transcript {task.id} to {written}"
        else:
            content = payload.get("content")
            human = content if isinstance(content, str) else None
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=human)


def report_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Write report to file."),
    ] = None,
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
    preset: Annotated[str, typer.Option("--preset")] = "full",
    section: Annotated[
        list[str] | None,
        typer.Option("--section", help="Render only this section. Repeatable."),
    ] = None,
    include: Annotated[
        list[str] | None,
        typer.Option("--include", help="Add a section. Repeatable."),
    ] = None,
    without: Annotated[
        list[str] | None,
        typer.Option("--without", help="Remove a section. Repeatable."),
    ] = None,
    events_limit: Annotated[int, typer.Option("--events-limit")] = 50,
    command_log_limit: Annotated[
        int,
        typer.Option("--command-log-limit"),
    ] = 100,
    include_command_output: Annotated[
        bool,
        typer.Option("--include-command-output/--no-include-command-output"),
    ] = False,
    include_empty: Annotated[
        bool,
        typer.Option(
            "--include-empty/--no-include-empty",
        ),
    ] = True,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = _render_task_report(
            state.cwd,
            task.id,
            options=TaskReportOptions(
                sections=tuple(section or ()),
                include_sections=tuple(include or ()),
                exclude_sections=tuple(without or ()),
                events_limit=events_limit,
                command_log_limit=command_log_limit,
                include_command_output=include_command_output,
                include_empty=include_empty,
                preset=cast(ReportPreset, preset),
            ),
            format_name=format_name,
        )
        content = payload.get("content")
        if output is not None:
            if not isinstance(content, str):
                raise LaunchError("Task report content was not rendered as text.")
            from taskledger.cli_common import write_text_output

            written = write_text_output(output, content)
            payload = dict(payload)
            payload["output_path"] = str(written)
            human = f"wrote task report {task.id} to {written}"
        else:
            if isinstance(content, str) and format_name == "markdown":
                human = content
            else:
                human = None
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=human)


def register_task_v2_commands(app: typer.Typer) -> None:
    app.command("create")(create_command)
    app.command("record")(record_command)
    app.command("follow-up")(follow_up_command)
    app.command("list")(list_command)
    app.command("active")(active_command)
    app.command("activate")(activate_command)
    app.command("deactivate")(deactivate_command)
    app.command("show")(show_command)
    app.command("edit")(edit_command)
    app.command("cancel")(cancel_command)
    app.command("uncancel")(uncancel_command)
    app.command("close")(close_command)
    app.command("events")(events_command)
    app.command("dossier")(dossier_command)
    app.command("transcript")(transcript_command)
    app.command("report")(report_command)

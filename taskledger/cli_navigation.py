from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.handoff import (
    render_handoff,
)
from taskledger.api.tasks import (
    can_perform,
    next_action,
)
from taskledger.cli_common import (
    CLIState,
    TaskOption,
    TaskRefArgument,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    render_json,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_effective_identity
from taskledger.services.usage import render_usage_text, usage_payload


def emit_next_action_command(
    ctx: typer.Context,
    task_ref: str | None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        current_actor, current_harness = resolve_effective_identity(
            state.cwd, cwd=state.cwd
        )
        payload = next_action(
            state.cwd,
            task.id,
            current_actor=current_actor,
            current_harness=current_harness,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_next_action_human(payload))


def _next_action_human(payload: dict[str, object]) -> str:
    lines = [f"{payload['action']}: {payload['reason']}"]

    next_item = payload.get("next_item")
    if isinstance(next_item, dict):
        kind = next_item.get("kind")
        item_id = next_item.get("id")
        text = next_item.get("text")
        if kind and kind != "none":
            label = f"Next {kind}:"
            if item_id and text:
                lines.append(f"{label} {item_id} -- {text}")
            elif item_id:
                lines.append(f"{label} {item_id}")

    command = payload.get("next_command")
    if command:
        lines.append(f"Command: {command}")
    _append_worker_pipeline_hint_lines(lines, payload)
    _append_planning_hint_lines(lines, payload)

    commands = payload.get("commands")
    if isinstance(commands, list):
        for item in commands:
            if not isinstance(item, dict) or item.get("primary"):
                continue
            command_label = item.get("label")
            command_text = item.get("command")
            if isinstance(command_label, str) and isinstance(command_text, str):
                lines.append(f"{command_label}: {command_text}")

    progress = payload.get("progress")
    if isinstance(progress, dict):
        todos = progress.get("todos")
        if isinstance(todos, dict):
            lines.append(
                f"Progress: {todos.get('done', 0)}/{todos.get('total', 0)} todos done"
            )
        questions = progress.get("questions")
        if isinstance(questions, dict) and questions.get("required_open") is not None:
            lines.append(f"Open required questions: {questions.get('required_open')}")
        validation = progress.get("validation")
        if isinstance(validation, dict):
            lines.append(
                "Validation progress: "
                f"{validation.get('satisfied', 0)}/"
                f"{validation.get('total', 0)} satisfied"
            )

    blockers = payload.get("blocking")
    if isinstance(blockers, list):
        for blocker in blockers:
            if isinstance(blocker, dict):
                msg = blocker.get("message")
                if msg:
                    lines.append(f"Blocker: {msg}")

    return "\n".join(lines)


def _append_worker_pipeline_hint_lines(
    lines: list[str],
    payload: dict[str, object],
) -> None:
    worker_pipeline = payload.get("worker_pipeline")
    if not isinstance(worker_pipeline, dict):
        return
    next_step = worker_pipeline.get("next_step")
    if isinstance(next_step, dict):
        step_id = next_step.get("id")
        if step_id:
            lines.append(f"Worker step: {step_id}")
    context_command = worker_pipeline.get("context_command")
    if isinstance(context_command, str):
        lines.append(f"Worker context: {context_command}")
    handoff_command = worker_pipeline.get("handoff_command")
    if isinstance(handoff_command, str):
        lines.append(f"Worker handoff: {handoff_command}")


def _append_planning_hint_lines(
    lines: list[str],
    payload: dict[str, object],
) -> None:
    guidance_command = payload.get("guidance_command")
    if isinstance(guidance_command, str):
        lines.append(f"Guidance: {guidance_command}")
    template_command = payload.get("template_command")
    if isinstance(template_command, str):
        lines.append(f"Template: {template_command}")
    required_plan_fields = payload.get("required_plan_fields")
    if isinstance(required_plan_fields, list) and required_plan_fields:
        lines.append(
            "Required plan fields: "
            + ", ".join(str(item) for item in required_plan_fields)
        )
    recommended_plan_fields = payload.get("recommended_plan_fields")
    if isinstance(recommended_plan_fields, list) and recommended_plan_fields:
        lines.append(
            "Recommended plan fields: "
            + ", ".join(str(item) for item in recommended_plan_fields)
        )


def emit_can_command(ctx: typer.Context, task_ref: str | None, action: str) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        current_actor, current_harness = resolve_effective_identity(
            state.cwd, cwd=state.cwd
        )
        payload = can_perform(
            state.cwd,
            task.id,
            action,
            current_actor=current_actor,
            current_harness=current_harness,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    prefix = "yes" if payload["ok"] else "no"
    emit_payload(ctx, payload, human=f"{prefix}: {payload['reason']}")


def _selected_task_ref(
    task_arg: str | None,
    task_ref: str | None,
    *,
    command_name: str,
) -> str | None:
    if task_arg and task_ref and task_arg != task_ref:
        raise LaunchError(
            (
                f"taskledger {command_name} received both TASK_REF and --task. "
                "Use only one."
            ),
            code="USAGE_ERROR",
            exit_code=2,
        )
    return task_arg or task_ref


def context_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    context_for: Annotated[
        str | None,
        typer.Option(
            "--for",
            help=(
                "Context role: planner, implementer, validator, "
                "spec-reviewer, code-reviewer, reviewer, full."
            ),
        ),
    ] = None,
    worker_step_id: Annotated[
        str | None,
        typer.Option("--worker", help="Configured worker step id."),
    ] = None,
    scope: Annotated[
        str | None,
        typer.Option("--scope", help="Context scope: task, todo, or run."),
    ] = None,
    todo_id: Annotated[
        str | None, typer.Option("--todo", help="Focus on one todo id.")
    ] = None,
    focus_run_id: Annotated[
        str | None, typer.Option("--run", help="Focus on one run id.")
    ] = None,
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = render_handoff(
            state.cwd,
            task.id,
            context_for=context_for,
            worker_step_id=worker_step_id,
            scope=scope,
            todo_id=todo_id,
            focus_run_id=focus_run_id,
            format_name=format_name,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human = (
        payload
        if isinstance(payload, str)
        else render_json(payload)
        if format_name == "json"
        else None
    )
    emit_payload(ctx, payload, human=human)


def usage_command(
    ctx: typer.Context,
    task_arg: TaskRefArgument = None,
    task_ref: Annotated[
        str | None,
        typer.Option("--task"),
    ] = None,
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = usage_payload(
            state.cwd,
            task_ref=_selected_task_ref(task_arg, task_ref, command_name="usage"),
            quiet=quiet,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=render_usage_text(payload, quiet=quiet))


def next_action_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    emit_next_action_command(ctx, task_ref)


def can_command(
    ctx: typer.Context,
    action_or_task: Annotated[str, typer.Argument(..., help="Action name.")],
    task_ref: TaskOption = None,
) -> None:
    emit_can_command(ctx, task_ref, action_or_task)


def register_navigation_commands(app: typer.Typer) -> None:
    app.command("context")(context_command)
    app.command("usage")(usage_command)
    app.command("next-action")(next_action_command)
    app.command("can")(can_command)

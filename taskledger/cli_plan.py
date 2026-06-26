from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

from taskledger.api.plans import (
    PlanReviewOptions,
    amend_plan,
    approve_plan,
    check_plan_input,
    diff_plan,
    export_plan,
    lint_plan,
    list_plan_versions,
    materialize_plan_todos,
    plan_input_schema_text,
    plan_template,
    propose_plan,
    regenerate_plan_from_answers,
    reject_plan,
    render_plan_review,
    revise_plan,
    run_planning_command,
    show_plan,
    start_planning,
    upsert_plan,
)
from taskledger.cli_common import (
    TaskOption,
    TaskRefArgument,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    read_text_input,
    reject_workflow_positional_task_ref,
    render_json,
    resolve_cli_actor_harness,
    resolve_cli_task,
    write_text_output,
)
from taskledger.domain.states import EXIT_CODE_VALIDATION_FAILED
from taskledger.errors import LaunchError
from taskledger.services.plan_editing import ensure_plan_input_path_allowed
from taskledger.services.plan_lint import PlanLintPayload
from taskledger.services.workflow_guidance import (
    has_planning_profile,
    planning_guidance_payload,
)


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
            reject_workflow_positional_task_ref("plan start", task_arg)
        task = resolve_cli_task(state.cwd, task_ref)
        resolved_actor, resolved_harness = resolve_cli_actor_harness(
            actor=actor,
            actor_name=actor_name,
            actor_role=actor_role,
            harness=harness,
            session_id=session_id,
            workspace_root=state.cwd,
        )
        payload = start_planning(
            state.cwd,
            task.id,
            actor=resolved_actor,
            harness=resolved_harness,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human = f"started planning {payload['task_id']}"
    if has_planning_profile(state.cwd):
        human = "\n".join(
            [
                human,
                "Next: taskledger plan guidance",
                "Then: taskledger plan template --include-guidance --file plan.md",
            ]
        )
    emit_payload(ctx, payload, human=human)


def propose_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    text: Annotated[str | None, typer.Option("--text")] = None,
    from_file: Annotated[Path | None, typer.Option("--file")] = None,
    criterion: Annotated[list[str] | None, typer.Option("--criterion")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = propose_plan(
            state.cwd,
            task.id,
            body=_read_plan_text_input(state.cwd, text=text, from_file=from_file),
            criteria=tuple(criterion or ()),
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    plan_version = payload.get("plan_version")
    assert isinstance(plan_version, int)
    emit_payload(
        ctx,
        payload,
        human=_render_plan_upsert_human(
            operation="proposed",
            task_id=str(payload["task_id"]),
            plan_version=plan_version,
            plan_input_warnings=cast(
                list[object], payload.get("plan_input_warnings", [])
            ),
        ),
    )


def draft_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    ask_questions: Annotated[bool, typer.Option("--ask-questions")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        guidance_payload = planning_guidance_payload(state.cwd, task.id)
        payload = {
            "kind": "plan_draft_context",
            "task_id": task.id,
            "ask_questions": ask_questions,
            "guidance": guidance_payload["guidance"],
            "question_policy": guidance_payload["question_policy"],
            "next_action": (
                'taskledger question add --text "..." --required-for-plan'
                if ask_questions
                else "taskledger plan propose --file plan.md"
            ),
        }
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=str(payload["next_action"]))


def template_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    from_answers: Annotated[bool, typer.Option("--from-answers")] = False,
    output: Annotated[Path | None, typer.Option("--file")] = None,
    include_guidance: Annotated[bool, typer.Option("--include-guidance")] = False,
    with_worker_pipeline: Annotated[
        bool,
        typer.Option(
            "--with-worker-pipeline",
            help="Include worker pipeline todo hints when enabled for this project.",
        ),
    ] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = plan_template(
            state.cwd,
            task.id,
            from_answers=from_answers,
            include_guidance=include_guidance,
            with_worker_pipeline=with_worker_pipeline,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    template_text = str(payload["template"])
    if output is not None:
        target = write_text_output(output, template_text)
        emit_payload(
            ctx,
            {**payload, "output_path": str(target)},
            human=f"wrote plan template to {target}",
            result_type="plan_template",
        )
        return
    emit_payload(ctx, payload, human=template_text, result_type="plan_template")


def regenerate_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    from_answers: Annotated[bool, typer.Option("--from-answers")] = False,
    text: Annotated[str | None, typer.Option("--text")] = None,
    from_file: Annotated[Path | None, typer.Option("--file")] = None,
    allow_open_questions: Annotated[
        bool,
        typer.Option("--allow-open-questions"),
    ] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        if not from_answers:
            raise LaunchError("plan regenerate requires --from-answers.")
        task = resolve_cli_task(state.cwd, task_ref)
        payload = regenerate_plan_from_answers(
            state.cwd,
            task.id,
            body=_read_plan_text_input(state.cwd, text=text, from_file=from_file),
            allow_open_questions=allow_open_questions,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    plan_version = payload.get("plan_version")
    assert isinstance(plan_version, int)
    emit_payload(
        ctx,
        payload,
        human=_render_plan_upsert_human(
            operation="regenerated",
            task_id=str(payload["task_id"]),
            plan_version=plan_version,
            plan_input_warnings=cast(
                list[object], payload.get("plan_input_warnings", [])
            ),
        ),
    )


def upsert_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    from_answers: Annotated[bool, typer.Option("--from-answers")] = False,
    text: Annotated[str | None, typer.Option("--text")] = None,
    from_file: Annotated[Path | None, typer.Option("--file")] = None,
    criterion: Annotated[list[str] | None, typer.Option("--criterion")] = None,
    allow_open_questions: Annotated[
        bool,
        typer.Option("--allow-open-questions"),
    ] = False,
    auto_revise: Annotated[
        bool,
        typer.Option("--auto-revise"),
    ] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = upsert_plan(
            state.cwd,
            task.id,
            body=_read_plan_text_input(state.cwd, text=text, from_file=from_file),
            criteria=tuple(criterion or ()),
            from_answers=from_answers,
            allow_open_questions=allow_open_questions,
            auto_revise=auto_revise,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    operation = str(payload.get("operation", "upserted"))
    plan_version = payload.get("plan_version")
    assert isinstance(plan_version, int)
    emit_payload(
        ctx,
        payload,
        human=_render_plan_upsert_human(
            operation=operation,
            task_id=str(payload["task_id"]),
            plan_version=plan_version,
            plan_input_warnings=cast(
                list[object], payload.get("plan_input_warnings", [])
            ),
        ),
    )


def materialize_todos_command(
    ctx: typer.Context,
    version: Annotated[int, typer.Option("--version")],
    task_ref: TaskOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = materialize_plan_todos(
            state.cwd,
            task.id,
            version=version,
            dry_run=dry_run,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"materialized {payload['materialized_todos']} todos",
    )


def show_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    version: Annotated[int | None, typer.Option("--version")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = show_plan(state.cwd, task.id, version=version)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    plan = payload["plan"]
    assert isinstance(plan, dict)
    emit_payload(
        ctx,
        payload,
        human=f"plan v{plan['plan_version']} ({plan['status']})",
    )


def review_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    version: Annotated[int | None, typer.Option("--version")] = None,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
    include_lint: Annotated[
        bool, typer.Option("--include-lint/--no-include-lint")
    ] = True,
    include_questions: Annotated[
        bool, typer.Option("--include-questions/--no-include-questions")
    ] = True,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = render_plan_review(
            state.cwd,
            task.id,
            version=version,
            options=PlanReviewOptions(
                include_lint=include_lint,
                include_questions=include_questions,
            ),
            format_name=format_name,
        )
        content = payload.get("content")
        if not isinstance(content, str):
            raise LaunchError("Plan review content was not rendered as text.")
        if output is not None:
            written = write_text_output(output, content)
            payload = {**payload, "output_path": str(written)}
            human = f"wrote plan review {payload['plan_id']} to {written}"
        else:
            human = content
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=human)


def list_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = list_plan_versions(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    plans = payload["plans"]
    assert isinstance(plans, list)
    lines = ["PLANS"]
    for item in plans:
        if isinstance(item, dict):
            lines.append(f"v{item['plan_version']}  {item['status']}")
    emit_payload(ctx, payload, human="\n".join(lines) if plans else "PLANS\n(empty)")


def export_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    version: Annotated[str | None, typer.Option("--version")] = None,
    output: Annotated[Path | None, typer.Option("--file")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    to_stdout: Annotated[bool, typer.Option("--stdout")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        if output is not None and to_stdout:
            raise LaunchError("Use either --file or --stdout, not both.")
        task = resolve_cli_task(state.cwd, task_ref)
        resolved_version = _parse_version_ref(version)
        payload = export_plan(state.cwd, task.id, version=resolved_version)
        plan_text = str(payload["text"])
        if output is not None:
            target = output.expanduser()
            if target.exists() and not overwrite:
                raise LaunchError(
                    f"Refusing to overwrite {target}. Use --overwrite to replace it."
                )
            written = write_text_output(target, plan_text)
            emit_payload(
                ctx,
                {**payload, "output_path": str(written)},
                human=f"wrote editable plan to {written}",
                result_type="plan_export",
            )
            return
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=plan_text, result_type="plan_export")


def diff_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    from_version: Annotated[int, typer.Option("--from")] = 1,
    to_version: Annotated[int, typer.Option("--to")] = 1,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = diff_plan(
            state.cwd,
            task.id,
            from_version=from_version,
            to_version=to_version,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=str(payload["diff"]))


def lint_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    version: Annotated[int | None, typer.Option("--version")] = None,
    strict: Annotated[bool, typer.Option("--strict")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = lint_plan(
            state.cwd,
            task.id,
            version=version,
            strict=strict,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_render_plan_lint(payload))
    if not payload["passed"]:
        raise typer.Exit(code=EXIT_CODE_VALIDATION_FAILED)


def approve_command(
    ctx: typer.Context,
    version: Annotated[int, typer.Option("--version")],
    actor: Annotated[str, typer.Option("--actor")] = "agent",
    actor_name: Annotated[str | None, typer.Option("--actor-name")] = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
    allow_agent_approval: Annotated[
        bool, typer.Option("--allow-agent-approval")
    ] = False,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    allow_empty_criteria: Annotated[
        bool, typer.Option("--allow-empty-criteria")
    ] = False,
    no_materialize_todos: Annotated[
        bool, typer.Option("--no-materialize-todos")
    ] = False,
    allow_open_questions: Annotated[
        bool, typer.Option("--allow-open-questions")
    ] = False,
    allow_empty_todos: Annotated[bool, typer.Option("--allow-empty-todos")] = False,
    allow_lint_errors: Annotated[bool, typer.Option("--allow-lint-errors")] = False,
    approval_source: Annotated[
        str | None,
        typer.Option("--approval-source"),
    ] = None,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = approve_plan(
            state.cwd,
            task.id,
            version=version,
            actor_type=actor,
            actor_name=actor_name,
            note=note,
            allow_agent_approval=allow_agent_approval,
            reason=reason,
            allow_empty_criteria=allow_empty_criteria,
            materialize_todos=not no_materialize_todos,
            allow_open_questions=allow_open_questions,
            allow_empty_todos=allow_empty_todos,
            allow_lint_errors=allow_lint_errors,
            approval_source=approval_source,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"approved plan v{payload['plan_version']} for {payload['task_id']}",
    )


def accept_command(
    ctx: typer.Context,
    version: Annotated[int, typer.Option("--version")],
    note: Annotated[str | None, typer.Option("--note")] = None,
    task_ref: TaskOption = None,
    allow_lint_errors: Annotated[bool, typer.Option("--allow-lint-errors")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = approve_plan(
            state.cwd,
            task.id,
            version=version,
            actor_type="user",
            note=note,
            allow_lint_errors=allow_lint_errors,
            reason=note if allow_lint_errors else None,
            approval_source="explicit_chat",
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"accepted plan v{payload['plan_version']} for {payload['task_id']}",
    )


def reject_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = reject_plan(state.cwd, task.id, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"rejected plan for {payload['task_id']}")


def revise_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = revise_plan(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"restarted planning {payload['task_id']}")


def amend_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    drop_criterion: Annotated[
        list[str] | None,
        typer.Option("--drop-criterion"),
    ] = None,
    drop_todo: Annotated[
        list[str] | None,
        typer.Option("--drop-todo"),
    ] = None,
    remove_file: Annotated[
        list[str] | None,
        typer.Option("--remove-file"),
    ] = None,
    reason: Annotated[str, typer.Option("--reason")] = "",
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = amend_plan(
            state.cwd,
            task.id,
            drop_criteria=tuple(drop_criterion or ()),
            drop_todos=tuple(drop_todo or ()),
            remove_files=tuple(remove_file or ()),
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"amended plan v{payload['plan_version']} for {payload['task_id']}",
    )


def plan_command_command(
    ctx: typer.Context,
    allow_failure: Annotated[bool, typer.Option("--allow-failure")] = False,
    task_ref: TaskOption = None,
) -> None:
    state = cli_state_from_context(ctx)
    argv = tuple(ctx.args)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = run_planning_command(
            state.cwd,
            task.id,
            argv=argv,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=f"ran planning command exit={payload['exit_code']}",
    )
    exit_code = int(payload.get("exit_code", 0))
    if exit_code != 0 and not allow_failure:
        from taskledger.services.agent_logging import note_error

        note_error("planning command failed", exit_code=exit_code)
        raise typer.Exit(code=exit_code)


def plan_guidance_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
) -> None:
    state = cli_state_from_context(ctx)
    try:
        normalized_format = format_name.strip().lower()
        if normalized_format not in {"markdown", "json"}:
            raise LaunchError("Invalid --format value. Use 'markdown' or 'json'.")
        task = resolve_cli_task(state.cwd, task_ref)
        payload = planning_guidance_payload(state.cwd, task.id)
        from taskledger.services.planning_flow import mark_planning_guidance_viewed

        mark_planning_guidance_viewed(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human: str | None = None
    if normalized_format == "json":
        human = render_json(payload)
    elif payload.get("has_project_guidance"):
        human = str(payload["guidance"])
    else:
        human = (
            "No project planning guidance configured.\n"
            "Add [prompt_profiles.planning] to taskledger.toml, then run "
            "taskledger plan guidance again."
        )
    emit_payload(ctx, payload, human=human)


def check_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    text: Annotated[str | None, typer.Option("--text")] = None,
    from_file: Annotated[Path | None, typer.Option("--file")] = None,
    strict: Annotated[bool, typer.Option("--strict")] = False,
) -> None:
    state = cli_state_from_context(ctx)
    task_id: str | None = None
    try:
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task_id = task.id
        except LaunchError:
            # plan check is pure and task-independent; it may run with no
            # active task so a plan file can be validated preflight.
            task_id = None
        body = _read_plan_text_input(state.cwd, text=text, from_file=from_file)
        payload = check_plan_input(
            state.cwd,
            body=body,
            task_id=task_id,
            strict=strict,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=render_plan_input_check(payload))
    if not payload["passed"]:
        raise typer.Exit(code=EXIT_CODE_VALIDATION_FAILED)


def schema_command(
    ctx: typer.Context,
) -> None:
    schema_text = plan_input_schema_text()
    payload = {
        "kind": "plan_input_schema",
        "schema": schema_text,
    }
    emit_payload(ctx, payload, human=schema_text)


def register_plan_v2_commands(app: typer.Typer) -> None:
    command_context_settings = {
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    }
    app.command("start")(start_command)
    app.command("propose")(propose_command)
    app.command("draft")(draft_command)
    app.command("template")(template_command)
    app.command("regenerate")(regenerate_command)
    app.command("upsert")(upsert_command)
    app.command("export")(export_command)
    app.command("materialize-todos")(materialize_todos_command)
    app.command("show")(show_command)
    app.command("review")(review_command)
    app.command("list")(list_command)
    app.command("diff")(diff_command)
    app.command("lint")(lint_command)
    app.command("approve")(approve_command)
    app.command("accept")(accept_command)
    app.command("reject")(reject_command)
    app.command("revise")(revise_command)
    app.command("amend")(amend_command)
    app.command(
        "command",
        context_settings=command_context_settings,
    )(plan_command_command)
    app.command("guidance")(plan_guidance_command)
    app.command("check")(check_command)
    app.command("schema")(schema_command)


def _render_plan_lint(payload: PlanLintPayload) -> str:
    lines = [
        f"Plan lint {'passed' if payload['passed'] else 'failed'} "
        f"for {payload['plan_id']}"
    ]
    summary = payload.get("summary", {})
    errors = int(summary.get("errors", 0)) if isinstance(summary, dict) else 0
    warnings = int(summary.get("warnings", 0)) if isinstance(summary, dict) else 0
    lines.append(f"Summary: {errors} error(s), {warnings} warning(s)")

    raw_issues = cast(list[object], payload.get("issues", []))
    issues = [item for item in raw_issues if isinstance(item, dict)]
    for issue in issues:
        severity = str(issue.get("severity", "warning")).upper()
        code = str(issue.get("code", "unknown"))
        location = str(issue.get("location", "plan"))
        message = str(issue.get("message", ""))
        lines.append(f"- {severity} {code} at {location}: {message}")
        hint = issue.get("hint")
        if isinstance(hint, str) and hint.strip():
            lines.append(f"  Hint: {hint}")

    if not issues:
        if payload["passed"]:
            lines.append("- No lint findings.")
        else:
            lines.append(
                "- Internal inconsistency: lint failed but returned no issue records."
            )
    return "\n".join(lines)


def _read_plan_text_input(
    workspace_root: Path,
    *,
    text: str | None,
    from_file: Path | None,
) -> str:
    if from_file is not None:
        ensure_plan_input_path_allowed(workspace_root, from_file)
    return read_text_input(text=text, from_file=from_file, file_label="--file")


def render_plan_input_check(payload: dict[str, object]) -> str:
    summary = payload.get("summary", {})
    errors = int(summary.get("errors", 0)) if isinstance(summary, dict) else 0
    warnings = int(summary.get("warnings", 0)) if isinstance(summary, dict) else 0
    header = f"Plan input check: warnings={warnings} errors={errors}"
    if payload.get("strict"):
        header += " (strict)"
    if not payload.get("passed"):
        header += " [failed]"
    lines = [header]
    raw_issues = cast(list[object], payload.get("issues", []))
    issues = [item for item in raw_issues if isinstance(item, dict)]
    for issue in issues:
        severity = str(issue.get("severity", "warning"))
        code = str(issue.get("code", "unknown"))
        location = str(issue.get("location", "plan"))
        message = str(issue.get("message", ""))
        lines.append(f"{severity} {location} {code}")
        if message:
            lines.append(f"  {message}")
        hint = issue.get("hint")
        if isinstance(hint, str) and hint.strip():
            lines.append(f"  hint: {hint}")
    parsed = payload.get("parsed", {})
    if isinstance(parsed, dict) and parsed:
        lines += ["", "Parsed commitments:"]
        for key, value in parsed.items():
            label = str(key).replace("_", " ")
            lines.append(f"  {label}: {value}")
    lines += [
        "",
        "Next: taskledger plan upsert --file ./plan.md",
        "Schema: taskledger plan schema",
    ]
    return "\n".join(lines)


def _parse_version_ref(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized or normalized == "latest":
        return None
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise LaunchError(
            "Invalid --version value. Use an integer or 'latest'."
        ) from exc
    if parsed < 1:
        raise LaunchError("Invalid --version value. Use an integer >= 1.")
    return parsed


def _render_plan_upsert_human(
    *,
    operation: str,
    task_id: str,
    plan_version: int,
    plan_input_warnings: list[object] | None = None,
) -> str:
    lines = [
        f"{operation} plan v{plan_version} for {task_id}",
        f"Next: taskledger plan review --version {plan_version}",
        (
            "After explicit approval: "
            f"taskledger plan accept --version {plan_version} --note "
            '"User approved in harness."'
        ),
    ]
    warnings = [item for item in (plan_input_warnings or []) if isinstance(item, dict)]
    if warnings:
        lines.append("")
        lines.append(f"Plan input warnings: {len(warnings)}")
        for item in warnings[:3]:
            code = str(item.get("code", "unknown"))
            location = str(item.get("location", "plan"))
            lines.append(f"  {location} {code}")
        remaining = len(warnings) - 3
        if remaining > 0:
            lines.append(f"  ... and {remaining} more")
    return "\n".join(lines)

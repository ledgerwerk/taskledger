from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

import click
import typer

from taskledger._version import __version__
from taskledger.api.handoff import render_handoff
from taskledger.api.project import (
    init_project,
    project_export_archive,
    project_import,
    project_import_archive,
    project_snapshot,
    project_status,
    project_status_summary,
    project_tree,
)
from taskledger.api.search import (
    dependencies_for_module,
    grep_workspace,
    search_workspace,
    symbols_workspace,
)
from taskledger.cli_actor import app as actors_app
from taskledger.cli_actor import harness_app
from taskledger.cli_common import (
    CLIState,
    TaskOption,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    render_json,
    resolve_cli_task,
    resolve_workspace_root,
)
from taskledger.cli_implement import register_implement_v2_commands
from taskledger.cli_ledger import ledger_app
from taskledger.cli_migrate import migrate_app
from taskledger.cli_misc import (
    emit_can_command,
    emit_doctor_command,
    emit_doctor_indexes_command,
    emit_doctor_locks_command,
    emit_doctor_schema_command,
    emit_next_action_command,
    emit_reindex_command,
    register_file_v2_commands,
    register_handoff_v2_commands,
    register_intro_v2_commands,
    register_link_v2_commands,
    register_lock_v2_commands,
    register_require_v2_commands,
    register_todo_v2_commands,
)
from taskledger.cli_plan import register_plan_v2_commands
from taskledger.cli_question import register_question_v2_commands
from taskledger.cli_task import register_task_v2_commands
from taskledger.cli_validate import register_validate_v2_commands
from taskledger.command_inventory import COMMAND_METADATA
from taskledger.errors import LaunchError, OptionalCommandGroupUnavailable
from taskledger.services.dashboard import dashboard, render_dashboard_text


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"taskledger, version {__version__}")
        raise typer.Exit()


app = typer.Typer(add_completion=False, help="Manage staged taskledger coding work.")
task_app = typer.Typer(add_completion=False, help="Manage coding tasks.")
plan_app = typer.Typer(add_completion=False, help="Manage plan versions.")
question_app = typer.Typer(add_completion=False, help="Manage planning questions.")
implement_app = typer.Typer(add_completion=False, help="Manage implementation runs.")
validate_app = typer.Typer(add_completion=False, help="Manage validation runs.")
todo_app = typer.Typer(add_completion=False, help="Manage task todos.")
intro_app = typer.Typer(add_completion=False, help="Manage shared introductions.")
file_app = typer.Typer(add_completion=False, help="Manage task file links.")
link_app = typer.Typer(
    add_completion=False,
    help="Manage external and typed task links.",
)
require_app = typer.Typer(add_completion=False, help="Manage task requirements.")
lock_app = typer.Typer(add_completion=False, help="Inspect and repair locks.")
handoff_app = typer.Typer(add_completion=False, help="Render fresh-context handoffs.")
release_app = typer.Typer(
    add_completion=False,
    help="Manage release tags and changelog context.",
)
repair_app = typer.Typer(add_completion=False, help="Repair taskledger state.")
doctor_app = typer.Typer(
    add_completion=False,
    help="Inspect taskledger integrity.",
    invoke_without_command=True,
)

app.add_typer(task_app, name="task")
app.add_typer(plan_app, name="plan")
app.add_typer(question_app, name="question")
app.add_typer(implement_app, name="implement")
app.add_typer(validate_app, name="validate")
app.add_typer(todo_app, name="todo")
app.add_typer(intro_app, name="intro")
app.add_typer(file_app, name="file")
app.add_typer(link_app, name="link")
app.add_typer(require_app, name="require")
app.add_typer(lock_app, name="lock")
app.add_typer(handoff_app, name="handoff")
app.add_typer(release_app, name="release")
app.add_typer(doctor_app, name="doctor")
app.add_typer(repair_app, name="repair")
app.add_typer(migrate_app, name="migrate")
app.add_typer(actors_app, name="actor")
app.add_typer(harness_app, name="harness")
app.add_typer(ledger_app, name="ledger")

register_task_v2_commands(task_app)
register_plan_v2_commands(plan_app)
register_question_v2_commands(question_app)
register_implement_v2_commands(implement_app)
register_validate_v2_commands(validate_app)
register_todo_v2_commands(todo_app)
register_intro_v2_commands(intro_app)
register_file_v2_commands(file_app)
register_link_v2_commands(link_app)
register_require_v2_commands(require_app)
register_lock_v2_commands(lock_app)
register_handoff_v2_commands(handoff_app)


def _optional_group_failure(
    *,
    group_name: str,
    module_name: str,
    exc: Exception,
) -> OptionalCommandGroupUnavailable:
    diagnostic_path = module_name.replace(".", "/") + ".py"
    diagnostic_command = f"python -m py_compile {diagnostic_path}"
    return OptionalCommandGroupUnavailable(
        (
            f"taskledger command group '{group_name}' failed to load from "
            f"{module_name}: {type(exc).__name__}: {exc}. "
            f"Run: {diagnostic_command}"
        ),
        details={
            "command_group": group_name,
            "module_name": module_name,
            "exception_type": type(exc).__name__,
            "diagnostic_command": diagnostic_command,
        },
        remediation=[f"Run: {diagnostic_command}"],
    )


def _emit_optional_group_failure(
    ctx: typer.Context,
    error: OptionalCommandGroupUnavailable,
) -> None:
    emit_error(ctx, error)
    raise typer.Exit(code=launch_error_exit_code(error)) from error


def _register_failed_group_placeholder(
    app: typer.Typer,
    *,
    error: OptionalCommandGroupUnavailable,
    command_names: tuple[str, ...],
) -> None:
    @app.callback(invoke_without_command=True)
    def failed_group_callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            _emit_optional_group_failure(ctx, error)

    def _placeholder(
        failed_error: OptionalCommandGroupUnavailable,
    ) -> Callable[[typer.Context], None]:
        def placeholder_command(ctx: typer.Context) -> None:
            _emit_optional_group_failure(ctx, failed_error)

        return placeholder_command

    for command_name in command_names:
        app.command(
            command_name,
            context_settings={
                "allow_extra_args": True,
                "ignore_unknown_options": True,
            },
        )(_placeholder(error))


def _register_optional_group(
    app: typer.Typer,
    *,
    group_name: str,
    module_name: str,
    register_name: str,
    command_names: tuple[str, ...],
) -> None:
    try:
        module = importlib.import_module(module_name)
        register = getattr(module, register_name)
    except Exception as exc:
        _register_failed_group_placeholder(
            app,
            error=_optional_group_failure(
                group_name=group_name,
                module_name=module_name,
                exc=exc,
            ),
            command_names=command_names,
        )
        return
    register(app)


_register_optional_group(
    release_app,
    group_name="release",
    module_name="taskledger.cli_release",
    register_name="register_release_commands",
    command_names=("tag", "list", "show", "changelog"),
)


@app.command("context")
def context_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    context_for: Annotated[
        str,
        typer.Option(
            "--for",
            help=(
                "Context role: planner, implementer, validator, "
                "spec-reviewer, code-reviewer, reviewer, full."
            ),
        ),
    ] = "full",
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


_HELP_FLAGS = {"--help", "-h", "--show-completion", "--install-completion"}
_ROOT_OPTIONS_WITH_VALUE = {"--cwd", "--root"}
_WORKFLOW_TASK_OPTION_COMMANDS = {
    ("plan", "start"),
    ("implement", "start"),
    ("validate", "start"),
}


def _is_help_or_introspection(argv: tuple[str, ...]) -> bool:
    """Return True if this is a help/completion invocation that should skip
    workspace discovery and agent-log recording."""
    return bool(_HELP_FLAGS.intersection(argv))


def _command_from_tokens(argv: tuple[str, ...]) -> str:
    tokens: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _ROOT_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if token.startswith("--cwd=") or token.startswith("--root="):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        tokens.append(token)
        index += 1
    if not tokens:
        return "taskledger"
    if len(tokens) == 1:
        return tokens[0]
    return f"{tokens[0]}.{tokens[1]}"


def _usage_error_remediation(
    argv: tuple[str, ...],
    *,
    command: str,
    message: str,
) -> list[str]:
    remediation: list[str] = ["Review command usage and retry."]
    lower_message = message.lower()
    if "no such option" in lower_message:
        if command == "question.answer" and "--question" in lower_message:
            return [
                'Use `taskledger question answer q-0001 --text "..."`.',
                'Or use `taskledger question answer --question q-0001 --text "..."`.',
            ]
        if command == "plan.lint" and (
            "--allow-empty-criteria" in lower_message
            or "--allow-empty-todos" in lower_message
            or "--allow-open-questions" in lower_message
        ):
            return [
                "Lint has no waiver flags.",
                (
                    "Fix lint findings, or use plan approval waiver flags with "
                    "explicit user intent."
                ),
                (
                    "Example: `taskledger plan approve --version N --actor user "
                    '--allow-lint-errors --reason "..."`.'
                ),
            ]
    if command == "doctor" and "no such command 'errors'" in lower_message:
        return [
            "Use `taskledger doctor` for project health summary.",
            (
                "Use `taskledger doctor locks`, `taskledger doctor schema`, "
                "or `taskledger doctor indexes` for focused diagnostics."
            ),
        ]
    extra_match = re.search(r"unexpected extra argument \(([^)]+)\)", message, re.I)
    if extra_match is None:
        return remediation
    extra = extra_match.group(1).strip()
    if command == "doctor" and extra == "errors":
        return [
            "Use `taskledger doctor` for project health summary.",
            (
                "Use `taskledger doctor locks`, `taskledger doctor schema`, "
                "or `taskledger doctor indexes` for focused diagnostics."
            ),
        ]
    command_parts = command.split(".")
    if (
        len(command_parts) >= 2
        and tuple(command_parts[:2]) in _WORKFLOW_TASK_OPTION_COMMANDS
    ):
        remediation = [
            f"Use `taskledger {command_parts[0]} {command_parts[1]} --task {extra}`."
        ]
    return remediation


def _usage_error_command(argv: tuple[str, ...], exc: click.ClickException) -> str:
    context = getattr(exc, "ctx", None)
    command_path = getattr(context, "command_path", None)
    if isinstance(command_path, str) and command_path.strip():
        parts = command_path.split()
        if parts and parts[0] == "taskledger":
            parts = parts[1:]
        if parts:
            return ".".join(parts)
    return _command_from_tokens(argv)


def _status_human(payload: dict[str, Any]) -> str:
    workspace = payload.get("workspace_root", "?")
    config_path = payload.get("config_path", "?")
    ledger_ref = payload.get("ledger_ref", "?")
    project_uuid = payload.get("project_uuid")
    project_name = payload.get("project_name")
    active_task = payload.get("active_task")
    counts = payload.get("counts")
    health = payload.get("health")

    lines = ["Taskledger status", f"Workspace: {workspace}", f"Config: {config_path}"]
    if isinstance(project_name, str) and project_name.strip():
        if isinstance(project_uuid, str) and project_uuid.strip():
            lines.append(f"Project: {project_name} ({project_uuid})")
        else:
            lines.append(f"Project: {project_name}")
    elif isinstance(project_uuid, str) and project_uuid.strip():
        lines.append(f"Project UUID: {project_uuid}")
    lines.append(f"Ledger: {ledger_ref}")
    if isinstance(active_task, dict):
        task_id = active_task.get("task_id", "?")
        slug = active_task.get("slug", "?")
        stage = active_task.get("status_stage", "?")
        lines.append(f"Active task: {task_id} {slug} ({stage})")
    else:
        lines.append("Active task: none")
    if isinstance(counts, dict):
        summary = " ".join(
            f"{key}={value}"
            for key, value in sorted(counts.items())
            if value is not None
        )
        lines.append(f"Counts: {summary}")
    if isinstance(health, dict):
        checked = bool(health.get("checked"))
        healthy = health.get("healthy")
        if checked:
            lines.append(f"Health: {'healthy' if healthy else 'issues found'}")
        else:
            lines.append("Health: not checked (use --check)")
    lines.append("Next: taskledger next-action")
    return "\n".join(lines)


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            help="Show the version and exit.",
        ),
    ] = False,
    cwd: Annotated[
        Path | None,
        typer.Option(
            "--cwd",
            help="Workspace root. Defaults to the current directory.",
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option(
            "--root",
            help="Workspace root. Preferred alias for --cwd.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Render machine-readable JSON."),
    ] = False,
    no_log: Annotated[
        bool,
        typer.Option(
            "--no-log",
            help="Skip writing an agent command-log record for this invocation.",
        ),
    ] = False,
) -> None:
    # Detect help/introspection invocations early to avoid workspace
    # discovery, config loading, and agent-log recording overhead.
    argv = tuple(sys.argv[1:])
    if _is_help_or_introspection(argv):
        ctx.obj = CLIState(cwd=Path.cwd(), json_output=json_output)
        return

    if cwd is not None and root is not None and cwd != root:
        raise typer.BadParameter(
            "Use either --cwd or --root, not both with different values."
        )
    raw_cwd = (root or cwd or Path.cwd()).expanduser().resolve()
    try:
        resolved_cwd = resolve_workspace_root(raw_cwd)
    except LaunchError as exc:
        ctx.obj = CLIState(cwd=raw_cwd, json_output=json_output)
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    ctx.obj = CLIState(cwd=resolved_cwd, json_output=json_output)
    from taskledger.services.agent_logging import start_cli_recorder

    # When running under test runners like pytest, sys.argv contains test runner args
    # But only reject it if it's clearly not a taskledger command
    _known_commands = {
        "can",
        "commands",
        "context",
        "deps",
        "doctor",
        "export",
        "grep",
        "import",
        "init",
        "next-action",
        "reindex",
        "search",
        "serve",
        "snapshot",
        "status",
        "symbols",
        "tree",
        "view",
        "task",
        "plan",
        "question",
        "implement",
        "validate",
        "todo",
        "intro",
        "file",
        "link",
        "require",
        "lock",
        "handoff",
        "ledger",
        "release",
        "actor",
        "harness",
    }
    is_test_runner_arg = (
        argv
        and (argv[0].startswith("tests/") or "::" in argv[0])
        and argv[0] not in _known_commands
    )
    if argv and argv[0] not in _known_commands and ctx.invoked_subcommand:
        argv = (ctx.invoked_subcommand, *tuple(ctx.args))
    if is_test_runner_arg:
        # This looks like pytest args, use ctx instead
        argv = ()
    if not argv and ctx.invoked_subcommand:
        argv = (ctx.invoked_subcommand,)
    if not argv:
        argv = tuple(ctx.args)
    start_cli_recorder(
        ctx,
        workspace_root=resolved_cwd,
        argv=argv,
        json_output=json_output,
        no_log=no_log,
    )


@app.command("init")
def init_command(
    ctx: typer.Context,
    taskledger_dir: Annotated[
        Path | None,
        typer.Option("--taskledger-dir", help="Durable taskledger storage root."),
    ] = None,
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            help=(
                "Human-readable project name used in reports and default "
                "archive filenames."
            ),
        ),
    ] = None,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    payload = init_project(
        state.cwd,
        taskledger_dir=taskledger_dir,
        project_name=project_name,
    )
    emit_payload(
        ctx,
        payload,
        human="\n".join(
            [
                f"initialized taskledger: {payload['root']}",
                f"project name: {payload['project_name']}",
                *[f"- {item}" for item in cast(list[str], payload["created"])],
            ]
        ),
    )


@app.command("status")
def status_command(
    ctx: typer.Context,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Show the full status payload instead of the compact summary.",
        ),
    ] = False,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Run doctor health check (slower, not done by default).",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        if full:
            payload = project_status(state.cwd)
        else:
            payload = project_status_summary(state.cwd, check_health=check)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=_status_human(payload) if isinstance(payload, dict) else None,
    )


@app.command("tree")
def tree_command(
    ctx: typer.Context,
    task_ref: Annotated[
        str | None,
        typer.Option(
            "--task", help="Render one task subtree instead of the full ledger."
        ),
    ] = None,
    all_ledgers: Annotated[
        bool,
        typer.Option("--all-ledgers", help="Include every local ledger namespace."),
    ] = False,
    details: Annotated[
        bool,
        typer.Option("--details", help="Show compact per-task counts."),
    ] = False,
    include_archived: Annotated[
        bool,
        typer.Option("--include-archived", help="Include archived tasks."),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Use ASCII tree glyphs."),
    ] = False,
) -> None:
    from taskledger.services.tree import render_tree_text

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = project_tree(
            state.cwd,
            task_ref=task_ref,
            include_all_ledgers=all_ledgers,
            details=details,
            include_archived=include_archived,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=render_tree_text(payload, plain=plain),
    )


@app.command("view")
def view_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = dashboard(state.cwd, ref=task_ref)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human = render_dashboard_text(payload)
    emit_payload(ctx, payload, human=human)


@app.command("commands")
def commands_command(
    ctx: typer.Context,
    audience: Annotated[
        str | None,
        typer.Option(
            "--audience",
            help="Filter by audience type.",
        ),
    ] = None,
    effect: Annotated[
        str | None,
        typer.Option(
            "--effect",
            help="Filter by command effect (safe-read-only, ledger-mutation).",
        ),
    ] = None,
    surface: Annotated[
        str | None,
        typer.Option(
            "--surface",
            help="Filter by surface tier (primary, support, advanced, etc.).",
        ),
    ] = None,
    phase: Annotated[
        str | None,
        typer.Option(
            "--phase",
            help="Filter by lifecycle phase.",
        ),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option(
            "--tier",
            help="Filter by tier (critical, normal, rare).",
        ),
    ] = None,
    include_deprecated: Annotated[
        bool,
        typer.Option(
            "--include-deprecated",
            help="Include deprecated commands (hidden by default).",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)

    audience_normalized = audience.replace("-", "_") if audience else None
    effect_normalized = effect.replace("-", "_") if effect else None

    filtered_commands: list[dict[str, str | bool]] = []
    for cmd, spec in sorted(COMMAND_METADATA.items()):
        if not include_deprecated and spec.deprecated:
            continue
        if audience_normalized and spec.audience != audience_normalized:
            continue
        if effect_normalized and spec.effect != effect_normalized:
            continue
        if surface and spec.surface != surface:
            continue
        if phase and spec.phase != phase:
            continue
        if tier and spec.tier != tier:
            continue
        filtered_commands.append(
            {
                "command": cmd,
                "audience": spec.audience,
                "effect": spec.effect,
                "surface": spec.surface,
                "phase": spec.phase,
                "tier": spec.tier,
                "targeting": spec.targeting,
                "deprecated": spec.deprecated,
                "replaced_by": spec.replaced_by,
                "ledger_effect": spec.ledger_effect,
                "workspace_effect": spec.workspace_effect,
                "external_effect": spec.external_effect,
                "agent_safe": spec.agent_safe,
            }
        )

    payload = {
        "kind": "taskledger_command_inventory",
        "commands": filtered_commands,
    }

    if state.json_output:
        emit_payload(ctx, payload)
    else:
        if not filtered_commands:
            typer.echo("No commands matching the specified filters.")
            return

        _cmd_lens = [len(str(cmd["command"])) for cmd in filtered_commands]
        _aud_lens = [len(str(cmd["audience"])) for cmd in filtered_commands]
        _eff_lens = [len(str(cmd["effect"])) for cmd in filtered_commands]
        _sur_lens = [len(str(cmd["surface"])) for cmd in filtered_commands]
        _pha_lens = [len(str(cmd["phase"])) for cmd in filtered_commands]
        _tier_lens = [len(str(cmd["tier"])) for cmd in filtered_commands]
        _target_lens = [len(str(cmd["targeting"])) for cmd in filtered_commands]
        max_cmd = max(_cmd_lens + [len("Command")]) if filtered_commands else 10
        max_aud = max(_aud_lens + [len("Audience")]) if filtered_commands else 10
        max_eff = max(_eff_lens + [len("Effect")]) if filtered_commands else 10
        max_sur = max(_sur_lens + [len("Surface")]) if filtered_commands else 10
        max_pha = max(_pha_lens + [len("Phase")]) if filtered_commands else 10
        max_tier = max(_tier_lens + [len("Tier")]) if filtered_commands else 10
        max_target = max(_target_lens + [len("Targeting")]) if filtered_commands else 10

        header = (
            f"{'Command':<{max_cmd}}  "
            f"{'Audience':<{max_aud}}  "
            f"{'Effect':<{max_eff}}  "
            f"{'Surface':<{max_sur}}  "
            f"{'Phase':<{max_pha}}  "
            f"{'Tier':<{max_tier}}  "
            f"{'Targeting':<{max_target}}"
        )
        typer.echo(header)
        sep_len = (
            max_cmd + max_aud + max_eff + max_sur + max_pha + max_tier + max_target + 12
        )
        typer.echo("-" * sep_len)

        for cmd_info in filtered_commands:
            typer.echo(
                f"{cmd_info['command']:<{max_cmd}}  "
                f"{cmd_info['audience']:<{max_aud}}  "
                f"{cmd_info['effect']:<{max_eff}}  "
                f"{cmd_info['surface']:<{max_sur}}  "
                f"{cmd_info['phase']:<{max_pha}}  "
                f"{cmd_info['tier']:<{max_tier}}  "
                f"{cmd_info['targeting']:<{max_target}}"
            )


@app.command("serve")
def serve_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    refresh_ms: Annotated[int, typer.Option("--refresh-ms")] = 1000,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        from taskledger.services.web_dashboard import (
            DashboardServerConfig,
            launch_dashboard_server,
        )
    except Exception as exc:
        error = _optional_group_failure(
            group_name="serve",
            module_name="taskledger.services.web_dashboard",
            exc=exc,
        )
        emit_error(ctx, error)
        raise typer.Exit(code=launch_error_exit_code(error)) from error
    try:
        handle = launch_dashboard_server(
            DashboardServerConfig(
                workspace_root=state.cwd,
                host=host,
                port=port,
                task_ref=task_ref,
                refresh_ms=refresh_ms,
                open_browser=open_browser,
            )
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        {
            "kind": "serve_started",
            "url": handle.url,
            "host": handle.host,
            "port": handle.port,
        },
        human=f"Serving taskledger dashboard at {handle.url}\nPress Ctrl-C to stop.",
    )
    try:
        handle.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        handle.close()


@doctor_app.callback()
def doctor_command(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Show expanded doctor output including raw warnings.",
        ),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    emit_doctor_command(ctx, verbose=verbose)


@doctor_app.command("locks")
def doctor_locks_command(ctx: typer.Context) -> None:
    emit_doctor_locks_command(ctx)


@doctor_app.command("schema")
def doctor_schema_command(ctx: typer.Context) -> None:
    emit_doctor_schema_command(ctx)


@doctor_app.command("indexes")
def doctor_indexes_command(ctx: typer.Context) -> None:
    emit_doctor_indexes_command(ctx)


@app.command("next-action")
def next_action_command(
    ctx: typer.Context,
    task_ref: TaskOption = None,
) -> None:
    emit_next_action_command(ctx, task_ref)


@app.command("can")
def can_command(
    ctx: typer.Context,
    action_or_task: Annotated[str, typer.Argument(..., help="Action name.")],
    task_ref: TaskOption = None,
) -> None:
    emit_can_command(ctx, task_ref, action_or_task)


@app.command("reindex")
def reindex_command(ctx: typer.Context) -> None:
    emit_reindex_command(ctx)


@repair_app.command("index")
def repair_index_command(ctx: typer.Context) -> None:
    emit_reindex_command(ctx)


@repair_app.command("lock")
def repair_lock_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.locks import break_lock

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = break_lock(state.cwd, task.id, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"repaired lock for {payload['task_id']}")


@repair_app.command("task")
def repair_task_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.tasks import repair_task_record

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = repair_task_record(state.cwd, task.id, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human_lines = [f"recorded repair inspection for {payload['task_id']}"]
    for warning in cast(list[str], payload.get("warnings", [])):
        human_lines.append(f"warning: {warning}")
    for command in cast(list[str], payload.get("recovery_commands", [])):
        human_lines.append(f"recovery: {command}")
    emit_payload(ctx, payload, human="\n".join(human_lines))


@repair_app.command("run")
def repair_run_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.tasks import repair_orphaned_planning_run

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = repair_orphaned_planning_run(
            state.cwd,
            task.id,
            run_id=run_id,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=(
            f"finished orphaned {payload['run_type']} run {payload['run_id']} "
            f"for {payload['task_id']}\nnext: {payload['next_command']}"
        ),
    )


@repair_app.command("planning-command-changes")
def repair_planning_command_changes_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be repaired without making changes.",
        ),
    ] = False,
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.tasks import repair_planning_command_changes

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = repair_planning_command_changes(
            state.cwd,
            task.id,
            reason=reason,
            dry_run=dry_run,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    repaired = cast(list[str], payload.get("repaired_changes", []))
    dry_run_str = " (dry run)" if payload.get("dry_run") else ""
    if repaired:
        human_lines = [
            f"repaired {len(repaired)} planning command changes{dry_run_str}:",
        ]
        for change_id in repaired:
            human_lines.append(f"  - {change_id}")
        human = "\n".join(human_lines)
    else:
        human = f"no planning command changes to repair{dry_run_str}"
    emit_payload(ctx, payload, human=human)


@repair_app.command("task-dirs")
def repair_task_dirs_command(ctx: typer.Context) -> None:
    from taskledger.services.doctor import cleanup_orphan_slug_dirs

    state = ctx.obj
    assert isinstance(state, CLIState)
    payload = cleanup_orphan_slug_dirs(state.cwd)
    removed = cast(list[str], payload.get("removed", []))
    names = ", ".join(removed) if removed else "(none)"
    emit_payload(
        ctx,
        payload,
        human=f"removed {payload['count']} orphan slug directories: {names}",
    )


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
    if path.parent != Path("."):
        return True
    return False


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
        typer.Option("--overwrite", help="Allow overwriting an existing output file."),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    resolved_output = output
    task_refs: list[str] = []
    if task_ref is not None:
        task_refs = [resolve_cli_task(state.cwd, task_ref).id]
        if target_or_output is not None:
            if output is not None:
                emit_error(
                    ctx,
                    LaunchError(
                        "export received both positional output and --output. Use one."
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
                        "export received both positional output and --output. Use one."
                    ),
                )
                raise typer.Exit(code=2)
            resolved_output = Path(target_or_output)
        else:
            try:
                task_refs = [resolve_cli_task(state.cwd, target_or_output).id]
            except LaunchError as exc:
                emit_error(
                    ctx,
                    LaunchError(
                        f"No task found for '{target_or_output}'. To write an archive "
                        "to that filename, use: taskledger export -o "
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
    state = ctx.obj
    assert isinstance(state, CLIState)
    # Detect .tar.gz vs legacy JSON
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


@app.command("snapshot")
def snapshot_command(
    ctx: typer.Context,
    output_dir: Annotated[Path, typer.Argument(..., file_okay=False, dir_okay=True)],
    include_bodies: Annotated[
        bool,
        typer.Option(
            "--include-bodies",
            help="Include Markdown bodies in the snapshot export.",
        ),
    ] = False,
    include_run_artifacts: Annotated[
        bool,
        typer.Option(
            "--include-run-artifacts",
            help="Include run artifact files in the snapshot export.",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = project_snapshot(
            state.cwd,
            output_dir=output_dir,
            include_bodies=include_bodies,
            include_run_artifacts=include_run_artifacts,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=f"wrote snapshot to {payload['snapshot_dir']}")


@app.command("search")
def search_command(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(..., help="Search query.")],
    repo_refs: Annotated[list[str] | None, typer.Option("--repo")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    _emit_search_results(
        ctx,
        lambda cwd: search_workspace(
            cwd,
            query=query,
            repo_refs=tuple(repo_refs or ()),
            limit=limit,
        ),
        title="SEARCH",
    )


@app.command("grep")
def grep_command(
    ctx: typer.Context,
    pattern: Annotated[str, typer.Argument(..., help="Regex pattern.")],
    repo_refs: Annotated[list[str] | None, typer.Option("--repo")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 100,
) -> None:
    _emit_search_results(
        ctx,
        lambda cwd: grep_workspace(
            cwd,
            pattern=pattern,
            repo_refs=tuple(repo_refs or ()),
            limit=limit,
        ),
        title="GREP",
    )


@app.command("symbols")
def symbols_command(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(..., help="Symbol query.")],
    repo_refs: Annotated[list[str] | None, typer.Option("--repo")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    _emit_search_results(
        ctx,
        lambda cwd: symbols_workspace(
            cwd,
            query=query,
            repo_refs=tuple(repo_refs or ()),
            limit=limit,
        ),
        title="SYMBOLS",
    )


@app.command("deps")
def deps_command(
    ctx: typer.Context,
    repo_ref: Annotated[str, typer.Argument(..., help="Repo ref.")],
    module: Annotated[str, typer.Argument(..., help="Module path.")],
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = dependencies_for_module(
            state.cwd,
            repo_ref=repo_ref,
            module=module,
        )
    except LaunchError as exc:
        emit_error(ctx, str(exc))
        raise typer.Exit(code=1) from exc
    emit_payload(ctx, payload)


def _emit_search_results(
    ctx: typer.Context,
    factory: Callable[..., Any],
    *,
    title: str,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        results = factory(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, str(exc))
        raise typer.Exit(code=1) from exc
    human = (
        "\n".join([title, *[item.path for item in results]])
        if results
        else f"{title}\n(empty)"
    )
    emit_payload(ctx, [item.to_dict() for item in results], human=human)


def _is_json_content(path: Path) -> bool:
    """Return True if file appears to contain JSON (starts with '{')."""
    try:
        with path.open("rb") as f:
            return f.read(1) == b"{"
    except OSError:
        return False


def cli_main() -> None:
    argv = tuple(sys.argv[1:])
    json_requested = "--json" in argv
    try:
        app(prog_name="taskledger", args=list(argv), standalone_mode=False)
    except click.ClickException as exc:
        if json_requested:
            command = _usage_error_command(argv, exc)
            error_payload = {
                "ok": False,
                "command": command,
                "error": {
                    "code": "USAGE_ERROR",
                    "message": str(exc),
                    "remediation": _usage_error_remediation(
                        argv,
                        command=command,
                        message=str(exc),
                    ),
                    "exit_code": exc.exit_code,
                },
            }
            typer.echo(render_json(error_payload))
        else:
            exc.show()
        raise SystemExit(exc.exit_code) from exc
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code) from exc

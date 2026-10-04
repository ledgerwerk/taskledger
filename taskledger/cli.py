from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from taskledger._version import __version__
from taskledger.cli_actor import app as actors_app
from taskledger.cli_actor import harness_app
from taskledger.cli_archive import register_archive_commands
from taskledger.cli_commands import register_command_inventory_command

# cli_build and cli_changelog were removed; changelog/build commands are gone.
from taskledger.cli_common import (
    CLIState,
    CommandRuntime,
    emit_error,
    launch_error_exit_code,
    resolve_workspace_root,
)
from taskledger.cli_config import register_config_commands
from taskledger.cli_entrypoint import (
    _command_from_tokens,
    _is_help_or_introspection,
)
from taskledger.cli_entrypoint import (
    cli_main as _run_cli,
)
from taskledger.cli_file import register_file_v2_commands
from taskledger.cli_handoff import register_handoff_v2_commands
from taskledger.cli_help import register_help_command
from taskledger.cli_implement import register_implement_v2_commands
from taskledger.cli_intro import register_intro_v2_commands
from taskledger.cli_ledger import ledger_app
from taskledger.cli_link import register_link_v2_commands
from taskledger.cli_lock import register_lock_v2_commands
from taskledger.cli_maintenance import app as maintenance_app
from taskledger.cli_migrate import migrate_app
from taskledger.cli_monitor import register_monitor_commands
from taskledger.cli_navigation import register_navigation_commands
from taskledger.cli_pipeline import register_pipeline_commands
from taskledger.cli_plan import register_plan_v2_commands
from taskledger.cli_project import register_project_commands
from taskledger.cli_question import register_question_v2_commands
from taskledger.cli_ref import ref_app
from taskledger.cli_repair import register_repair_commands
from taskledger.cli_require import register_require_v2_commands
from taskledger.cli_review import register_review_commands
from taskledger.cli_runtime import runtime_app
from taskledger.cli_search import register_search_commands
from taskledger.cli_storage import register_storage_commands
from taskledger.cli_sync import register_sync_commands
from taskledger.cli_task import register_task_v2_commands
from taskledger.cli_todo import register_todo_v2_commands
from taskledger.cli_trace import register_trace_command
from taskledger.cli_validate import register_validate_v2_commands
from taskledger.command_inventory import top_level_command_names
from taskledger.errors import LaunchError, OptionalCommandGroupUnavailable


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"taskledger {__version__}")
        raise typer.Exit()


app = typer.Typer(add_completion=True, help="Manage staged taskledger coding work.")
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
    help="Manage release tags.",
)
storage_app = typer.Typer(
    add_completion=False,
    help="Inspect and migrate storage locations.",
)
sync_app = typer.Typer(
    add_completion=False,
    help="Manage Git-based state sync.",
)
repair_app = typer.Typer(add_completion=False, help="Repair taskledger state.")
doctor_app = typer.Typer(
    add_completion=False,
    help="Inspect taskledger integrity.",
    invoke_without_command=True,
)
pipeline_app = typer.Typer(
    add_completion=False,
    help="Inspect optional worker pipeline overlays.",
)
review_app = typer.Typer(add_completion=False, help="Record code review evidence.")
config_app = typer.Typer(
    add_completion=False,
    help="Inspect and update project configuration.",
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
# changelog_app removed; changelog commands are no longer registered.
app.add_typer(storage_app, name="storage")
app.add_typer(sync_app, name="sync")
app.add_typer(doctor_app, name="doctor")
app.add_typer(repair_app, name="repair")
app.add_typer(migrate_app, name="migrate")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(runtime_app, name="runtime")
app.add_typer(actors_app, name="actor")
app.add_typer(harness_app, name="harness")
app.add_typer(ledger_app, name="ledger")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(review_app, name="review")
app.add_typer(config_app, name="config")
app.add_typer(ref_app, name="ref")

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
register_storage_commands(storage_app)
register_sync_commands(sync_app)
register_pipeline_commands(pipeline_app)
register_review_commands(review_app)
register_config_commands(config_app)
register_trace_command(app)
register_help_command(app)
register_archive_commands(app)
register_command_inventory_command(app)
register_monitor_commands(app)
register_navigation_commands(app)
register_project_commands(app)
register_repair_commands(repair_app, doctor_app)
register_search_commands(app)
# register_changelog_commands removed.
# register_build_command removed.


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
    except Exception as exc:  # noqa: BLE001
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
    command_names=("tag", "list", "show"),
)


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
    root: Annotated[
        Path | None,
        typer.Option(
            "--root",
            help="Workspace root. Defaults to the current directory.",
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
        current = Path.cwd().resolve()
        ctx.obj = CLIState(
            cwd=current,
            json_output=json_output,
            command_cwd=current,
        )
        return

    raw_cwd = (root or Path.cwd()).expanduser().resolve()

    # Commands that tolerate uninitialized workspaces
    _tolerant_commands = {
        "init",
        "status",
        "info",
        "doctor",
        "commands",
        "help",
        "storage",
        "migrate",
    }
    command = _command_from_tokens(argv)
    command_base = command.split(".")[0] if command else ""
    is_tolerant = command_base in _tolerant_commands

    try:
        resolved_cwd = resolve_workspace_root(raw_cwd)
    except LaunchError as exc:
        if is_tolerant:
            # For tolerant commands, use the raw cwd without failing
            ctx.obj = CLIState(
                cwd=raw_cwd,
                json_output=json_output,
                command_cwd=raw_cwd,
            )
            return
        ctx.obj = CLIState(
            cwd=raw_cwd,
            json_output=json_output,
            command_cwd=raw_cwd,
        )
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    ctx.obj = CLIState(
        cwd=resolved_cwd,
        json_output=json_output,
        runtime=CommandRuntime(workspace_root=resolved_cwd),
        command_cwd=raw_cwd,
    )
    from taskledger.services.agent_logging import start_cli_recorder

    # When running under test runners like pytest, sys.argv contains test runner args
    # But only reject it if it's clearly not a taskledger command
    _known_commands = top_level_command_names()
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


def cli_main() -> None:
    _run_cli(app)

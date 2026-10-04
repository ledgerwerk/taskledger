from __future__ import annotations

import os
import re
import sys
from typing import Any, cast

import click
import typer

from taskledger.cli_common import render_json

try:
    from typer._click import exceptions as _typer_click_exceptions
except ImportError:  # pragma: no cover - older Typer
    TyperClickException: Any = None
else:
    TyperClickException = _typer_click_exceptions.ClickException
_HELP_FLAGS = {"--help", "-h", "--show-completion", "--install-completion"}
_COMPLETION_SHELLS = frozenset({"bash", "zsh", "fish", "powershell", "pwsh"})
_COMPLETION_OPTIONS = frozenset({"--show-completion", "--install-completion"})
_ROOT_OPTIONS_WITH_VALUE = {"--root"}
_WORKFLOW_TASK_OPTION_COMMANDS = {
    ("plan", "start"),
    ("implement", "start"),
    ("validate", "start"),
}


def _is_help_or_introspection(argv: tuple[str, ...]) -> bool:
    """Return True if this is a help/completion invocation that should skip
    workspace discovery and agent-log recording."""
    return bool(_HELP_FLAGS.intersection(argv))


def _has_explicit_completion_shell(argv: tuple[str, ...]) -> bool:
    """Return True when a supported shell follows a completion option."""
    for index, token in enumerate(argv):
        option, separator, value = token.partition("=")
        if option not in _COMPLETION_OPTIONS:
            continue
        if separator:
            if value in _COMPLETION_SHELLS:
                return True
        elif index + 1 < len(argv) and argv[index + 1] in _COMPLETION_SHELLS:
            return True
    return False


def _command_from_tokens(argv: tuple[str, ...]) -> str:
    tokens: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _ROOT_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if token.startswith("--root="):
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
    extra_match = re.search(
        r"unexpected extra argument \(([^)]+)\)", message, re.IGNORECASE
    )
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


_CLICK_EXCEPTION_TYPES: tuple[type[Exception], ...] = (
    click.ClickException,
    *([TyperClickException] if TyperClickException is not None else []),
)


def cli_main(app: typer.Typer) -> None:
    argv = tuple(sys.argv[1:])
    json_requested = "--json" in argv
    completion_detection_env = "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION"
    previous_completion_detection = os.environ.get(completion_detection_env)
    if _has_explicit_completion_shell(argv):
        # Typer uses a boolean completion option when it can auto-detect the
        # shell, which makes an explicit trailing shell look like an extra
        # argument. Force its explicit-shell parameter mode for this call.
        os.environ[completion_detection_env] = "1"
    try:
        result = app(prog_name="taskledger", args=list(argv), standalone_mode=False)
        if isinstance(result, int) and result != 0:
            raise SystemExit(result)
    except _CLICK_EXCEPTION_TYPES as exc:
        click_exc = cast(click.ClickException, exc)
        if json_requested:
            command = _usage_error_command(argv, click_exc)
            error_payload = {
                "ok": False,
                "command": command,
                "error": {
                    "code": "USAGE_ERROR",
                    "message": str(click_exc),
                    "remediation": _usage_error_remediation(
                        argv,
                        command=command,
                        message=str(click_exc),
                    ),
                    "exit_code": click_exc.exit_code,
                },
            }
            typer.echo(render_json(error_payload))
        else:
            click_exc.show()
        raise SystemExit(click_exc.exit_code) from click_exc
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code) from exc
    finally:
        if previous_completion_detection is None:
            os.environ.pop(completion_detection_env, None)
        else:
            os.environ[completion_detection_env] = previous_completion_detection

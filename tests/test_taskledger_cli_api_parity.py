from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def test_cli_command_tree_matches_task_first_contract(tmp_path: Path) -> None:
    runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    result = runner.invoke(app, ["--cwd", str(tmp_path), "--help"])

    assert result.exit_code == 0
    for name in (
        "init",
        "usage",
        "monitor",
        "status",
        "doctor",
        "export",
        "import",
        "snapshot",
        "search",
        "grep",
        "symbols",
        "deps",
        "release",
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
        "context",
        "handoff",
        "repair",
        "next-action",
        "can",
        "reindex",
        "tree",
    ):
        assert name in result.stdout


def test_legacy_cli_groups_are_removed(tmp_path: Path) -> None:
    runner.invoke(app, ["--cwd", str(tmp_path), "init"])

    for command in (
        "board",
        "next",
        "item",
        "memory",
        "repo",
        "runs",
        "run",
        "validation",
        "workflow",
        "exec-request",
        "compose",
        "runtime-support",
    ):
        result = runner.invoke(app, ["--cwd", str(tmp_path), command, "--help"])
        assert result.exit_code != 0


def test_task_first_subcommands_are_registered(tmp_path: Path) -> None:
    runner.invoke(app, ["--cwd", str(tmp_path), "init"])

    expected = {
        "task": (
            "create",
            "list",
            "show",
            "edit",
            "cancel",
            "close",
            "follow-up",
            "dossier",
            "transcript",
        ),
        "plan": (
            "start",
            "propose",
            "export",
            "upsert",
            "list",
            "show",
            "diff",
            "approve",
            "accept",
            "reject",
            "revise",
            "amend",
        ),
        "question": ("add", "list", "open", "answer", "answer-many", "dismiss"),
        "implement": (
            "start",
            "log",
            "deviation",
            "artifact",
            "change",
            "scan-changes",
            "command",
            "show",
            "finish",
        ),
        "validate": ("start", "check", "show", "finish"),
        "todo": ("add", "list", "show", "done", "undone"),
        "file": ("add", "link", "remove", "list", "status", "refresh"),
        "link": ("add", "remove", "list"),
        "require": ("add", "list", "remove", "waive"),
        "release": ("tag", "list", "show", "changelog"),
        "lock": ("show", "break", "list"),
        "handoff": (
            "show",
            "plan-context",
            "implementation-context",
            "validation-context",
        ),
        "repair": ("index", "lock", "task"),
    }

    for command, subcommands in expected.items():
        result = runner.invoke(app, ["--cwd", str(tmp_path), command, "--help"])
        assert result.exit_code == 0
        for subcommand in subcommands:
            assert subcommand in result.stdout


def test_file_and_link_help_describe_distinct_surfaces(tmp_path: Path) -> None:
    runner.invoke(app, ["--cwd", str(tmp_path), "init"])

    file_help = runner.invoke(app, ["--cwd", str(tmp_path), "file", "--help"])
    link_help = runner.invoke(app, ["--cwd", str(tmp_path), "link", "--help"])

    assert file_help.exit_code == 0
    assert link_help.exit_code == 0
    assert "Manage task file links." in file_help.stdout
    assert "Manage external and typed task links." in link_help.stdout

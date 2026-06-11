from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from taskledger.cli import app

REMOVED_COMMANDS = {
    "task new",
    "task clear-active",
    "implement add-change",
    "validate add-check",
    "file unlink",
    "link link",
    "link unlink",
}


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _registered_command_paths() -> set[str]:
    paths: set[str] = {
        command.name for command in app.registered_commands if command.name
    }

    def _walk(prefix: str, typer_app: Any) -> None:
        instance = typer_app
        if " " in prefix:
            paths.add(prefix)
        for command in instance.registered_commands:
            if command.name:
                paths.add(f"{prefix} {command.name}".strip())
        for subgroup in instance.registered_groups:
            if subgroup.name:
                _walk(f"{prefix} {subgroup.name}".strip(), subgroup.typer_instance)

    for group in app.registered_groups:
        if group.name:
            _walk(group.name, group.typer_instance)
    paths.add("doctor")
    return paths


# sw: f=specs/behavior/features/cli_command_contract/cli-command-contract.feature
# sw: s=@bdd-cli-command-contract-removed-aliases-are-not-registered
def test_removed_aliases_are_not_registered() -> None:
    assert REMOVED_COMMANDS.isdisjoint(_registered_command_paths())


# sw: f=specs/behavior/features/cli_command_contract/cli-command-contract.feature
# sw: s=@bdd-cli-command-contract-commands-do-not-register-local-json-options
def test_commands_do_not_register_local_json_options() -> None:
    import inspect

    callbacks: list[tuple[str, object]] = []
    for command in app.registered_commands:
        if command.name is not None:
            callbacks.append((command.name, command.callback))
    for group in app.registered_groups:
        for command in group.typer_instance.registered_commands:
            if command.name is not None:
                callbacks.append((f"{group.name} {command.name}", command.callback))

    offenders: list[str] = []
    for command, callback in callbacks:
        if command == "taskledger":
            continue
        for parameter in inspect.signature(callback).parameters.values():
            if "--json" in str(parameter.annotation):
                offenders.append(f"{command}:{parameter.name}")
    assert not offenders


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/cli_command_contract/cli-command-contract.feature"
    ),
    scenario=(
        "@bdd-cli-command-contract-workflow-commands-reject-positional-task-"
        "refs-with-json-remediation"
    ),
)
def test_workflow_commands_reject_positional_task_refs_with_json_remediation(
    tmp_path: Path,
) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    workflow_commands = [
        ("plan", "start"),
        ("implement", "start"),
        ("validate", "start"),
    ]
    for group, command in workflow_commands:
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", group, command, "task-0001"],
        )
        assert result.exit_code == 2, (group, command, result.stdout)
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "USAGE_ERROR"
        assert f"taskledger {group} {command} --task task-0001" in " ".join(
            payload["error"]["remediation"]
        )


# sw: f=specs/behavior/features/cli_command_contract/cli-command-contract.feature
# sw: s=@bdd-cli-command-contract-task-show-accepts-positional-task-ref-and-task-option
def test_task_show_accepts_positional_task_ref_and_task_option(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Contract Task",
                "--slug",
                "contract-task",
                "--description",
                "Exercise the task resource grammar.",
            ],
        ).exit_code
        == 0
    )

    positional = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "show", "contract-task"],
    )
    assert positional.exit_code == 0, positional.stdout
    positional_payload = json.loads(positional.stdout)
    assert positional_payload["ok"] is True
    assert positional_payload["result"]["task"]["id"] == "task-0001"

    explicit = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "show", "--task", "contract-task"],
    )
    assert explicit.exit_code == 0, explicit.stdout
    explicit_payload = json.loads(explicit.stdout)
    assert explicit_payload["ok"] is True
    assert explicit_payload["result"]["task"]["id"] == "task-0001"


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/cli_command_contract/cli-command-contract.feature"
    ),
    scenario=(
        "@bdd-cli-command-contract-task-cancel-requires-explicit-target-even-"
        "when-active-exists"
    ),
)
def test_task_cancel_requires_explicit_target_even_when_active_exists(
    tmp_path: Path,
) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Task A",
                "--slug",
                "task-a",
                "--description",
                "A",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "activate",
                "task-a",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "cancel", "--reason", "duplicate"],
    )
    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "USAGE_ERROR"
    assert "requires an explicit target" in payload["error"]["message"]


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/cli_command_contract/cli-command-contract.feature"
    ),
    scenario=(
        "@bdd-cli-command-contract-task-cancel-accepts-positional-task-ref-"
        "and-active-flag"
    ),
)
def test_task_cancel_accepts_positional_task_ref_and_active_flag(
    tmp_path: Path,
) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Task A",
                "--slug",
                "task-a",
                "--description",
                "A",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "task",
                "cancel",
                "task-a",
                "--reason",
                "duplicate",
            ],
        ).exit_code
        == 0
    )
    show_a = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "show", "task-a"],
    )
    assert show_a.exit_code == 0
    show_payload = json.loads(show_a.stdout)
    assert show_payload["result"]["task"]["status_stage"] == "cancelled"

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Task B",
                "--slug",
                "task-b",
                "--description",
                "B",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "task-b"],
        ).exit_code
        == 0
    )
    cancel_active = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "cancel",
            "--active",
            "--reason",
            "duplicate",
        ],
    )
    assert cancel_active.exit_code == 0, cancel_active.stdout
    active_payload = json.loads(cancel_active.stdout)
    assert active_payload["result"]["target"]["selection"] == "active_explicit"


# sw: f=specs/behavior/features/cli_command_contract/cli-command-contract.feature
# sw: s=@bdd-cli-command-contract-global-json-only-for-task-show
def test_global_json_only_for_task_show(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Json Task",
                "--slug",
                "json-task",
                "--description",
                "Exercise global JSON output.",
            ],
        ).exit_code
        == 0
    )

    local = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "show", "--task", "json-task", "--json"],
    )
    assert local.exit_code != 0

    global_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "show", "--task", "json-task"],
    )
    assert global_result.exit_code == 0, global_result.stdout
    payload = json.loads(global_result.stdout)
    assert payload["command"] == "task.show"
    assert payload["ok"] is True


# sw: f=specs/behavior/features/cli_command_contract/cli-command-contract.feature
# sw: s=@bdd-cli-command-contract-version-flag-displays-version
def test_version_flag_displays_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "taskledger, version" in result.stdout


# ── Ledger isolation tests ──────────────────────────────────────


def test_bdd_group_is_not_registered() -> None:
    result = runner.invoke(app, ["bdd", "--help"])
    assert result.exit_code != 0
    assert (
        "No such command" in result.output
        or "Got unexpected extra argument" in result.output
    )


def test_validate_import_bdd_report_is_not_registered() -> None:
    result = runner.invoke(app, ["validate", "import-bdd-report", "report.xml"])
    assert result.exit_code != 0


def test_task_bundle_does_not_create_bdd_directory(tmp_path: Path) -> None:
    from tests.support.builders import init_workspace

    init_workspace(tmp_path)
    result = runner.invoke(app, ["--cwd", str(tmp_path), "task", "create", "Example"])
    assert result.exit_code == 0
    assert not list(tmp_path.glob(".taskledger/**/tasks/task-*/bdd"))

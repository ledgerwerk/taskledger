from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.task_store import (
    overwrite_plan,
    resolve_plan,
    resolve_run,
    resolve_task,
    save_run,
)
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _json(result) -> dict[str, object]:
    payload = json.loads(result.stdout)
    return payload


def _prepare_proposed_plan(
    tmp_path: Path, *, criterion: str | None = "Must be explicit."
) -> None:
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "approval-task",
                "--description",
                "Exercise plan approval.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "start", "--task", "approval-task"],
        ).exit_code
        == 0
    )
    command = [
        "--cwd",
        str(tmp_path),
        "plan",
        "propose",
        "--task",
        "approval-task",
        "--text",
        "## Goal\n\nShip safely.",
    ]
    if criterion is not None:
        command.extend(["--criterion", criterion])
    assert runner.invoke(app, command).exit_code == 0


# specmason: req=REQ-0036 ac=AC-0403
def test_plan_approval_records_actor_metadata_and_criteria_ids(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)

    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--approval-source",
            "explicit_chat",
            "--note",
            "Reviewed and approved.",
            "--allow-empty-todos",
            "--reason",
            "test",
            "--allow-lint-errors",
        ],
    )
    assert approve.exit_code == 0

    show = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "show",
                "--task",
                "approval-task",
                "--version",
                "1",
            ],
        )
    )
    plan = show["result"]["plan"]
    assert plan["criteria"][0]["id"] == "ac-0001"
    assert plan["approved_by"]["actor_type"] == "user"
    assert plan["approval_note"] == "Reviewed and approved."
    assert plan["approval_source"] == "explicit_chat"
    assert isinstance(plan["approved_plan_hash"], str)
    assert plan["approved_plan_hash"]
    assert plan["approved_at"]


# specmason: req=REQ-0036 ac=AC-0406
def test_plan_approval_warns_when_source_is_missing(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)

    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "Reviewed and approved.",
            "--allow-empty-todos",
            "--reason",
            "test",
            "--allow-lint-errors",
        ],
    )
    assert approve.exit_code == 0, approve.stdout
    payload = _json(approve)
    warnings = payload.get("warnings", [])
    assert isinstance(warnings, list)
    assert any("Approval source missing" in str(item) for item in warnings)


# specmason: req=REQ-0036 ac=AC-0409
def test_task_report_warns_when_approved_plan_hash_mismatches(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)
    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--approval-source",
            "explicit_chat",
            "--note",
            "Reviewed and approved.",
            "--allow-empty-todos",
            "--reason",
            "test",
            "--allow-lint-errors",
        ],
    )
    assert approve.exit_code == 0, approve.stdout

    task = resolve_task(tmp_path, "approval-task")
    plan = resolve_plan(tmp_path, task.id, version=1)
    tampered = replace(plan, body=plan.body + "\nTampered.")
    overwrite_plan(tmp_path, tampered)

    report = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "report",
            "--task",
            "approval-task",
            "--section",
            "accepted-plan",
        ],
    )
    assert report.exit_code == 0, report.stdout
    assert "approved plan content hash does not match" in report.stdout


# specmason: req=REQ-0036 ac=AC-0402
def test_plan_approval_blocks_running_planning_run_without_lock(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)
    task = resolve_task(tmp_path, "approval-task")
    assert task.latest_planning_run is not None
    run = resolve_run(tmp_path, task.id, task.latest_planning_run)
    save_run(tmp_path, replace(run, status="running", finished_at=None))

    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--allow-empty-todos",
            "--reason",
            "test",
            "--allow-lint-errors",
        ],
    )

    assert approve.exit_code != 0
    payload = _json(approve)
    assert payload["error"]["code"] == "APPROVAL_REQUIRED"
    assert "running planning run" in payload["error"]["message"]
    details = payload["error"]["details"]
    assert details["running_run"]["run_id"] == run.run_id
    assert details["running_run"]["run_type"] == "planning"


# specmason: req=REQ-0036 ac=AC-0404
def test_plan_approval_rejects_agent_approval_without_escape_hatch(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)

    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "agent",
            "--note",
            "Auto-approved.",
            "--allow-empty-todos",
            "--reason",
            "test",
        ],
    )
    payload = _json(approve)
    assert approve.exit_code != 0
    assert payload["ok"] is False
    assert "allow-agent-approval" in payload["error"]["message"]


# specmason: req=REQ-0036 ac=AC-0405
def test_plan_approval_requires_criteria_by_default(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path, criterion=None)

    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "Reviewed and approved.",
            "--allow-empty-todos",
            "--reason",
            "test",
        ],
    )
    payload = _json(approve)
    assert approve.exit_code != 0
    assert payload["ok"] is False
    assert "acceptance criterion" in payload["error"]["message"]


# specmason: req=REQ-0036 ac=AC-0401
def test_plan_accept_human_error_includes_lint_issue_details(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--allow-empty-todos",
            "--reason",
            "test lint detail rendering",
        ],
    )

    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "Plan lint details:" in combined
    assert "missing_todos" in combined
    assert "plan.todos" in combined


# specmason: req=REQ-0036 ac=AC-0407
def test_plan_approve_default_actor_is_agent(tmp_path: Path) -> None:
    """Verify that plan approve defaults to agent,
    requiring explicit --actor user for user approval."""
    _init_project(tmp_path)
    _prepare_proposed_plan(tmp_path)

    approve = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "approval-task",
            "--version",
            "1",
            "--note",
            "Auto-approved without specifying actor.",
            "--allow-empty-todos",
            "--reason",
            "test",
        ],
    )
    payload = _json(approve)
    assert approve.exit_code != 0
    assert payload["ok"] is False
    assert "allow-agent-approval" in payload["error"]["message"]


# specmason: req=REQ-0036 ac=AC-0408
def test_plan_yaml_single_key_shorthand_criteria(tmp_path: Path) -> None:
    """Verify plan YAML accepts single-key shorthand mappings for criteria."""
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "shorthand-task",
                "--description",
                "Test shorthand.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "start", "--task", "shorthand-task"],
        ).exit_code
        == 0
    )

    plan_text = """---
acceptance_criteria:
  - ac-0001: The feature works correctly.
  - id: ac-0002
    text: Edge cases handled.
---\n\n# Plan\n\nDo the work."""
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--task",
                "shorthand-task",
                "--text",
                plan_text,
            ],
        ).exit_code
        == 0
    )

    show = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "show",
            "--task",
            "shorthand-task",
            "--version",
            "1",
        ],
    )
    assert show.exit_code == 0
    plan = json.loads(show.stdout)["result"]["plan"]
    assert len(plan["criteria"]) == 2
    assert plan["criteria"][0]["id"] == "ac-0001"
    assert plan["criteria"][0]["text"] == "The feature works correctly."
    assert plan["criteria"][1]["id"] == "ac-0002"
    assert plan["criteria"][1]["text"] == "Edge cases handled."

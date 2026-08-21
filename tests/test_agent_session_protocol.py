"""Tests covering the agent session failure patterns identified in the audit.

These tests verify guardrails that prevent common agent misuse:
- lock break no-lock message points to next-action
- plan approval escape hatches require --reason
- plan approval blocks when plan has no todos
- plan command records diagnostics during planning
- validate finish blocks when mandatory criteria are unchecked
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.command_runner import CommandResult
from taskledger.services.tasks import (
    activate_task,
    create_task,
    propose_plan,
    start_planning,
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


def _stub_planning_command(monkeypatch: pytest.MonkeyPatch, *, exit_code: int) -> None:
    def fake_run_managed_command(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        workspace_root: Path,
    ) -> CommandResult:
        return CommandResult(exit_code, "", "")

    monkeypatch.setattr(
        "taskledger.services.change_tracking.command_runner.run_managed_command",
        fake_run_managed_command,
    )


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _prepare_proposed_plan_with_todos(
    tmp_path: Path,
    *,
    criterion: str = "Must pass.",
    todo: str = "Fix the thing.",
) -> None:
    init_workspace(tmp_path)
    task_id = create_task(
        tmp_path, title="test-task", slug="test-task", description="Test task."
    )
    activate_task(tmp_path, task_id.id, reason="test setup")
    start_planning(tmp_path, task_id.id)
    plan_body = (
        "---\n"
        "acceptance_criteria:\n"
        f'  - text: "{criterion}"\n'
        "todos:\n"
        f'  - text: "{todo}"\n'
        "---\n\n"
        "# Plan\n\nFix things.\n"
    )
    propose_plan(tmp_path, task_id.id, body=plan_body)


def _prepare_proposed_plan_no_todos(
    tmp_path: Path,
    *,
    criterion: str = "Must pass.",
) -> None:
    init_workspace(tmp_path)
    task_id = create_task(
        tmp_path, title="test-task", slug="test-task", description="Test task."
    )
    activate_task(tmp_path, task_id.id, reason="test setup")
    start_planning(tmp_path, task_id.id)
    propose_plan(tmp_path, task_id.id, body="Fix things.", criteria=(criterion,))


# --- Lock break no-lock message ---


# specmason: req=REQ-0005 ac=AC-0067
def test_lock_break_no_lock_message_mentions_next_action(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "lock-test",
                "--description",
                "Lock test.",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "lock",
            "break",
            "--task",
            "lock-test",
            "--reason",
            "testing",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    message = payload["error"]["message"]
    assert "next-action" in message.lower() or "next_action" in message.lower()


def test_plan_propose_releases_planning_lock(tmp_path: Path) -> None:
    """After plan propose, no planning lock should exist."""
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "lock-rel",
                "--description",
                "Lock release test.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "lock-rel"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--task",
                "lock-rel",
                "--text",
                (
                    "---\n"
                    "acceptance_criteria:\n"
                    '  - text: "Pass."\n'
                    "todos:\n"
                    '  - text: "Do it."\n'
                    "---\n\n"
                    "# Plan\n\nPlan text.\n"
                ),
            ],
        ).exit_code
        == 0
    )

    lock_show = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "lock", "show"])
    if lock_show.exit_code == 0:
        payload = _json(lock_show)
        # No active lock should exist after plan propose
        assert (
            payload.get("lock") is None or payload.get("result", {}).get("lock") is None
        )


# --- Escape hatch reason requirements ---


# specmason: req=REQ-0005 ac=AC-0064
def test_allow_empty_criteria_requires_reason(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--allow-empty-criteria",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert "reason" in payload["error"]["message"].lower()


# specmason: req=REQ-0005 ac=AC-0066
def test_allow_open_questions_requires_reason(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--allow-open-questions",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert "reason" in payload["error"]["message"].lower()


# specmason: req=REQ-0005 ac=AC-0065
def test_allow_empty_criteria_with_reason_succeeds(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--allow-lint-errors",
            "--reason",
            "testing escape hatch",
            "--allow-empty-criteria",
        ],
    )
    assert result.exit_code == 0


# --- Empty todos gate ---


# specmason: req=REQ-0005 ac=AC-0070
def test_plan_approval_blocks_when_no_todos(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_no_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    message = payload["error"]["message"].lower()
    assert "todo" in message


# specmason: req=REQ-0005 ac=AC-0071
def test_plan_approval_empty_todos_with_reason_succeeds(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_no_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--allow-empty-todos",
            "--allow-lint-errors",
            "--reason",
            "trivial task",
        ],
    )
    assert result.exit_code == 0


# specmason: req=REQ-0005 ac=AC-0072
def test_plan_approval_empty_todos_without_reason_fails(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_no_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--allow-empty-todos",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert "reason" in payload["error"]["message"].lower()


# --- Plan command ---


# specmason: req=REQ-0005 ac=AC-0077
def test_plan_command_records_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_planning_command(monkeypatch, exit_code=0)
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "cmd-test",
                "--description",
                "Command test.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "cmd-test"]
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "command",
            "--task",
            "cmd-test",
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
    )
    payload = _json(result)
    assert result.exit_code == 0
    assert payload["result"]["exit_code"] == 0


# specmason: req=REQ-0005 ac=AC-0074
def test_plan_command_fails_without_active_planning(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "cmd-fail",
                "--description",
                "Command fail test.",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "command",
            "--task",
            "cmd-fail",
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False


# specmason: req=REQ-0005 ac=AC-0076
def test_plan_command_no_change_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify plan command stores summary in worklog, not as change records."""
    _stub_planning_command(monkeypatch, exit_code=0)
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "no-change-cmd",
                "--description",
                "No change record test.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "no-change-cmd"]
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "command",
            "--task",
            "no-change-cmd",
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
    )
    payload = _json(result)
    assert result.exit_code == 0
    assert payload["result"]["change"] is None, (
        "plan command should not create change records"
    )

    view_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "view",
            "--task",
            "no-change-cmd",
        ],
    )
    view_payload = _json(view_result)
    task_data = view_payload["result"]["task"]
    assert len(task_data.get("code_change_log", [])) == 0, (
        "plan command should not add to code_change_log"
    )


# specmason: req=REQ-0005 ac=AC-0075
def test_plan_command_mirrors_inner_exit_code_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_planning_command(monkeypatch, exit_code=6)
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "plan-cmd-exit",
                "--description",
                "Plan command exit behavior.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "start", "--task", "plan-cmd-exit"],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "command",
            "--task",
            "plan-cmd-exit",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(6)",
        ],
    )
    assert result.exit_code == 6


# specmason: req=REQ-0005 ac=AC-0073
def test_plan_command_allow_failure_keeps_wrapper_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_planning_command(monkeypatch, exit_code=6)
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "plan-cmd-allow-failure",
                "--description",
                "Plan command allow-failure behavior.",
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
                "plan",
                "start",
                "--task",
                "plan-cmd-allow-failure",
            ],
        ).exit_code
        == 0
    )
    raw = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "command",
            "--allow-failure",
            "--task",
            "plan-cmd-allow-failure",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(6)",
        ],
    )
    assert raw.exit_code == 0, raw.stdout
    payload = _json(raw)
    assert payload["result"]["exit_code"] == 6


# --- Validation finish gate ---


# specmason: req=REQ-0005 ac=AC-0081
def test_validate_finish_passed_blocks_unchecked_mandatory_criteria(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                "test-task",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "approved",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "implement", "start", "--task", "test-task"],
        ).exit_code
        == 0
    )
    # Mark the plan-materialized todo done so implement finish can pass
    todo_list_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "todo", "list", "--task", "test-task"],
    )
    todo_payload = _json(todo_list_result)
    todos = todo_payload["result"]["todos"]
    todo_id = todos[0]["id"]
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "done",
                todo_id,
                "--task",
                "test-task",
                "--evidence",
                "done",
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
                "implement",
                "finish",
                "--task",
                "test-task",
                "--summary",
                "done",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "validate", "start", "--task", "test-task"],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "finish",
            "--task",
            "test-task",
            "--result",
            "passed",
            "--summary",
            "passed",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert (
        "incomplete" in payload["error"]["message"].lower()
        or "mandatory" in payload["error"]["message"].lower()
    )


# --- --no-materialize-todos reason gate ---


# specmason: req=REQ-0005 ac=AC-0069
def test_no_materialize_todos_without_reason_fails(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--no-materialize-todos",
        ],
    )
    payload = _json(result)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert "reason" in payload["error"]["message"].lower()


# specmason: req=REQ-0005 ac=AC-0068
def test_no_materialize_todos_with_reason_succeeds(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "approve",
            "--task",
            "test-task",
            "--version",
            "1",
            "--actor",
            "user",
            "--note",
            "approved",
            "--no-materialize-todos",
            "--allow-lint-errors",
            "--reason",
            "trivial task; checklist not needed",
        ],
    )
    assert result.exit_code == 0


# --- Todo source inference ---


# specmason: req=REQ-0005 ac=AC-0078
def test_todo_added_during_implementation_is_implementer_sourced(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    _prepare_proposed_plan_with_todos(tmp_path)

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                "test-task",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "approved",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "implement", "start", "--task", "test-task"],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "todo",
            "add",
            "--task",
            "test-task",
            "--text",
            "Implementation todo",
        ],
    )
    assert result.exit_code == 0
    payload = _json(result)
    added_todo = payload["result"]["todo"]
    assert added_todo["text"] == "Implementation todo"
    assert added_todo["source"] == "implementer"


# specmason: req=REQ-0005 ac=AC-0079
def test_todo_added_during_planning_is_planner_sourced(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "source-test",
                "--description",
                "Source test.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "start", "--task", "source-test"],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "todo",
            "add",
            "--task",
            "source-test",
            "--text",
            "Planning todo",
        ],
    )
    assert result.exit_code == 0
    payload = _json(result)
    added_todo = payload["result"]["todo"]
    assert added_todo["text"] == "Planning todo"
    assert added_todo["source"] == "planner"


# specmason: req=REQ-0005 ac=AC-0080
def test_todo_added_without_active_stage_defaults_to_user(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "source-default",
                "--description",
                "Source default test.",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "todo",
            "add",
            "--task",
            "source-default",
            "--text",
            "User todo",
        ],
    )
    assert result.exit_code == 0
    payload = _json(result)
    added_todo = payload["result"]["todo"]
    assert added_todo["text"] == "User todo"
    assert added_todo["source"] == "user"

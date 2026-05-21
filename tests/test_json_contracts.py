from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0


def _append_pipeline_config(path: Path) -> None:
    current = path.read_text(encoding="utf-8")
    current += """

[worker_pipeline]
enabled = true
name = "tdd-four-context"
mode = "guided"

[[worker_pipeline.steps]]
id = "tester"
label = "Test Writer"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "check"
test_command_policy = "may_fail"

[[worker_pipeline.steps]]
id = "coder"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"
test_command_policy = "must_pass"
"""
    path.write_text(current, encoding="utf-8")


def _setup_worker_pipeline_task(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _append_pipeline_config(tmp_path / "taskledger.toml")
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "pipeline-json-task",
                "--slug",
                "pipeline-json-task",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "pipeline-json-task"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    plan_text = """---
acceptance_criteria:
  - text: Pipeline JSON surfaces remain stable.
todos:
  - text: Add failing regression tests.
    worker_step: tester
    validation_hint: pytest tests/test_json_contracts.py
  - text: Implement the approved change.
    worker_step: coder
    validation_hint: pytest tests/test_json_contracts.py
---

# Plan

Keep worker pipeline JSON payloads explicit and stable.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "propose", "--text", plan_text],
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
                "approve",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved.",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(tmp_path), "implement", "start"]).exit_code
        == 0
    )


def test_json_success_envelope_uses_ok_command_result_and_events(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "create",
            "json-contract-task",
            "--description",
            "Verify the stable JSON success envelope.",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload == {
        "ok": True,
        "command": "task.create",
        "task_id": "task-0001",
        "result": payload["result"],
        "events": [],
    }
    assert payload["result"]["slug"] == "json-contract-task"


def test_json_failure_envelope_includes_structured_error(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "question-blocked",
            "--description",
            "Approval should fail while a question is open.",
        ],
    )
    runner.invoke(
        app, ["--cwd", str(tmp_path), "plan", "start", "--task", "question-blocked"]
    )
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "question",
            "add",
            "question-blocked",
            "--text",
            "Need one more decision?",
        ],
    )
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "propose",
            "--task",
            "question-blocked",
            "--text",
            "## Goal\n\nAnswer the question first.\n",
        ],
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--task",
            "question-blocked",
            "--version",
            "1",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "plan.approve"
    assert payload["error"]["code"] == "WORKFLOW_REJECTION"
    assert payload["error"]["message"]
    assert payload["error"]["exit_code"] == 3


def test_context_missing_todo_focus_returns_json_error(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "focus-error",
            "--description",
            "Need an active task for context errors.",
        ],
    )
    runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", "focus-error"])

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "context",
            "--for",
            "implementer",
            "--scope",
            "todo",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["message"] == "--scope todo requires --todo"


def test_status_json_reports_workspace_and_storage_paths(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "status",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    status = payload["result"]
    assert status["workspace_root"] == str(tmp_path)
    assert status["config_path"] == str(tmp_path / "taskledger.toml")
    assert status["taskledger_dir"] == str(tmp_path / ".taskledger")
    assert status["project_dir"] == str(tmp_path / ".taskledger" / "ledgers" / "main")


def test_worker_pipeline_json_contracts_cover_guided_surfaces(tmp_path: Path) -> None:
    _setup_worker_pipeline_task(tmp_path)

    show_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "pipeline", "show"],
    )
    assert show_result.exit_code == 0, show_result.stdout
    show_payload = json.loads(show_result.stdout)
    assert show_payload["ok"] is True
    assert show_payload["result"]["pipeline"]["mode"] == "guided"

    next_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "pipeline", "next"],
    )
    assert next_result.exit_code == 0, next_result.stdout
    next_payload = json.loads(next_result.stdout)
    assert next_payload["result"]["step"]["id"] == "tester"

    context_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "pipeline",
            "context",
            "tester",
            "--format",
            "json",
        ],
    )
    assert context_result.exit_code == 0, context_result.stdout
    context_payload = json.loads(context_result.stdout)
    assert context_payload["result"]["worker_step"]["id"] == "tester"

    handoff_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "handoff",
            "create",
            "--worker",
            "tester",
            "--summary",
            "Add failing tests only.",
        ],
    )
    assert handoff_result.exit_code == 0, handoff_result.stdout
    handoff_payload = json.loads(handoff_result.stdout)
    assert handoff_payload["result"]["worker_step_id"] == "tester"

    action_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "next-action"],
    )
    assert action_result.exit_code == 0, action_result.stdout
    action_payload = json.loads(action_result.stdout)
    worker_pipeline = action_payload["result"]["worker_pipeline"]
    assert worker_pipeline["enabled"] is True
    assert worker_pipeline["mode"] == "guided"
    assert worker_pipeline["next_step"]["id"] == "tester"
    assert worker_pipeline["context_command"] == "taskledger pipeline context tester"
    assert worker_pipeline["handoff_command"] == (
        'taskledger handoff create --worker tester --summary "..."'
    )


def test_python_m_taskledger_uses_canonical_json_command_names(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "taskledger",
            "--cwd",
            str(tmp_path),
            "--json",
            "status",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "status"


def test_workflow_positional_task_ref_returns_json_usage_error_envelope(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "plan", "start", "task-0001"],
    )
    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "plan.start"
    assert payload["error"]["code"] == "USAGE_ERROR"
    assert "plan start --task task-0001" in " ".join(payload["error"]["remediation"])


def test_python_m_taskledger_json_parse_error_envelope(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "taskledger",
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "show",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "USAGE_ERROR"
    assert payload["error"]["exit_code"] == 2


def test_plan_lint_usage_error_includes_waiver_hint(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "taskledger",
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "lint",
            "--allow-empty-criteria",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "USAGE_ERROR"
    remediation = " ".join(payload["error"]["remediation"])
    assert "Lint has no waiver flags" in remediation
    assert "allow-lint-errors" in remediation


def test_doctor_usage_error_for_errors_argument_has_specific_hint(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "taskledger",
            "--cwd",
            str(tmp_path),
            "--json",
            "doctor",
            "errors",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "USAGE_ERROR"
    remediation = " ".join(payload["error"]["remediation"])
    assert "doctor locks" in remediation
    assert "doctor schema" in remediation

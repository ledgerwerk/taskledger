from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _append_pipeline_config(path: Path, text: str) -> None:
    current = path.read_text(encoding="utf-8")
    path.write_text(f"{current.rstrip()}\n\n{text.strip()}\n", encoding="utf-8")


def _enabled_pipeline_config() -> str:
    return """
[worker_pipeline]
enabled = true
name = "tdd-four-context"
mode = "guided"

[[worker_pipeline.steps]]
id = "planner"
lifecycle_stage = "planning"
base_context = "planner"

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

[[worker_pipeline.steps]]
id = "reviewer"
lifecycle_stage = "review"
base_context = "code-reviewer"
kind = "review"
"""


def _disabled_pipeline_config() -> str:
    return """
[worker_pipeline]
name = "disabled-pipeline"

[[worker_pipeline.steps]]
id = "planner"
lifecycle_stage = "planning"
base_context = "planner"
    """


def _review_pipeline_config() -> str:
    return """
[worker_pipeline]
enabled = true
name = "review-pipeline"
mode = "guided"

[[worker_pipeline.steps]]
id = "planner"
lifecycle_stage = "planning"
base_context = "planner"

[[worker_pipeline.steps]]
id = "coder"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"

[[worker_pipeline.steps]]
id = "spec-review"
lifecycle_stage = "review"
base_context = "spec-reviewer"
kind = "review"

[[worker_pipeline.steps]]
id = "code-review"
lifecycle_stage = "review"
base_context = "code-reviewer"
kind = "review"

[[worker_pipeline.steps]]
id = "validator"
lifecycle_stage = "validation"
base_context = "validator"
kind = "validate"
"""


def _setup_implemented_review_task(workspace: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(workspace), "init"]).exit_code == 0
    _append_pipeline_config(workspace / "taskledger.toml", _review_pipeline_config())
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "Review pipeline task",
                "--slug",
                "review-pipeline-task",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "task", "activate", "review-pipeline-task"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(workspace), "plan", "start"]).exit_code == 0
    plan_text = """---
acceptance_criteria:
  - text: Pipeline next advances through review steps.
todos:
  - text: Implement the approved change.
    worker_step: coder
    validation_hint: pytest tests/test_worker_pipeline_cli.py
---

# Plan

Drive review-step routing from closed worker handoffs once implementation is done.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "plan", "propose", "--text", plan_text],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
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
        runner.invoke(app, ["--cwd", str(workspace), "implement", "start"]).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "todo",
                "done",
                "todo-0001",
                "--evidence",
                "Implemented for test.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "implement",
                "finish",
                "--summary",
                "Implemented review pipeline task.",
            ],
        ).exit_code
        == 0
    )


def _setup_guided_implementation_task(workspace: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(workspace), "init"]).exit_code == 0
    _append_pipeline_config(workspace / "taskledger.toml", _enabled_pipeline_config())
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "Guided next action task",
                "--slug",
                "guided-next-action-task",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "task", "activate", "guided-next-action-task"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(workspace), "plan", "start"]).exit_code == 0
    plan_text = """---
acceptance_criteria:
  - text: Guided next-action exposes worker hints.
todos:
  - text: Add failing regression tests.
    worker_step: tester
    validation_hint: pytest tests/test_worker_pipeline_cli.py
  - text: Implement the approved change.
    worker_step: coder
    validation_hint: pytest tests/test_worker_pipeline_cli.py
---

# Plan

Use the guided worker pipeline to surface the next implementation handoff.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "plan", "propose", "--text", plan_text],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
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
        runner.invoke(app, ["--cwd", str(workspace), "implement", "start"]).exit_code
        == 0
    )


def test_pipeline_commands_print_no_config_message(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0

    for command in (["pipeline", "show"], ["pipeline", "list"], ["pipeline", "next"]):
        result = runner.invoke(app, ["--cwd", str(tmp_path), *command])
        assert result.exit_code == 0, result.stdout
        assert result.stdout.strip() == "No worker pipeline configured."


def test_pipeline_commands_print_disabled_message(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _append_pipeline_config(tmp_path / "taskledger.toml", _disabled_pipeline_config())

    for command in (["pipeline", "show"], ["pipeline", "list"], ["pipeline", "next"]):
        result = runner.invoke(app, ["--cwd", str(tmp_path), *command])
        assert result.exit_code == 0, result.stdout
        assert result.stdout.strip() == "Worker pipeline is disabled."


def test_pipeline_show_and_list_render_enabled_config(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _append_pipeline_config(tmp_path / "taskledger.toml", _enabled_pipeline_config())

    show_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "pipeline", "show"],
    )
    assert show_result.exit_code == 0, show_result.stdout
    show_payload = _json(show_result)
    assert show_payload["result"]["configured"] is True
    assert show_payload["result"]["enabled"] is True
    assert show_payload["result"]["pipeline"]["name"] == "tdd-four-context"

    list_result = runner.invoke(app, ["--cwd", str(tmp_path), "pipeline", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert "planner" in list_result.stdout
    assert "Test Writer" in list_result.stdout
    assert "reviewer" in list_result.stdout


def test_pipeline_next_returns_planner_before_plan_acceptance(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _append_pipeline_config(tmp_path / "taskledger.toml", _enabled_pipeline_config())
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Pipeline task",
                "--slug",
                "pipeline-task",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "pipeline-task"],
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "pipeline", "next"])

    assert result.exit_code == 0, result.stdout
    payload = _json(result)
    assert payload["result"]["step"]["id"] == "planner"
    assert payload["result"]["reason"] == "No accepted plan exists yet."


def test_pipeline_next_advances_after_closed_worker_review_handoff(
    tmp_path: Path,
) -> None:
    _setup_implemented_review_task(tmp_path)

    first = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "pipeline", "next"])
    assert first.exit_code == 0, first.stdout
    assert _json(first)["result"]["step"]["id"] == "spec-review"

    handoff = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "handoff",
            "create",
            "--worker",
            "spec-review",
            "--scope",
            "task",
            "--summary",
            "Review spec compliance.",
        ],
    )
    assert handoff.exit_code == 0, handoff.stdout
    handoff_id = str(_json(handoff)["result"]["handoff_id"])
    close = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "handoff",
            "close",
            handoff_id,
            "--reason",
            "Review complete.",
        ],
    )
    assert close.exit_code == 0, close.stdout

    second = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "pipeline", "next"])
    assert second.exit_code == 0, second.stdout
    assert _json(second)["result"]["step"]["id"] == "code-review"


def test_pipeline_next_ignores_cancelled_worker_review_handoff(tmp_path: Path) -> None:
    _setup_implemented_review_task(tmp_path)

    handoff = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "handoff",
            "create",
            "--worker",
            "spec-review",
            "--scope",
            "task",
            "--summary",
            "Review spec compliance.",
        ],
    )
    assert handoff.exit_code == 0, handoff.stdout
    handoff_id = str(_json(handoff)["result"]["handoff_id"])
    cancel = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "handoff",
            "cancel",
            handoff_id,
            "--reason",
            "Skipping this handoff.",
        ],
    )
    assert cancel.exit_code == 0, cancel.stdout

    result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "pipeline", "next"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["result"]["step"]["id"] == "spec-review"


def test_next_action_guided_worker_pipeline_payload_and_commands(
    tmp_path: Path,
) -> None:
    _setup_guided_implementation_task(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "next-action"],
    )

    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    assert payload["action"] == "todo-work"
    assert payload["next_item"]["id"] == "todo-0001"
    assert payload["worker_pipeline"] == {
        "configured": True,
        "enabled": True,
        "mode": "guided",
        "next_step": {
            "id": "tester",
            "label": "Test Writer",
            "lifecycle_stage": "implementation",
            "base_context": "implementer",
            "actor_role": "implementer",
            "kind": "check",
            "required_output": [],
            "must_not": [],
            "test_command_policy": "may_fail",
        },
        "context_command": "taskledger pipeline context tester",
        "handoff_command": (
            'taskledger handoff create --worker tester --summary "..."'
        ),
    }
    assert payload["commands"][0] == {
        "kind": "inspect",
        "label": "Show next todo",
        "command": "taskledger todo show todo-0001",
        "primary": True,
    }
    assert payload["commands"][1] == {
        "kind": "context",
        "label": "Show worker context",
        "command": "taskledger pipeline context tester",
        "primary": False,
    }
    assert payload["commands"][2] == {
        "kind": "handoff",
        "label": "Create worker handoff",
        "command": 'taskledger handoff create --worker tester --summary "..."',
        "primary": False,
    }


def test_next_action_guided_worker_pipeline_human_output(tmp_path: Path) -> None:
    _setup_guided_implementation_task(tmp_path)

    result = runner.invoke(app, ["--cwd", str(tmp_path), "next-action"])

    assert result.exit_code == 0, result.stdout
    assert "Worker step: tester" in result.stdout
    assert "Worker context: taskledger pipeline context tester" in result.stdout
    assert (
        'Worker handoff: taskledger handoff create --worker tester --summary "..."'
        in result.stdout
    )


def test_pipeline_next_ignores_normal_review_handoff(tmp_path: Path) -> None:
    _setup_implemented_review_task(tmp_path)

    handoff = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "handoff",
            "create",
            "--mode",
            "review",
            "--summary",
            "Generic review handoff.",
        ],
    )
    assert handoff.exit_code == 0, handoff.stdout
    handoff_id = str(_json(handoff)["result"]["handoff_id"])
    close = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "handoff",
            "close",
            handoff_id,
            "--reason",
            "Closed generic handoff.",
        ],
    )
    assert close.exit_code == 0, close.stdout

    result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "pipeline", "next"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["result"]["step"]["id"] == "spec-review"

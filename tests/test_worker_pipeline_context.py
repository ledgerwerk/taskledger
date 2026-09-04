from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _append_pipeline_config(path: Path) -> None:
    config = """
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
actor_role = "implementer"
kind = "check"
todo_tag = "test-first"
test_command_policy = "may_fail"
description = "Add regression tests that fail for the expected reason before \
implementation."
required_output = ["Failing test command recorded with --allow-failure."]
must_not = ["Do not implement production behavior to make the test pass."]

[[worker_pipeline.steps]]
id = "coder"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"
"""
    current = path.read_text(encoding="utf-8")
    path.write_text(f"{current.rstrip()}\n\n{config.strip()}\n", encoding="utf-8")


def _setup_task_with_accepted_plan(workspace: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(workspace), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "Worker pipeline context task",
                "--slug",
                "worker-context",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "task", "activate", "worker-context"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(workspace), "plan", "start"]).exit_code == 0
    plan_text = """---
acceptance_criteria:
  - id: ac-0001
    text: Worker context exists.
todos:
  - id: plan-todo-0001
    text: Add worker context support.
    validation_hint: pytest tests/test_worker_pipeline_context.py
---

# Plan

Add worker-aware context support without changing default context rendering.
"""
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "plan",
                "propose",
                "--text",
                plan_text,
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


# specmason: req=REQ-0073 ac=AC-0812
def test_context_for_implementer_unchanged_without_worker_pipeline(
    tmp_path: Path,
) -> None:
    _setup_task_with_accepted_plan(tmp_path)

    before = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "context", "--for", "implementer"],
    )
    assert before.exit_code == 0, before.stdout

    _append_pipeline_config(tmp_path / ".ledger" / "taskledger" / "config.toml")

    after = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "context", "--for", "implementer"],
    )
    assert after.exit_code == 0, after.stdout
    assert after.stdout == before.stdout


# specmason: req=REQ-0073 ac=AC-0815
def test_worker_context_renders_base_context_plus_worker_guidance(
    tmp_path: Path,
) -> None:
    _setup_task_with_accepted_plan(tmp_path)
    _append_pipeline_config(tmp_path / ".ledger" / "taskledger" / "config.toml")

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "context", "--worker", "tester"],
    )

    assert result.exit_code == 0, result.stdout
    assert "# Implementation Context:" in result.stdout
    assert "## Worker step" in result.stdout
    assert "- id: tester" in result.stdout
    assert "- lifecycle_stage: implementation" in result.stdout
    assert "- base_context: implementer" in result.stdout
    assert "- actor_role: implementer" in result.stdout
    assert "- kind: check" in result.stdout
    assert "- todo_tag: test-first" in result.stdout
    assert "- test_command_policy: may_fail" in result.stdout
    assert "Add regression tests that fail for the expected reason" in result.stdout
    assert (
        "record failing test commands as evidence when this worker step expects them"
        in result.stdout
    )
    assert "Must not:" in result.stdout
    assert (
        "Do not implement production behavior to make the test pass." in result.stdout
    )


# specmason: req=REQ-0073 ac=AC-0814
def test_pipeline_context_command_renders_worker_context(tmp_path: Path) -> None:
    _setup_task_with_accepted_plan(tmp_path)
    _append_pipeline_config(tmp_path / ".ledger" / "taskledger" / "config.toml")

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "pipeline", "context", "tester"],
    )

    assert result.exit_code == 0, result.stdout
    assert "## Worker step" in result.stdout
    assert "Test Writer" in result.stdout


# specmason: req=REQ-0073 ac=AC-0813
def test_context_worker_requires_enabled_pipeline(tmp_path: Path) -> None:
    _setup_task_with_accepted_plan(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "context", "--worker", "tester"],
    )

    assert result.exit_code != 0
    output = result.stdout
    stderr = getattr(result, "stderr", "")
    assert "No worker pipeline configured" in f"{output}{stderr}"


def test_validator_context_distinguishes_target_and_probe_failures(
    tmp_path: Path,
) -> None:
    _setup_task_with_accepted_plan(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "context", "--for", "validator"],
    )

    assert result.exit_code == 0, result.stdout
    assert "target behavior" in result.stdout
    assert "probe/setup" in result.stdout
    assert "correct the probe and rerun" in result.stdout.lower()
    assert "criterion failure" in result.stdout

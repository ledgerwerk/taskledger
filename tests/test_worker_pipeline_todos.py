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
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "check"

[[worker_pipeline.steps]]
id = "coder"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"

[[worker_pipeline.steps]]
id = "reviewer"
lifecycle_stage = "review"
base_context = "code-reviewer"
kind = "review"
"""
    current = path.read_text(encoding="utf-8")
    path.write_text(f"{current.rstrip()}\n\n{config.strip()}\n", encoding="utf-8")


def _setup_planning_task(workspace: Path, *, with_pipeline: bool) -> None:
    assert runner.invoke(app, ["--cwd", str(workspace), "init"]).exit_code == 0
    if with_pipeline:
        _append_pipeline_config(workspace / ".ledger" / "taskledger" / "config.toml")
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "Worker todo task",
                "--slug",
                "worker-todo",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "task", "activate", "worker-todo"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(workspace), "plan", "start"]).exit_code == 0


def _approve_plan(workspace: Path, plan_text: str) -> None:
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
                "--json",
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


def test_worker_todo_materialization_stores_worker_step_id_sparse(
    tmp_path: Path,
) -> None:
    _setup_planning_task(tmp_path, with_pipeline=True)
    _approve_plan(
        tmp_path,
        """---
acceptance_criteria:
  - text: Worker todo metadata survives approval.
todos:
  - text: Add failing regression tests.
    worker_step: tester
    validation_hint: pytest tests/test_worker_pipeline_todos.py
  - text: Update worker docs.
    mandatory: false
---

# Plan

Use worker-tagged todos when the pipeline is enabled.
""",
    )

    todos = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "todo", "list"])
    )["result"]["todos"]

    assert todos[0]["worker_step_id"] == "tester"
    assert "worker_step_id" not in todos[1]


# sw: f=specs/behavior/features/worker_pipeline_todos/worker-pipeline-todos.feature
# sw: s=@bdd-worker-pipeline-todos-pipeline-next-returns-first-open-worker-todo
def test_pipeline_next_returns_first_open_worker_todo(tmp_path: Path) -> None:
    _setup_planning_task(tmp_path, with_pipeline=True)
    _approve_plan(
        tmp_path,
        """---
acceptance_criteria:
  - text: Pipeline next returns the next worker step.
todos:
  - text: Add failing regression tests.
    worker_step: tester
    validation_hint: pytest tests/test_worker_pipeline_todos.py
  - text: Implement production behavior.
    worker_step: coder
    validation_hint: pytest tests/test_worker_pipeline_todos.py
---

# Plan

Drive pipeline-next from worker-tagged todos.
""",
    )

    result = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "pipeline", "next"])

    assert result.exit_code == 0, result.stdout
    payload = _json(result)
    assert payload["result"]["step"]["id"] == "tester"


# sw: f=specs/behavior/features/worker_pipeline_todos/worker-pipeline-todos.feature
# sw: s=@bdd-worker-pipeline-todos-plan-todo-worker-step-requires-enabled-pipeline
def test_plan_todo_worker_step_requires_enabled_pipeline(tmp_path: Path) -> None:
    _setup_planning_task(tmp_path, with_pipeline=False)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "propose",
            "--text",
            """---
acceptance_criteria:
  - text: Fails without pipeline config.
todos:
  - text: Add failing tests.
    worker_step: tester
---

# Plan

This should fail because no worker pipeline is configured.
""",
        ],
    )

    assert result.exit_code != 0
    output = f"{result.stdout}{getattr(result, 'stderr', '')}"
    assert "requires an enabled worker pipeline" in output


def test_task_records_do_not_gain_worker_null_fields_without_worker_pipeline(
    tmp_path: Path,
) -> None:
    _setup_planning_task(tmp_path, with_pipeline=False)
    _approve_plan(
        tmp_path,
        """---
acceptance_criteria:
  - text: No worker fields are serialized by default.
todos:
  - text: Add feature tests.
    validation_hint: pytest tests/test_worker_pipeline_todos.py
---

# Plan

Keep no-config serialization unchanged.
""",
    )

    todos = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "todo", "list"])
    )["result"]["todos"]
    assert "worker_step_id" not in todos[0]

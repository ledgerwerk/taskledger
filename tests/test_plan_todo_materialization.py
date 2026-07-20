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


# specmason: req=REQ-0040 ac=AC-0454
def test_plan_approval_materializes_structured_todos_once(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Materialize plan todos",
                "--slug",
                "todo-plan",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "todo-plan"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0

    plan_text = """---
acceptance_criteria:
  - text: Tests cover the feature.
todos:
  - text: Add feature tests.
    validation_hint: pytest tests/test_feature.py
  - text: Update docs.
    mandatory: false
---

# Plan

Ship the feature.
"""
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--text",
                plan_text,
            ],
        ).exit_code
        == 0
    )

    approved = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
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
        )
    )
    assert approved["result"]["materialized_todos"] == 2

    todos = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "todo", "list"])
    )["result"]["todos"]
    assert [todo["text"] for todo in todos] == ["Add feature tests.", "Update docs."]
    assert todos[0]["mandatory"] is True
    assert todos[0]["source"] == "plan"
    assert todos[0]["source_plan_id"] == "plan-v1"
    assert todos[1]["mandatory"] is False

    rerun = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "materialize-todos",
                "--version",
                "1",
            ],
        )
    )
    assert rerun["result"]["materialized_todos"] == 0

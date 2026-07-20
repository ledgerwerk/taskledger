from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init_task_with_questions(tmp_path: Path) -> None:
    """Create a task with planning started and two questions."""
    init_workspace(tmp_path)
    from taskledger.services.tasks import (
        activate_task as svc_activate,
    )
    from taskledger.services.tasks import (
        create_task as svc_create,
    )
    from taskledger.services.tasks import (
        start_planning as svc_start_planning,
    )

    svc_create(tmp_path, title="Test task", slug="test-task", description="Test task.")
    svc_activate(tmp_path, "test-task", reason="test setup")
    svc_start_planning(tmp_path, "test-task")
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Q1?",
                "--required-for-plan",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "question", "add", "--text", "Q2?"],
        ).exit_code
        == 0
    )
    # answer q-0001, dismiss q-0002
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "answer",
                "q-0001",
                "--text",
                "A1",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "question", "dismiss", "q-0002"],
        ).exit_code
        == 0
    )


# --- --status filter tests ---


# specmason: req=REQ-0043 ac=AC-0488
def test_list_with_status_answered(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "question",
                "list",
                "--status",
                "answered",
            ],
        )
    )
    items = result["result"]
    assert len(items) == 1
    assert items[0]["status"] == "answered"
    assert items[0]["id"] == "q-0001"


# specmason: req=REQ-0043 ac=AC-0492
def test_list_with_status_dismissed(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "question",
                "list",
                "--status",
                "dismissed",
            ],
        )
    )
    items = result["result"]
    assert len(items) == 1
    assert items[0]["status"] == "dismissed"
    assert items[0]["id"] == "q-0002"


def test_list_with_comma_separated_status(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "question",
                "list",
                "--status",
                "answered,dismissed",
            ],
        )
    )
    items = result["result"]
    assert len(items) == 2
    statuses = {item["status"] for item in items}
    assert statuses == {"answered", "dismissed"}


# specmason: req=REQ-0043 ac=AC-0492
def test_list_without_status_returns_all(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "question", "list"],
        )
    )
    items = result["result"]
    assert len(items) == 2


# specmason: req=REQ-0043 ac=AC-0492
def test_list_with_status_open_returns_empty(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "question", "list", "--status", "open"],
        )
    )
    items = result["result"]
    assert items == []


# --- answers command tests ---


# specmason: req=REQ-0043 ac=AC-0489
def test_answers_markdown_format(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "question", "answers"],
    )
    assert result.exit_code == 0
    assert "q-0001" in result.output
    assert "Q: Q1?" in result.output
    assert "A: A1" in result.output


# specmason: req=REQ-0043 ac=AC-0489
def test_answers_json_format(tmp_path: Path) -> None:
    _init_task_with_questions(tmp_path)
    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "question",
                "answers",
                "--format",
                "json",
            ],
        )
    )
    payload = result["result"]
    assert payload["kind"] == "question_answers"
    questions = payload["questions"]
    assert len(questions) == 1
    assert questions[0]["id"] == "q-0001"
    assert questions[0]["answer"] == "A1"


# specmason: req=REQ-0043 ac=AC-0488
def test_answers_empty_when_none_answered(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "create", "T", "--slug", "t"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", "t"]).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "question", "add", "--text", "Q?"],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "question", "answers"],
    )
    assert result.exit_code == 0
    assert "(empty)" in result.output


# --- empty answer validation test ---


# specmason: req=REQ-0043 ac=AC-0486
# specmason: req=REQ-0043 ac=AC-0490
# specmason: req=REQ-0043 ac=AC-0491
def test_answer_empty_text_rejected(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "create", "T", "--slug", "t"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", "t"]).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "question", "add", "--text", "Q?"],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "question",
            "answer",
            "q-0001",
            "--text",
            "",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert "empty" in payload["error"]["message"].lower()


# specmason: req=REQ-0043 ac=AC-0487
def test_answer_whitespace_only_rejected(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "create", "T", "--slug", "t"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", "t"]).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "question", "add", "--text", "Q?"],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "question",
            "answer",
            "q-0001",
            "--text",
            "   ",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert "empty" in payload["error"]["message"].lower()

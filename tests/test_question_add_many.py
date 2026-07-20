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


def _init_planning_task(tmp_path: Path, slug: str = "question-batch") -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Question batch task",
                "--slug",
                slug,
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", slug],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0


# specmason: req=REQ-0042 ac=AC-0482
def test_question_add_many_adds_required_questions_to_active_task(
    tmp_path: Path,
) -> None:
    _init_planning_task(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "question",
            "add-many",
            "--required-for-plan",
            "--text",
            "Which database?\nWhich cache?",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _json(result)["result"]
    assert payload["kind"] == "question_add_many"
    assert payload["added_question_ids"] == ["q-0001", "q-0002"]
    added = payload["added"]
    assert isinstance(added, list)
    assert [item["required_for_plan"] for item in added] == [True, True]


# specmason: req=REQ-0042 ac=AC-0485
def test_question_add_many_supports_yaml_file_and_explicit_task(tmp_path: Path) -> None:
    _init_planning_task(tmp_path, slug="yaml-batch")
    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(
        "questions:\n"
        "  - text: Which database?\n"
        "    required_for_plan: true\n"
        "  - text: Which cache?\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "question",
            "add-many",
            "--task",
            "yaml-batch",
            "--yaml-file",
            str(questions_file),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _json(result)["result"]
    added = payload["added"]
    assert isinstance(added, list)
    assert [item["required_for_plan"] for item in added] == [True, False]


# specmason: req=REQ-0042 ac=AC-0483
def test_question_add_many_rejects_blank_lines_without_partial_write(
    tmp_path: Path,
) -> None:
    _init_planning_task(tmp_path, slug="blank-lines")
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "question",
            "add-many",
            "--text",
            "Which database?\n\nWhich cache?",
        ],
    )
    assert result.exit_code != 0
    assert "empty or whitespace-only" in _json(result)["error"]["message"]

    listed = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "question", "list"],
    )
    assert listed.exit_code == 0, listed.output
    assert _json(listed)["result"] == []


# specmason: req=REQ-0042 ac=AC-0484
def test_question_add_many_rejects_duplicates_without_partial_write(
    tmp_path: Path,
) -> None:
    _init_planning_task(tmp_path, slug="duplicate-lines")
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "question",
            "add-many",
            "--text",
            "Which database?\nWhich database?",
        ],
    )
    assert result.exit_code != 0
    assert "Duplicate question text in batch" in _json(result)["error"]["message"]

    listed = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "question", "list"],
    )
    assert listed.exit_code == 0, listed.output
    assert _json(listed)["result"] == []

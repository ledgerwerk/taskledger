from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.plan_review import (
    build_plan_review_payload,
    render_plan_review,
)
from taskledger.services.tasks import (
    activate_task,
    add_question,
    answer_question,
    create_task,
    propose_plan,
    start_planning,
)
from tests.support.builders import init_workspace


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _json(result) -> dict[str, object]:
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


PLAN_TEXT = """---
goal: Add plan review output.
files:
  - "taskledger/services/plan_review.py"
test_commands:
  - "pytest tests/test_plan_review.py -q"
expected_outputs:
  - "All plan review tests pass."
acceptance_criteria:
  - id: ac-0001
    text: Review command renders markdown.
todos:
  - id: todo-0001
    text: Add a plan review service.
    validation_hint: pytest tests/test_plan_review.py -q
---

# Proposed Plan

Render a concise approval-focused review artifact.
"""


def _setup_review_task(tmp_path: Path) -> str:
    ws = init_workspace(tmp_path)
    task = create_task(
        ws,
        title="Plan review task",
        slug="plan-review-task",
        description="Exercise plan review rendering.",
    )
    activate_task(ws, task.id, reason="test setup")
    start_planning(ws, task.id)
    propose_plan(ws, task.id, body=PLAN_TEXT)
    return task.id


def test_plan_review_markdown_includes_proposed_plan_body(tmp_path: Path) -> None:
    task_id = _setup_review_task(tmp_path)
    payload = render_plan_review(tmp_path, task_id, version=1)
    content = payload["content"]
    assert isinstance(content, str)
    assert content.startswith("# Proposed Plan:")
    assert "## Proposed Plan" in content
    assert "Render a concise approval-focused review artifact." in content


def test_plan_review_includes_machine_commitments(tmp_path: Path) -> None:
    task_id = _setup_review_task(tmp_path)
    payload = render_plan_review(tmp_path, task_id, version=1)
    content = str(payload["content"])
    assert "## Machine-Readable Commitments" in content
    assert "### Acceptance Criteria" in content
    assert "ac-0001: Review command renders markdown." in content
    assert "### Planned Todos" in content
    assert "todo-0001: Add a plan review service." in content
    assert "### Files" in content
    assert "taskledger/services/plan_review.py" in content
    assert "### Test Commands" in content
    assert "pytest tests/test_plan_review.py -q" in content
    assert "### Expected Outputs" in content
    assert "All plan review tests pass." in content


def test_plan_review_reports_ready_when_lint_passes_and_no_blockers(
    tmp_path: Path,
) -> None:
    task_id = _setup_review_task(tmp_path)
    payload = build_plan_review_payload(tmp_path, task_id, version=1)
    assert payload["approval_ready"] is True
    assert payload["blockers"] == []
    lint = payload["lint"]
    assert isinstance(lint, dict)
    assert lint.get("passed") is True


def test_plan_review_reports_blocked_for_open_questions(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(
        ws,
        title="Open question",
        slug="open-question",
        description="Open required planning question scenario.",
    )
    activate_task(ws, task.id, reason="test setup")
    start_planning(ws, task.id)
    add_question(ws, task.id, text="Should this be optional?", required_for_plan=True)
    propose_plan(ws, task.id, body=PLAN_TEXT)

    payload = build_plan_review_payload(ws, task.id, version=1)
    kinds = {item["kind"] for item in payload["blockers"] if isinstance(item, dict)}
    assert "open_questions" in kinds
    assert payload["approval_ready"] is False


def test_plan_review_reports_blocked_for_stale_answers(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(
        ws,
        title="Stale answers",
        slug="stale-answers",
        description="Answered question stale against selected plan.",
    )
    activate_task(ws, task.id, reason="test setup")
    start_planning(ws, task.id)
    question = add_question(ws, task.id, text="Which approach?", required_for_plan=True)
    propose_plan(ws, task.id, body=PLAN_TEXT)
    answer_question(
        ws,
        task.id,
        question.id,
        text="Use the dedicated review command.",
        answer_source="explicit_user_chat",
    )

    payload = build_plan_review_payload(ws, task.id, version=1)
    kinds = {item["kind"] for item in payload["blockers"] if isinstance(item, dict)}
    assert "stale_answers" in kinds
    assert payload["approval_ready"] is False


def test_plan_review_reports_blocked_for_missing_todos(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(
        ws,
        title="Missing todos",
        slug="missing-todos",
        description="Plan without todos should be blocked.",
    )
    activate_task(ws, task.id, reason="test setup")
    start_planning(ws, task.id)
    propose_plan(
        ws,
        task.id,
        body="""---
acceptance_criteria:
  - id: ac-0001
    text: Keep readiness checks strict.
---

# Proposed Plan

No todos were defined here.
""",
    )

    payload = build_plan_review_payload(ws, task.id, version=1)
    kinds = {item["kind"] for item in payload["blockers"] if isinstance(item, dict)}
    assert "missing_todos" in kinds
    assert payload["approval_ready"] is False


def test_plan_review_json_payload_is_structured(tmp_path: Path) -> None:
    task_id = _setup_review_task(tmp_path)
    payload = render_plan_review(tmp_path, task_id, version=1, format_name="json")
    assert payload["approval_ready"] is True
    assert isinstance(payload["blockers"], list)
    assert isinstance(payload["warnings"], list)
    assert isinstance(payload["content"], str)
    rendered = json.loads(str(payload["content"]))
    assert rendered["kind"] == "plan_review"
    assert rendered["plan_id"] == "plan-v1"


def test_plan_review_stdout_markdown(tmp_path: Path) -> None:
    _setup_review_task(tmp_path)
    runner = _runner()
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "plan", "review", "--version", "1"],
    )
    assert result.exit_code == 0, result.stdout
    assert "# Proposed Plan:" in result.stdout
    assert "## Review Summary" in result.stdout


def test_plan_review_output_writes_file(tmp_path: Path) -> None:
    _setup_review_task(tmp_path)
    output_path = tmp_path / "plan-review.md"
    runner = _runner()
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "review",
            "--version",
            "1",
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    written = output_path.read_text(encoding="utf-8")
    assert "# Proposed Plan:" in written
    assert "## Review Summary" in written


def test_plan_review_json_output(tmp_path: Path) -> None:
    _setup_review_task(tmp_path)
    runner = _runner()
    payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "review", "--version", "1"],
        )
    )
    result = payload["result"]
    assert result["kind"] == "plan_review"
    assert result["approval_ready"] is True
    assert isinstance(result["blockers"], list)
    assert isinstance(result["warnings"], list)
    assert isinstance(result["content"], str)


def test_plan_review_defaults_to_latest_plan(tmp_path: Path) -> None:
    task_id = _setup_review_task(tmp_path)
    start_planning(tmp_path, task_id)
    propose_plan(
        tmp_path,
        task_id,
        body=PLAN_TEXT.replace("Render a concise", "Render a richer"),
    )
    runner = _runner()
    payload = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "plan", "review"])
    )
    assert payload["result"]["plan_id"] == "plan-v2"

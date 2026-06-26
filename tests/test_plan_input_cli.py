from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.tasks import activate_task, create_task, start_planning
from taskledger.storage.task_store import resolve_task
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


RECOVERABLE_PLAN_INPUT_FIXTURE = """---
goal: "Implement the review."
files:
  - "@pkg/module.py"
test_commands:
  - "pytest -q tests/test_module.py"
expected_outputs:
  - "pytest exits 0"
acceptance_criteria:
  - id: ac-0001
    description: "Observable behavior is fixed."
    mandatory: true
todos:
  - id: todo-0001
    text: "Edit @pkg/module.py to implement the behavior."
    mandatory: true
    files:
      - "@pkg/module.py"
---

## Goal

Implement the review.
"""

INVALID_PLAN_INPUT_MISSING_CRITERION_TEXT = """---
goal: "Test goal."
acceptance_criteria:
  - id: ac-0001
    mandatory: true
todos:
  - id: todo-0001
    text: "Do something."
---

# Plan

Test plan.
"""


# ---------------------------------------------------------------------------
# Test 1: Upsert accepts recoverable plan-input regression fixture
# ---------------------------------------------------------------------------


def test_plan_upsert_accepts_recoverable_plan_input_fixture_with_warnings(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Plan input test",
        slug="plan-input",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    start_planning(tmp_path, task.id)

    plan_file = tmp_path / "plan.md"
    plan_file.write_text(RECOVERABLE_PLAN_INPUT_FIXTURE, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--file",
            str(plan_file),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    assert payload["command"] == "plan upsert", payload
    warning_codes = {issue["code"] for issue in payload.get("plan_input_warnings", [])}
    assert "criterion_description_alias" in warning_codes
    assert "unsupported_todo_files" in warning_codes

    stored = resolve_task(tmp_path, task.id)
    assert stored.status_stage == "plan_review"
    from taskledger.storage.task_store import resolve_plan

    plan = resolve_plan(tmp_path, task.id)
    criterion_texts = [c.text for c in plan.criteria]
    assert "Observable behavior is fixed." in criterion_texts
    assert plan.todos[0].text == "Edit @pkg/module.py to implement the behavior."


# ---------------------------------------------------------------------------
# Test 2: plan check passes with warnings on recoverable fixture
# ---------------------------------------------------------------------------


def test_plan_check_passes_with_warnings_on_recoverable_fixture(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(RECOVERABLE_PLAN_INPUT_FIXTURE, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "check",
            "--file",
            str(plan_file),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    assert payload["passed"] is True
    issues = {issue["code"] for issue in payload.get("issues", [])}
    assert "criterion_description_alias" in issues
    assert "unsupported_todo_files" in issues


# ---------------------------------------------------------------------------
# Test 3: plan check --strict fails on warnings
# ---------------------------------------------------------------------------


def test_plan_check_strict_fails_on_recoverable_fixture(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(RECOVERABLE_PLAN_INPUT_FIXTURE, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "check",
            "--strict",
            "--file",
            str(plan_file),
        ],
    )

    assert result.exit_code != 0, result.stdout
    payload = _json(result)["result"]
    assert payload["passed"] is False


# ---------------------------------------------------------------------------
# Test 4: Invalid input returns non-zero exit code
# ---------------------------------------------------------------------------


def test_plan_upsert_invalid_input_returns_nonzero(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Invalid input test",
        slug="invalid-input",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    start_planning(tmp_path, task.id)

    plan_file = tmp_path / "plan.md"
    plan_file.write_text(INVALID_PLAN_INPUT_MISSING_CRITERION_TEXT, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--file",
            str(plan_file),
        ],
    )

    assert result.exit_code != 0, result.stdout


# ---------------------------------------------------------------------------
# Test 5: plan check invalid input returns non-zero
# ---------------------------------------------------------------------------


def test_plan_check_invalid_input_returns_nonzero(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(INVALID_PLAN_INPUT_MISSING_CRITERION_TEXT, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "check",
            "--file",
            str(plan_file),
        ],
    )

    assert result.exit_code != 0, result.stdout
    payload = _json(result)["result"]
    assert payload["passed"] is False


# ---------------------------------------------------------------------------
# Test 6: Guidance exists without profile
# ---------------------------------------------------------------------------


def test_plan_guidance_without_profile_prints_builtin_contract(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Guidance test",
        slug="guidance-test",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    start_planning(tmp_path, task.id)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "guidance",
        ],
    )

    assert result.exit_code == 0
    assert "Built-in Taskledger plan input guidance" in result.stdout
    assert "Acceptance criteria use `text`" in result.stdout
    assert "No project planning guidance configured" not in result.stdout


# ---------------------------------------------------------------------------
# Test 7: Next-action includes ordered guidance/template/check/upsert commands
# ---------------------------------------------------------------------------


def test_next_action_planning_without_profile_includes_plan_input_command_sequence(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Next-action test",
        slug="next-action-test",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    start_planning(tmp_path, task.id)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "next-action",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    commands = payload["commands"]
    kinds = [cmd["kind"] for cmd in commands]
    assert kinds[:3] == ["guidance", "template", "check"], kinds
    assert payload["guidance_command"] == "taskledger plan guidance"
    assert str(payload["template_command"]).startswith("taskledger plan template")
    assert payload["check_command"] == "taskledger plan check --file plan.md"


# ---------------------------------------------------------------------------
# Test 8: Template contains checklist and single body comment
# ---------------------------------------------------------------------------


def test_plan_template_contains_checklist_and_single_body_comment(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Template test",
        slug="template-test",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    start_planning(tmp_path, task.id)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "template",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    template = str(payload["template"])
    assert "## Plan input checklist before upsert" in template
    assert "- [ ] I ran `taskledger plan check --file plan.md`." in template
    assert template.count("Required: keep this body") == 1


# ---------------------------------------------------------------------------
# Test 9: plan start prints next-step hints even without profile
# ---------------------------------------------------------------------------


def test_plan_start_prints_next_step_hints(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Start test",
        slug="start-test",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "start",
        ],
    )

    assert result.exit_code == 0
    assert "taskledger plan guidance" in result.stdout
    assert "taskledger plan template" in result.stdout

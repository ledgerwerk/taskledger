from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.states import EXIT_CODE_VALIDATION_FAILED
from tests.support.builders import (
    add_and_answer_question,
    create_planning_task,
    init_workspace,
)


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project_cli(tmp_path: Path) -> None:
    """Initialize project via CLI for tests that need .ledger layout."""
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0, result.output


def _init_project(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _create_and_start_planning(
    tmp_path: Path,
    slug: str = "lint-task",
    plan_text: str | None = None,
) -> str:
    """Use service builders for init, create, activate, start planning."""
    _init_project(tmp_path)
    return create_planning_task(
        tmp_path,
        slug=slug,
        description="lint test",
        plan_text=plan_text,
    )


def _enable_planning_guidance(tmp_path: Path) -> None:
    config_path = tmp_path / ".ledger" / "taskledger" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "[prompt_profiles.planning]\n"
        + 'profile = "strict"\n'
        + 'question_policy = "always_before_plan"\n'
        + "max_required_questions = 3\n"
        + "min_acceptance_criteria = 2\n"
        + 'todo_granularity = "atomic"\n'
        + "require_files = true\n"
        + "require_test_commands = true\n"
        + "require_expected_outputs = true\n"
        + "require_validation_hints = true\n"
        + 'plan_body_detail = "detailed"\n'
        + 'required_question_topics = ["scope", "tests"]\n'
        + 'extra_guidance = "Always mention docs updates."\n',
        encoding="utf-8",
    )


def _propose_plan(
    tmp_path: Path,
    plan_text: str,
    slug: str = "lint-task",
) -> None:
    """Propose a plan via CLI (this is a target command, not setup)."""
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "propose",
            "--task",
            slug,
            "--text",
            plan_text,
        ],
    )
    assert result.exit_code == 0, result.output


def _add_and_answer_required_question(
    tmp_path: Path,
    slug: str,
    answer: str = "PostgreSQL.",
) -> None:
    """Add and answer a question via service builders."""
    from taskledger.storage.task_store import resolve_active_task

    task = resolve_active_task(tmp_path)
    add_and_answer_question(
        tmp_path,
        task.id,
        answer_text=answer,
    )


# Full plan with all required fields
_FULL_PLAN = """\
---
goal: Test goal for plan linting.
files:
  - taskledger/services/plan_lint.py
test_commands:
  - pytest tests/test_plan_lint.py
expected_outputs:
  - pytest exits 0
acceptance_criteria:
  - id: ac-0001
    text: Lint command reports issues correctly.
todos:
  - text: Create `taskledger/services/plan_lint.py` with lint rules.
    validation_hint: pytest tests/test_plan_lint.py
---

## Goal

Test goal for plan linting.
"""

# Plan missing goal
_NO_GOAL_PLAN = """\
---
acceptance_criteria:
  - id: ac-0001
    text: Some criterion.
todos:
  - text: Add lint_service.py with lint_plan function.
---

## Steps

Do the work.
"""

# Plan missing criteria
_NO_CRITERIA_PLAN = """\
---
goal: Fix something.
todos:
  - text: Add lint_service.py with lint_plan function.
---

## Steps

Do the work.
"""

# Plan missing todos
_NO_TODOS_PLAN = """\
---
goal: Fix something.
acceptance_criteria:
  - id: ac-0001
    text: Some criterion.
---

## Steps

Do the work.
"""

# Plan with todo waiver
_WAIVED_TODOS_PLAN = """\
---
goal: Fix something.
todos_waived_reason: "No checklist needed for docs-only correction."
acceptance_criteria:
  - id: ac-0001
    text: Some criterion.
---

## Steps

Do the work.
"""

# Plan with vague todo
_VAGUE_TODO_PLAN = """\
---
goal: Fix something.
acceptance_criteria:
  - id: ac-0001
    text: Some criterion.
todos:
  - fix tests
---

## Steps

Do the work.
"""

# Plan with placeholders
_PLACEHOLDER_PLAN = """\
---
goal: Fix something TBD.
acceptance_criteria:
  - id: ac-0001
    text: Some criterion.
todos:
  - text: Add lint_service.py with appropriate tests.
    validation_hint: pytest tests/test_plan_lint.py
---

## Steps

Do the work later.
"""

_NO_TODO_HINTS_PLAN = """\
---
goal: Wire compact execution hints.
files:
  - taskledger/services/plan_lint.py
expected_outputs:
  - plan lint emits a warning
acceptance_criteria:
  - id: ac-0001
    text: A warning is emitted.
todos:
  - text: Update `taskledger/services/plan_lint.py` to emit a warning.
---

## Goal

Wire compact execution hints.
"""

_FRONT_MATTER_ONLY_PLAN = """\
---
goal: Fix something.
files:
  - taskledger/services/plan_lint.py
test_commands:
  - pytest tests/test_plan_lint.py
expected_outputs:
  - pytest exits 0
acceptance_criteria:
  - id: ac-0001
    text: Some criterion.
todos:
  - text: Update `taskledger/services/plan_lint.py` to reject empty bodies.
    validation_hint: pytest tests/test_plan_lint.py
---
"""

_SHORT_PATH_TODO_PLAN = """\
---
goal: Create CI workflow.
acceptance_criteria:
  - id: ac-0001
    text: CI workflow file exists.
todos:
  - id: plan-todo-0001
    text: Create .github/workflows/ci.yml
    validation_hint: test -f .github/workflows/ci.yml
---

## Goal

Create the workflow file.
"""


class TestPlanLintPasses:
    # specmason: req=REQ-0037 ac=AC-0422
    def test_plan_lint_passes_for_executable_plan(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "lint-pass")
        _propose_plan(tmp_path, _FULL_PLAN, slug="lint-pass")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "lint", "--task", "lint-pass"],
        )
        assert result.exit_code == 0, result.output
        payload = _json(result)
        assert payload["ok"] is True
        res = payload["result"]
        assert isinstance(res, dict)
        assert res["kind"] == "plan_lint"
        assert res["passed"] is True
        assert res["plan_version"] == 1
        summary = res["summary"]
        assert isinstance(summary, dict)
        assert summary["errors"] == 0

    # specmason: req=REQ-0037 ac=AC-0435
    def test_plan_template_prints_stdout_when_no_file(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "template-stdout")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "template", "--task", "template-stdout"],
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.startswith("---\n")
        assert "acceptance_criteria:" in result.stdout

    # specmason: req=REQ-0037 ac=AC-0415
    def test_plan_guidance_human_message_when_no_profile(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "guidance-empty")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "guidance", "--task", "guidance-empty"],
        )

        assert result.exit_code == 0, result.output
        assert "Built-in Taskledger plan input guidance" in result.stdout
        assert "Acceptance criteria use `text`" in result.stdout
        assert "No project planning guidance configured" not in result.stdout

    # specmason: req=REQ-0037 ac=AC-0416
    def test_plan_guidance_json_contract_when_no_profile(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "guidance-json-empty")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "guidance",
                "--task",
                "guidance-json-empty",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = _json(result)
        assert payload["ok"] is True
        result_payload = payload["result"]
        assert isinstance(result_payload, dict)
        assert result_payload["kind"] == "planning_guidance"
        assert result_payload["has_project_guidance"] is False
        assert result_payload["profile"] is None
        assert isinstance(result_payload["guidance"], str)
        assert result_payload["guidance"].startswith(
            "## Built-in Taskledger plan input guidance"
        )

    # specmason: req=REQ-0037 ac=AC-0417
    def test_plan_guidance_rejects_invalid_format(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "guidance-invalid-format")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "guidance",
                "--task",
                "guidance-invalid-format",
                "--format",
                "yaml",
            ],
        )

        assert result.exit_code != 0
        combined = f"{result.stdout}\n{result.stderr}"
        assert "Invalid --format value" in combined

    # specmason: req=REQ-0037 ac=AC-0433
    def test_plan_template_from_answers_writes_file(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "template-file")
        _add_and_answer_required_question(tmp_path, "template-file")
        plan_path = tmp_path / "plan.md"

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "template",
                "--task",
                "template-file",
                "--from-answers",
                "--file",
                str(plan_path),
            ],
        )

        assert result.exit_code == 0, result.output
        contents = plan_path.read_text(encoding="utf-8")
        assert "## Notes from answered questions" in contents
        assert "- q-0001: PostgreSQL." in contents

    # specmason: req=REQ-0037 ac=AC-0434
    def test_plan_template_include_guidance_writes_guidance_in_file(
        self, tmp_path: Path
    ) -> None:
        _init_project_cli(tmp_path)
        _enable_planning_guidance(tmp_path)
        # Use service layer directly since workspace is already initialized
        from taskledger.services.tasks import activate_task, create_task, start_planning

        task = create_task(
            tmp_path,
            title="Template guidance",
            slug="template-guidance",
            description="lint test",
        )
        activate_task(tmp_path, task.id, reason="test setup")
        start_planning(tmp_path, task.id)
        plan_path = tmp_path / "plan.md"

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "template",
                "--task",
                "template-guidance",
                "--include-guidance",
                "--file",
                str(plan_path),
            ],
        )

        assert result.exit_code == 0, result.output
        contents = plan_path.read_text(encoding="utf-8")
        lines = contents.splitlines()
        markers = [idx for idx, line in enumerate(lines) if line.strip() == "---"]
        assert len(markers) >= 2
        assert lines[0] == "---"
        guidance_line = lines.index("## Project planning guidance")
        assert guidance_line > markers[1]
        assert (
            "<!-- Advisory project planning guidance from taskledger plan guidance. -->"
            in contents
        )

    # specmason: req=REQ-0037 ac=AC-0410
    def test_filled_plan_template_passes_lint(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "template-lint")
        _add_and_answer_required_question(tmp_path, "template-lint")
        plan_path = tmp_path / "plan.md"

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "template",
                "--task",
                "template-lint",
                "--from-answers",
                "--file",
                str(plan_path),
            ],
        )
        assert result.exit_code == 0, result.output

        contents = plan_path.read_text(encoding="utf-8")
        contents = contents.replace(
            "<one sentence describing the desired outcome>",
            "Implement PostgreSQL-only behavior.",
        )
        contents = contents.replace("@path/to/file.py", "taskledger/services/tasks.py")
        contents = contents.replace(
            "pytest -q path/to/test_file.py",
            "pytest -q tests/test_plan_lint.py",
        )
        contents = contents.replace(
            "<observable acceptance criterion>",
            (
                "The template-based plan can be linted after concrete values are "
                "filled in."
            ),
        )
        contents = contents.replace(
            "<specific behavior>",
            "the PostgreSQL-only planning behavior",
        )
        contents = contents.replace(
            "<repeat or expand the goal in human prose>",
            (
                "Implement PostgreSQL-only behavior and keep the answered planning "
                "context visible."
            ),
        )
        plan_path.write_text(contents, encoding="utf-8")

        upserted = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "upsert",
                "--task",
                "template-lint",
                "--from-answers",
                "--file",
                str(plan_path),
            ],
        )
        assert upserted.exit_code == 0, upserted.output

        linted = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "template-lint",
            ],
        )
        assert linted.exit_code == 0, linted.output
        assert _json(linted)["result"]["passed"] is True


class TestPlanLintErrors:
    # specmason: req=REQ-0037 ac=AC-0426
    def test_plan_lint_reports_missing_goal(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "no-goal")
        _propose_plan(tmp_path, _NO_GOAL_PLAN, slug="no-goal")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "no-goal",
                "--version",
                "1",
            ],
        )
        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        assert res["passed"] is False
        codes = [i["code"] for i in res["issues"]]
        assert "missing_goal" in codes
        goal_issues = [i for i in res["issues"] if i["code"] == "missing_goal"]
        assert goal_issues[0]["severity"] == "error"

    # specmason: req=REQ-0037 ac=AC-0425
    def test_plan_lint_reports_missing_criteria(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "no-criteria")
        _propose_plan(tmp_path, _NO_CRITERIA_PLAN, slug="no-criteria")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "no-criteria",
            ],
        )
        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        assert res["passed"] is False
        codes = [i["code"] for i in res["issues"]]
        assert "missing_acceptance_criteria" in codes

    # specmason: req=REQ-0037 ac=AC-0428
    def test_plan_lint_reports_missing_todos(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "no-todos")
        _propose_plan(tmp_path, _NO_TODOS_PLAN, slug="no-todos")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "no-todos",
            ],
        )
        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        assert res["passed"] is False
        codes = [i["code"] for i in res["issues"]]
        assert "missing_todos" in codes

    # specmason: req=REQ-0037 ac=AC-0419
    def test_plan_lint_allows_todo_waiver_reason(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "waived")
        _propose_plan(tmp_path, _WAIVED_TODOS_PLAN, slug="waived")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "lint", "--task", "waived"],
        )
        assert result.exit_code == 0, result.output
        payload = _json(result)
        res = payload["result"]
        codes = [i["code"] for i in res["issues"]]
        assert "missing_todos" not in codes

    # specmason: req=REQ-0037 ac=AC-0424
    def test_plan_lint_rejects_vague_todo(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "vague")
        _propose_plan(tmp_path, _VAGUE_TODO_PLAN, slug="vague")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "lint", "--task", "vague"],
        )
        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        codes = [i["code"] for i in res["issues"]]
        assert "todo_not_concrete" in codes


class TestPlanLintWarnings:
    # specmason: req=REQ-0037 ac=AC-0431
    def test_plan_lint_warns_on_placeholders(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "placeholder")
        _propose_plan(tmp_path, _PLACEHOLDER_PLAN, slug="placeholder")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "placeholder",
            ],
        )
        # Warnings only, no strict: should exit 0
        assert result.exit_code == 0, result.output
        payload = _json(result)
        res = payload["result"]
        placeholder_issues = [i for i in res["issues"] if i["code"] == "placeholder"]
        assert len(placeholder_issues) >= 1
        assert placeholder_issues[0]["severity"] == "warning"

    # specmason: req=REQ-0037 ac=AC-0430
    def test_plan_lint_strict_fails_on_placeholders(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "strict-ph")
        _propose_plan(tmp_path, _PLACEHOLDER_PLAN, slug="strict-ph")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "strict-ph",
                "--strict",
            ],
        )
        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        assert res["passed"] is False
        placeholder_issues = [i for i in res["issues"] if i["code"] == "placeholder"]
        assert len(placeholder_issues) >= 1
        assert placeholder_issues[0]["severity"] == "error"

    # specmason: req=REQ-0037 ac=AC-0432
    def test_plan_lint_warns_when_todos_lack_validation_hints_and_no_tests(
        self, tmp_path: Path
    ) -> None:
        _create_and_start_planning(tmp_path, "todo-hints")
        _propose_plan(tmp_path, _NO_TODO_HINTS_PLAN, slug="todo-hints")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "lint", "--task", "todo-hints"],
        )
        assert result.exit_code == 0, result.output
        payload = _json(result)
        res = payload["result"]
        hint_issues = [
            issue
            for issue in res["issues"]
            if issue["code"] == "missing_todo_validation_hint"
        ]
        assert len(hint_issues) == 1
        assert hint_issues[0]["severity"] == "warning"

    # specmason: req=REQ-0037 ac=AC-0429
    def test_plan_lint_strict_errors_when_todos_lack_validation_hints_and_no_tests(
        self, tmp_path: Path
    ) -> None:
        _create_and_start_planning(tmp_path, "todo-hints-strict")
        _propose_plan(tmp_path, _NO_TODO_HINTS_PLAN, slug="todo-hints-strict")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "todo-hints-strict",
                "--strict",
            ],
        )
        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        hint_issues = [
            issue
            for issue in res["issues"]
            if issue["code"] == "missing_todo_validation_hint"
        ]
        assert len(hint_issues) == 1
        assert hint_issues[0]["severity"] == "error"


class TestPlanLintVersioning:
    # specmason: req=REQ-0037 ac=AC-0420
    def test_plan_lint_defaults_to_latest_plan(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "multi")
        _propose_plan(tmp_path, _NO_GOAL_PLAN, slug="multi")

        # Propose a second plan via another planning cycle
        # Use service layer for second planning cycle start
        from taskledger.services.tasks import start_planning as svc_start_planning

        svc_start_planning(tmp_path, "multi")
        _propose_plan(tmp_path, _FULL_PLAN, slug="multi")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "lint", "--task", "multi"],
        )
        assert result.exit_code == 0, result.output
        payload = _json(result)
        res = payload["result"]
        assert res["plan_version"] == 2


class TestPlanLintApprovalGate:
    # specmason: req=REQ-0037 ac=AC-0411
    def test_plan_approval_blocks_lint_errors(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "gate-block")
        _propose_plan(tmp_path, _NO_GOAL_PLAN, slug="gate-block")

        result = runner.invoke(
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
                "approved",
                "--task",
                "gate-block",
            ],
        )
        assert result.exit_code != 0
        output = result.output
        assert "lint" in output.lower() or "LINT" in output

    # specmason: req=REQ-0037 ac=AC-0413
    def test_plan_approval_lint_escape_hatch_requires_reason(
        self, tmp_path: Path
    ) -> None:
        _create_and_start_planning(tmp_path, "gate-reason")
        _propose_plan(tmp_path, _NO_GOAL_PLAN, slug="gate-reason")

        result = runner.invoke(
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
                "approved",
                "--allow-lint-errors",
                "--task",
                "gate-reason",
            ],
        )
        assert result.exit_code != 0
        assert "reason" in result.output.lower()

    # specmason: req=REQ-0037 ac=AC-0414
    def test_plan_approval_lint_escape_hatch_succeeds_with_reason(
        self, tmp_path: Path
    ) -> None:
        _create_and_start_planning(tmp_path, "gate-ok")
        _propose_plan(tmp_path, _NO_GOAL_PLAN, slug="gate-ok")

        result = runner.invoke(
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
                "approved",
                "--allow-lint-errors",
                "--reason",
                "user accepted rough plan",
                "--task",
                "gate-ok",
            ],
        )
        assert result.exit_code == 0, result.output


class TestPlanLintMissingBody:
    # specmason: req=REQ-0037 ac=AC-0427
    def test_plan_lint_reports_missing_plan_body(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "empty-body")
        _propose_plan(tmp_path, _FRONT_MATTER_ONLY_PLAN, slug="empty-body")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "empty-body",
                "--version",
                "1",
            ],
        )

        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        payload = _json(result)
        res = payload["result"]
        assert res["passed"] is False
        codes = [i["code"] for i in res["issues"]]
        assert "missing_plan_body" in codes
        body_issues = [i for i in res["issues"] if i["code"] == "missing_plan_body"]
        assert body_issues[0]["severity"] == "error"

    # specmason: req=REQ-0037 ac=AC-0412
    def test_plan_approval_blocks_missing_body(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "body-approve")
        _propose_plan(tmp_path, _FRONT_MATTER_ONLY_PLAN, slug="body-approve")

        result = runner.invoke(
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
                "approved",
                "--task",
                "body-approve",
            ],
        )
        assert result.exit_code != 0
        output = result.output.lower()
        assert "lint" in output or "missing_plan_body" in output

    # specmason: req=REQ-0037 ac=AC-0423
    def test_plan_lint_passes_with_body(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "has-body")
        _propose_plan(tmp_path, _FULL_PLAN, slug="has-body")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "lint",
                "--task",
                "has-body",
            ],
        )
        assert result.exit_code == 0
        payload = _json(result)
        codes = [i["code"] for i in payload["result"]["issues"]]
        assert "missing_plan_body" not in codes


class TestPlanLintHumanOutput:
    # specmason: req=REQ-0037 ac=AC-0421
    def test_plan_lint_human_output_renders_issue_details(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "human-details")
        _propose_plan(tmp_path, _VAGUE_TODO_PLAN, slug="human-details")

        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "lint",
                "--task",
                "human-details",
            ],
        )

        assert result.exit_code == EXIT_CODE_VALIDATION_FAILED
        assert "Plan lint failed" in result.stdout
        assert "Summary:" in result.stdout
        assert "ERROR todo_not_concrete" in result.stdout
        assert "plan.todos[0]" in result.stdout
        assert "No lint findings" not in result.stdout

    # specmason: req=REQ-0037 ac=AC-0418
    def test_plan_lint_accepts_short_file_path_todo(self, tmp_path: Path) -> None:
        _create_and_start_planning(tmp_path, "short-path")
        _propose_plan(tmp_path, _SHORT_PATH_TODO_PLAN, slug="short-path")

        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "lint", "--task", "short-path"],
        )

        assert result.exit_code == 0, result.output
        payload = _json(result)
        assert payload["result"]["passed"] is True
        codes = [i["code"] for i in payload["result"]["issues"]]
        assert "todo_not_concrete" not in codes


# specmason: req=REQ-0037 ac=AC-0432
def test_plan_lint_warns_when_approval_ready_heading_is_missing(
    tmp_path: Path,
) -> None:
    _create_and_start_planning(tmp_path, "approval-heading-warning")
    _propose_plan(
        tmp_path,
        _FULL_PLAN,
        slug="approval-heading-warning",
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "lint",
            "--task",
            "approval-heading-warning",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result)["result"]
    heading_issues = [
        issue
        for issue in payload["issues"]
        if issue["code"] == "missing_approval_heading"
    ]
    assert len(heading_issues) == 1
    assert heading_issues[0]["severity"] == "warning"


# specmason: req=REQ-0037 ac=AC-0429
def test_plan_lint_strict_errors_when_approval_ready_heading_is_missing(
    tmp_path: Path,
) -> None:
    _create_and_start_planning(tmp_path, "approval-heading-strict")
    _propose_plan(
        tmp_path,
        _FULL_PLAN,
        slug="approval-heading-strict",
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "lint",
            "--strict",
            "--task",
            "approval-heading-strict",
        ],
    )

    assert result.exit_code == EXIT_CODE_VALIDATION_FAILED, result.output
    payload = _json(result)["result"]
    heading_issues = [
        issue
        for issue in payload["issues"]
        if issue["code"] == "missing_approval_heading"
    ]
    assert len(heading_issues) == 1
    assert heading_issues[0]["severity"] == "error"


# specmason: req=REQ-0037 ac=AC-0413
def test_plan_lint_does_not_require_out_of_scope_heading(tmp_path: Path) -> None:
    _create_and_start_planning(tmp_path, "approval-heading-complete")
    approval_body = _FULL_PLAN.replace(
        "## Goal\n\nTest goal for plan linting.",
        "# Approval Plan\n\n"
        "## Summary\n\nBounded outcome.\n\n"
        "## Implementation Changes\n\n- Update the implementation.\n\n"
        "## Tests\n\n- Run the test suite.\n\n"
        "## Assumptions\n\n- Existing behavior remains stable.",
    )
    _propose_plan(
        tmp_path,
        approval_body,
        slug="approval-heading-complete",
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "lint",
            "--strict",
            "--task",
            "approval-heading-complete",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result)["result"]
    codes = [issue["code"] for issue in payload["issues"]]
    assert "missing_approval_heading" not in codes

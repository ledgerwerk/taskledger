"""Tests for task report service and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.services.task_reports import (
    TaskReportOptions,
    render_task_report,
    resolve_report_sections,
)
from taskledger.services.tasks import (
    activate_task,
    create_task,
    propose_plan,
    start_planning,
)
from tests.support.builders import (
    create_approved_task,
    create_done_task,
    create_implemented_task,
    init_workspace,
)


def _invoke(args: list[str], cwd: Path) -> tuple[int, str, str]:
    from taskledger.cli import app

    try:
        runner = CliRunner(mix_stderr=False)
    except TypeError:
        runner = CliRunner()
    full_args = ["--cwd", str(cwd), *args]
    result = runner.invoke(app, full_args)
    return result.exit_code, result.output, (result.stderr or "")


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestServiceReport:
    def test_task_report_full_markdown_includes_major_sections(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws, task_id, options=TaskReportOptions(preset="full")
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert f"# Task {task_id}" in content
        assert "## Summary" in content
        assert "## Accepted Plan" in content
        assert "## Acceptance Criteria" in content
        assert "## Todo Checklist" in content
        assert "## Implementation" in content
        assert "## Code Reviews" in content
        assert "## Code Changes" in content
        assert "## Validation" in content

        assert "## Worker Role" not in content
        assert "## Worker Contract" not in content
        assert "## Required Output" not in content

    def test_task_report_planning_preset_excludes_impl_and_val(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_approved_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws, task_id, options=TaskReportOptions(preset="planning")
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Plans" in content
        assert "## Questions" in content
        assert "## Implementation" not in content
        assert "## Code Reviews" not in content
        assert "## Validation" not in content
        assert "## Code Changes" not in content

    def test_task_report_implementation_preset_includes_code_reviews(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_implemented_task(ws, allow_lint_errors=True)

        from taskledger.services.code_review import record_code_review

        record_code_review(
            ws,
            task_id,
            result="pass",
            body="No blocking issues.",
        )

        payload = render_task_report(
            ws, task_id, options=TaskReportOptions(preset="implementation")
        )
        content = payload["content"]
        assert isinstance(content, str)
        assert "## Code Reviews" in content
        assert "review-0001" in content

    def test_task_report_planning_report_includes_proposed_plan_details(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task = create_task(
            ws,
            title="Needs review",
            slug="needs-review",
            description="Task with a proposed plan.",
        )
        activate_task(ws, task.id, reason="test setup")
        start_planning(ws, task.id)
        propose_plan(
            ws,
            task.id,
            body="""---
goal: Review proposed plan visibility.
acceptance_criteria:
  - id: ac-0001
    text: Proposed criterion is visible.
todos:
  - id: todo-0001
    text: Proposed todo is visible.
    validation_hint: pytest tests/test_task_report.py
---

# Proposed Plan

Render this proposed plan body in the task report.
""",
        )

        payload = render_task_report(
            ws, task.id, options=TaskReportOptions(preset="planning")
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert "- plan-v1 — proposed" in content
        assert "### Reviewable Plan Details" in content
        assert "#### plan-v1 — proposed" in content
        assert "Render this proposed plan body in the task report." in content
        assert "Proposed criterion is visible." in content
        assert "Proposed todo is visible." in content
        assert "No accepted plan." in content

    def test_task_report_without_removes_sections(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws,
            task_id,
            options=TaskReportOptions(
                preset="full",
                exclude_sections=("todos", "acceptance-criteria"),
            ),
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Todo Checklist" not in content
        assert "## Acceptance Criteria" not in content
        assert "## Summary" in content

    def test_task_report_explicit_sections_override_preset(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws,
            task_id,
            options=TaskReportOptions(
                sections=("summary", "todos"),
            ),
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Summary" in content
        assert "## Todo Checklist" in content
        assert "## Implementation" not in content
        assert "## Validation" not in content

    def test_task_report_archive_includes_events(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws, task_id, options=TaskReportOptions(preset="archive")
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Events" in content

    def test_task_report_events_limit(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws,
            task_id,
            options=TaskReportOptions(
                preset="archive",
                events_limit=2,
            ),
        )
        content = payload["content"]
        assert isinstance(content, str)
        assert "## Events" in content

    def test_task_report_include_command_log_section(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws,
            task_id,
            options=TaskReportOptions(include_sections=("command-log",)),
        )
        content = payload["content"]
        assert isinstance(content, str)
        assert "## Command Transcript" in content

    def test_task_report_unknown_section_fails(self, tmp_path: Path) -> None:
        from taskledger.errors import LaunchError

        with pytest.raises(LaunchError, match="Unsupported"):
            resolve_report_sections(
                preset="full",
                sections=("bogus-section",),
                include_sections=(),
                exclude_sections=(),
            )

    def test_task_report_unknown_preset_fails(self) -> None:
        from taskledger.errors import LaunchError

        with pytest.raises(LaunchError, match="Unsupported"):
            resolve_report_sections(
                preset="nonexistent",
                sections=(),
                include_sections=(),
                exclude_sections=(),
            )

    def test_task_report_negative_events_limit_fails(self, tmp_path: Path) -> None:
        from taskledger.errors import LaunchError

        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        with pytest.raises(LaunchError, match="events-limit"):
            render_task_report(
                ws,
                task_id,
                options=TaskReportOptions(events_limit=-1),
            )

    def test_task_report_json_payload_is_structured(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = render_task_report(
            ws,
            task_id,
            options=TaskReportOptions(preset="full"),
            format_name="json",
        )
        assert payload["kind"] == "task_report"
        assert payload["task_id"] == task_id
        assert isinstance(payload["sections"], list)
        assert isinstance(payload["content"], str)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLIReport:
    def test_task_report_stdout_markdown(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        exit_code, stdout, _ = _invoke(["task", "report", "--task", task_id], cwd=ws)
        assert exit_code == 0
        assert f"# Task {task_id}" in stdout
        assert "## Summary" in stdout

    def test_task_report_output_writes_file(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        output_path = tmp_path / "report.md"

        exit_code, stdout, _ = _invoke(
            [
                "task",
                "report",
                "--task",
                task_id,
                "-o",
                str(output_path),
            ],
            cwd=ws,
        )
        assert exit_code == 0
        assert "wrote task report" in stdout
        assert output_path.exists()
        content = output_path.read_text()
        assert f"# Task {task_id}" in content

    def test_task_report_output_json(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        output_path = tmp_path / "report.md"

        exit_code, stdout, _ = _invoke(
            [
                "--json",
                "task",
                "report",
                "--task",
                task_id,
                "-o",
                str(output_path),
            ],
            cwd=ws,
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert data["ok"] is True
        assert data["command"] == "task.report"
        assert data["result"]["kind"] == "task_report"
        assert data["result"]["output_path"] == str(output_path)

    def test_task_report_uses_active_task_default(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        from taskledger.services.tasks import activate_task

        activate_task(ws, task_id, reason="test")

        exit_code, stdout, _ = _invoke(["task", "report"], cwd=ws)
        assert exit_code == 0
        assert f"# Task {task_id}" in stdout

    def test_task_report_preset_planning(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_approved_task(ws, allow_lint_errors=True)

        exit_code, stdout, _ = _invoke(
            [
                "task",
                "report",
                "--task",
                task_id,
                "--preset",
                "planning",
            ],
            cwd=ws,
        )
        assert exit_code == 0
        assert "## Plans" in stdout
        assert "## Implementation" not in stdout

    def test_task_report_without_todos_and_criteria(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        exit_code, stdout, _ = _invoke(
            [
                "task",
                "report",
                "--task",
                task_id,
                "--without",
                "todos",
                "--without",
                "acceptance-criteria",
            ],
            cwd=ws,
        )
        assert exit_code == 0
        assert "## Todo Checklist" not in stdout
        assert "## Acceptance Criteria" not in stdout
        assert "## Summary" in stdout

    def test_task_report_invalid_format(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        exit_code, stdout, stderr = _invoke(
            [
                "task",
                "report",
                "--task",
                task_id,
                "--format",
                "xml",
            ],
            cwd=ws,
        )
        assert exit_code != 0

"""Tests for task export service and CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.services.task_export import (
    TaskMarkdownExportOptions,
    export_task_markdown,
)
from tests.support.builders import (
    create_done_task,
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


class TestServiceExport:
    def test_task_export_includes_curated_report_and_raw_task_files(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = export_task_markdown(ws, task_id)
        content = payload["content"]
        assert isinstance(content, str)

        assert "# Compiled Task Export:" in content
        assert f"# Compiled Task Export: {task_id}" in content
        assert "## Curated Task Report" in content
        assert "## Raw Taskledger Record Files" in content
        assert "task.md" in content
        assert "plans/" in content
        assert payload["kind"] == "task_markdown_export"
        assert payload["task_id"] == task_id
        assert isinstance(payload["bytes"], int)
        assert payload["bytes"] > 0

    def test_task_export_includes_source_file_snapshots_from_changes(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(
            ws,
            allow_lint_errors=True,
            change_path="README.md",
            change_summary="Updated readme.",
        )
        # Write a README.md so source snapshot can find it
        readme = ws / "README.md"
        readme.write_text("# Test Project\n")

        payload = export_task_markdown(ws, task_id)
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Source File Snapshots" in content
        assert "# Test Project" in content
        assert "README.md" in payload["included_source_files"]

    def test_task_export_no_source_files_skips_source_snapshot_section(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        # Write a file that would be a candidate
        readme = ws / "README.md"
        readme.write_text("# Test Project\n")

        payload = export_task_markdown(
            ws,
            task_id,
            options=TaskMarkdownExportOptions(include_source_files=False),
        )
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Source File Snapshots" not in content
        assert "# Test Project" not in content
        assert payload["included_source_files"] == []

    def test_task_export_skips_outside_workspace_file(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = export_task_markdown(
            ws,
            task_id,
            options=TaskMarkdownExportOptions(
                extra_source_files=("/etc/passwd",),
            ),
        )
        assert isinstance(payload["content"], str)
        # Should succeed without error
        skipped = payload["skipped_files"]
        assert isinstance(skipped, list)
        paths = [s["path"] for s in skipped]
        assert "/etc/passwd" in paths

    def test_task_export_skips_oversized_source_file(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        # Create a large file that's referenced as a change
        large_file = ws / "bigfile.txt"
        large_file.write_text("x" * 500)
        task_id = create_done_task(
            ws,
            allow_lint_errors=True,
            change_path="bigfile.txt",
            change_summary="Big file.",
        )

        payload = export_task_markdown(
            ws,
            task_id,
            options=TaskMarkdownExportOptions(max_source_file_bytes=100),
        )
        assert isinstance(payload["content"], str)
        skipped = payload["skipped_files"]
        assert isinstance(skipped, list)
        reasons_by_path = {s["path"]: s["reason"] for s in skipped}
        assert "bigfile.txt" in reasons_by_path
        assert "bytes" in reasons_by_path["bigfile.txt"]

    def test_task_export_does_not_mutate_taskledger_state(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        from taskledger.storage.task_store import resolve_v2_paths, task_dir

        paths = resolve_v2_paths(ws)
        bundle = task_dir(paths, task_id)

        def _snapshot() -> dict[str, int]:
            result = {}
            for f in sorted(bundle.rglob("*")):
                if f.is_file():
                    try:
                        result[str(f.relative_to(bundle))] = f.stat().st_size
                    except OSError:
                        pass
            return result

        before = _snapshot()
        export_task_markdown(ws, task_id)
        after = _snapshot()
        assert before == after

    def test_task_export_front_matter_contains_metadata(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = export_task_markdown(ws, task_id)
        content = payload["content"]
        assert isinstance(content, str)

        assert "object_type: task_markdown_export" in content
        assert "export_version: 1" in content
        assert f"task_id: {task_id}" in content
        assert "taskledger_version:" in content
        assert "include_source_files: True" in content

    def test_task_export_deterministic_body(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload1 = export_task_markdown(ws, task_id)
        payload2 = export_task_markdown(ws, task_id)

        content1 = payload1["content"]
        content2 = payload2["content"]
        assert isinstance(content1, str)
        assert isinstance(content2, str)

        # Strip front matter (generated_at changes)
        body1 = content1.split("## How to use this file", 1)[1]
        body2 = content2.split("## How to use this file", 1)[1]
        assert body1 == body2

    def test_task_export_summary_table(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        payload = export_task_markdown(ws, task_id)
        content = payload["content"]
        assert isinstance(content, str)

        assert "## Export Summary" in content
        assert f"| Task ID | {task_id} |" in content
        assert "| Record files included |" in content
        assert "| Source files included |" in content

    def test_task_export_dedupes_change_and_plan_source_paths(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        (ws / "README.md").write_text("# Test Project\n")
        plan_text = """---
goal: Test goal.
acceptance_criteria:
  - id: ac-0001
    text: Criterion passes.
todos:
  - id: todo-0001
    text: Implement it.
    validation_hint: pytest tests
files:
  - "@README.md"
---

# Plan

Test plan.
"""
        task_id = create_done_task(
            ws,
            allow_lint_errors=True,
            change_path="README.md",
            change_summary="Updated readme.",
            plan_text=plan_text,
        )

        payload = export_task_markdown(ws, task_id)
        content = payload["content"]
        assert isinstance(content, str)
        assert content.count("### `README.md`") == 1
        assert payload["included_source_files"] == ["README.md"]

    def test_task_export_skips_nested_git_directory(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        secret = ws / "src" / ".git" / "config"
        secret.parent.mkdir(parents=True)
        secret.write_text("should not be exported\n")

        payload = export_task_markdown(
            ws,
            task_id,
            options=TaskMarkdownExportOptions(
                extra_source_files=("src/.git/config",),
            ),
        )
        content = payload["content"]
        assert isinstance(content, str)
        assert "should not be exported" not in content
        skipped = payload["skipped_files"]
        assert isinstance(skipped, list)
        assert any(s["path"] == "src/.git/config" for s in skipped)

    def test_task_export_does_not_report_missing_plan_only_source_file(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        (ws / "README.md").write_text("# Test Project\n")
        plan_text = """---
goal: Test goal.
files:
  - "@temporary_review_input.md"
  - "@README.md"
acceptance_criteria:
  - id: ac-0001
    text: Criterion passes.
todos:
  - id: todo-0001
    text: Implement it.
    validation_hint: pytest tests
---

# Plan

Use the temporary review input to plan the change.
"""
        task_id = create_done_task(
            ws,
            allow_lint_errors=True,
            change_path="README.md",
            change_summary="Updated readme.",
            plan_text=plan_text,
        )

        payload = export_task_markdown(ws, task_id)

        skipped = payload["skipped_files"]
        assert isinstance(skipped, list)
        assert all(s["path"] != "@temporary_review_input.md" for s in skipped)
        assert "README.md" in payload["included_source_files"]

    def test_task_export_does_not_report_git_scan_dot_as_source_file(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        (ws / "README.md").write_text("# Test Project\n")
        task_id = create_done_task(
            ws,
            allow_lint_errors=True,
            change_path="README.md",
            change_summary="Updated readme.",
        )

        from taskledger.domain.change import CodeChangeRecord
        from taskledger.storage.task_store import save_change
        from taskledger.timeutils import utc_now_iso

        save_change(
            ws,
            CodeChangeRecord(
                change_id="change-9999",
                task_id=task_id,
                implementation_run="run-9999",
                timestamp=utc_now_iso(),
                kind="scan",
                path=".",
                summary="Captured git status.",
            ),
        )

        payload = export_task_markdown(ws, task_id)

        skipped = payload["skipped_files"]
        assert isinstance(skipped, list)
        assert all(s["path"] != "." for s in skipped)

    def test_task_export_total_source_budget_does_not_charge_skipped_file(
        self, tmp_path: Path
    ) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        (ws / "a.txt").write_text("a" * 90)
        (ws / "b.txt").write_text("b" * 20)
        (ws / "c.txt").write_text("c" * 5)

        payload = export_task_markdown(
            ws,
            task_id,
            options=TaskMarkdownExportOptions(
                extra_source_files=("a.txt", "b.txt", "c.txt"),
                max_source_file_bytes=1000,
                max_total_source_bytes=100,
            ),
        )

        assert "a.txt" in payload["included_source_files"]
        assert "b.txt" not in payload["included_source_files"]
        assert "c.txt" in payload["included_source_files"]


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCliExport:
    def test_task_export_writes_markdown_file(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        output_path = tmp_path / "task-0001.llm.md"

        exit_code, stdout, _ = _invoke(
            ["task", "export", "--task", task_id, "-o", str(output_path)],
            cwd=ws,
        )

        assert exit_code == 0
        assert "wrote task export" in stdout
        content = output_path.read_text()
        assert "# Compiled Task Export:" in content
        assert "## Raw Taskledger Record Files" in content

    def test_task_export_stdout_markdown(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        exit_code, stdout, _ = _invoke(
            ["task", "export", "--task", task_id],
            cwd=ws,
        )

        assert exit_code == 0
        assert "# Compiled Task Export:" in stdout
        assert "## Raw Taskledger Record Files" in stdout

    def test_task_export_json_output_writes_file(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        output_path = tmp_path / "task-0001.llm.md"

        exit_code, stdout, _ = _invoke(
            [
                "--json",
                "task",
                "export",
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
        assert data["result"]["kind"] == "task_markdown_export"
        # content should be stripped when writing to file
        assert "content" not in data["result"]
        assert "output_path" in data["result"]

        # File should have the markdown content
        file_content = output_path.read_text()
        assert "# Compiled Task Export:" in file_content

    def test_task_export_uses_active_task_default(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)

        from taskledger.services.tasks import activate_task

        activate_task(ws, task_id, reason="test setup")

        exit_code, stdout, _ = _invoke(
            ["task", "export"],
            cwd=ws,
        )

        assert exit_code == 0
        assert f"# Compiled Task Export: {task_id}" in stdout

    def test_task_export_no_source_files_flag(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(
            ws,
            allow_lint_errors=True,
            change_path="README.md",
            change_summary="Updated.",
        )
        readme = ws / "README.md"
        readme.write_text("# Test\n")

        exit_code, stdout, _ = _invoke(
            ["task", "export", "--task", task_id, "--no-source-files"],
            cwd=ws,
        )

        assert exit_code == 0
        assert "## Source File Snapshots" not in stdout

    def test_task_export_positional_task_ref(self, tmp_path: Path) -> None:
        ws = init_workspace(tmp_path)
        task_id = create_done_task(ws, allow_lint_errors=True)
        output_path = tmp_path / "export.md"

        exit_code, stdout, _ = _invoke(
            ["task", "export", task_id, "-o", str(output_path)],
            cwd=ws,
        )

        assert exit_code == 0
        assert "wrote task export" in stdout
        content = output_path.read_text()
        assert f"# Compiled Task Export: {task_id}" in content

"""Tests for `taskledger tree` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from taskledger.cli import app
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _json(result: Result) -> dict:
    return json.loads(result.stdout)


def _init(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _create_task(tmp_path: Path, title: str, slug: str | None = None) -> None:
    args = ["--cwd", str(tmp_path), "task", "create", title]
    if slug:
        args += ["--slug", slug]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def _activate(tmp_path: Path, ref: str) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", ref])
    assert result.exit_code == 0, result.output


def _tree(tmp_path: Path, *extra: str) -> Result:
    args = ["--cwd", str(tmp_path), "tree", *extra]
    return runner.invoke(app, args)


def _json_tree(tmp_path: Path, *extra: str) -> dict:
    args = ["--cwd", str(tmp_path), "--json", "tree", *extra]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return _json(result)


# ---------------------------------------------------------------------------
# 9.1 Empty ledger
# ---------------------------------------------------------------------------


class TestEmptyLedger:
    # specmason: req=REQ-0069 ac=AC-0780
    def test_human_output_shows_no_tasks(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "TASKLEDGER TREE" in result.output
        assert "ledger main" in result.output
        assert "(current)" in result.output
        assert "(no tasks)" in result.output

    def test_json_payload_structure(self, tmp_path: Path) -> None:
        _init(tmp_path)
        data = _json_tree(tmp_path)
        payload = data["result"]
        assert payload["kind"] == "taskledger_tree"
        assert payload["scope"] == "current_ledger"
        ledgers = payload["ledgers"]
        assert len(ledgers) == 1
        ledger = ledgers[0]
        assert ledger["ref"] == "main"
        assert ledger["is_current"] is True
        assert ledger["task_count"] == 0
        assert ledger["tasks"] == []
        assert ledger["orphaned_children"] == []
        assert ledger["active_task_id"] is None

    def test_json_envelope_ok(self, tmp_path: Path) -> None:
        _init(tmp_path)
        data = _json_tree(tmp_path)
        assert data["ok"] is True
        assert data["command"] == "tree"


# ---------------------------------------------------------------------------
# 9.2 Current ledger tasks
# ---------------------------------------------------------------------------


class TestCurrentLedgerTasks:
    # specmason: req=REQ-0069 ac=AC-0785
    def test_shows_both_tasks(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Parser fix", slug="parser-fix")
        _create_task(tmp_path, "Docs cleanup", slug="docs-cleanup")
        _activate(tmp_path, "docs-cleanup")

        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "task-0001" in result.output
        assert "task-0002" in result.output
        assert "parser-fix" in result.output
        assert "docs-cleanup" in result.output
        # Active marker
        assert "*" in result.output

    # specmason: req=REQ-0069 ac=AC-0781
    def test_json_active_task_marker(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "First", slug="first")
        _create_task(tmp_path, "Second", slug="second")
        _activate(tmp_path, "second")

        data = _json_tree(tmp_path)
        tasks = data["result"]["ledgers"][0]["tasks"]
        assert len(tasks) == 2
        assert tasks[0]["is_active"] is False
        assert tasks[1]["is_active"] is True

    # specmason: req=REQ-0069 ac=AC-0781
    def test_no_active_task_still_succeeds(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Lonely task", slug="lonely")
        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "task-0001" in result.output


# ---------------------------------------------------------------------------
# 9.3 Follow-up nesting
# ---------------------------------------------------------------------------


class TestFollowUpNesting:
    # specmason: req=REQ-0069 ac=AC-0775
    def test_child_nested_under_parent_human(self, tmp_path: Path) -> None:
        _init(tmp_path)
        # Create a done parent via task record
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Parent task",
                "--slug",
                "parent-task",
                "--description",
                "done parent",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        # Create follow-up
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "follow-up",
                "parent-task",
                "Follow-up child",
                "--slug",
                "follow-up-child",
                "--activate",
            ],
        )
        assert result.exit_code == 0, result.output

        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "task-0001" in result.output
        assert "task-0002" in result.output
        assert "(follow-up)" in result.output

    # specmason: req=REQ-0069 ac=AC-0776
    def test_child_nested_under_parent_json(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Parent task",
                "--slug",
                "parent-task",
                "--description",
                "done parent",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "follow-up",
                "parent-task",
                "Follow-up child",
                "--slug",
                "follow-up-child",
                "--activate",
            ],
        )
        assert result.exit_code == 0, result.output

        data = _json_tree(tmp_path)
        tasks = data["result"]["ledgers"][0]["tasks"]
        parent = tasks[0]
        assert parent["id"] == "task-0001"
        assert len(parent["children"]) == 1
        child = parent["children"][0]
        assert child["id"] == "task-0002"
        assert child["parent_relation"] == "follow_up"
        assert child["parent_task_id"] == "task-0001"


# ---------------------------------------------------------------------------
# 9.4 Task subtree
# ---------------------------------------------------------------------------


class TestTaskSubtree:
    # specmason: req=REQ-0069 ac=AC-0786
    def test_subtree_shows_only_selected(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Alpha", slug="alpha")
        _create_task(tmp_path, "Beta", slug="beta")

        result = _tree(tmp_path, "--task", "alpha")
        assert result.exit_code == 0, result.output
        assert "task-0001" in result.output
        # beta should not appear as a separate root
        output_lines = result.output.split("\n")
        task_lines = [
            line for line in output_lines if "task-0002" in line and "beta" in line
        ]
        assert len(task_lines) == 0

    # specmason: req=REQ-0069 ac=AC-0786
    def test_subtree_json_scope(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Alpha", slug="alpha")
        _create_task(tmp_path, "Beta", slug="beta")

        data = _json_tree(tmp_path, "--task", "alpha")
        payload = data["result"]
        assert payload["scope"] == "task_subtree"
        tasks = payload["ledgers"][0]["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["slug"] == "alpha"

    # specmason: req=REQ-0069 ac=AC-0787
    def test_subtree_with_children(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Parent",
                "--slug",
                "parent",
                "--description",
                "done",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "follow-up",
                "parent",
                "Child",
                "--slug",
                "child",
                "--activate",
            ],
        )
        assert result.exit_code == 0, result.output

        # Subtree of parent should include child
        data = _json_tree(tmp_path, "--task", "parent")
        tasks = data["result"]["ledgers"][0]["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["id"] == "task-0001"
        assert len(tasks[0]["children"]) == 1
        assert tasks[0]["children"][0]["id"] == "task-0002"


# ---------------------------------------------------------------------------
# 9.5 Details mode
# ---------------------------------------------------------------------------


class TestDetails:
    # specmason: req=REQ-0069 ac=AC-0779
    def test_details_shows_counts(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Detailed task", slug="detailed")
        _activate(tmp_path, "detailed")

        # Start planning to create a planning run
        result = runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"])
        assert result.exit_code == 0, result.output

        data = _json_tree(tmp_path, "--details")
        tasks = data["result"]["ledgers"][0]["tasks"]
        assert len(tasks) == 1
        counts = tasks[0]["counts"]
        assert counts is not None
        assert "todos" in counts
        assert "plans" in counts
        assert "runs" in counts
        assert "changes" in counts
        assert "has_lock" in counts

    # specmason: req=REQ-0069 ac=AC-0778
    def test_details_human_output_compact(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Detailed task", slug="detailed")

        result = _tree(tmp_path, "--details")
        assert result.exit_code == 0, result.output
        # Should contain count-like patterns
        assert "todos=" in result.output or "plans=" in result.output

    # specmason: req=REQ-0069 ac=AC-0779
    def test_no_details_means_null_counts(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Simple task", slug="simple")

        data = _json_tree(tmp_path)
        tasks = data["result"]["ledgers"][0]["tasks"]
        assert tasks[0]["counts"] is None


# ---------------------------------------------------------------------------
# 9.6 All ledgers
# ---------------------------------------------------------------------------


class TestAllLedgers:
    # specmason: req=REQ-0069 ac=AC-0773
    def test_all_ledgers_shows_multiple(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Main task", slug="main-task")

        # Fork to feature-a
        result = runner.invoke(
            app, ["--cwd", str(tmp_path), "ledger", "fork", "feature-a"]
        )
        assert result.exit_code == 0, result.output

        # Create a task in feature-a
        _create_task(tmp_path, "Feature task", slug="feature-task")

        data = _json_tree(tmp_path, "--all-ledgers")
        payload = data["result"]
        assert payload["scope"] == "all_ledgers"
        ledgers = payload["ledgers"]
        assert len(ledgers) == 2
        refs = [ledger["ref"] for ledger in ledgers]
        assert "main" in refs
        assert "feature-a" in refs
        # Exactly one is current
        current = [ledger for ledger in ledgers if ledger["is_current"]]
        assert len(current) == 1

    # specmason: req=REQ-0069 ac=AC-0772
    def test_all_ledgers_does_not_mutate_config(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Main task", slug="main-task")
        result = runner.invoke(
            app, ["--cwd", str(tmp_path), "ledger", "fork", "feature-a"]
        )
        assert result.exit_code == 0, result.output

        # Read config before
        config_before = (tmp_path / "taskledger.toml").read_text()

        # Run tree --all-ledgers
        _tree(tmp_path, "--all-ledgers")

        # Config should be unchanged
        config_after = (tmp_path / "taskledger.toml").read_text()
        assert config_before == config_after


class TestReleaseRendering:
    # specmason: req=REQ-0069 ac=AC-0777
    def test_current_ledger_release_is_rendered(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Done parent",
                "--slug",
                "done-parent",
                "--description",
                "done",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "release",
                "tag",
                "0.1.0",
                "--at-task",
                "done-parent",
            ],
        )
        assert result.exit_code == 0, result.output

        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "releases" in result.output
        assert "0.1.0 -> task-0001" in result.output

        data = _json_tree(tmp_path)
        ledger = data["result"]["ledgers"][0]
        assert ledger["release_count"] == 1
        assert ledger["releases"][0]["version"] == "0.1.0"
        assert ledger["releases"][0]["boundary_task_id"] == "task-0001"

    # specmason: req=REQ-0069 ac=AC-0774
    def test_all_ledgers_uses_each_ledger_release_records(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Main done",
                "--slug",
                "main-done",
                "--description",
                "done",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "release",
                "tag",
                "0.1.0",
                "--at-task",
                "main-done",
            ],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(
            app, ["--cwd", str(tmp_path), "ledger", "fork", "feature-a"]
        )
        assert result.exit_code == 0, result.output

        data = _json_tree(tmp_path, "--all-ledgers")
        ledgers = {ledger["ref"]: ledger for ledger in data["result"]["ledgers"]}
        assert ledgers["main"]["releases"][0]["version"] == "0.1.0"
        assert ledgers["feature-a"]["releases"] == []

        result = _tree(tmp_path, "--all-ledgers")
        assert result.exit_code == 0, result.output
        assert result.output.count("0.1.0 -> task-0001") == 1


# ---------------------------------------------------------------------------
# Plain ASCII output
# ---------------------------------------------------------------------------


class TestPlainOutput:
    # specmason: req=REQ-0069 ac=AC-0782
    def test_plain_uses_ascii_glyphs(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _create_task(tmp_path, "Test task", slug="test-task")

        result = _tree(tmp_path, "--plain")
        assert result.exit_code == 0, result.output
        assert "+- " in result.output or "`- " in result.output
        # Should NOT contain unicode glyphs
        assert "├─" not in result.output
        assert "└─" not in result.output


# ---------------------------------------------------------------------------
# Recorded task type
# ---------------------------------------------------------------------------


class TestRecordedTaskType:
    # specmason: req=REQ-0069 ac=AC-0784
    def test_recorded_marker_in_output(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Manual fix",
                "--slug",
                "manual-fix",
                "--description",
                "Fixed manually",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output

        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "{recorded}" in result.output

    # specmason: req=REQ-0069 ac=AC-0783
    def test_recorded_in_json(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Manual fix",
                "--slug",
                "manual-fix",
                "--description",
                "Fixed manually",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output

        data = _json_tree(tmp_path)
        tasks = data["result"]["ledgers"][0]["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["task_type"] == "recorded"


class TestArchivedTasks:
    # specmason: req=REQ-0069 ac=AC-0788
    def test_tree_hides_archived_by_default(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Legacy",
                "--slug",
                "legacy",
                "--description",
                "Legacy done task",
                "--summary",
                "Legacy complete",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        archived = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "archive",
                "legacy",
                "--reason",
                "hide",
            ],
        )
        assert archived.exit_code == 0, archived.output

        result = _tree(tmp_path)
        assert result.exit_code == 0, result.output
        assert "legacy" not in result.output
        assert "next=task-0002" in result.output

    # specmason: req=REQ-0069 ac=AC-0789
    def test_tree_include_archived_marks_nodes(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "record",
                "Legacy",
                "--slug",
                "legacy",
                "--description",
                "Legacy done task",
                "--summary",
                "Legacy complete",
                "--allow-empty-record",
                "--reason",
                "test",
            ],
        )
        assert result.exit_code == 0, result.output
        archived = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "archive",
                "legacy",
                "--reason",
                "hide",
            ],
        )
        assert archived.exit_code == 0, archived.output

        result = _tree(tmp_path, "--include-archived")
        assert result.exit_code == 0, result.output
        assert "legacy" in result.output
        assert "{archived}" in result.output

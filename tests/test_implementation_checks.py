"""Tests for ImplementationCheckRecord domain model and check tracking."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.check import ImplementationCheckRecord
from taskledger.services.check_tracking import classify_check_command


class TestImplementationCheckRecordRoundTrip:
    # specmason: req=REQ-0026 ac=AC-0322
    def test_to_dict_from_dict_round_trip(self) -> None:
        record = ImplementationCheckRecord(
            check_id="check-0001",
            task_id="task-0001",
            implementation_run="run-0001",
            timestamp="2025-01-01T00:00:00Z",
            command="python -m pytest -q",
            argv=("python", "-m", "pytest", "-q"),
            exit_code=0,
            status="passed",
            category="test",
            summary="All tests passed.",
        )
        data = record.to_dict()
        restored = ImplementationCheckRecord.from_dict(data)
        assert restored == record

    # specmason: req=REQ-0026 ac=AC-0322
    def test_from_dict_rejects_wrong_object_type(self) -> None:
        data = {
            "object_type": "change",
            "check_id": "check-0001",
            "task_id": "task-0001",
            "implementation_run": "run-0001",
            "timestamp": "2025-01-01",
            "command": "echo",
            "schema_version": 1,
        }
        with pytest.raises(Exception, match="object_type"):
            ImplementationCheckRecord.from_dict(data)

    # specmason: req=REQ-0026 ac=AC-0322
    def test_from_dict_rejects_unknown_status(self) -> None:
        data = {
            "object_type": "implementation_check",
            "check_id": "check-0001",
            "task_id": "task-0001",
            "implementation_run": "run-0001",
            "timestamp": "2025-01-01",
            "command": "echo",
            "status": "exploding",
            "schema_version": 1,
            "file_version": "v2",
        }
        with pytest.raises(Exception, match="Unsupported check status"):
            ImplementationCheckRecord.from_dict(data)

    # specmason: req=REQ-0026 ac=AC-0322
    def test_from_dict_rejects_unknown_category(self) -> None:
        data = {
            "object_type": "implementation_check",
            "check_id": "check-0001",
            "task_id": "task-0001",
            "implementation_run": "run-0001",
            "timestamp": "2025-01-01",
            "command": "echo",
            "category": "exploding",
            "schema_version": 1,
            "file_version": "v2",
        }
        with pytest.raises(Exception, match="Unsupported check category"):
            ImplementationCheckRecord.from_dict(data)

    # specmason: req=REQ-0026 ac=AC-0320
    def test_missing_command_fails(self) -> None:
        data = {
            "object_type": "implementation_check",
            "check_id": "check-0001",
            "task_id": "task-0001",
            "implementation_run": "run-0001",
            "timestamp": "2025-01-01",
            "schema_version": 1,
            "file_version": "v2",
        }
        with pytest.raises(Exception, match="command"):
            ImplementationCheckRecord.from_dict(data)

    # specmason: req=REQ-0026 ac=AC-0319
    def test_defaults(self) -> None:
        data = {
            "object_type": "implementation_check",
            "check_id": "check-0001",
            "task_id": "task-0001",
            "implementation_run": "run-0001",
            "timestamp": "2025-01-01",
            "command": "echo hi",
            "schema_version": 1,
            "file_version": "v2",
        }
        record = ImplementationCheckRecord.from_dict(data)
        assert record.status == "unknown"
        assert record.category == "other"
        assert record.exit_code is None
        assert record.summary is None
        assert record.argv == ()


class TestClassifyCheckCommand:
    def test_pytest_direct(self) -> None:
        assert classify_check_command(("pytest", "-q")) == "test"

    def test_python_m_pytest(self) -> None:
        assert classify_check_command(("python", "-m", "pytest", "-q")) == "test"

    def test_ruff_check(self) -> None:
        assert classify_check_command(("ruff", "check", ".")) == "lint"

    def test_ruff_format(self) -> None:
        assert classify_check_command(("ruff", "format", "--check", ".")) == "format"

    def test_mypy(self) -> None:
        assert classify_check_command(("mypy", "solvecost")) == "typecheck"

    def test_pyright(self) -> None:
        assert classify_check_command(("pyright", ".")) == "typecheck"

    def test_tox(self) -> None:
        assert classify_check_command(("tox",)) == "test"

    def test_npm_test(self) -> None:
        assert classify_check_command(("npm", "test")) == "test"

    def test_unknown(self) -> None:
        assert classify_check_command(("echo", "hello")) == "other"

    def test_empty(self) -> None:
        assert classify_check_command(()) == "other"

    def test_pnpm_test(self) -> None:
        assert classify_check_command(("pnpm", "test")) == "test"

    def test_yarn_test(self) -> None:
        assert classify_check_command(("yarn", "test")) == "test"

    def test_nox(self) -> None:
        assert classify_check_command(("nox",)) == "test"

    def test_pyre(self) -> None:
        assert classify_check_command(("pyre", "check")) == "typecheck"


def _prepare_task_with_impl_run(tmp_path: Path) -> str:
    """Create a task with an active implementation run for testing."""
    runner = CliRunner()
    initialized = runner.invoke(app, ["--root", str(tmp_path), "init"])
    assert initialized.exit_code == 0, initialized.output
    r = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "task",
            "create",
            "Test task",
            "--slug",
            "test-checks",
        ],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--root", str(tmp_path), "task", "activate", "test-checks"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--root", str(tmp_path), "plan", "start"])
    assert r.exit_code == 0, r.output
    # Write a minimal plan
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(
        "---\n"
        "goal: test\n"
        "test_commands:\n"
        "  - python -c 'print(1)'\n"
        "expected_outputs:\n"
        "  - prints 1\n"
        "acceptance_criteria:\n"
        "  - id: ac-0001\n"
        "    text: passes\n"
        "    mandatory: true\n"
        "todos:\n"
        "  - id: plan-todo-0001\n"
        "    text: do it\n"
        "    mandatory: true\n"
        "    validation_hint: check output\n"
        "---\n"
        "## Plan\nDo it.\n",
    )
    r = runner.invoke(
        app, ["--root", str(tmp_path), "plan", "upsert", "--file", str(plan_path)]
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "plan",
            "accept",
            "--version",
            "1",
            "--note",
            "test approval",
        ],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--root", str(tmp_path), "implement", "start"])
    assert r.exit_code == 0, r.output
    return str(tmp_path)


class TestImplementCommandCreatesCheck:
    # specmason: req=REQ-0026 ac=AC-0318
    def test_creates_check_not_change(self, tmp_path: Path) -> None:
        root = _prepare_task_with_impl_run(tmp_path)
        runner = CliRunner()
        r = runner.invoke(
            app,
            [
                "--root",
                root,
                "--json",
                "implement",
                "command",
                "--",
                "python",
                "-c",
                "print(1)",
            ],
        )
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["result"]["kind"] == "implementation_check"
        assert payload["result"]["check"]["check_id"].startswith("check-")
        assert payload["result"]["change"] is None

    # specmason: req=REQ-0026 ac=AC-0316
    def test_check_has_category(self, tmp_path: Path) -> None:
        root = _prepare_task_with_impl_run(tmp_path)
        runner = CliRunner()
        r = runner.invoke(
            app,
            [
                "--root",
                root,
                "--json",
                "implement",
                "command",
                "--allow-failure",
                "--",
                "python",
                "-m",
                "pytest",
                "-q",
            ],
            catch_exceptions=False,
        )
        assert r.exit_code == 0, r.output  # --allow-failure
        payload = json.loads(r.output)
        assert payload["result"]["check"]["category"] == "test"

    # specmason: req=REQ-0026 ac=AC-0317
    def test_check_refs_on_run(self, tmp_path: Path) -> None:
        root = _prepare_task_with_impl_run(tmp_path)
        runner = CliRunner()
        r = runner.invoke(
            app,
            [
                "--root",
                root,
                "--json",
                "implement",
                "command",
                "--",
                "python",
                "-c",
                "print(1)",
            ],
        )
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        check_id = payload["result"]["check"]["check_id"]
        # Verify run has check_refs via storage directly
        from pathlib import Path as P

        from taskledger.storage.task_store import (
            resolve_run,
            resolve_task,
        )

        task = resolve_task(P(root), "test-checks")
        run = resolve_run(P(root), task.id, task.latest_implementation_run)
        assert check_id in run.check_refs

    # specmason: req=REQ-0026 ac=AC-0321
    def test_human_output_shows_check(self, tmp_path: Path) -> None:
        root = _prepare_task_with_impl_run(tmp_path)
        runner = CliRunner()
        r = runner.invoke(
            app,
            ["--root", root, "implement", "command", "--", "python", "-c", "print(1)"],
        )
        assert r.exit_code == 0, r.output
        assert "recorded check check-" in r.output

    # specmason: req=REQ-0026 ac=AC-0320
    def test_failed_command_creates_failed_check(self, tmp_path: Path) -> None:
        root = _prepare_task_with_impl_run(tmp_path)
        runner = CliRunner()
        r = runner.invoke(
            app,
            [
                "--root",
                root,
                "--json",
                "implement",
                "command",
                "--",
                "python",
                "-c",
                "exit(1)",
            ],
        )
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["result"]["check"]["status"] == "failed"
        assert payload["result"]["check"]["exit_code"] == 1

    # specmason: req=REQ-0026 ac=AC-0315
    def test_allow_failure_records_check(self, tmp_path: Path) -> None:
        root = _prepare_task_with_impl_run(tmp_path)
        runner = CliRunner()
        r = runner.invoke(
            app,
            [
                "--root",
                root,
                "--json",
                "implement",
                "command",
                "--allow-failure",
                "--",
                "python",
                "-c",
                "exit(1)",
            ],
        )
        assert r.exit_code == 0
        payload = json.loads(r.output)
        assert payload["result"]["check"]["status"] == "failed"


# specmason: req=REQ-0026 ac=AC-0321
def test_implement_command_preserves_exact_child_argv(tmp_path: Path) -> None:
    root = _prepare_task_with_impl_run(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "--root",
            root,
            "--json",
            "implement",
            "command",
            "--",
            sys.executable,
            "-c",
            "import sys; print(repr(sys.argv[1:]))",
            "--maxfail=1",
            "-k",
            "not slow",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert "['--maxfail=1', '-k', 'not slow']" in payload["stdout"]
    assert payload["cwd"] == str(tmp_path.resolve())


# specmason: req=REQ-0026 ac=AC-0321
def test_implement_command_runs_from_nested_invocation_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(_prepare_task_with_impl_run(tmp_path))
    nested = root / "subproject"
    nested.mkdir()
    monkeypatch.chdir(nested)

    result = CliRunner().invoke(
        app,
        [
            "--json",
            "implement",
            "command",
            "--task",
            "test-checks",
            "--",
            sys.executable,
            "-c",
            "import os; print(os.getcwd())",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["cwd"] == str(nested.resolve())
    assert str(nested.resolve()) in payload["stdout"]


# specmason: req=REQ-0026 ac=AC-0321
def test_implement_command_human_mode_emits_child_output(tmp_path: Path) -> None:
    root = _prepare_task_with_impl_run(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "--root",
            root,
            "implement",
            "command",
            "--",
            sys.executable,
            "-c",
            (
                "import sys; print('managed stdout marker'); "
                "print('managed stderr marker', file=sys.stderr)"
            ),
        ],
    )
    combined = result.output + str(getattr(result, "stderr", ""))
    assert result.exit_code == 0, combined
    assert "managed stdout marker" in combined
    assert "managed stderr marker" in combined
    assert "recorded check check-" in combined


# specmason: req=REQ-0026 ac=AC-0321
def test_plan_command_preserves_cwd_and_json_streams(tmp_path: Path) -> None:
    runner = CliRunner()
    initialized = runner.invoke(app, ["--root", str(tmp_path), "init"])
    assert initialized.exit_code == 0, initialized.output
    create = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "task",
            "create",
            "Planning task",
            "--slug",
            "planning-task",
        ],
    )
    assert create.exit_code == 0, create.output
    activate = runner.invoke(
        app, ["--root", str(tmp_path), "task", "activate", "planning-task"]
    )
    assert activate.exit_code == 0, activate.output
    start = runner.invoke(app, ["--root", str(tmp_path), "plan", "start"])
    assert start.exit_code == 0, start.output

    result = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "--json",
            "plan",
            "command",
            "--",
            sys.executable,
            "-c",
            "import os, sys; print(os.getcwd()); print(repr(sys.argv[1:]))",
            "--maxfail=1",
            "-k",
            "not slow",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["cwd"] == str(tmp_path.resolve())
    assert str(tmp_path.resolve()) in payload["stdout"]
    assert "['--maxfail=1', '-k', 'not slow']" in payload["stdout"]
    json.loads(result.output)


# specmason: req=REQ-0026 ac=AC-0321
def test_plan_command_human_mode_emits_child_output(tmp_path: Path) -> None:
    runner = CliRunner()
    initialized = runner.invoke(app, ["--root", str(tmp_path), "init"])
    assert initialized.exit_code == 0, initialized.output
    for args in (
        ["task", "create", "Planning task", "--slug", "planning-task"],
        ["task", "activate", "planning-task"],
        ["plan", "start"],
    ):
        result = runner.invoke(app, ["--root", str(tmp_path), *args])
        assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "plan",
            "command",
            "--",
            sys.executable,
            "-c",
            (
                "import sys; print('planning stdout marker'); "
                "print('planning stderr marker', file=sys.stderr)"
            ),
        ],
    )
    combined = result.output + str(getattr(result, "stderr", ""))
    assert result.exit_code == 0, combined
    assert "planning stdout marker" in combined
    assert "planning stderr marker" in combined
    assert "ran planning command exit=0" in combined

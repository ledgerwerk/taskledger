from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.events import load_events
from taskledger.storage.task_store import resolve_run, resolve_task, resolve_v2_paths

runner = CliRunner()


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )


def _invoke(args: list[str], *, cwd: Path, ok: bool = True) -> Any:
    result = runner.invoke(app, ["--cwd", str(cwd), *args])
    if ok:
        assert result.exit_code == 0, result.output
    return result


def _invoke_json(args: list[str], *, cwd: Path, ok: bool = True) -> dict[str, Any]:
    result = runner.invoke(app, ["--cwd", str(cwd), "--json", *args])
    if ok:
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        return payload
    assert result.exit_code != 0, result.output
    return json.loads(result.stdout)


def _write_local_config(tmp_path: Path) -> None:
    (tmp_path / "taskledger.toml").write_text(
        "config_version = 2\n"
        'taskledger_dir = ".taskledger"\n'
        'ledger_ref = "main"\n'
        "ledger_next_task_number = 1\n"
        "[ledger]\n"
        'code = "tl"\n'
        'name = "taskledger"\n',
        encoding="utf-8",
    )


def _init_git_project(tmp_path: Path) -> None:
    _write_local_config(tmp_path)
    _run_git(tmp_path, "init")
    _run_git(tmp_path, "config", "user.email", "test@example.invalid")
    _run_git(tmp_path, "config", "user.name", "Taskledger Test")
    (tmp_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".")
    _run_git(tmp_path, "commit", "-m", "initial")
    _invoke(["init"], cwd=tmp_path)
    _write_local_config(tmp_path)


def _prepare_implemented_task(
    tmp_path: Path, *, stage_before_finish: bool = False
) -> str:
    payload = _invoke_json(
        ["task", "create", "Git snapshot task", "--slug", "git-snapshot-task"],
        cwd=tmp_path,
    )
    task_id = payload["result"]["id"]
    _invoke(["task", "activate", task_id], cwd=tmp_path)
    _invoke(["plan", "start", "--task", task_id], cwd=tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text(
        "---\n"
        "goal: Test git snapshots\n"
        "files:\n"
        '  - "@tracked.txt"\n'
        "test_commands:\n"
        '  - "pytest tests/test_validation_git_snapshot_recovery.py"\n'
        "acceptance_criteria:\n"
        "  - id: ac-0001\n"
        "    text: Validation starts safely\n"
        "    mandatory: true\n"
        "todos:\n"
        "  - id: plan-todo-0001\n"
        '    text: "Modify @tracked.txt"\n'
        "    mandatory: true\n"
        "---\n"
        "## Plan body\n",
        encoding="utf-8",
    )
    _invoke(["plan", "upsert", "--file", str(plan), "--task", task_id], cwd=tmp_path)
    _invoke(
        [
            "plan",
            "accept",
            "--version",
            "1",
            "--task",
            task_id,
            "--note",
            "Approved for test",
            "--allow-lint-errors",
        ],
        cwd=tmp_path,
    )
    _invoke(["implement", "start", "--task", task_id], cwd=tmp_path)
    (tmp_path / "tracked.txt").write_text("implemented\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    if stage_before_finish:
        _run_git(tmp_path, "add", "tracked.txt", "new.txt")
    todo_payload = _invoke_json(["todo", "status", "--task", task_id], cwd=tmp_path)
    todo_id = todo_payload["result"]["open_todos"][0]
    _invoke(
        ["todo", "done", todo_id, "--evidence", "modified files", "--task", task_id],
        cwd=tmp_path,
    )
    _invoke(
        ["implement", "finish", "--task", task_id, "--summary", "Done"],
        cwd=tmp_path,
    )
    return task_id


def test_validate_start_ignores_staging_only_snapshot_change(tmp_path: Path) -> None:
    _init_git_project(tmp_path)
    task_id = _prepare_implemented_task(tmp_path, stage_before_finish=True)

    _run_git(tmp_path, "restore", "--staged", ".")
    result = _invoke(["validate", "start", "--task", task_id], cwd=tmp_path)

    assert "started validation" in result.output


def test_validate_start_blocks_actual_content_change_after_finish(
    tmp_path: Path,
) -> None:
    _init_git_project(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)
    (tmp_path / "tracked.txt").write_text("changed-after-finish\n", encoding="utf-8")

    payload = _invoke_json(
        ["validate", "start", "--task", task_id], cwd=tmp_path, ok=False
    )

    assert payload["error"]["code"] == "IMPLEMENTATION_SNAPSHOT_MISMATCH"
    details = payload["error"]["details"]
    assert details["reason_code"] == "content_snapshot_mismatch"
    changed_paths = details["details"]["changed_paths"]
    assert any(item["path"] == "tracked.txt" for item in changed_paths)


def test_can_validate_and_next_action_report_snapshot_mismatch(tmp_path: Path) -> None:
    _init_git_project(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)
    (tmp_path / "tracked.txt").write_text("changed-after-finish\n", encoding="utf-8")

    can_payload = _invoke_json(["can", "validate", "--task", task_id], cwd=tmp_path)
    assert can_payload["result"]["ok"] is False
    assert can_payload["result"]["blocking"][0]["kind"] == "implementation_snapshot"
    assert (
        "implement snapshot refresh"
        in can_payload["result"]["blocking"][0]["command_hint"]
    )

    _invoke(["task", "activate", task_id], cwd=tmp_path)
    next_payload = _invoke_json(["next-action"], cwd=tmp_path)
    assert next_payload["result"]["action"] == "validate-reconcile"
    assert "implement snapshot refresh" in next_payload["result"]["next_command"]


def test_refresh_implementation_snapshot_unblocks_validation_and_logs_event(
    tmp_path: Path,
) -> None:
    _init_git_project(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)
    task = resolve_task(tmp_path, task_id)
    old_run = resolve_run(tmp_path, task.id, task.latest_implementation_run or "")
    (tmp_path / "tracked.txt").write_text("accepted-current\n", encoding="utf-8")

    refresh = _invoke_json(
        [
            "implement",
            "snapshot",
            "refresh",
            "--task",
            task_id,
            "--reason",
            "Accept current workspace",
        ],
        cwd=tmp_path,
    )
    assert refresh["result"]["next_command"] == "taskledger validate start"
    new_run = resolve_run(tmp_path, task.id, old_run.run_id)
    assert new_run.workspace_content_hash != old_run.workspace_content_hash
    events = load_events(resolve_v2_paths(tmp_path).events_dir)
    assert any(event.event == "implementation.snapshot.refreshed" for event in events)

    _invoke(["validate", "start", "--task", task_id], cwd=tmp_path)


def test_refresh_implementation_snapshot_requires_reason(tmp_path: Path) -> None:
    _init_git_project(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)

    result = _invoke(
        ["implement", "snapshot", "refresh", "--task", task_id, "--reason", ""],
        cwd=tmp_path,
        ok=False,
    )

    assert result.exit_code != 0


def test_no_git_workspace_remains_compatible(tmp_path: Path) -> None:
    _write_local_config(tmp_path)
    _invoke(["init"], cwd=tmp_path)
    _write_local_config(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)

    result = _invoke(["validate", "start", "--task", task_id], cwd=tmp_path)

    assert "started validation" in result.output

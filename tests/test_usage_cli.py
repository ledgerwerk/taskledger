from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from taskledger.api.handoff import create_handoff
from taskledger.cli import app
from taskledger.services.code_review import record_code_review
from taskledger.services.tasks import start_implementation
from taskledger.services.usage import usage_payload
from taskledger.storage.locks import read_lock, update_lock
from taskledger.storage.task_store import (
    list_handoffs,
    resolve_v2_paths,
    task_lock_path,
)
from tests.support.builders import (
    create_approved_task,
    create_implemented_task,
    init_workspace,
)


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def test_usage_works_in_empty_initialized_project(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    result = runner.invoke(app, ["--cwd", str(ws), "--no-log", "usage"])
    assert result.exit_code == 0, result.stdout
    assert "SESSION" in result.stdout
    assert "ACTIVE" in result.stdout


def test_usage_json_emits_usage_result(empty_workspace: Path) -> None:
    result = runner.invoke(
        app,
        ["--cwd", str(empty_workspace), "--no-log", "--json", "usage"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["kind"] == "usage"
    assert payload["result"]["active"] is None


def test_usage_reports_active_implementation_and_next_action(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_approved_task(ws, title="Impl task", slug="impl-task")
    start_implementation(ws, task_id)

    payload = usage_payload(ws)
    active = payload["active"]
    assert isinstance(active, dict)
    assert active["task_id"] == task_id
    assert active["stage"] == "implementing"
    assert isinstance(active["next_action"], dict)

    result = runner.invoke(app, ["--cwd", str(ws), "--no-log", "usage"])
    assert result.exit_code == 0, result.stdout
    assert task_id in result.stdout
    assert "next:" in result.stdout


def test_usage_lists_claimable_handoffs_without_claiming(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_approved_task(ws, title="Handoff task", slug="handoff-task")
    start_implementation(ws, task_id)
    create_handoff(
        ws,
        task_id,
        mode="implementation",
        intended_actor_type="agent",
        intended_harness="codex",
        summary="Ready to continue.",
        next_action="taskledger next-action",
    )

    payload = usage_payload(ws)
    handoffs = payload["inbox"]["claimable_handoffs"]
    assert len(handoffs) == 1
    assert handoffs[0]["task_id"] == task_id
    assert list_handoffs(ws, task_id)[0].status == "open"


def test_usage_does_not_mark_latest_run_review_ready_when_review_exists(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    reviewed_task = create_implemented_task(
        ws, title="Reviewed task", slug="reviewed-task"
    )
    record_code_review(
        ws,
        reviewed_task,
        result="pass",
        body="Reviewed.",
    )
    review_ready_task = create_implemented_task(
        ws, title="Needs review", slug="needs-review"
    )

    payload = usage_payload(ws)
    review_ready = payload["inbox"]["review_ready"]
    review_ready_ids = {item["task_id"] for item in review_ready}
    assert review_ready_task in review_ready_ids
    assert reviewed_task not in review_ready_ids


def test_usage_reports_expired_lock_in_inbox(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_approved_task(
        ws, title="Expired lock task", slug="expired-lock-task"
    )
    start_implementation(ws, task_id)

    paths = resolve_v2_paths(ws)
    lock_path = task_lock_path(paths, task_id)
    lock = read_lock(lock_path)
    assert lock is not None
    expired = replace(
        lock,
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    )
    update_lock(lock_path, expired)

    payload = usage_payload(ws)
    stale_locks = payload["inbox"]["stale_locks"]
    assert any(item["task_id"] == task_id for item in stale_locks)

"""Tests for expired-lock-resume next-action and implement resume path."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from taskledger.cli import app
from tests.support.builders import (
    create_approved_task,
    init_workspace,
    start_implementation,
)

runner = CliRunner()


def _json(output: str) -> dict:
    return json.loads(output)


def _expire_lock(tmp: Path, task_id: str) -> dict:
    lock_path = tmp / ".taskledger" / "checkouts" / "main" / "locks" / f"{task_id}.yaml"
    lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock_payload["expires_at"] = "2000-01-01T00:00:00+00:00"
    lock_path.write_text(
        yaml.safe_dump(lock_payload, sort_keys=False), encoding="utf-8"
    )
    return lock_payload


def _setup_impl_task(tmp: Path, slug: str) -> str:
    task_id = create_approved_task(
        tmp,
        title=slug,
        slug=slug,
        plan_text="## Goal\n\nImplement the feature.",
        criteria=("Feature works.",),
        allow_empty_todos=True,
        allow_lint_errors=True,
    )
    start_implementation(tmp, task_id)
    return task_id


# specmason: req=REQ-0034 ac=AC-0374
def test_expired_impl_lock_next_action_recommends_resume(
    tmp_path: Path,
) -> None:
    """Expired implementation lock + running run -> expired-lock-resume."""
    init_workspace(tmp_path)
    task_id = _setup_impl_task(tmp_path, "impl-task")
    _expire_lock(tmp_path, task_id)

    r = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "next-action"],
    )
    assert r.exit_code == 0, r.output
    data = _json(r.stdout)["result"]
    assert data["action"] == "expired-lock-resume", (
        f"Expected expired-lock-resume, got {data['next_item']}"
    )


# specmason: req=REQ-0034 ac=AC-0375
def test_expired_impl_lock_resume_succeeds(tmp_path: Path) -> None:
    """implement resume --repair-expired-lock succeeds after expired lock."""
    init_workspace(tmp_path)
    task_id = _setup_impl_task(tmp_path, "impl-task2")
    _expire_lock(tmp_path, task_id)

    r = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "implement",
            "resume",
            "--reason",
            "Continue after expired lock.",
            "--repair-expired-lock",
        ],
    )
    assert r.exit_code == 0, r.output


# specmason: req=REQ-0034 ac=AC-0376
def test_expired_planning_lock_still_routes_to_repair(tmp_path: Path) -> None:
    """Expired planning lock should still route to repair-lock."""
    init_workspace(tmp_path)
    # Just create + activate + plan start (no plan upsert/approve)
    r = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "create", "pt", "--slug", "pt"],
    )
    assert r.exit_code == 0
    r = runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", "pt"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"])
    assert r.exit_code == 0

    _expire_lock(tmp_path, "task-0001")

    r = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "next-action"],
    )
    assert r.exit_code == 0, r.output
    data = _json(r.stdout)["result"]
    assert data["action"] == "repair-lock", (
        f"Expected repair-lock for expired planning lock, got {data['next_item']}"
    )

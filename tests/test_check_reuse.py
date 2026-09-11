from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.domain.check import ImplementationCheckRecord
from taskledger.domain.models import TaskRecord, TaskRunRecord
from taskledger.services.check_reuse import (
    evaluate_implementation_check_reuse,
    plan_command_matches_check,
)
from taskledger.services.workspace_snapshot import WorkspaceContentSnapshot


@pytest.fixture
def task() -> TaskRecord:
    return TaskRecord("task-0001", "reuse", "Reuse checks", "")


@pytest.fixture
def workspace_snapshot() -> WorkspaceContentSnapshot:
    return WorkspaceContentSnapshot(
        git_commit="commit-1",
        dirty=True,
        content_hash="sha256:content",
        paths_hash="sha256:paths",
        entry_count=1,
        entries=(),
        captured_at=None,
    )


def _run() -> TaskRunRecord:
    return TaskRunRecord(
        run_id="run-0001",
        task_id="task-0001",
        run_type="implementation",
        status="finished",
        workspace_git_commit="commit-1",
        workspace_content_hash="sha256:content",
        workspace_paths_hash="sha256:paths",
        workspace_entry_count=1,
        workspace_snapshot_format="worktree-content:v1",
    )


def _validation_run() -> TaskRunRecord:
    return TaskRunRecord(
        run_id="run-0002",
        task_id="task-0001",
        run_type="validation",
        based_on_implementation_run="run-0001",
    )


def _check(**changes: object) -> ImplementationCheckRecord:
    values: dict[str, object] = {
        "check_id": "check-0001",
        "task_id": "task-0001",
        "implementation_run": "run-0001",
        "timestamp": "2025-01-01T00:00:00Z",
        "command": "python -m pytest",
        "argv": ("python", "-m", "pytest"),
        "exit_code": 0,
        "status": "passed",
        "cwd": "/workspace",
        "workspace_git_commit": "commit-1",
        "workspace_content_hash": "sha256:content",
        "workspace_paths_hash": "sha256:paths",
        "workspace_entry_count": 1,
        "workspace_snapshot_format": "worktree-content:v1",
    }
    values.update(changes)
    return ImplementationCheckRecord(**values)  # type: ignore[arg-type]


def test_reuse_is_eligible_for_exact_current_snapshot(
    tmp_path: Path,
    task: TaskRecord,
    workspace_snapshot: WorkspaceContentSnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "taskledger.services.check_reuse.resolve_run", lambda *_args: _run()
    )

    evaluation = evaluate_implementation_check_reuse(
        tmp_path,
        task,
        _validation_run(),
        _check(),
        current_state=workspace_snapshot,
    )

    assert evaluation.eligible is True
    assert evaluation.reason_code == "eligible"
    assert evaluation.snapshot_match is True
    assert evaluation.current_workspace_match is True


def test_reuse_rejects_current_workspace_change(
    tmp_path: Path,
    task: TaskRecord,
    workspace_snapshot: WorkspaceContentSnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "taskledger.services.check_reuse.resolve_run", lambda *_args: _run()
    )
    changed = WorkspaceContentSnapshot(
        git_commit="commit-1",
        dirty=True,
        content_hash="sha256:changed",
        paths_hash="sha256:paths",
        entry_count=1,
        entries=(),
        captured_at=None,
    )

    evaluation = evaluate_implementation_check_reuse(
        tmp_path,
        task,
        _validation_run(),
        _check(),
        current_state=changed,
    )

    assert evaluation.eligible is False
    assert evaluation.reason_code == "implementation_snapshot_stale"
    assert workspace_snapshot.content_hash != changed.content_hash


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"status": "failed", "exit_code": 1}, "check_not_passed"),
        ({"workspace_content_hash": None}, "missing_check_snapshot"),
        ({"workspace_content_hash": "sha256:other"}, "check_content_mismatch"),
    ],
)
def test_reuse_rejects_invalid_checks(
    tmp_path: Path,
    task: TaskRecord,
    workspace_snapshot: WorkspaceContentSnapshot,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
    reason_code: str,
) -> None:
    monkeypatch.setattr(
        "taskledger.services.check_reuse.resolve_run", lambda *_args: _run()
    )

    evaluation = evaluate_implementation_check_reuse(
        tmp_path,
        task,
        _validation_run(),
        _check(**changes),
        current_state=workspace_snapshot,
    )

    assert evaluation.eligible is False
    assert evaluation.reason_code == reason_code


def test_reuse_rejects_wrong_run_and_incompatible_format(
    tmp_path: Path,
    task: TaskRecord,
    workspace_snapshot: WorkspaceContentSnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "taskledger.services.check_reuse.resolve_run", lambda *_args: _run()
    )
    wrong_run = evaluate_implementation_check_reuse(
        tmp_path,
        task,
        _validation_run(),
        _check(implementation_run="run-old"),
        current_state=workspace_snapshot,
    )
    assert wrong_run.reason_code == "wrong_implementation_run"

    format_mismatch = evaluate_implementation_check_reuse(
        tmp_path,
        task,
        _validation_run(),
        _check(workspace_snapshot_format="worktree-content:v2"),
        current_state=workspace_snapshot,
    )
    assert format_mismatch.reason_code == "snapshot_format_mismatch"


def test_legacy_implementation_snapshot_is_not_reusable(
    tmp_path: Path,
    task: TaskRecord,
    workspace_snapshot: WorkspaceContentSnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_run = TaskRunRecord(
        run_id="run-0001",
        task_id=task.id,
        run_type="implementation",
        status="finished",
    )
    monkeypatch.setattr(
        "taskledger.services.check_reuse.resolve_run", lambda *_args: legacy_run
    )
    evaluation = evaluate_implementation_check_reuse(
        tmp_path,
        task,
        _validation_run(),
        _check(),
        current_state=workspace_snapshot,
    )
    assert evaluation.reason_code == "legacy_snapshot_not_reusable"


def test_plan_command_matching_requires_exact_argv_and_root_cwd(
    tmp_path: Path,
) -> None:
    check = _check(cwd=str(tmp_path.resolve()))

    assert plan_command_matches_check(tmp_path, "python -m pytest", check)
    assert not plan_command_matches_check(tmp_path, "python -m pytest -q", check)
    assert not plan_command_matches_check(tmp_path, "python3 -m pytest", check)
    assert not plan_command_matches_check(
        tmp_path, "python -m pytest", _check(cwd=str(tmp_path / "nested"))
    )

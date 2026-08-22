from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.api.handoff import create_handoff, create_review_handoff
from taskledger.cli import app
from taskledger.domain.models import ActorRef, CodeReviewRecord, HarnessRef
from taskledger.errors import LaunchError
from taskledger.services.code_review import (
    list_code_review_records,
    record_code_review,
    show_code_review,
)
from taskledger.services.handoff_lifecycle import claim_handoff
from taskledger.services.navigation import next_action_for_task
from taskledger.services.tasks import archive_task, create_task, start_implementation
from taskledger.storage.task_store import (
    code_review_markdown_path,
    list_code_reviews,
    resolve_code_review,
    resolve_lock,
    resolve_task,
    resolve_v2_paths,
    save_code_review,
)
from tests.support.builders import (
    create_approved_task,
    create_done_task,
    create_implemented_task,
    init_workspace,
)

pytestmark = [
    pytest.mark.cli,
    pytest.mark.integration,
    pytest.mark.git,
    pytest.mark.slow,
]


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _git_required() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required for this test")


def _run(argv: list[str], cwd: Path) -> None:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _invoke(cwd: Path, args: list[str]) -> object:
    result = runner.invoke(app, ["--cwd", str(cwd), *args])
    assert result.exit_code == 0, result.stdout
    return result


# specmason: req=REQ-0009 ac=AC-0096
def test_code_review_record_round_trip() -> None:
    item = CodeReviewRecord(
        review_id="review-0001",
        task_id="task-0001",
        implementation_run="run-0001",
        result="pass",
        source="working_tree",
        body="Review summary",
        summary="Review summary",
        worker_step_id="code-review",
        git_branch="main",
        git_changed_paths=("taskledger/services/tasks.py",),
    )
    loaded = CodeReviewRecord.from_dict(item.to_dict())
    assert loaded.review_id == "review-0001"
    assert loaded.result == "pass"
    assert loaded.source == "working_tree"
    assert loaded.git_changed_paths == ("taskledger/services/tasks.py",)


# specmason: req=REQ-0009 ac=AC-0096
def test_code_review_record_rejects_invalid_result_and_source() -> None:
    payload = CodeReviewRecord(
        review_id="review-0001",
        task_id="task-0001",
        implementation_run="run-0001",
        body="ok",
    ).to_dict()
    payload["result"] = "unknown"
    with pytest.raises(LaunchError, match="Unsupported code review result"):
        CodeReviewRecord.from_dict(payload)
    payload["result"] = "pass"
    payload["source"] = "other"
    with pytest.raises(LaunchError, match="Unsupported code review source"):
        CodeReviewRecord.from_dict(payload)


# specmason: req=REQ-0009 ac=AC-0101
def test_storage_save_list_resolve_code_reviews(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    review = CodeReviewRecord(
        review_id="review-0001",
        task_id="task-0001",
        implementation_run="run-0001",
        result="pass",
        body="stored",
    )
    save_code_review(ws, review)
    paths = resolve_v2_paths(ws)
    assert code_review_markdown_path(paths, "task-0001", "review-0001").exists()
    listed = list_code_reviews(ws, "task-0001")
    assert [item.review_id for item in listed] == ["review-0001"]
    resolved = resolve_code_review(ws, "task-0001", "review-1")
    assert resolved.review_id == "review-0001"


# specmason: req=REQ-0009 ac=AC-0097
def test_service_records_and_lists_manual_review(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)

    review = record_code_review(
        ws,
        task_id,
        result="pass",
        body="No blocking issues.",
    )
    assert review.review_id == "review-0001"
    assert review.source == "manual"
    listed = list_code_review_records(ws, task_id)
    assert len(listed) == 1
    shown = show_code_review(ws, task_id, "review-0001")
    assert shown.body == "No blocking issues."


# specmason: req=REQ-0009 ac=AC-0099
def test_service_records_review_after_task_is_done(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_done_task(ws, allow_lint_errors=True)

    review = record_code_review(
        ws,
        task_id,
        result="pass",
        body="Post-completion code review.",
    )

    assert review.review_id == "review-0001"
    assert review.implementation_run is not None
    shown = show_code_review(ws, task_id, "review-1")
    assert shown.body == "Post-completion code review."


# specmason: req=REQ-0009 ac=AC-0099
def test_service_rejects_review_record_outside_allowed_stages(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(
        ws,
        title="No implementation",
        slug="no-implementation",
        description="No implementation run.",
    )
    with pytest.raises(LaunchError, match="recorded only during implementing"):
        record_code_review(ws, task.id, result="blocked", body="missing run")


# specmason: req=REQ-0009 ac=AC-0099
def test_service_rejects_archived_task(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    archive_task(ws, task_id, reason="archive for test", force=True)
    with pytest.raises(LaunchError, match="archived task"):
        record_code_review(ws, task_id, result="pass", body="archived")


# specmason: req=REQ-0009 ac=AC-0100
def test_service_records_working_tree_git_metadata(tmp_path: Path) -> None:
    _git_required()
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    _run(["git", "init"], ws)
    _run(["git", "config", "user.email", "test@example.com"], ws)
    _run(["git", "config", "user.name", "Test User"], ws)
    sample = ws / "sample.txt"
    sample.write_text("one\n", encoding="utf-8")
    _run(["git", "add", "sample.txt"], ws)
    _run(["git", "commit", "-m", "base"], ws)
    sample.write_text("one\ntwo\n", encoding="utf-8")

    review = record_code_review(
        ws,
        task_id,
        result="pass",
        body="working tree",
        from_git=True,
    )
    assert review.source == "working_tree"
    assert review.git_status_short is not None
    assert "sample.txt" in (review.git_status_short or "")
    assert review.git_diff_hash is not None
    assert review.git_diff_hash.startswith("sha256:")
    assert "sample.txt" in review.git_changed_paths


# specmason: req=REQ-0009 ac=AC-0098
def test_service_records_commit_git_metadata(tmp_path: Path) -> None:
    _git_required()
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    _run(["git", "init"], ws)
    _run(["git", "config", "user.email", "test@example.com"], ws)
    _run(["git", "config", "user.name", "Test User"], ws)
    sample = ws / "sample.txt"
    sample.write_text("commit target\n", encoding="utf-8")
    _run(["git", "add", "sample.txt"], ws)
    _run(["git", "commit", "-m", "target"], ws)

    review = record_code_review(
        ws,
        task_id,
        result="pass",
        body="commit review",
        commit="HEAD",
    )
    assert review.source == "commit"
    assert review.git_commit is not None
    assert len(review.git_commit) >= 40
    assert "sample.txt" in review.git_changed_paths


# specmason: req=REQ-0009 ac=AC-0094
def test_cli_review_record_list_show_and_json(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)

    _invoke(
        ws,
        [
            "review",
            "record",
            "--task",
            task_id,
            "--result",
            "pass",
            "--summary",
            "Looks good.",
        ],
    )
    list_result = _invoke(ws, ["review", "list", "--task", task_id])
    assert "review-0001" in list_result.stdout
    show_result = _invoke(ws, ["review", "show", "review-0001", "--task", task_id])
    assert "Looks good." in show_result.stdout

    json_result = _invoke(
        ws,
        [
            "--json",
            "review",
            "record",
            "--task",
            task_id,
            "--result",
            "blocked",
            "--summary",
            "Need more evidence.",
        ],
    )
    payload = json.loads(json_result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["kind"] == "code_review_recorded"
    assert payload["result"]["review_id"] == "review-0002"


# specmason: req=REQ-0009 ac=AC-0095
def test_cli_review_record_summary_and_file_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    summary_path = ws / "review.md"
    summary_path.write_text("From file\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws),
            "review",
            "record",
            "--task",
            task_id,
            "--result",
            "pass",
            "--summary",
            "inline",
            "--summary-file",
            str(summary_path),
        ],
    )
    assert result.exit_code != 0
    stderr = result.stderr or result.output
    assert "Use either --summary or --summary-file" in stderr


def test_review_handoff_is_run_scoped_and_recording_derives_run(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    task = resolve_task(ws, task_id)
    handoff = create_review_handoff(
        ws,
        task_id,
        run_id=task.latest_implementation_run,
        kind="code",
        intended_harness="pi",
    )
    assert handoff["mode"] == "review"
    assert handoff["context_for"] == "code-reviewer"
    assert handoff["scope"] == "run"
    actor = ActorRef(
        actor_type="agent",
        actor_name="pi-reviewer",
        role="reviewer",
        session_id="pi-session",
    )
    harness = HarnessRef(
        harness_id="h-pi", name="pi", kind="agent_harness", session_id="pi-session"
    )
    claim_handoff(ws, task_id, str(handoff["handoff_id"]), actor=actor, harness=harness)
    review = record_code_review(
        ws,
        task_id,
        result="fail",
        body="Found a blocking issue.",
        handoff_id=str(handoff["handoff_id"]),
        actor=actor,
        harness=harness,
    )
    assert review.handoff_id == handoff["handoff_id"]
    assert review.implementation_run == task.latest_implementation_run
    assert review.reviewer == actor
    assert review.harness == harness


def test_review_handoff_coexists_with_implementation_lock_and_navigation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Override CI auto-detection so persisted identity is used.
    monkeypatch.setenv("TASKLEDGER_ACTOR_TYPE", "agent")
    monkeypatch.setenv("TASKLEDGER_ACTOR_NAME", "pi-reviewer")
    monkeypatch.setenv("TASKLEDGER_ACTOR_ROLE", "reviewer")
    monkeypatch.setenv("TASKLEDGER_HARNESS", "pi")
    monkeypatch.setenv("TASKLEDGER_SESSION_ID", "pi-session")
    ws = init_workspace(tmp_path)
    task_id = create_approved_task(ws, allow_lint_errors=True)
    start_implementation(ws, task_id)
    task = resolve_task(ws, task_id)
    handoff = create_review_handoff(
        ws,
        task_id,
        run_id=task.latest_implementation_run,
        kind="general",
        intended_harness="pi",
    )
    actor = ActorRef(
        actor_type="agent",
        actor_name="pi-reviewer",
        role="reviewer",
        session_id="pi-session",
    )
    harness = HarnessRef(
        harness_id="h-pi", name="pi", kind="agent_harness", session_id="pi-session"
    )
    claim_handoff(ws, task_id, str(handoff["handoff_id"]), actor=actor, harness=harness)
    from taskledger.domain.models import ActiveActorState, ActiveHarnessState
    from taskledger.storage.task_store import save_actor_state, save_harness_state

    save_actor_state(
        ws,
        ActiveActorState(
            actor_type="agent",
            actor_name="pi-reviewer",
            role="reviewer",
            tool="pi",
            session_id="pi-session",
        ),
    )
    save_harness_state(
        ws, ActiveHarnessState(name="pi", kind="agent_harness", session_id="pi-session")
    )
    next_payload = next_action_for_task(ws, resolve_task(ws, task_id))
    assert next_payload["action"] == "review-work"
    assert next_payload["next_item"]["handoff_id"] == handoff["handoff_id"]
    lock = resolve_lock(ws, task_id)
    assert lock is not None
    assert lock.run_id == task.latest_implementation_run
    review = record_code_review(
        ws,
        task_id,
        result="pass",
        body="Read-only review complete.",
        handoff_id=str(handoff["handoff_id"]),
        actor=actor,
        harness=harness,
    )
    assert review.handoff_id == handoff["handoff_id"]
    assert resolve_lock(ws, task_id) is not None


def test_implementation_handoff_cannot_be_review_evidence(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    task = resolve_task(ws, task_id)
    handoff = create_handoff(
        ws, task_id, mode="implementation", focus_run_id=task.latest_implementation_run
    )
    actor = ActorRef(
        actor_type="agent", actor_name="reviewer", role="reviewer", session_id="s"
    )
    harness = HarnessRef(
        harness_id="h", name="pi", kind="agent_harness", session_id="s"
    )
    claim_handoff(ws, task_id, str(handoff["handoff_id"]), actor=actor, harness=harness)
    with pytest.raises(
        LaunchError, match="cannot be used as independent review evidence"
    ):
        record_code_review(
            ws,
            task_id,
            result="fail",
            body="wrong mode",
            handoff_id=str(handoff["handoff_id"]),
            actor=actor,
            harness=harness,
        )


def test_cli_review_handoff_convenience_exposes_run_scoped_review(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    result = _invoke(
        ws,
        [
            "handoff",
            "review",
            "--task",
            task_id,
            "--kind",
            "code",
            "--intended-harness",
            "pi",
        ],
    )
    assert "created review handoff" in result.stdout
    assert f"run={resolve_task(ws, task_id).latest_implementation_run}" in result.stdout


def test_review_handoff_records_snapshot_drift(tmp_path: Path) -> None:
    _git_required()
    ws = init_workspace(tmp_path)
    task_id = create_implemented_task(ws, allow_lint_errors=True)
    _run(["git", "init"], ws)
    _run(["git", "config", "user.email", "test@example.com"], ws)
    _run(["git", "config", "user.name", "Test User"], ws)
    sample = ws / "sample.txt"
    sample.write_text("before\n", encoding="utf-8")
    _run(["git", "add", "sample.txt"], ws)
    _run(["git", "commit", "-m", "base"], ws)
    task = resolve_task(ws, task_id)
    handoff = create_review_handoff(
        ws, task_id, run_id=task.latest_implementation_run, kind="code"
    )
    actor = ActorRef(
        actor_type="agent", actor_name="reviewer", role="reviewer", session_id="s"
    )
    harness = HarnessRef(
        harness_id="h", name="pi", kind="agent_harness", session_id="s"
    )
    claim_handoff(ws, task_id, str(handoff["handoff_id"]), actor=actor, harness=harness)
    sample.write_text("after\n", encoding="utf-8")
    review = record_code_review(
        ws,
        task_id,
        result="blocked",
        body="Snapshot changed.",
        from_git=True,
        handoff_id=str(handoff["handoff_id"]),
        actor=actor,
        harness=harness,
    )
    assert review.snapshot_drift is True

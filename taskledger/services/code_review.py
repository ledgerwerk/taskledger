from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import cast

from taskledger.domain.models import ActorRef, CodeReviewRecord, HarnessRef
from taskledger.domain.review import ReviewResult, ReviewSource
from taskledger.domain.states import (
    EXIT_CODE_BAD_INPUT,
    EXIT_CODE_INVALID_TRANSITION,
    EXIT_CODE_MISSING,
)
from taskledger.errors import LaunchError
from taskledger.ids import next_project_id
from taskledger.services import command_runner
from taskledger.services import tasks as _tasks
from taskledger.services.worker_pipeline import resolve_worker_pipeline_step
from taskledger.storage.task_store import (
    list_code_reviews,
    resolve_code_review,
    resolve_handoff,
    resolve_run,
    resolve_task,
    save_code_review,
    save_task,
)
from taskledger.timeutils import utc_now_iso

ALLOWED_REVIEW_STAGES = frozenset(
    {"implementing", "implemented", "validating", "failed_validation", "done"}
)
ALLOWED_WORKER_REVIEW_CONTEXTS = frozenset(
    {"code-reviewer", "reviewer", "spec-reviewer"}
)


def record_code_review(
    workspace_root: Path,
    task_ref: str,
    *,
    result: str,
    body: str,
    summary: str | None = None,
    from_git: bool = False,
    commit: str | None = None,
    run_id: str | None = None,
    worker_step_id: str | None = None,
    handoff_id: str | None = None,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> CodeReviewRecord:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="record code review on")
    if task.status_stage not in ALLOWED_REVIEW_STAGES:
        raise _tasks._cli_error(
            "Code review can be recorded only during implementing, implemented, "
            "validating, failed_validation, or done stages.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    if not body.strip():
        raise _tasks._cli_error(
            "Code review summary must not be empty.", EXIT_CODE_BAD_INPUT
        )

    handoff = None
    if handoff_id:
        handoff = resolve_handoff(workspace_root, task.id, handoff_id)
        if (
            handoff.mode != "review"
            or handoff.context_for not in ALLOWED_WORKER_REVIEW_CONTEXTS
        ):
            raise _tasks._cli_error(
                f"{handoff.handoff_id} is an {handoff.mode} handoff (context_for={handoff.context_for or 'none'}). "  # noqa: E501
                "It cannot be used as independent review evidence. Create a review handoff with "  # noqa: E501
                "taskledger handoff create --mode review --for code-reviewer --run RUN_ID.",  # noqa: E501
                EXIT_CODE_INVALID_TRANSITION,
            )
        if handoff.status != "claimed":
            raise _tasks._cli_error(
                f"Review handoff {handoff.handoff_id} must be claimed before recording review evidence.",  # noqa: E501
                EXIT_CODE_INVALID_TRANSITION,
            )
        if worker_step_id is None:
            worker_step_id = handoff.worker_step_id

    effective_run_id = (
        (handoff.focus_run_id if handoff is not None else None)
        or run_id
        or task.latest_implementation_run
    )
    if effective_run_id is None:
        raise _tasks._cli_error(
            "Task does not have an implementation run to attach review evidence.",
            EXIT_CODE_MISSING,
        )
    if handoff is not None and run_id is not None and run_id != handoff.focus_run_id:
        raise _tasks._cli_error(
            f"Review handoff {handoff.handoff_id} is focused on {handoff.focus_run_id}, not {run_id}.",  # noqa: E501
            EXIT_CODE_BAD_INPUT,
        )
    run = resolve_run(workspace_root, task.id, effective_run_id)
    if run.run_type != "implementation":
        raise _tasks._cli_error(
            f"Run {run.run_id} is {run.run_type}, not implementation.",
            EXIT_CODE_INVALID_TRANSITION,
        )

    normalized_result = _normalize_review_result(result)
    source = _resolve_review_source(from_git=from_git, commit=commit)

    if worker_step_id:
        _validate_worker_step(workspace_root, worker_step_id)
    if handoff is not None:
        _validate_handoff(
            workspace_root,
            task_id=task.id,
            handoff_id=handoff.handoff_id,
            worker_step_id=worker_step_id,
            actor=actor,
            harness=harness,
            effective_run_id=run.run_id,
        )

    git_metadata = _resolve_git_metadata(
        workspace_root,
        source=source,
        commit=commit,
    )
    snapshot_drift = None
    if handoff is not None and handoff.git_diff_hash:
        try:
            current_snapshot = _collect_working_tree_metadata(workspace_root)
        except LaunchError:
            current_snapshot = {}
        current_hash = current_snapshot.get("git_diff_hash")
        if isinstance(current_hash, str):
            snapshot_drift = current_hash != handoff.git_diff_hash

    review = CodeReviewRecord(
        review_id=next_project_id(
            "review",
            [item.review_id for item in list_code_reviews(workspace_root, task.id)],
        ),
        task_id=task.id,
        implementation_run=run.run_id,
        reviewed_at=utc_now_iso(),
        result=normalized_result,
        source=source,
        body=body.strip(),
        summary=_normalize_summary(summary, body),
        reviewer=actor if actor is not None else _tasks._default_actor(),
        harness=harness if harness is not None else _tasks._default_harness(),
        worker_step_id=worker_step_id,
        handoff_id=handoff_id,
        snapshot_drift=snapshot_drift,
        git_branch=_optional_string(git_metadata.get("git_branch")),
        git_commit=_optional_string(git_metadata.get("git_commit")),
        git_status_short=_optional_string(git_metadata.get("git_status_short")),
        git_diff_stat=_optional_string(git_metadata.get("git_diff_stat")),
        git_staged_diff_stat=_optional_string(git_metadata.get("git_staged_diff_stat")),
        git_changed_paths=_string_tuple(git_metadata.get("git_changed_paths")),
        git_diff_hash=_optional_string(git_metadata.get("git_diff_hash")),
    )
    save_code_review(workspace_root, review)
    save_task(workspace_root, replace(task, updated_at=utc_now_iso()))
    _tasks._append_event(
        workspace_root,
        task.id,
        "code_review.recorded",
        {
            "review_id": review.review_id,
            "result": review.result,
            "source": review.source,
            "worker_step_id": review.worker_step_id,
            "git_commit": review.git_commit,
        },
    )
    return review


def list_code_review_records(
    workspace_root: Path, task_ref: str
) -> list[CodeReviewRecord]:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="list code reviews on")
    return list_code_reviews(workspace_root, task.id)


def show_code_review(
    workspace_root: Path,
    task_ref: str,
    review_ref: str,
) -> CodeReviewRecord:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="show code review on")
    return resolve_code_review(workspace_root, task.id, review_ref)


def _normalize_review_result(value: str) -> ReviewResult:
    normalized = value.strip().lower()
    if normalized not in {"pass", "fail", "blocked"}:
        raise _tasks._cli_error(
            f"Unsupported code review result: {value}",
            EXIT_CODE_BAD_INPUT,
        )
    return cast(ReviewResult, normalized)


def _resolve_review_source(*, from_git: bool, commit: str | None) -> ReviewSource:
    if commit is not None and not commit.strip():
        raise _tasks._cli_error("Git commit must not be empty.", EXIT_CODE_BAD_INPUT)
    if commit is not None:
        return "commit"
    if from_git:
        return "working_tree"
    return "manual"


def _validate_worker_step(workspace_root: Path, worker_step_id: str) -> None:
    _, step = resolve_worker_pipeline_step(workspace_root, worker_step_id)
    if step.lifecycle_stage != "review":
        raise _tasks._cli_error(
            f"Worker step {worker_step_id} is {step.lifecycle_stage}, not review.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    if step.base_context not in ALLOWED_WORKER_REVIEW_CONTEXTS:
        raise _tasks._cli_error(
            f"Worker step {worker_step_id} uses unsupported review context "
            f"{step.base_context}.",
            EXIT_CODE_BAD_INPUT,
        )


def _validate_handoff(
    workspace_root: Path,
    *,
    task_id: str,
    handoff_id: str,
    worker_step_id: str | None,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    effective_run_id: str | None = None,
) -> None:
    handoff = resolve_handoff(workspace_root, task_id, handoff_id)
    if (
        handoff.mode != "review"
        or handoff.context_for not in ALLOWED_WORKER_REVIEW_CONTEXTS
    ):
        raise _tasks._cli_error(
            f"{handoff.handoff_id} is not a claimed review handoff; use --mode review.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    if handoff.status != "claimed":
        raise _tasks._cli_error(
            f"Review handoff {handoff.handoff_id} is {handoff.status}; claim it before recording review evidence.",  # noqa: E501
            EXIT_CODE_INVALID_TRANSITION,
        )
    if (
        handoff.focus_run_id
        and effective_run_id
        and handoff.focus_run_id != effective_run_id
    ):
        raise _tasks._cli_error(
            f"Review handoff {handoff.handoff_id} is focused on {handoff.focus_run_id}, not {effective_run_id}.",  # noqa: E501
            EXIT_CODE_BAD_INPUT,
        )
    if (
        actor is not None
        and handoff.claimed_by is not None
        and (
            (actor.actor_type, actor.actor_name, actor.session_id)
            != (
                handoff.claimed_by.actor_type,
                handoff.claimed_by.actor_name,
                handoff.claimed_by.session_id,
            )
        )
    ):
        raise _tasks._cli_error(
            f"Review handoff {handoff.handoff_id} is claimed by {handoff.claimed_by.actor_name} in session {handoff.claimed_by.session_id}; reviewer identity does not match.",  # noqa: E501
            EXIT_CODE_BAD_INPUT,
        )
    if (
        harness is not None
        and handoff.claimed_in_harness is not None
        and (
            (harness.name, harness.session_id)
            != (
                handoff.claimed_in_harness.name,
                handoff.claimed_in_harness.session_id,
            )
        )
    ):
        raise _tasks._cli_error(
            f"Review handoff {handoff.handoff_id} is claimed in harness {handoff.claimed_in_harness.name}/{handoff.claimed_in_harness.session_id}; reviewer harness does not match.",  # noqa: E501
            EXIT_CODE_BAD_INPUT,
        )

    if handoff.task_id != task_id:
        raise _tasks._cli_error(
            f"Handoff {handoff_id} belongs to {handoff.task_id}, not {task_id}.",
            EXIT_CODE_BAD_INPUT,
        )
    if (
        worker_step_id is not None
        and handoff.worker_step_id is not None
        and handoff.worker_step_id != worker_step_id
    ):
        raise _tasks._cli_error(
            f"Handoff {handoff_id} is bound to worker step "
            f"{handoff.worker_step_id}, not {worker_step_id}.",
            EXIT_CODE_BAD_INPUT,
        )


def _resolve_git_metadata(
    workspace_root: Path,
    *,
    source: str,
    commit: str | None,
) -> dict[str, object]:
    if source == "manual":
        return {}
    if source == "working_tree":
        return _collect_working_tree_metadata(workspace_root)
    if source == "commit":
        if commit is None:
            raise LaunchError("Internal error: commit source missing commit ref.")
        return _collect_commit_metadata(workspace_root, commit)
    raise LaunchError(f"Unsupported code review source: {source}")


def _collect_working_tree_metadata(workspace_root: Path) -> dict[str, object]:
    _ensure_git_workspace(workspace_root)
    head = _git_text(workspace_root, ("git", "rev-parse", "HEAD")).strip()
    branch = _git_text(workspace_root, ("git", "branch", "--show-current")).strip()
    status = _git_text(workspace_root, ("git", "status", "--short")).strip()
    diff_stat = _git_text(workspace_root, ("git", "diff", "--stat")).strip()
    staged_diff_stat = _git_text(
        workspace_root, ("git", "diff", "--cached", "--stat")
    ).strip()
    unstaged_paths = _git_text(
        workspace_root, ("git", "diff", "--name-only")
    ).splitlines()
    staged_paths = _git_text(
        workspace_root, ("git", "diff", "--cached", "--name-only")
    ).splitlines()
    unstaged_binary = _git_text(workspace_root, ("git", "diff", "--binary"))
    staged_binary = _git_text(workspace_root, ("git", "diff", "--cached", "--binary"))
    changed_paths = _dedupe_preserving_order([*unstaged_paths, *staged_paths])
    digest = sha256(
        (unstaged_binary + "\n---STAGED---\n" + staged_binary).encode("utf-8")
    ).hexdigest()
    return {
        "git_head": head or None,
        "git_branch": branch or "(detached)",
        "git_status_short": status or None,
        "git_diff_stat": diff_stat or None,
        "git_staged_diff_stat": staged_diff_stat or None,
        "git_changed_paths": tuple(changed_paths),
        "git_diff_hash": f"sha256:{digest}",
    }


def _collect_commit_metadata(workspace_root: Path, commit: str) -> dict[str, object]:
    _ensure_git_workspace(workspace_root)
    resolved = _git_text(
        workspace_root,
        ("git", "rev-parse", "--verify", f"{commit}^{{commit}}"),
        not_found_message=f"Git commit not found: {commit}",
    ).strip()
    if not resolved:
        raise LaunchError(f"Git commit not found: {commit}")
    show_output = _git_text(
        workspace_root,
        (
            "git",
            "show",
            "--stat",
            "--format=fuller",
            "--no-ext-diff",
            "--no-color",
            resolved,
        ),
    ).strip()
    changed_paths = _git_text(
        workspace_root,
        ("git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", resolved),
    ).splitlines()
    branch = _git_text(workspace_root, ("git", "branch", "--show-current")).strip()
    return {
        "git_branch": branch or "(detached)",
        "git_commit": resolved,
        "git_diff_stat": show_output or None,
        "git_changed_paths": tuple(_dedupe_preserving_order(changed_paths)),
        "git_diff_hash": f"sha256:{sha256(show_output.encode('utf-8')).hexdigest()}",
    }


def _ensure_git_workspace(workspace_root: Path) -> None:
    result = command_runner.run_command(
        ("git", "rev-parse", "--is-inside-work-tree"),
        cwd=workspace_root,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise LaunchError("Code review git source requires a Git workspace.")


def _git_text(
    workspace_root: Path,
    argv: tuple[str, ...],
    *,
    not_found_message: str | None = None,
) -> str:
    result = command_runner.run_command(argv, cwd=workspace_root)
    if result.returncode == 0:
        return result.stdout
    if not_found_message is not None:
        raise LaunchError(not_found_message)
    raise LaunchError("Code review git source requires a Git workspace.")


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        stripped = item.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result


def _normalize_summary(summary: str | None, body: str) -> str | None:
    if summary is not None and summary.strip():
        return _tasks._summary_line(summary.strip())
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if not first_line:
        return None
    return _tasks._summary_line(first_line)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))

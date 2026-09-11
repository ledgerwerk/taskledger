"""Eligibility checks for reusing implementation command evidence."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from taskledger.domain.check import ImplementationCheckRecord
from taskledger.domain.models import TaskRecord, TaskRunRecord
from taskledger.services.workspace_snapshot import (
    SNAPSHOT_FORMAT,
    WorkspaceContentSnapshot,
    capture_workspace_content_snapshot,
)
from taskledger.storage.task_store import list_checks, resolve_run


@dataclass(frozen=True, slots=True)
class CheckReuseEvaluation:
    eligible: bool
    reason_code: str
    message: str
    check_id: str
    command: str
    implementation_run: str
    snapshot_match: bool
    current_workspace_match: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reason_code": self.reason_code,
            "message": self.message,
            "check_id": self.check_id,
            "command": self.command,
            "implementation_run": self.implementation_run,
            "snapshot_match": self.snapshot_match,
            "current_workspace_match": self.current_workspace_match,
        }


def _evaluation(
    check: ImplementationCheckRecord,
    *,
    eligible: bool = False,
    reason_code: str,
    message: str,
    snapshot_match: bool = False,
    current_workspace_match: bool = False,
) -> CheckReuseEvaluation:
    return CheckReuseEvaluation(
        eligible=eligible,
        reason_code=reason_code,
        message=message,
        check_id=check.check_id,
        command=check.command,
        implementation_run=check.implementation_run,
        snapshot_match=snapshot_match,
        current_workspace_match=current_workspace_match,
    )


def _has_check_snapshot(check: ImplementationCheckRecord) -> bool:
    return all(
        value is not None
        for value in (
            check.cwd,
            check.workspace_git_commit,
            check.workspace_content_hash,
            check.workspace_paths_hash,
            check.workspace_entry_count,
            check.workspace_snapshot_format,
        )
    )


def _has_implementation_snapshot(run: TaskRunRecord) -> bool:
    return all(
        value is not None
        for value in (
            run.workspace_git_commit,
            run.workspace_content_hash,
            run.workspace_paths_hash,
            run.workspace_entry_count,
            run.workspace_snapshot_format,
        )
    )


def _check_matches_run(
    check: ImplementationCheckRecord, run: TaskRunRecord
) -> tuple[bool, str]:
    if check.workspace_snapshot_format != run.workspace_snapshot_format:
        return False, "snapshot_format_mismatch"
    if check.workspace_git_commit != run.workspace_git_commit:
        return False, "check_commit_mismatch"
    if check.workspace_content_hash != run.workspace_content_hash:
        return False, "check_content_mismatch"
    if check.workspace_paths_hash != run.workspace_paths_hash:
        return False, "check_content_mismatch"
    if check.workspace_entry_count != run.workspace_entry_count:
        return False, "check_content_mismatch"
    return True, "eligible"


def _current_matches_run(current: WorkspaceContentSnapshot, run: TaskRunRecord) -> bool:
    return (
        current.git_commit == run.workspace_git_commit
        and current.content_hash == run.workspace_content_hash
        and current.paths_hash == run.workspace_paths_hash
        and current.entry_count == run.workspace_entry_count
        and SNAPSHOT_FORMAT == run.workspace_snapshot_format
    )


def evaluate_implementation_check_reuse(
    workspace_root: Path,
    task: TaskRecord,
    validation_run: TaskRunRecord | None,
    check: ImplementationCheckRecord,
    *,
    current_state: WorkspaceContentSnapshot | None = None,
) -> CheckReuseEvaluation:
    """Evaluate whether an implementation check can be cited as evidence."""
    if check.status != "passed" or check.exit_code != 0:
        return _evaluation(
            check,
            reason_code="check_not_passed",
            message="Implementation check did not pass with exit code 0.",
        )

    if validation_run is None or validation_run.based_on_implementation_run is None:
        return _evaluation(
            check,
            reason_code="wrong_implementation_run",
            message="Validation run has no implementation snapshot baseline.",
        )

    implementation_run_id = validation_run.based_on_implementation_run
    if check.implementation_run != implementation_run_id:
        return _evaluation(
            check,
            reason_code="wrong_implementation_run",
            message="Implementation check belongs to a different implementation run.",
        )

    implementation_run = resolve_run(workspace_root, task.id, implementation_run_id)
    if not _has_check_snapshot(check):
        return _evaluation(
            check,
            reason_code="missing_check_snapshot",
            message="Implementation check has no tested-state provenance.",
        )
    if not _has_implementation_snapshot(implementation_run):
        return _evaluation(
            check,
            reason_code="legacy_snapshot_not_reusable",
            message="Implementation run has no reusable content snapshot.",
        )

    snapshot_match, reason_code = _check_matches_run(check, implementation_run)
    if not snapshot_match:
        messages = {
            "snapshot_format_mismatch": (
                "Implementation check uses an incompatible snapshot format."
            ),
            "check_commit_mismatch": (
                "Implementation check was run against a different Git commit."
            ),
            "check_content_mismatch": (
                "Check content differs from implementation snapshot."
            ),
        }
        return _evaluation(
            check,
            reason_code=reason_code,
            message=messages[reason_code],
        )

    current = current_state or capture_workspace_content_snapshot(workspace_root)
    current_workspace_match = _current_matches_run(current, implementation_run)
    if not current_workspace_match:
        return _evaluation(
            check,
            reason_code="implementation_snapshot_stale",
            message=(
                "Current workspace no longer matches the final implementation snapshot."
            ),
            snapshot_match=True,
        )

    return _evaluation(
        check,
        eligible=True,
        reason_code="eligible",
        message=(
            "Implementation check matches the final and current workspace snapshots."
        ),
        snapshot_match=True,
        current_workspace_match=True,
    )


def reusable_implementation_checks(
    workspace_root: Path,
    task: TaskRecord,
    validation_run: TaskRunRecord | None,
    *,
    current_state: WorkspaceContentSnapshot | None = None,
) -> list[CheckReuseEvaluation]:
    """Evaluate all implementation checks for a validation run."""
    return [
        evaluate_implementation_check_reuse(
            workspace_root,
            task,
            validation_run,
            check,
            current_state=current_state,
        )
        for check in list_checks(workspace_root, task.id)
    ]


def plan_command_matches_check(
    workspace_root: Path,
    plan_command: str,
    check: ImplementationCheckRecord,
) -> bool:
    """Match a root-scoped plan command to a check without fuzzy equivalence."""
    try:
        plan_argv = tuple(shlex.split(plan_command))
    except ValueError:
        return False
    return (
        plan_argv == check.argv
        and check.cwd is not None
        and Path(check.cwd).expanduser().resolve()
        == workspace_root.expanduser().resolve()
    )

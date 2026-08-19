"""Check tracking service for implementation verification commands."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from taskledger.domain.models import ImplementationCheckRecord
from taskledger.domain.policies import implementation_mutation_decision
from taskledger.ids import next_project_id
from taskledger.services import tasks as _tasks
from taskledger.storage.task_store import (
    list_checks,
    resolve_task,
    save_check,
    save_run,
    save_task,
)
from taskledger.timeutils import utc_now_iso


def add_check(
    workspace_root: Path,
    task_ref: str,
    *,
    argv: tuple[str, ...],
    command: str,
    exit_code: int | None,
    summary: str | None = None,
    category: Literal[
        "test",
        "lint",
        "format",
        "typecheck",
        "build",
        "security",
        "other",
    ] = "other",
    artifact_refs: tuple[str, ...] = (),
) -> ImplementationCheckRecord:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="record checks on")
    run = _tasks._require_running_run(
        workspace_root,
        task,
        task.latest_implementation_run,
        expected_type="implementation",
    )
    _tasks._enforce_decision(
        implementation_mutation_decision(
            task,
            _tasks._lock_for_mutation(workspace_root, task.id),
            run=run,
            action="record implementation checks",
        )
    )
    status: Literal["passed", "failed", "unknown"] = (
        "passed"
        if exit_code == 0
        else ("failed" if exit_code is not None else "unknown")
    )
    check = ImplementationCheckRecord(
        check_id=next_project_id(
            "check",
            [item.check_id for item in list_checks(workspace_root, task.id)],
        ),
        task_id=task.id,
        implementation_run=run.run_id,
        timestamp=utc_now_iso(),
        command=command,
        argv=argv,
        exit_code=exit_code,
        status=status,
        category=category,
        summary=(summary or "").strip() or None,
    )
    save_check(workspace_root, check)
    save_run(
        workspace_root,
        replace(
            run,
            check_refs=(*run.check_refs, check.check_id),
            artifact_refs=(*run.artifact_refs, *artifact_refs),
        ),
    )
    save_task(
        workspace_root,
        replace(
            task,
            updated_at=utc_now_iso(),
        ),
    )
    _tasks._append_event(
        workspace_root,
        task.id,
        "implementation.check.logged",
        {"check_id": check.check_id, "command": command},
    )
    return check


def classify_check_command(
    argv: tuple[str, ...],
) -> Literal["test", "lint", "format", "typecheck", "build", "security", "other"]:
    """Classify a verification command into a category."""
    if not argv:
        return "other"
    normalized = tuple(part.lower() for part in argv)
    if "pytest" in normalized:
        return "test"
    if (
        len(normalized) >= 3
        and normalized[:2] == ("python", "-m")
        and normalized[2] == "pytest"
    ):
        return "test"
    if normalized[0] == "ruff":
        if "format" in normalized:
            return "format"
        return "lint"
    if normalized[0] in {"mypy", "pyright", "pyre"}:
        return "typecheck"
    if normalized[0] in {"tox", "nox"}:
        return "test"
    if normalized[0] in {"npm", "pnpm", "yarn"} and "test" in normalized:
        return "test"
    return "other"

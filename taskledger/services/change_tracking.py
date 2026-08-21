"""Change tracking, command execution, run inspection, and event listing.

These functions were extracted from services/tasks.py to shrink the monolith.
tasks.py re-exports them for backward compatibility.
"""

from __future__ import annotations

import shlex
from dataclasses import replace
from pathlib import Path

from taskledger.domain.models import CodeChangeRecord
from taskledger.domain.policies import (
    implementation_mutation_decision,
    plan_command_decision,
)
from taskledger.domain.states import EXIT_CODE_BAD_INPUT, EXIT_CODE_INVALID_TRANSITION
from taskledger.ids import next_project_id
from taskledger.services import command_runner
from taskledger.services import tasks as _tasks
from taskledger.storage.events import load_events
from taskledger.storage.task_store import (
    list_changes,
    resolve_task,
    resolve_v2_paths,
    save_change,
    save_run,
    save_task,
)
from taskledger.timeutils import utc_now_iso


def add_change(
    workspace_root: Path,
    task_ref: str,
    *,
    path: str,
    kind: str,
    summary: str,
    git_commit: str | None = None,
    git_diff_stat: str | None = None,
    command: str | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    exit_code: int | None = None,
    artifact_refs: tuple[str, ...] = (),
) -> CodeChangeRecord:
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="record changes on")
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
            action="record code changes",
        )
    )
    change = CodeChangeRecord(
        change_id=next_project_id(
            "change",
            [item.change_id for item in list_changes(workspace_root, task.id)],
        ),
        task_id=task.id,
        implementation_run=run.run_id,
        timestamp=utc_now_iso(),
        kind=kind,
        path=path,
        summary=summary.strip(),
        git_commit=git_commit,
        git_diff_stat=git_diff_stat,
        command=command,
        before_hash=before_hash,
        after_hash=after_hash,
        exit_code=exit_code,
    )
    save_change(workspace_root, change)
    save_run(
        workspace_root,
        replace(
            run,
            change_refs=(*run.change_refs, change.change_id),
            artifact_refs=(*run.artifact_refs, *artifact_refs),
        ),
    )
    save_task(
        workspace_root,
        replace(
            task,
            code_change_log_refs=(*task.code_change_log_refs, change.change_id),
            updated_at=utc_now_iso(),
        ),
    )
    _tasks._append_event(
        workspace_root,
        task.id,
        "change.logged",
        {"change_id": change.change_id, "path": path},
    )
    return change


def scan_changes(
    workspace_root: Path,
    task_ref: str,
    *,
    from_git: bool,
    summary: str,
) -> CodeChangeRecord:
    if not from_git:
        raise _tasks._cli_error(
            "scan-changes currently requires --from-git.",
            EXIT_CODE_BAD_INPUT,
        )
    git_state = _tasks._git_change_state(workspace_root)
    diff_stat = "\n".join(
        [
            f"branch: {git_state['branch']}",
            "status:",
            git_state["status"] or "(clean)",
            "diff_stat:",
            git_state["diff_stat"] or "(no diff)",
        ]
    )
    return add_change(
        workspace_root,
        task_ref,
        path=".",
        kind="scan",
        summary=summary.strip() or "Scanned Git changes.",
        command="git branch --show-current && git status --short && git diff --stat",
        git_diff_stat=diff_stat,
    )


def run_planning_command(
    workspace_root: Path,
    task_ref: str,
    *,
    argv: tuple[str, ...],
    command_cwd: Path | None = None,
) -> dict[str, object]:
    from taskledger.services.agent_logging import record_managed_shell_command

    if not argv:
        raise _tasks._cli_error(
            "plan command requires a command to run.", EXIT_CODE_BAD_INPUT
        )
    task = resolve_task(workspace_root, task_ref)
    _tasks._ensure_not_archived(task, operation="run planning command on")
    run = _tasks._require_running_run(
        workspace_root,
        task,
        task.latest_planning_run,
        expected_type="planning",
    )
    _tasks._enforce_decision(
        plan_command_decision(
            task,
            _tasks._lock_for_mutation(workspace_root, task.id),
            run=run,
        )
    )
    execution_cwd = (command_cwd or workspace_root).expanduser().resolve()
    completed = command_runner.run_managed_command(
        argv,
        cwd=execution_cwd,
        workspace_root=workspace_root,
    )
    record_managed_shell_command(
        workspace_root,
        task_id=task.id,
        run_id=run.run_id,
        run_type="planning",
        argv=argv,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        command_cwd=execution_cwd,
    )
    output = _tasks._command_output(argv, completed.stdout, completed.stderr)
    artifact_ref: str | None = None
    if len(output) > 4000 or output.count("\n") > 50:
        artifact_ref = _tasks._write_command_artifact(
            workspace_root,
            task.id,
            run.run_id,
            output,
        )
    summary = _tasks._command_summary(argv, completed.returncode, artifact_ref)
    updated_run = replace(
        run,
        worklog=(*run.worklog, summary),
        artifact_refs=(*run.artifact_refs, *((artifact_ref,) if artifact_ref else ())),
    )
    save_run(workspace_root, updated_run)
    save_task(
        workspace_root,
        replace(task, updated_at=utc_now_iso()),
    )
    _tasks._append_event(
        workspace_root,
        task.id,
        "plan.command",
        {
            "run_id": run.run_id,
            "command": shlex.join(argv),
            "exit_code": completed.returncode,
            "artifact_ref": artifact_ref,
        },
    )
    return {
        "kind": "planning_command",
        "task_id": task.id,
        "change": None,
        "exit_code": completed.returncode,
        "cwd": str(execution_cwd),
        "artifact_path": artifact_ref,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def show_task_run(
    workspace_root: Path,
    task_ref: str,
    *,
    run_id: str | None = None,
    run_type: str,
) -> dict[str, object]:
    task = resolve_task(workspace_root, task_ref)
    selected_run_id = run_id
    if selected_run_id is None:
        if run_type == "implementation":
            selected_run_id = task.latest_implementation_run
        elif run_type == "validation":
            selected_run_id = task.latest_validation_run
        else:
            selected_run_id = task.latest_planning_run
    run = _tasks._require_run(workspace_root, task, selected_run_id)
    if run.run_type != run_type:
        raise _tasks._cli_error(
            f"Run {run.run_id} is {run.run_type}, not {run_type}.",
            EXIT_CODE_INVALID_TRANSITION,
        )
    return {"kind": "task_run", "task_id": task.id, "run": run.to_dict()}


def list_events(workspace_root: Path) -> list[dict[str, object]]:
    events_dir = resolve_v2_paths(workspace_root).events_dir
    return [item.to_dict() for item in load_events(events_dir)]

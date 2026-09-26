from __future__ import annotations

from pathlib import Path

import yaml

from taskledger.domain.models import PlanRecord
from taskledger.domain.states import EXIT_CODE_BAD_INPUT
from taskledger.errors import LaunchError
from taskledger.storage.task_store import resolve_v2_paths


def ensure_plan_input_path_allowed(workspace_root: Path, input_path: Path) -> None:
    """Reject plan input files from taskledger durable storage roots."""

    paths = resolve_v2_paths(workspace_root)
    storage_root = paths.taskledger_root.resolve()
    candidate = _resolve_candidate(workspace_root, input_path)
    default_storage_root = (workspace_root / ".taskledger").resolve()
    if (
        candidate == storage_root
        or storage_root in candidate.parents
        or candidate == default_storage_root
        or default_storage_root in candidate.parents
    ):
        message = (
            "Refusing to read a plan input file from Taskledger storage. "
            "Export the proposed plan to a workspace file such as "
            "`./plan.revision.md`, edit and check that file, then submit it "
            "with `taskledger plan upsert --auto-revise`. Never edit `.taskledger/` "
            "files directly."
        )
        error = LaunchError(message)
        error.taskledger_exit_code = EXIT_CODE_BAD_INPUT
        error.taskledger_error_code = "INVALID_INPUT"
        error.taskledger_remediation = [
            "taskledger plan export --version latest --file ./plan.revision.md",
            "taskledger plan check --file ./plan.revision.md",
            "taskledger plan upsert --auto-revise --file ./plan.revision.md",
        ]
        error.taskledger_data = {
            "input_path": str(candidate),
            "taskledger_root": str(storage_root),
            "next_commands": [
                "taskledger plan export --version latest --file ./plan.revision.md",
                "taskledger plan check --file ./plan.revision.md",
                "taskledger plan upsert --auto-revise --file ./plan.revision.md",
            ],
            "remediation": (
                "Export the proposed plan to `./plan.revision.md`, edit and check "
                "that workspace file, then submit it with "
                "`taskledger plan upsert --auto-revise`."
            ),
        }
        raise error


def render_editable_plan(plan: PlanRecord) -> str:
    front_matter = _editable_front_matter(plan)
    front_matter_text = yaml.safe_dump(
        front_matter,
        sort_keys=False,
        allow_unicode=False,
    ).strip()
    body = plan.body.rstrip()
    if body:
        return f"---\n{front_matter_text}\n---\n\n{body}\n"
    return f"---\n{front_matter_text}\n---\n\n"


def _editable_front_matter(plan: PlanRecord) -> dict[str, object]:
    payload: dict[str, object] = {}
    if plan.goal:
        payload["goal"] = plan.goal
    if plan.files:
        payload["files"] = list(plan.files)
    if plan.test_commands:
        payload["test_commands"] = list(plan.test_commands)
    if plan.expected_outputs:
        payload["expected_outputs"] = list(plan.expected_outputs)
    if plan.generation_reason:
        payload["generation_reason"] = plan.generation_reason
    if plan.todos_waived_reason:
        payload["todos_waived_reason"] = plan.todos_waived_reason
    payload["acceptance_criteria"] = [
        {
            "id": criterion.id,
            "text": criterion.text,
            "mandatory": criterion.mandatory,
        }
        for criterion in plan.criteria
    ]
    payload["todos"] = [_todo_payload(todo) for todo in plan.todos]
    return payload


def _todo_payload(todo: object) -> dict[str, object]:
    from taskledger.domain.models import TaskTodo

    if not isinstance(todo, TaskTodo):
        raise TypeError("todo must be TaskTodo")
    payload: dict[str, object] = {
        "id": todo.id,
        "text": todo.text,
        "mandatory": todo.mandatory,
    }
    if todo.validation_hint:
        payload["validation_hint"] = todo.validation_hint
    if todo.worker_step_id:
        payload["worker_step"] = todo.worker_step_id
    return payload


def _resolve_candidate(workspace_root: Path, input_path: Path) -> Path:
    expanded = input_path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (workspace_root / expanded).resolve()

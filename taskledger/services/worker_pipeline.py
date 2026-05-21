from __future__ import annotations

from pathlib import Path

from taskledger.domain.models import TaskRecord
from taskledger.domain.run import TaskRunRecord
from taskledger.errors import LaunchError
from taskledger.storage.project_config import load_worker_pipeline_config
from taskledger.storage.task_store import (
    list_handoffs,
    list_runs,
    load_todos,
    resolve_task,
)
from taskledger.storage.worker_pipeline_config import (
    WorkerPipelineConfig,
    WorkerStepConfig,
)

HANDOFF_COMPLETION_STEP_KINDS = frozenset({"review", "custom", "check"})


def worker_pipeline_status(workspace_root: Path) -> dict[str, object]:
    pipeline = load_worker_pipeline_config(workspace_root)
    if pipeline is None:
        return {
            "kind": "worker_pipeline_status",
            "configured": False,
            "enabled": False,
            "message": "No worker pipeline configured.",
            "pipeline": None,
        }
    if not pipeline.enabled:
        return {
            "kind": "worker_pipeline_status",
            "configured": True,
            "enabled": False,
            "message": "Worker pipeline is disabled.",
            "pipeline": pipeline.to_dict(),
        }
    return {
        "kind": "worker_pipeline_status",
        "configured": True,
        "enabled": True,
        "message": "Worker pipeline is enabled.",
        "pipeline": pipeline.to_dict(),
    }


def worker_pipeline_show(workspace_root: Path) -> dict[str, object]:
    payload = worker_pipeline_status(workspace_root)
    payload["kind"] = "worker_pipeline_show"
    return payload


def worker_pipeline_list(workspace_root: Path) -> dict[str, object]:
    payload = worker_pipeline_status(workspace_root)
    payload["kind"] = "worker_pipeline_list"
    pipeline = load_worker_pipeline_config(workspace_root)
    payload["steps"] = [step.to_dict() for step in pipeline.steps] if pipeline else []
    return payload


def worker_pipeline_next(workspace_root: Path, task_ref: str) -> dict[str, object]:
    status = worker_pipeline_status(workspace_root)
    if not bool(status["configured"]) or not bool(status["enabled"]):
        return {
            "kind": "worker_pipeline_next",
            "configured": status["configured"],
            "enabled": status["enabled"],
            "task_id": None,
            "step": None,
            "reason": status["message"],
        }
    pipeline = _require_enabled_pipeline(workspace_root)
    task = resolve_task(workspace_root, task_ref)
    step = determine_next_worker_step(workspace_root, task, pipeline)
    return {
        "kind": "worker_pipeline_next",
        "configured": True,
        "enabled": True,
        "task_id": task.id,
        "step": step.to_dict() if step is not None else None,
        "reason": _worker_pipeline_next_reason(task, step),
    }


def resolve_worker_pipeline_step(
    workspace_root: Path,
    step_id: str,
) -> tuple[WorkerPipelineConfig, WorkerStepConfig]:
    pipeline = _require_enabled_pipeline(workspace_root)
    return pipeline, pipeline.resolve_step(step_id)


def determine_next_worker_step(
    workspace_root: Path,
    task: TaskRecord,
    pipeline: WorkerPipelineConfig,
) -> WorkerStepConfig | None:
    if task.accepted_plan_version is None:
        return _first_step_for_stage(pipeline, "planning")
    open_worker_step_ids = _open_worker_todo_step_ids(workspace_root, task.id)
    if open_worker_step_ids:
        return _first_matching_step(pipeline, open_worker_step_ids)
    runs = list_runs(workspace_root, task.id)
    completed_handoff_steps = _closed_worker_handoff_step_ids(workspace_root, task.id)
    if (
        task.status_stage in {"implemented", "validating", "failed_validation"}
        and _latest_run(runs, "validation") is None
    ):
        review_step = _first_pending_review_step(pipeline, completed_handoff_steps)
        if review_step is not None:
            return review_step
    if task.status_stage in {"implemented", "validating", "failed_validation"}:
        validator_step = _first_step_for_stage(pipeline, "validation")
        if validator_step is not None:
            return validator_step
    return None


def worker_step_handoff_mode(step: WorkerStepConfig) -> str:
    return step.lifecycle_stage


def worker_step_context_for(step: WorkerStepConfig) -> str:
    return step.base_context


def _require_enabled_pipeline(workspace_root: Path) -> WorkerPipelineConfig:
    pipeline = load_worker_pipeline_config(workspace_root)
    if pipeline is None:
        raise LaunchError("No worker pipeline configured.")
    if not pipeline.enabled:
        raise LaunchError("Worker pipeline is disabled.")
    return pipeline


def _first_step_for_stage(
    pipeline: WorkerPipelineConfig,
    lifecycle_stage: str,
) -> WorkerStepConfig | None:
    for step in pipeline.steps:
        if step.lifecycle_stage == lifecycle_stage:
            return step
    return None


def _first_matching_step(
    pipeline: WorkerPipelineConfig,
    step_ids: list[str],
) -> WorkerStepConfig | None:
    wanted = set(step_ids)
    for step in pipeline.steps:
        if step.id in wanted:
            return step
    return None


def _latest_run(
    runs: list[TaskRunRecord],
    run_type: str,
) -> TaskRunRecord | None:
    matching = [run for run in runs if run.run_type == run_type]
    if not matching:
        return None
    return matching[-1]


def _open_worker_todo_step_ids(workspace_root: Path, task_id: str) -> list[str]:
    todo_collection = load_todos(workspace_root, task_id)
    open_todos = [todo for todo in todo_collection.todos if not todo.done]
    open_worker_step_ids: list[str] = []
    for todo in open_todos:
        worker_step_id = getattr(todo, "worker_step_id", None)
        if isinstance(worker_step_id, str) and worker_step_id.strip():
            open_worker_step_ids.append(worker_step_id)
    return open_worker_step_ids


def _closed_worker_handoff_step_ids(workspace_root: Path, task_id: str) -> set[str]:
    return {
        handoff.worker_step_id
        for handoff in list_handoffs(workspace_root, task_id)
        if handoff.worker_step_id
        and handoff.status == "closed"
        and handoff.worker_step_id.strip()
    }


def _first_pending_review_step(
    pipeline: WorkerPipelineConfig,
    completed_handoff_steps: set[str],
) -> WorkerStepConfig | None:
    for step in pipeline.steps:
        if step.lifecycle_stage != "review":
            continue
        if step.kind not in HANDOFF_COMPLETION_STEP_KINDS:
            continue
        if step.id in completed_handoff_steps:
            continue
        return step
    return None


def _worker_pipeline_next_reason(
    task: TaskRecord,
    step: WorkerStepConfig | None,
) -> str:
    if step is None:
        return (
            f"No configured worker step is pending for task stage {task.status_stage}."
        )
    if task.accepted_plan_version is None:
        return "No accepted plan exists yet."
    return f"Next configured worker step is {step.id}."

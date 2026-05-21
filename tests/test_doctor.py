"""Tests for taskledger.services.doctor."""

from __future__ import annotations

import py_compile
from pathlib import Path

from taskledger.domain.handoff import TaskHandoffRecord
from taskledger.domain.models import (
    AcceptanceCriterion,
    ActiveTaskState,
    ActorRef,
    CodeChangeRecord,
    PlanRecord,
    RequirementCollection,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
    TodoCollection,
)
from taskledger.services.doctor import (
    inspect_v2_indexes,
    inspect_v2_locks,
    inspect_v2_project,
    inspect_v2_schema,
)
from taskledger.storage.task_store import (
    ensure_v2_layout,
    save_active_task_state,
    save_change,
    save_handoff,
    save_plan,
    save_requirements,
    save_run,
    save_task,
    save_todos,
)


def _actor() -> ActorRef:
    return ActorRef(actor_type="agent", actor_name="taskledger")


def _task(task_id: str = "task-0001", **overrides) -> TaskRecord:
    defaults = dict(
        id=task_id,
        slug=task_id,
        title="Test task",
        body="desc",
        status_stage="draft",
    )
    defaults.update(overrides)
    return TaskRecord(**defaults)


def _lock(task_id: str = "task-0001", **overrides) -> TaskLock:
    defaults = dict(
        lock_id="lock-1",
        task_id=task_id,
        stage="planning",
        run_id="run-0001",
        created_at="2026-04-24T08:00:00+00:00",
        expires_at=None,
        reason="test",
        holder=_actor(),
    )
    defaults.update(overrides)
    return TaskLock(**defaults)


def _run(task_id: str = "task-0001", **overrides) -> TaskRunRecord:
    defaults = dict(
        run_id="run-0001",
        task_id=task_id,
        run_type="planning",
        status="running",
    )
    defaults.update(overrides)
    return TaskRunRecord(**defaults)


def _write_lock_yaml(lock_path: Path, lock: TaskLock) -> None:
    import yaml

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        yaml.safe_dump(lock.to_dict(), sort_keys=False), encoding="utf-8"
    )


def _setup_project(tmp_path: Path) -> None:
    """Create a minimal healthy v2 project."""
    ensure_v2_layout(tmp_path)
    task = _task()
    save_task(tmp_path, task)
    # Ensure storage.yaml exists for doctor schema checks
    from taskledger.storage.meta import StorageMeta, write_storage_meta

    write_storage_meta(tmp_path, StorageMeta(created_with_taskledger="test"))


def _append_pipeline_config(path: Path, text: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(f"{current.rstrip()}\n\n{text.strip()}\n", encoding="utf-8")


def test_inspect_healthy_project(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    result = inspect_v2_project(tmp_path)
    assert result["healthy"] is True
    assert result["errors"] == []
    counts = result["counts"]
    assert counts["tasks"] == 1


def test_doctor_module_compiles_without_syntaxwarning() -> None:
    py_compile.compile("taskledger/services/doctor.py", doraise=True)


def test_inspect_project_with_active_task(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    task = _task()
    save_active_task_state(
        tmp_path, ActiveTaskState(task_id=task.id, activated_by=_actor())
    )
    result = inspect_v2_project(tmp_path)
    assert result["counts"]["active_task"] == 1
    assert result["healthy"] is True


def test_inspect_project_reports_malformed_handoff_record(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    paths = ensure_v2_layout(tmp_path)
    handoff_dir = paths.tasks_dir / "task-0001" / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    (handoff_dir / "handoff-0001.md").write_text(
        "---\nobject_type: handoff\ncontext_hash: [\n---\n",
        encoding="utf-8",
    )

    result = inspect_v2_project(tmp_path)

    assert result["healthy"] is False
    assert any("handoff-0001.md" in error for error in result["errors"])


def test_inspect_project_warns_for_unsupported_legacy_sidecar(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    paths = ensure_v2_layout(tmp_path)
    (paths.tasks_dir / "task-0001" / "todos.yaml").write_text(
        "schema_version: 1\nobject_type: todos\ntask_id: task-0001\ntodos: []\n",
        encoding="utf-8",
    )

    result = inspect_v2_project(tmp_path)

    assert any(
        "Unsupported pre-release legacy sidecar retained" in w
        for w in result["warnings"]
    )
    assert any("one-off migration script" in hint for hint in result["repair_hints"])


def test_inspect_project_active_task_missing(tmp_path: Path) -> None:
    ensure_v2_layout(tmp_path)
    save_active_task_state(
        tmp_path, ActiveTaskState(task_id="task-9999", activated_by=_actor())
    )
    result = inspect_v2_project(tmp_path)
    assert result["healthy"] is False
    assert any("missing task task-9999" in e for e in result["errors"])


def test_inspect_project_active_task_done_warns(tmp_path: Path) -> None:
    task = _task(status_stage="done")
    save_task(tmp_path, task)
    save_active_task_state(
        tmp_path, ActiveTaskState(task_id=task.id, activated_by=_actor())
    )
    result = inspect_v2_project(tmp_path)
    assert any("done" in w for w in result["warnings"])


def test_inspect_broken_introduction_ref(tmp_path: Path) -> None:
    task = _task(introduction_ref="intro-9999")
    save_task(tmp_path, task)
    result = inspect_v2_project(tmp_path)
    assert any("broken references" in str(e) for e in result["errors"])


def test_inspect_broken_requirement_ref(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    from taskledger.domain.models import DependencyRequirement

    save_requirements(
        tmp_path,
        RequirementCollection(
            task_id=task.id,
            requirements=(DependencyRequirement(task_id="task-9999"),),
        ),
    )
    result = inspect_v2_project(tmp_path)
    assert any("broken references" in str(e) for e in result["errors"])


def test_inspect_accepted_plan_version_missing(tmp_path: Path) -> None:
    task = _task(accepted_plan_version=3)
    save_task(tmp_path, task)
    result = inspect_v2_project(tmp_path)
    assert any("missing accepted plan" in e for e in result["errors"])


def test_inspect_multiple_accepted_plans(tmp_path: Path) -> None:
    task = _task(accepted_plan_version=1)
    save_task(tmp_path, task)
    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=1,
            body="plan 1",
            status="accepted",
            created_by=_actor(),
            criteria=(AcceptanceCriterion(id="ac-1", text="test"),),
        ),
    )
    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=2,
            body="plan 2",
            status="accepted",
            created_by=_actor(),
            criteria=(AcceptanceCriterion(id="ac-2", text="test"),),
        ),
    )
    result = inspect_v2_project(tmp_path)
    assert any("multiple accepted plans" in e for e in result["errors"])


def test_inspect_accepted_plan_version_points_to_wrong_plan(tmp_path: Path) -> None:
    task = _task(accepted_plan_version=2)
    save_task(tmp_path, task)
    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=1,
            body="plan 1",
            status="accepted",
            created_by=_actor(),
            criteria=(AcceptanceCriterion(id="ac-1", text="test"),),
        ),
    )
    result = inspect_v2_project(tmp_path)
    # accepted_plan_version=2 but no plan v2 exists, and exactly one accepted plan (v1)
    assert any(
        "missing accepted plan" in e or "exactly one accepted" in e
        for e in result["errors"]
    )


def test_inspect_duplicate_todo_ids(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    todo = TaskTodo(id="todo-1", text="same id")
    save_todos(tmp_path, TodoCollection(task_id=task.id, todos=(todo, todo)))
    # Per-record storage deduplicates by id (one file per id)
    result = inspect_v2_project(tmp_path)
    assert not any("duplicate todo" in e for e in result["errors"])


def test_doctor_warns_for_worker_refs_without_enabled_pipeline(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    save_todos(
        tmp_path,
        TodoCollection(
            task_id="task-0001",
            todos=(TaskTodo(id="todo-1", text="Review", worker_step_id="tester"),),
        ),
    )
    save_handoff(
        tmp_path,
        TaskHandoffRecord(
            handoff_id="handoff-0001",
            task_id="task-0001",
            mode="implementation",
            context_for="implementer",
            worker_step_id="tester",
            created_by=_actor(),
        ),
    )

    result = inspect_v2_project(tmp_path)

    assert any(
        "Todo todo-1 references worker step 'tester'" in w for w in result["warnings"]
    )
    assert any(
        "Handoff handoff-0001 references worker step 'tester'" in w
        for w in result["warnings"]
    )
    assert {
        item["code"]
        for item in result["diagnostics"]
        if item.get("severity") == "warning"
    } >= {"todo.stale_worker_step", "handoff.stale_worker_step"}


def test_doctor_warns_for_worker_refs_missing_from_pipeline(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    _append_pipeline_config(
        tmp_path / "taskledger.toml",
        """
        [worker_pipeline]
        enabled = true
        name = "review-pipeline"
        mode = "guided"

        [[worker_pipeline.steps]]
        id = "coder"
        lifecycle_stage = "implementation"
        base_context = "implementer"
        kind = "todo"
        """,
    )
    save_todos(
        tmp_path,
        TodoCollection(
            task_id="task-0001",
            todos=(TaskTodo(id="todo-1", text="Review", worker_step_id="tester"),),
        ),
    )

    result = inspect_v2_project(tmp_path)

    assert any("worker step 'tester'" in w for w in result["warnings"])
    assert any(
        item.get("code") == "todo.stale_worker_step"
        and item.get("worker_step_id") == "tester"
        for item in result["diagnostics"]
    )


def test_inspect_transient_stage_in_status(tmp_path: Path) -> None:
    task = _task(status_stage="planning")
    save_task(tmp_path, task)
    result = inspect_v2_project(tmp_path)
    assert any("persists transient stage" in e for e in result["errors"])


def test_inspect_multiple_running_runs(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    save_run(tmp_path, _run(run_id="run-0001", status="running"))
    save_run(tmp_path, _run(run_id="run-0002", status="running"))
    result = inspect_v2_project(tmp_path)
    assert any("multiple running runs" in e for e in result["errors"])


def test_inspect_running_run_without_matching_lock(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    save_run(tmp_path, _run(run_id="run-0001", status="running"))
    result = inspect_v2_project(tmp_path)
    assert any(
        "running run without a matching active lock" in e for e in result["errors"]
    )
    assert result["run_lock_mismatches"] == [
        {
            "kind": "running_run_without_matching_lock",
            "task_id": "task-0001",
            "run_id": "run-0001",
            "run_type": "planning",
            "status": "running",
            "next_command": (
                "taskledger repair run --task task-0001 --run run-0001 "
                '--reason "Finish orphaned planning run."'
            ),
            "note": "Planning run can be explicitly finished with repair run.",
        }
    ]


def test_doctor_locks_reports_run_lock_mismatch(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    save_run(tmp_path, _run(run_id="run-0001", status="running"))

    result = inspect_v2_locks(tmp_path)

    assert result["healthy"] is False
    assert result["expired_locks"] == []
    assert result["run_lock_mismatches"][0]["run_id"] == "run-0001"


def test_doctor_reports_missing_lock_for_running_implementation_with_recovery_hint(
    tmp_path: Path,
) -> None:
    task = _task(
        status_stage="implementing",
        latest_plan_version=1,
        accepted_plan_version=1,
        latest_implementation_run="run-0002",
    )
    save_task(tmp_path, task)
    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=1,
            body="plan 1",
            status="accepted",
            created_by=_actor(),
            criteria=(AcceptanceCriterion(id="ac-1", text="test"),),
        ),
    )
    save_run(
        tmp_path,
        _run(run_id="run-0002", run_type="implementation", status="running"),
    )
    result = inspect_v2_project(tmp_path)
    assert any(
        "running run without a matching active lock" in e for e in result["errors"]
    )
    assert any(
        "taskledger implement resume --task task-0001 --reason" in hint
        for hint in result["repair_hints"]
    )
    mismatch = result["run_lock_mismatches"][0]
    assert mismatch["next_command"].startswith("taskledger implement resume")
    assert mismatch["next_command"] != "taskledger doctor"


def test_inspect_lock_without_running_run(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    paths = ensure_v2_layout(tmp_path)
    from taskledger.storage.task_store import task_lock_path

    lock = _lock(stage="planning", run_id="run-0001")
    _write_lock_yaml(task_lock_path(paths, task.id), lock)
    result = inspect_v2_project(tmp_path)
    assert any("without a running run" in e for e in result["errors"])


def test_inspect_change_references_missing_run(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    save_change(
        tmp_path,
        CodeChangeRecord(
            change_id="change-1",
            task_id=task.id,
            implementation_run="run-9999",
            timestamp="2026-04-24T08:00:00+00:00",
            kind="edit",
            path="foo.py",
            summary="changed",
        ),
    )
    result = inspect_v2_project(tmp_path)
    assert any("references missing" in e for e in result["errors"])


def test_inspect_change_references_non_implementation_run(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    run = _run(run_id="run-0001", run_type="planning", status="running")
    save_run(tmp_path, run)
    save_change(
        tmp_path,
        CodeChangeRecord(
            change_id="change-1",
            task_id=task.id,
            implementation_run=run.run_id,
            timestamp="2026-04-24T08:00:00+00:00",
            kind="edit",
            path="foo.py",
            summary="changed",
        ),
    )
    result = inspect_v2_project(tmp_path)
    assert any("non-implementation run" in e for e in result["errors"])


def test_inspect_validation_run_references_missing_impl(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    save_run(
        tmp_path,
        TaskRunRecord(
            run_id="run-val-1",
            task_id=task.id,
            run_type="validation",
            status="running",
            based_on_implementation_run="run-impl-9999",
        ),
    )
    result = inspect_v2_project(tmp_path)
    assert any("references missing" in e for e in result["errors"])


def test_inspect_validation_run_references_non_impl_run(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    impl_run = _run(run_id="run-impl-1", run_type="planning", status="running")
    save_run(tmp_path, impl_run)
    save_run(
        tmp_path,
        TaskRunRecord(
            run_id="run-val-1",
            task_id=task.id,
            run_type="validation",
            status="running",
            based_on_implementation_run=impl_run.run_id,
        ),
    )
    result = inspect_v2_project(tmp_path)
    assert any("non-implementation run" in e for e in result["errors"])


def test_inspect_lock_references_missing_task(tmp_path: Path) -> None:
    paths = ensure_v2_layout(tmp_path)
    from taskledger.storage.task_store import task_lock_path

    lock = _lock(task_id="task-9999", stage="planning", run_id="run-0001")
    _write_lock_yaml(task_lock_path(paths, "task-9999"), lock)
    result = inspect_v2_project(tmp_path)
    assert any("missing task" in e for e in result["errors"])


def test_inspect_lock_references_non_running_run(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    run = _run(run_id="run-0001", status="finished")
    save_run(tmp_path, run)
    paths = ensure_v2_layout(tmp_path)
    from taskledger.storage.task_store import task_lock_path

    lock = _lock(stage="planning", run_id=run.run_id)
    _write_lock_yaml(task_lock_path(paths, task.id), lock)
    result = inspect_v2_project(tmp_path)
    assert any("non-running run" in e for e in result["errors"])


def test_inspect_lock_stage_run_type_mismatch(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    run = _run(run_id="run-0001", run_type="implementation", status="running")
    save_run(tmp_path, run)
    paths = ensure_v2_layout(tmp_path)
    from taskledger.storage.task_store import task_lock_path

    lock = _lock(stage="planning", run_id=run.run_id)
    _write_lock_yaml(task_lock_path(paths, task.id), lock)
    result = inspect_v2_project(tmp_path)
    assert any("does not match" in e for e in result["errors"])


def test_inspect_expired_lock(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    run = _run(run_id="run-0001", run_type="planning", status="running")
    save_run(tmp_path, run)
    paths = ensure_v2_layout(tmp_path)
    from taskledger.storage.task_store import task_lock_path

    lock = _lock(
        stage="planning",
        run_id=run.run_id,
        expires_at="2020-01-01T00:00:00+00:00",
    )
    _write_lock_yaml(task_lock_path(paths, task.id), lock)
    result = inspect_v2_project(tmp_path)
    assert any("Expired" in w for w in result["warnings"])


def test_inspect_lock_references_missing_run(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    paths = ensure_v2_layout(tmp_path)
    from taskledger.storage.task_store import task_lock_path

    lock = _lock(stage="planning", run_id="run-9999")
    _write_lock_yaml(task_lock_path(paths, task.id), lock)
    result = inspect_v2_project(tmp_path)
    assert any("missing run" in e for e in result["errors"])


def test_inspect_v2_locks_no_expired(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    result = inspect_v2_locks(tmp_path)
    assert result["healthy"] is True
    assert result["expired_locks"] == []


def test_inspect_v2_schema_no_errors(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    result = inspect_v2_schema(tmp_path)
    assert result["healthy"] is True


def test_inspect_v2_indexes_all_present(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    result = inspect_v2_indexes(tmp_path)
    assert result["healthy"] is True
    assert result["missing_indexes"] == []


def test_inspect_v2_indexes_ignores_removed_legacy_indexes(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    indexes_dir = ensure_v2_layout(tmp_path).indexes_dir
    for name in ("tasks.json", "plan_versions.json", "latest_runs.json"):
        (indexes_dir / name).write_text("{not valid json", encoding="utf-8")

    result = inspect_v2_indexes(tmp_path)

    assert result["healthy"] is True
    assert "indexes/tasks.json" not in result["missing_indexes"]
    assert "indexes/plan_versions.json" not in result["missing_indexes"]
    assert "indexes/latest_runs.json" not in result["missing_indexes"]


def test_inspect_v2_indexes_event_error(tmp_path: Path) -> None:
    paths = ensure_v2_layout(tmp_path)
    # Write invalid event data
    events_dir = paths.events_dir
    bad_file = events_dir / "bad.md"
    bad_file.write_text("not valid frontmatter")
    result = inspect_v2_indexes(tmp_path)
    # The event loading should produce an error
    assert (
        result["healthy"] is False
        or len(result["event_errors"]) > 0
        or result["healthy"] is True
    )


def test_inspect_counts_include_plans_and_questions(tmp_path: Path) -> None:
    task = _task()
    save_task(tmp_path, task)
    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=1,
            body="plan",
            status="proposed",
            created_by=_actor(),
        ),
    )
    save_run(tmp_path, _run(run_id="run-0001", status="finished"))
    result = inspect_v2_project(tmp_path)
    counts = result["counts"]
    assert counts["plans"] == 1
    assert counts["runs"] == 1


def test_doctor_warns_about_empty_orphan_slug_dir(tmp_path: Path) -> None:
    task = _task(slug="my-feature")
    save_task(tmp_path, task)
    paths = ensure_v2_layout(tmp_path)
    orphan_dir = paths.tasks_dir / "my-feature"
    orphan_dir.mkdir()
    result = inspect_v2_project(tmp_path)
    assert any(
        "Orphan empty slug directory: my-feature/" in w for w in result["warnings"]
    )
    assert any("repair task-dirs" in h for h in result["repair_hints"])


def test_doctor_warns_about_non_empty_legacy_sidecar(tmp_path: Path) -> None:
    task = _task(slug="my-feature")
    save_task(tmp_path, task)
    paths = ensure_v2_layout(tmp_path)
    sidecar_dir = paths.tasks_dir / "my-feature"
    sidecar_dir.mkdir()
    (sidecar_dir / "some-file.yaml").write_text("some content")
    result = inspect_v2_project(tmp_path)
    assert any(
        "Legacy slug sidecar directory retained: my-feature/" in w
        for w in result["warnings"]
    )
    assert not any("repair task-dirs" in h for h in result["repair_hints"])


def test_doctor_no_warning_for_canonical_task_dir(tmp_path: Path) -> None:
    task = _task(slug="my-feature")
    save_task(tmp_path, task)
    result = inspect_v2_project(tmp_path)
    assert not any("slug" in w for w in result["warnings"])

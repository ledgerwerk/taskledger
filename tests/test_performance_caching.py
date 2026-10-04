"""Performance tests: verify that hot-path commands read minimal Markdown files.

These tests count front-matter reads rather than measuring wall-clock time,
so they are deterministic and not flaky.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.support.builders import (
    create_approved_task,
    init_workspace,
)


def test_resolve_task_by_id_reads_one_file(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    ids = []
    for i in range(5):
        tid = create_approved_task(ws, title=f"Task {i}", slug=f"task-{i}")
        ids.append(tid)

    from taskledger.storage import task_store
    from taskledger.storage.task_store import resolve_task

    counter: Counter = Counter()
    original = task_store.read_markdown_front_matter

    def counted(path: Path) -> tuple:
        counter[path.name] += 1
        return original(path)

    with patch.object(task_store, "read_markdown_front_matter", counted):
        task = resolve_task(ws, ids[2])

    assert task.id == ids[2]
    task_md_reads = sum(v for k, v in counter.items() if k == "task.md")
    assert task_md_reads == 1, (
        f"Expected 1 task.md read, got {task_md_reads}: {counter}"
    )


def test_resolve_task_by_slug_reads_all(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    ids = []
    for i in range(5):
        tid = create_approved_task(ws, title=f"Task {i}", slug=f"unique-slug-{i}")
        ids.append(tid)

    from taskledger.storage import task_store
    from taskledger.storage.task_store import resolve_task

    counter: Counter = Counter()
    original = task_store.read_markdown_front_matter

    def counted(path: Path) -> tuple:
        counter[path.name] += 1
        return original(path)

    with patch.object(task_store, "read_markdown_front_matter", counted):
        task = resolve_task(ws, "unique-slug-3")

    assert task.id == ids[3]
    task_md_reads = sum(v for k, v in counter.items() if k == "task.md")
    assert task_md_reads == 5, f"Expected 5 for slug, got {task_md_reads}"


def test_ready_work_skip_next_action(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    create_approved_task(ws, title="A", slug="task-a")
    create_approved_task(ws, title="B", slug="task-b")

    from taskledger.services.ready_work import ready_work_items
    from taskledger.storage.task_store import list_tasks_by_visibility

    visible = list_tasks_by_visibility(ws, visibility="visible")

    with patch("taskledger.services.ready_work.next_action") as mock_na:
        items = ready_work_items(ws, visible, include_next_action=False)

    mock_na.assert_not_called()
    assert len(items) == 2
    for item in items:
        assert "next_action" not in item
        assert isinstance(item.get("next"), str)
        assert isinstance(item.get("reason"), str)


def test_next_event_id_does_not_load_events(tmp_path: Path) -> None:
    from taskledger.storage.events import next_event_id

    with patch("taskledger.storage.events.load_events") as mock_load:
        eid = next_event_id(tmp_path, "2026-06-11T12:00:00+00:00")

    mock_load.assert_not_called()
    assert eid.startswith("evt-")
    assert len(eid.split("-")[-1]) == 12


def test_monitor_uses_summaries_for_in_progress(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    create_approved_task(ws, title="Ready", slug="ready-task")

    from taskledger.services.monitor import monitor_snapshot

    snapshot = monitor_snapshot(ws)

    assert isinstance(snapshot, dict)
    assert snapshot["kind"] == "monitor_snapshot"
    assert isinstance(snapshot.get("in_progress"), list)
    assert isinstance(snapshot.get("ready"), list)


def test_save_task_updates_task_index(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    tid = create_approved_task(ws, title="Index check", slug="index-check")

    from taskledger.storage.task_index import _read_index
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(ws)
    index = _read_index(paths)
    assert index is not None
    entries = index.get("entries", [])
    matching = [e for e in entries if isinstance(e, dict) and e.get("id") == tid]
    assert len(matching) == 1
    assert matching[0]["title"] == "Index check"


def test_missing_task_index_triggers_rebuild(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    tid = create_approved_task(ws, title="Rebuild check", slug="rebuild-check")

    from taskledger.storage.task_index import (
        _task_index_path,
        list_task_summaries,
    )
    from taskledger.storage.task_store import resolve_v2_paths

    paths = resolve_v2_paths(ws)
    index_path = _task_index_path(paths)

    # Index should exist from write-through.
    assert index_path.exists()

    # Delete it.
    index_path.unlink()
    assert not index_path.exists()

    # list_task_summaries should rebuild automatically.
    summaries = list_task_summaries(paths, visibility="visible")
    assert any(s.id == tid for s in summaries)
    assert index_path.exists()


def _create_tasks_without_global_rebuild(workspace: Path, count: int) -> list[str]:
    from taskledger.services import task_lifecycle
    from taskledger.storage import indexes
    from taskledger.storage.task_store import resolve_v2_paths

    created = []
    with patch.object(indexes, "rebuild_v2_indexes"):
        for index in range(count):
            task = task_lifecycle.create_task(
                workspace,
                title=f"Task {index}",
                description="Performance fixture.",
                slug=f"performance-task-{index}",
            )
            created.append(task.id)
    indexes.rebuild_v2_indexes(resolve_v2_paths(workspace))
    return created


def test_task_create_does_not_rebuild_all_indexes_or_scan_tasks_twice(
    tmp_path: Path,
) -> None:
    from taskledger.services import task_lifecycle
    from taskledger.storage import indexes

    ws = init_workspace(tmp_path)
    with (
        patch.object(indexes, "rebuild_v2_indexes") as rebuild,
        patch.object(
            task_lifecycle, "list_tasks", wraps=task_lifecycle.list_tasks
        ) as list_tasks,
    ):
        task_lifecycle.create_task(
            ws, title="New task", description="Description.", slug="new-task"
        )

    rebuild.assert_not_called()
    assert list_tasks.call_count == 0


def test_plan_start_does_not_rebuild_all_indexes(tmp_path: Path) -> None:
    from taskledger.services import planning_flow
    from taskledger.services.task_lifecycle import activate_task, create_task
    from taskledger.storage import indexes

    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Plan", description="Description.", slug="plan")
    activate_task(ws, task.id, reason="test setup")

    with patch.object(indexes, "rebuild_v2_indexes") as rebuild:
        planning_flow.start_planning(ws, task.id)

    rebuild.assert_not_called()


def test_task_list_uses_summaries_and_bounded_reference_resolution(
    tmp_path: Path,
) -> None:
    from typer.testing import CliRunner

    from taskledger import refs
    from taskledger.cli import app
    from taskledger.services import tasks
    from taskledger.storage import task_store

    ws = init_workspace(tmp_path)
    _create_tasks_without_global_rebuild(ws, 4)

    task_md_reads = 0
    original_read = task_store.read_markdown_front_matter
    original_resolve = tasks.resolve_v2_paths

    def counted_read(path: Path) -> tuple:
        nonlocal task_md_reads
        if path.name == "task.md":
            task_md_reads += 1
        return original_read(path)

    with (
        patch.object(task_store, "read_markdown_front_matter", counted_read),
        patch.object(
            tasks, "resolve_v2_paths", wraps=original_resolve
        ) as resolve_paths,
        patch.object(
            refs, "ref_context_for_workspace", wraps=refs.ref_context_for_workspace
        ) as ref_context,
    ):
        result = CliRunner().invoke(
            app, ["--root", str(ws), "--no-log", "task", "list"]
        )

    assert result.exit_code == 0, result.output
    assert task_md_reads == 0
    assert resolve_paths.call_count <= 1
    assert ref_context.call_count <= 1


def test_task_list_reports_active_stage_from_indexes(tmp_path: Path) -> None:
    from taskledger.services.planning_flow import start_planning
    from taskledger.services.task_lifecycle import activate_task, create_task
    from taskledger.services.tasks import list_task_summaries

    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Active", description="Description.", slug="active")
    activate_task(ws, task.id, reason="test setup")
    start_planning(ws, task.id)

    rows = list_task_summaries(ws)

    assert rows[0]["active_stage"] == "planning"


def test_usage_skips_sidecar_reads_for_tasks_without_inbox_items(
    tmp_path: Path,
) -> None:
    from taskledger.services import usage

    ws = init_workspace(tmp_path)
    _create_tasks_without_global_rebuild(ws, 4)

    with (
        patch.object(
            usage,
            "list_handoffs_from_paths",
            wraps=usage.list_handoffs_from_paths,
        ) as handoffs,
        patch.object(
            usage,
            "list_questions_from_paths",
            wraps=usage.list_questions_from_paths,
        ) as questions,
        patch.object(
            usage,
            "list_code_reviews_from_paths",
            wraps=usage.list_code_reviews_from_paths,
        ) as reviews,
    ):
        usage.usage_payload(ws)

    handoffs.assert_not_called()
    questions.assert_not_called()
    reviews.assert_not_called()


def test_doctor_locks_does_not_call_full_doctor(tmp_path: Path) -> None:
    from taskledger.services import doctor

    ws = init_workspace(tmp_path)
    with (
        patch.object(doctor, "inspect_v2_project", side_effect=AssertionError),
        patch(
            "taskledger.services.doctor_checks.artifact_checks.find_oversized_artifacts",
            side_effect=AssertionError,
        ),
    ):
        result = doctor.inspect_v2_locks(ws)

    assert result["kind"] == "taskledger_lock_inspection"


def test_full_doctor_skips_workspace_capture_without_finished_implementation(
    tmp_path: Path,
) -> None:
    from taskledger.services import doctor, workspace_snapshot

    ws = init_workspace(tmp_path)
    with patch.object(
        workspace_snapshot,
        "capture_current_workspace_state",
        side_effect=AssertionError,
    ) as capture:
        doctor.inspect_v2_project(ws)

    capture.assert_not_called()


def test_artifact_scan_ignores_non_artifact_task_files(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from taskledger.services.doctor_checks.artifact_checks import (
        find_oversized_artifacts,
    )

    tasks_dir = tmp_path / "tasks"
    task_dir = tasks_dir / "task-0001"
    (task_dir / "artifacts").mkdir(parents=True)
    (task_dir / "task.md").write_bytes(b"metadata larger than limit")
    artifact = task_dir / "artifacts" / "output.bin"
    artifact.write_bytes(b"artifact larger than limit")
    paths = SimpleNamespace(
        tasks_dir=tasks_dir,
        events_dir=tmp_path / "logs" / "events",
        project_dir=tmp_path,
    )

    violations = find_oversized_artifacts(paths, max_bytes=8)

    assert [item["path"] for item in violations] == [
        "tasks/task-0001/artifacts/output.bin"
    ]


def test_stage_timing_is_opt_in_without_global_context_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taskledger import timing
    from taskledger.services import doctor
    from taskledger.storage import project_context

    ws = init_workspace(tmp_path)

    # Disabled by default: no active timer and no timing output.
    monkeypatch.delenv("TASKLEDGER_TIMINGS", raising=False)
    with timing.stage_timer() as timer, timing.stage("probe"):
        pass
    assert timer is None
    assert "timing " not in capsys.readouterr().err

    # Enabled explicitly: coarse stage timings are emitted to stderr.
    monkeypatch.setenv("TASKLEDGER_TIMINGS", "1")
    with timing.stage_timer() as timer, timing.stage("probe"):
        pass
    err = capsys.readouterr().err
    assert timer is not None
    assert "timing probe" in err
    assert "timing total" in err
    # The timer lives in a per-invocation ContextVar and is cleared on exit.
    assert timing._active.get() is None

    # Enabling timing does not introduce a process-global project-context cache:
    # each invocation re-resolves project context rather than reusing a memo.
    calls = {"n": 0}
    original = project_context.load_project_context

    def counted(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        return original(*args, **kwargs)

    with patch.object(project_context, "load_project_context", counted):
        doctor.inspect_v2_project(ws)
        first = calls["n"]
        doctor.inspect_v2_project(ws)
    assert first >= 1
    assert calls["n"] > first

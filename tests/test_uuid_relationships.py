from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from taskledger.api.tasks import activate_task, add_requirement, create_task
from taskledger.domain.models import (
    ActorRef,
    HarnessRef,
    ReleaseRecord,
    TaskEvent,
    TaskRecord,
)
from taskledger.errors import LaunchError
from taskledger.services.change_tracking import list_events
from taskledger.services.phase5_lock_transfer import transfer_lock
from taskledger.services.planning_flow import start_planning
from taskledger.services.task_lifecycle import list_follow_up_tasks
from taskledger.storage.events import append_event
from taskledger.storage.project_context import load_project_context
from taskledger.storage.task_identity import (
    deterministic_legacy_task_uuid,
    task_identity_for_ref,
    task_identity_for_stored_ref,
)
from taskledger.storage.task_store import (
    list_releases,
    list_tasks,
    load_active_task_state,
    load_requirements,
    load_task_bundle_by_uuid,
    resolve_lock,
    resolve_task,
    resolve_v2_paths,
    save_release,
    save_task,
    save_task_from_paths,
    task_lock_path,
)
from tests.support.builders import init_workspace


def test_relationship_uuids_survive_derived_alias_reordering(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    target = create_task(
        tmp_path, title="Dependency target", description="Target.", slug="target"
    )
    dependent = create_task(
        tmp_path, title="Dependent", description="Depends on target.", slug="dependent"
    )
    child = create_task(
        tmp_path, title="Follow-up", description="Linked child.", slug="follow-up"
    )
    target_uuid = target.task_uuid or ""
    dependent_uuid = dependent.task_uuid or ""
    child_uuid = child.task_uuid or ""
    assert target_uuid and dependent_uuid and child_uuid

    add_requirement(tmp_path, dependent.id, target.id)
    save_task(
        tmp_path,
        replace(
            child,
            parent_task_id=target.id,
            parent_task_uuid=target_uuid,
            parent_relation="follow_up",
        ),
    )
    activate_task(tmp_path, dependent.id, reason="UUID relationship test")
    start_planning(tmp_path, dependent.id)

    paths = resolve_v2_paths(tmp_path)
    save_release(
        tmp_path,
        ReleaseRecord(
            version="0.1.0",
            boundary_task_id=target.id,
            boundary_task_uuid=target_uuid,
        ),
    )
    append_event(
        paths.events_dir,
        TaskEvent(
            ts="2026-06-01T12:00:00+00:00",
            event="task.updated",
            task_id=target.id,
            task_uuid=target_uuid,
            actor=ActorRef(actor_type="agent", actor_name="test"),
            event_id="evt-20260601T120000Z-000001",
        ),
    )
    original_lock = resolve_lock(tmp_path, dependent_uuid)
    assert original_lock is not None
    assert original_lock.task_uuid == dependent_uuid

    earlier_uuid = "00000000-0000-7000-8000-000000000001"
    save_task_from_paths(
        paths,
        TaskRecord(
            id="task-9999",
            slug="merged-earlier-task",
            title="Merged earlier task",
            body="Introduced by the merged branch.",
            task_uuid=earlier_uuid,
        ),
    )

    target_after_merge = resolve_task(tmp_path, target_uuid)
    dependent_after_merge = resolve_task(tmp_path, dependent_uuid)
    assert target_after_merge.id != target.id
    assert dependent_after_merge.id != dependent.id

    requirement = load_requirements(tmp_path, dependent_after_merge.id).requirements[0]
    assert requirement.required_task_uuid == target_uuid
    assert requirement.required_task_id == target_after_merge.id
    assert requirement.parent_task_uuid == dependent_uuid
    assert requirement.parent_task_id == dependent_after_merge.id
    active_state = load_active_task_state(tmp_path)
    assert active_state is not None
    assert active_state.task_uuid == dependent_uuid
    assert active_state.task_id == dependent_after_merge.id
    follow_up = list_follow_up_tasks(tmp_path, target_uuid)[0]
    assert follow_up.task_uuid == child_uuid
    assert follow_up.parent_task_uuid == target_uuid
    assert follow_up.parent_task_id == target_after_merge.id
    assert list_releases(tmp_path)[0].boundary_task_id == target_after_merge.id
    event = next(
        item
        for item in list_events(tmp_path)
        if item["event_id"] == "evt-20260601T120000Z-000001"
    )
    assert event["task_uuid"] == target_uuid
    assert event["task_id"] == target_after_merge.id

    lock_path = task_lock_path(paths, dependent_uuid)
    assert lock_path.stem == dependent_uuid
    transferred = transfer_lock(
        tmp_path,
        dependent_after_merge.id,
        original_lock.lock_id,
        ActorRef(actor_type="agent", actor_name="receiver"),
        HarnessRef(
            harness_id="harness-receiver", name="receiver", kind="agent_harness"
        ),
    )
    assert transferred.task_uuid == dependent_uuid
    persisted_lock = resolve_lock(tmp_path, dependent_uuid)
    assert persisted_lock is not None
    assert persisted_lock.task_id == dependent_after_merge.id
    assert persisted_lock.task_uuid == dependent_uuid


def test_legacy_numeric_ref_is_resolved_or_rejected_as_ambiguous(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    paths = resolve_v2_paths(tmp_path)
    project_uuid = load_project_context(tmp_path).project_uuid
    first_created_at = "2024-01-01T00:00:00+00:00"
    first_legacy_uuid = deterministic_legacy_task_uuid(
        project_uuid=project_uuid,
        ledger_ref=paths.ledger_ref,
        legacy_task_id="task-0001",
        created_at=first_created_at,
    )
    save_task_from_paths(
        paths,
        TaskRecord(
            id="task-0001",
            slug="legacy-first",
            title="Legacy first",
            body="Migrated task.",
            task_uuid=str(first_legacy_uuid),
            created_at=first_created_at,
        ),
    )

    earlier_uuid = "00000000-0000-7000-8000-000000000001"
    save_task_from_paths(
        paths,
        TaskRecord(
            id="task-0002",
            slug="merged-first",
            title="Merged first",
            body="Earlier UUID from another branch.",
            task_uuid=earlier_uuid,
        ),
    )
    assert task_identity_for_ref(paths, "task-0001").task_uuid == UUID(earlier_uuid)
    legacy_identity = task_identity_for_stored_ref(
        paths, task_id="task-0001", task_uuid=None
    )
    assert legacy_identity.task_uuid == first_legacy_uuid
    assert legacy_identity.task_id == "task-0002"

    child_uuid = "01a00000-0000-7000-8000-000000000001"
    save_task_from_paths(
        paths,
        TaskRecord(
            id="task-0003",
            slug="legacy-reference-child",
            title="Legacy reference child",
            body="Contains an old numeric parent reference.",
            task_uuid=child_uuid,
            parent_task_id="task-0001",
            parent_relation="follow_up",
        ),
    )
    child = next(task for task in list_tasks(tmp_path) if task.task_uuid == child_uuid)
    assert child.parent_task_uuid == str(first_legacy_uuid)
    assert child.parent_task_id == legacy_identity.task_id

    second_created_at = "2024-01-02T00:00:00+00:00"
    second_legacy_uuid = deterministic_legacy_task_uuid(
        project_uuid=project_uuid,
        ledger_ref=paths.ledger_ref,
        legacy_task_id="task-0001",
        created_at=second_created_at,
    )
    save_task_from_paths(
        paths,
        TaskRecord(
            id="task-0001",
            slug="legacy-second",
            title="Legacy second",
            body="Conflicting branch allocation.",
            task_uuid=str(second_legacy_uuid),
            created_at=second_created_at,
        ),
    )

    with pytest.raises(LaunchError) as caught:
        task_identity_for_stored_ref(paths, task_id="task-0001", task_uuid=None)

    assert caught.value.code == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    assert caught.value.details["legacy_task_id"] == "task-0001"
    sources = caught.value.details["sources"]
    assert isinstance(sources, list)
    assert len(sources) == 2
    assert all(
        isinstance(source, dict) and source.get("kind") == "uuid_task"
        for source in sources
    )


def test_direct_uuid_task_show_reports_broken_parent_without_scanning_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import taskledger.storage.task_identity as identity_module
    import taskledger.storage.task_store as task_store_module
    from taskledger.services.tasks import show_task

    init_workspace(tmp_path)
    task_uuid = "00dc6acf-ac25-76b7-9c95-3e6e51ff322d"
    task = TaskRecord(
        id="task-0038",
        slug="child",
        title="Child task",
        body="Load this bundle directly.",
        status_stage="draft",
        task_uuid=task_uuid,
        parent_task_id="task-0037",
    )
    save_task(tmp_path, task)

    def fail_unrelated_scan(*_args, **_kwargs):
        raise AssertionError("direct UUID inspection must not enumerate tasks")

    monkeypatch.setattr(
        identity_module, "scan_task_identity_inventory", fail_unrelated_scan
    )
    monkeypatch.setattr(task_store_module, "list_tasks_from_paths", fail_unrelated_scan)

    raw_task = load_task_bundle_by_uuid(resolve_v2_paths(tmp_path), task_uuid)
    assert raw_task.id == "task-0038"
    payload = show_task(tmp_path, task_uuid)
    shown_task = payload["task"]
    assert isinstance(shown_task, dict)
    assert shown_task["task_uuid"] == task_uuid
    assert shown_task["parent_task_id"] == "task-0037"
    diagnostics = payload["relationship_diagnostics"]
    assert isinstance(diagnostics, list)
    assert any(
        item.get("code") == "PARENT_TASK_UUID_MISSING"
        for item in diagnostics
        if isinstance(item, dict)
    )
    assert any(
        item.get("code") == "FOLLOW_UP_TASKS_NOT_SCANNED"
        for item in diagnostics
        if isinstance(item, dict)
    )

    import json

    from typer.testing import CliRunner

    from taskledger.cli import app

    cli_result = CliRunner().invoke(
        app,
        ["--root", str(tmp_path), "--json", "task", "show", task_uuid],
    )
    assert cli_result.exit_code == 0, cli_result.stdout
    cli_payload = json.loads(cli_result.stdout)
    assert cli_payload["result"]["task"]["task_uuid"] == task_uuid
    assert any(
        item.get("code") == "PARENT_TASK_UUID_MISSING"
        for item in cli_payload["result"]["relationship_diagnostics"]
    )

    human_result = CliRunner().invoke(
        app,
        ["--root", str(tmp_path), "task", "show", task_uuid],
    )
    assert human_result.exit_code == 0, human_result.stdout
    assert "relationship [error:PARENT_TASK_UUID_MISSING]" in human_result.stdout

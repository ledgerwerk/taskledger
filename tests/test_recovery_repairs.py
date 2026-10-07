from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from taskledger.api.repair import (
    audit_allocation_repairs,
    reconcile_allocation_tombstone,
    repair_allocations,
    repair_locks,
    repair_task_relation,
)
from taskledger.errors import LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.task_events import append_task_event
from taskledger.services.task_lifecycle import activate_task, deactivate_task
from taskledger.services.tasks import create_task, start_planning
from taskledger.storage.events import load_events
from taskledger.storage.frontmatter import (
    read_markdown_front_matter,
    write_markdown_front_matter,
)
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.locks import read_lock, write_lock
from taskledger.storage.project_identity import load_project_uuid
from taskledger.storage.sidecar_index import load_sidecar_index
from taskledger.storage.task_identity import (
    deterministic_legacy_task_uuid,
    task_identity_inventory,
)
from taskledger.storage.task_ids import write_task_id_tombstone
from taskledger.storage.task_store import (
    load_active_task_state,
    resolve_v2_paths,
    task_lock_path,
    task_markdown_path,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_canonical_project_state(workspace, create_sibling_store=True)
    return workspace


def _shadowed_migrated_allocation(
    workspace: Path, *, legacy_task_id: str = "task-0012"
) -> tuple[object, Path, Path, str]:
    paths = resolve_v2_paths(workspace)
    task = create_task(
        workspace, title="Migrated task", description="", slug="migrated-owner"
    )
    original_dir = paths.tasks_dir / str(task.task_uuid)
    task_path = original_dir / "task.md"
    metadata, body = read_markdown_front_matter(task_path)
    project_uuid = load_project_uuid(
        workspace / ".ledger" / "taskledger" / "config.toml"
    )
    assert project_uuid is not None
    created_at = metadata["created_at"]
    assert isinstance(created_at, str)
    migrated_uuid = deterministic_legacy_task_uuid(
        project_uuid=project_uuid,
        ledger_ref=paths.ledger_ref,
        legacy_task_id=legacy_task_id,
        created_at=created_at,
    )
    metadata["id"] = legacy_task_id
    metadata["legacy_task_id"] = legacy_task_id
    metadata["task_uuid"] = str(migrated_uuid)
    write_markdown_front_matter(task_path, metadata, body)
    migrated_dir = paths.tasks_dir / str(migrated_uuid)
    original_dir.rename(migrated_dir)

    stale_dir = paths.tasks_dir / legacy_task_id
    (stale_dir / "audit").mkdir(parents=True)
    sidecar = stale_dir / "audit" / "preserve.bin"
    sidecar.write_bytes(b"stale pre-migration allocation")
    return paths, stale_dir, migrated_dir, str(migrated_uuid)


def test_allocation_repair_uses_physical_source_not_display_alias(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)

    live_uuid = "00dc6acf-ac25-76b7-9c95-3e6e51ff322d"
    live_dir = paths.tasks_dir / live_uuid
    live_dir.mkdir()
    write_markdown_front_matter(
        live_dir / "task.md", {"object_type": "task", "id": "task-0037"}, ""
    )
    for ordinal in range(1, 19):
        incomplete_uuid = f"00000000-0000-7000-8000-{ordinal:012x}"
        incomplete_dir = paths.tasks_dir / incomplete_uuid
        incomplete_dir.mkdir()
        (incomplete_dir / "partial.bin").write_bytes(bytes([ordinal]))

    physical_dir = paths.tasks_dir / "task-0019"
    physical_dir.mkdir()
    (physical_dir / "partial.bin").write_bytes(b"original task-0019 payload")

    dry_run = repair_allocations(workspace, task_id="task-0019")
    assert dry_run["apply_safe"] is True
    entries = dry_run["incomplete_allocations"]
    target = next(
        entry for entry in entries if entry["physical_source"] == "tasks/task-0019"
    )
    assert target["legacy_source_id"] == "task-0019"
    assert target["display_task_id"] == "task-0037"
    assert target["planned_quarantine"].endswith("/task-0019")
    assert target["planned_tombstone"].endswith("/task-0019.toml")

    applied = repair_allocations(
        workspace,
        apply=True,
        reason="Quarantine the verified physical allocation.",
        task_id="task-0019",
        plan_id=dry_run["plan_id"],
    )
    repaired = applied["repaired"]
    assert isinstance(repaired, list)
    assert repaired[0]["legacy_task_id"] == "task-0019"
    quarantine = Path(repaired[0]["quarantined_path"])
    assert (quarantine / "partial.bin").read_bytes() == b"original task-0019 payload"
    assert (paths.ledger_dir / "tombstones" / "task-0019.toml").is_file()
    assert not (paths.ledger_dir / "tombstones" / "task-0037.toml").exists()
    assert not physical_dir.exists()

    audit = audit_allocation_repairs(workspace)
    audit_entries = audit["entries"]
    assert isinstance(audit_entries, list)
    assert audit_entries[0]["status"] == "verified"
    assert audit_entries[0]["physical_source_id"] == "task-0019"


def test_shadowed_migrated_legacy_allocation_dry_run_identifies_owner(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths, stale_dir, migrated_dir, migrated_uuid = _shadowed_migrated_allocation(
        workspace
    )

    dry_run = repair_allocations(workspace, task_id="task-0012")
    entry = dry_run["incomplete_allocations"][0]
    assert dry_run["apply_safe"] is True
    assert entry["repair_mode"] == "quarantine_shadowed_legacy_source"
    assert entry["apply_safe"] is True
    assert entry["planned_tombstone"] is None
    assert entry["surviving_identity"]["task_uuid"] == migrated_uuid
    assert (
        entry["surviving_identity"]["path"]
        == migrated_dir.relative_to(paths.ledger_dir).as_posix()
    )
    assert entry["collision_findings"][0]["state"] == "live"
    assert entry["planned_quarantine"].endswith("/task-0012")
    assert dry_run["next_command"]
    from typer.testing import CliRunner

    from taskledger.cli import app

    cli_result = CliRunner().invoke(
        app,
        ["--root", str(workspace), "repair", "allocations", "--task-id", "task-0012"],
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert "mode=quarantine_shadowed_legacy_source" in cli_result.output
    assert f"owner={migrated_uuid}" in cli_result.output
    assert "tombstone=none" in cli_result.output
    assert stale_dir.is_dir()


def test_task_list_identity_conflict_is_structured_until_repaired(
    tmp_path: Path,
) -> None:
    import json

    from typer.testing import CliRunner

    from taskledger.cli import app

    workspace = _workspace(tmp_path)
    paths, _stale_dir, _migrated_dir, _migrated_uuid = _shadowed_migrated_allocation(
        workspace
    )
    from taskledger.storage.indexes import mark_index_dirty

    mark_index_dirty(paths, "task_index")
    runner = CliRunner()
    human = runner.invoke(app, ["--root", str(workspace), "task", "list"])
    assert human.exit_code != 0
    assert "Task identity conflict" in human.output
    assert "Traceback" not in human.output

    json_result = runner.invoke(
        app, ["--root", str(workspace), "--json", "task", "list"]
    )
    assert json_result.exit_code != 0
    payload = json.loads(json_result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    assert payload["error"]["details"]["legacy_task_id"] == "task-0012"

    dry_run = repair_allocations(workspace, task_id="task-0012")
    repair_allocations(
        workspace,
        task_id="task-0012",
        apply=True,
        plan_id=str(dry_run["plan_id"]),
        reason="Quarantine stale pre-migration allocation.",
    )
    listed = runner.invoke(app, ["--root", str(workspace), "task", "list"])
    assert listed.exit_code == 0, listed.output
    assert "task-0012" in listed.output


def test_shadowed_migrated_legacy_allocation_apply_preserves_live_owner(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths, stale_dir, migrated_dir, migrated_uuid = _shadowed_migrated_allocation(
        workspace
    )
    task_path = migrated_dir / "task.md"
    live_task_before = task_path.read_bytes()
    dry_run = repair_allocations(workspace, task_id="task-0012")

    result = repair_allocations(
        workspace,
        task_id="task-0012",
        apply=True,
        plan_id=str(dry_run["plan_id"]),
        reason="Quarantine stale pre-migration allocation.",
    )

    repaired = result["repaired"]
    assert isinstance(repaired, list) and len(repaired) == 1
    item = repaired[0]
    assert item["repair_mode"] == "quarantine_shadowed_legacy_source"
    assert item["tombstone_path"] is None
    assert item["surviving_task_uuid"] == migrated_uuid
    assert not stale_dir.exists()
    assert task_path.read_bytes() == live_task_before
    assert (paths.ledger_dir / "tombstones" / "task-0012.toml").exists() is False
    quarantine = Path(item["quarantined_path"])
    assert (quarantine / "audit" / "preserve.bin").read_bytes() == (
        b"stale pre-migration allocation"
    )

    inventory = task_identity_inventory(paths)
    matches = [
        identity
        for identity in inventory.entries
        if identity.legacy_task_id == "task-0012"
    ]
    assert len(matches) == 1
    assert str(matches[0].task_uuid) == migrated_uuid
    assert matches[0].source_kind == "uuid_task"
    assert matches[0].state == "live"
    events = load_events(paths.events_dir)
    repair_event = next(
        event for event in events if event.event == "repair.task_allocation_quarantined"
    )
    assert repair_event.data["repair_mode"] == "quarantine_shadowed_legacy_source"
    assert repair_event.data["tombstone_path"] is None
    assert repair_event.data["surviving_task_uuid"] == migrated_uuid
    audit = audit_allocation_repairs(workspace)
    assert audit["entries"][0]["status"] == "existing_owner_preserved"


def test_shadowed_owner_change_invalidates_allocation_repair_plan(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _paths, stale_dir, migrated_dir, _migrated_uuid = _shadowed_migrated_allocation(
        workspace
    )
    dry_run = repair_allocations(workspace, task_id="task-0012")
    task_path = migrated_dir / "task.md"
    metadata, body = read_markdown_front_matter(task_path)
    metadata["legacy_task_id"] = "task-0013"
    write_markdown_front_matter(task_path, metadata, body)

    with pytest.raises(LaunchError) as caught:
        repair_allocations(
            workspace,
            task_id="task-0012",
            apply=True,
            plan_id=str(dry_run["plan_id"]),
            reason="Reject changed migrated owner.",
        )

    assert caught.value.code == "TASKLEDGER_REPAIR_PLAN_CHANGED"
    assert stale_dir.is_dir()
    assert (stale_dir / "audit" / "preserve.bin").read_bytes() == (
        b"stale pre-migration allocation"
    )


def test_multiple_live_legacy_identity_owners_are_blocked_before_apply(
    tmp_path: Path,
) -> None:
    import shutil

    from taskledger.ids import uuid7

    workspace = _workspace(tmp_path)
    paths, stale_dir, migrated_dir, _migrated_uuid = _shadowed_migrated_allocation(
        workspace
    )
    second_uuid = uuid7()
    second_dir = paths.tasks_dir / str(second_uuid)
    shutil.copytree(migrated_dir, second_dir)
    second_task_path = second_dir / "task.md"
    metadata, body = read_markdown_front_matter(second_task_path)
    metadata["task_uuid"] = str(second_uuid)
    metadata["slug"] = "second-migrated-owner"
    write_markdown_front_matter(second_task_path, metadata, body)

    dry_run = repair_allocations(workspace, task_id="task-0012")
    entry = dry_run["incomplete_allocations"][0]
    assert entry["repair_mode"] == "blocked_identity_conflict"
    assert entry["apply_safe"] is False
    assert dry_run["next_command"] is None
    assert len(entry["collision_findings"]) == 2

    with pytest.raises(LaunchError) as caught:
        repair_allocations(
            workspace,
            task_id="task-0012",
            apply=True,
            plan_id=str(dry_run["plan_id"]),
            reason="Do not choose between duplicate live owners.",
        )

    assert caught.value.code == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    assert stale_dir.is_dir()
    assert not (paths.ledger_dir / "tombstones" / "task-0012.toml").exists()


def test_allocation_apply_requires_reviewed_unchanged_plan(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    source = paths.tasks_dir / "task-0001"
    source.mkdir()
    payload = source / "partial.bin"
    payload.write_bytes(b"initial")

    with pytest.raises(LaunchError, match="explicit --task-id or --all"):
        repair_allocations(
            workspace,
            apply=True,
            reason="Refuse unreviewed broad repair.",
        )

    dry_run = repair_allocations(workspace, task_id="task-0001")
    payload.write_bytes(b"changed after review")
    with pytest.raises(LaunchError, match="plan changed since dry-run"):
        repair_allocations(
            workspace,
            apply=True,
            reason="Refuse changed source.",
            task_id="task-0001",
            plan_id=dry_run["plan_id"],
        )

    assert source.is_dir()
    assert payload.read_bytes() == b"changed after review"
    assert not (paths.ledger_dir / "tombstones" / "task-0001.toml").exists()


def test_allocation_apply_refuses_live_tombstone_identity_conflict(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    source = paths.tasks_dir / "task-0001"
    source.mkdir()
    payload = source / "partial.bin"
    payload.write_bytes(b"do not move conflicting source")
    old_quarantine = paths.ledger_dir / "_recovery" / "prior" / "task-0001"
    old_quarantine.mkdir(parents=True)
    write_task_id_tombstone(
        paths,
        "task-0001",
        reason="Existing conflicting tombstone for regression coverage.",
        quarantined_path=old_quarantine,
    )
    dry_run = repair_allocations(workspace, task_id="task-0001")

    entry = dry_run["incomplete_allocations"][0]
    assert entry["repair_mode"] == "blocked_identity_conflict"
    assert entry["apply_safe"] is False
    assert dry_run["apply_safe"] is False
    assert dry_run["next_command"] is None
    with pytest.raises(LaunchError) as exc_info:
        repair_allocations(
            workspace,
            apply=True,
            reason="Must refuse identity conflicts before moving data.",
            task_id="task-0001",
            plan_id=str(dry_run["plan_id"]),
        )

    assert exc_info.value.code == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    assert source.is_dir()
    assert payload.read_bytes() == b"do not move conflicting source"


def test_allocation_repair_rolls_back_failed_identity_postcondition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import taskledger.storage.task_identity as identity_module

    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    source = paths.tasks_dir / "task-0001"
    source.mkdir()
    payload = source / "partial.bin"
    payload.write_bytes(b"preserve on failure")
    dry_run = repair_allocations(workspace, task_id="task-0001")

    original_scan = identity_module.scan_task_identity_inventory
    scan_count = 0

    def fail_identity_scan(_paths):
        nonlocal scan_count
        scan_count += 1
        if scan_count == 1:
            raise LaunchError("Injected postcondition failure.")
        return original_scan(_paths)

    monkeypatch.setattr(
        identity_module, "scan_task_identity_inventory", fail_identity_scan
    )
    result = repair_allocations(
        workspace,
        apply=True,
        reason="Exercise rollback after a failed identity postcondition.",
        task_id="task-0001",
        plan_id=dry_run["plan_id"],
    )

    assert result["repaired"] == []
    assert "postcondition failure" in result["failed"][0]["error"]
    assert source.is_dir()
    assert payload.read_bytes() == b"preserve on failure"
    assert not (paths.ledger_dir / "tombstones" / "task-0001.toml").exists()


def test_repair_locks_handles_bundle_local_expired_lock(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = create_task(
        workspace, title="Migrated task", description="", slug="migrated"
    )
    activate_task(workspace, task.id, reason="test setup")
    start_planning(workspace, task.id)
    paths = resolve_v2_paths(workspace)
    runtime_lock_path = task_lock_path(paths, task.id)
    lock = read_lock(runtime_lock_path)
    assert lock is not None

    bundle_lock_path = paths.tasks_dir / task.task_uuid / "lock.yaml"
    bundle_lock_path.parent.mkdir(parents=True, exist_ok=True)
    write_lock(bundle_lock_path, replace(lock, expires_at="2020-01-01T00:00:00+00:00"))
    runtime_lock_path.unlink()

    dry_run = repair_locks(workspace)
    assert dry_run["entries"][0]["classification"] == "expired"

    repaired = repair_locks(
        workspace,
        apply=True,
        reason="Repair migrated bundle-local expired lock.",
    )
    assert repaired["repaired"] == [task.id]
    assert not bundle_lock_path.exists()


def test_recovery_repairs_dangling_active_task_orphan_lock_and_partial_allocation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    task = create_task(
        workspace, title="Interrupted task", description="", slug="interrupted"
    )
    activate_task(workspace, task.id, reason="test setup")
    start_planning(workspace, task.id)
    paths = resolve_v2_paths(workspace)
    lock_path = task_lock_path(paths, task.id)
    assert read_lock(lock_path) is not None

    task_markdown_path(paths, task.id).unlink()

    doctor = inspect_v2_project(workspace)
    assert doctor["healthy"] is False
    assert any(task.id in error for error in doctor["errors"])
    incomplete = doctor["incomplete_task_allocations"]
    assert isinstance(incomplete, list)
    assert incomplete[0]["task_id"] == task.id

    lock_dry_run = repair_locks(workspace)
    assert lock_dry_run["dry_run"] is True
    lock_entries = lock_dry_run["entries"]
    assert isinstance(lock_entries, list)
    assert lock_entries[0]["classification"] == "orphan_missing_task"

    with pytest.raises(LaunchError):
        deactivate_task(workspace, reason="", force=True)
    cleared = deactivate_task(
        workspace, reason="Clear dangling active task after record loss.", force=True
    )
    assert cleared["active"] is False
    assert load_active_task_state(workspace) is None
    events = load_events(paths.events_dir)
    assert any(
        event.event == "repair.active_task_cleared" and event.task_id == task.id
        for event in events
    )
    assert read_lock(lock_path) is not None

    lock_repair = repair_locks(
        workspace,
        apply=True,
        reason="Preserve and remove the orphaned runtime lock.",
    )
    assert lock_repair["orphan_missing_task_repaired"] == [task.id]
    assert read_lock(lock_path) is None
    sidecar_index = load_sidecar_index(paths)
    assert sidecar_index[task.task_uuid]["locks"]["has_lock"] is False
    recovery_locks = paths.ledger_dir / "recovery" / "orphan-locks" / task.id
    audit_files = list(recovery_locks.glob("broken-lock-*.yaml"))
    assert len(audit_files) == 1
    events = load_events(paths.events_dir)
    assert any(event.event == "repair.orphan_lock_broken" for event in events)

    allocation_dry_run = repair_allocations(workspace)
    assert allocation_dry_run["dry_run"] is True
    allocation_entries = allocation_dry_run["incomplete_allocations"]
    assert isinstance(allocation_entries, list)
    assert allocation_entries[0]["display_task_id"] == task.id
    assert any(
        str(identity.task_uuid) == task.task_uuid and identity.state == "incomplete"
        for identity in task_identity_inventory(paths).entries
    )

    allocation_repair = repair_allocations(
        workspace,
        apply=True,
        all_allocations=True,
        plan_id=allocation_dry_run["plan_id"],
        reason="Quarantine incomplete task data without reusing its ID.",
    )
    repaired = allocation_repair["repaired"]
    assert isinstance(repaired, list)
    assert repaired, allocation_repair["failed"]
    assert repaired[0]["task_uuid"] == task.task_uuid
    quarantined = Path(repaired[0]["quarantined_path"])
    assert (quarantined / "runs").is_dir()
    assert not (paths.tasks_dir / task.task_uuid).exists()
    assert (paths.ledger_dir / "tombstones" / f"{task.task_uuid}.toml").is_file()
    tombstone = next(
        identity
        for identity in task_identity_inventory(paths).entries
        if str(identity.task_uuid) == task.task_uuid
    )
    assert tombstone.state == "tombstone"
    assert tombstone.task_id == task.id
    events = load_events(paths.events_dir)
    assert any(event.event == "repair.task_allocation_quarantined" for event in events)


def test_reconcile_misattributed_tombstone_preserves_recovery_payload(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    live_uuid = "00dc6acf-ac25-76b7-9c95-3e6e51ff322d"
    live_dir = paths.tasks_dir / live_uuid
    live_dir.mkdir()
    write_markdown_front_matter(
        live_dir / "task.md", {"object_type": "task", "id": "task-0037"}, ""
    )

    quarantine = (
        paths.ledger_dir / "_recovery" / "incomplete-task-allocations" / "task-0037"
    )
    quarantine.mkdir(parents=True)
    payload_file = quarantine / "partial.bin"
    payload_file.write_bytes(b"preserve this recovered payload")
    write_task_id_tombstone(
        paths,
        "task-0037",
        reason="Earlier repair used the computed display ID.",
        quarantined_path=quarantine,
    )
    append_task_event(
        workspace,
        "*",
        "repair.task_allocation_quarantined",
        {
            "task_id": "task-0037",
            "quarantined_path": "_recovery/incomplete-task-allocations/task-0037",
            "tombstone_path": "tombstones/task-0037.toml",
        },
    )

    before = audit_allocation_repairs(workspace)
    before_entries = before["entries"]
    assert isinstance(before_entries, list)
    assert before_entries[0]["status"] == "unverifiable"

    dry_run = reconcile_allocation_tombstone(
        workspace, source_id="task-0019", tombstone_id="task-0037"
    )
    assert dry_run["evidence_status"] == "operator_asserted"
    assert "independent physical evidence" in str(dry_run["warning"])
    with pytest.raises(LaunchError) as exc_info:
        reconcile_allocation_tombstone(
            workspace,
            source_id="task-0019",
            tombstone_id="task-0037",
            apply=True,
            reason=(
                "Correct the source attribution using the reviewed physical evidence."
            ),
            plan_id="stale-plan",
        )
    assert exc_info.value.code == "TASKLEDGER_REPAIR_PLAN_CHANGED"
    assert payload_file.read_bytes() == b"preserve this recovered payload"

    applied = reconcile_allocation_tombstone(
        workspace,
        source_id="task-0019",
        tombstone_id="task-0037",
        apply=True,
        reason="Physical source directory was task-0019, not the computed display ID.",
        plan_id=str(dry_run["plan_id"]),
    )
    assert applied["status"] == "applied"
    assert payload_file.read_bytes() == b"preserve this recovered payload"
    assert not (paths.ledger_dir / "tombstones" / "task-0037.toml").exists()
    assert (paths.ledger_dir / "tombstones" / "task-0019.toml").is_file()
    assert (
        paths.ledger_dir
        / "recovery"
        / "misattributed-allocation-tombstones"
        / "task-0037.toml"
    ).is_file()
    inventory = task_identity_inventory(paths)
    assert any(
        identity.legacy_task_id == "task-0037" and identity.state == "live"
        for identity in inventory.entries
    )
    assert any(
        identity.legacy_task_id == "task-0019" and identity.state == "tombstone"
        for identity in inventory.entries
    )
    after = audit_allocation_repairs(workspace)
    after_entries = after["entries"]
    assert isinstance(after_entries, list)
    assert after_entries[0]["status"] == "reconciled"


def test_relation_repair_requires_reviewed_plan_and_audits_parent_and_requirement(
    tmp_path: Path,
) -> None:
    from taskledger.api.tasks import add_requirement
    from taskledger.storage.task_store import load_requirements

    workspace = _workspace(tmp_path)
    parent = create_task(
        workspace, title="Parent", description="", slug="relation-parent"
    )
    child = create_task(workspace, title="Child", description="", slug="relation-child")
    paths = resolve_v2_paths(workspace)
    child_uuid = child.task_uuid
    parent_uuid = parent.task_uuid
    assert child_uuid and parent_uuid

    task_path = paths.tasks_dir / child_uuid / "task.md"
    task_metadata, task_body = read_markdown_front_matter(task_path)
    task_metadata["parent_task_id"] = parent.id
    task_metadata.pop("parent_task_uuid", None)
    write_markdown_front_matter(task_path, task_metadata, task_body)
    task_source_before = task_path.read_bytes()

    parent_plan = repair_task_relation(
        workspace,
        task_uuid=child_uuid,
        field="parent_task_uuid",
    )
    assert parent_plan["status"] == "dry_run"
    assert parent_plan["target_task_uuid"] == parent_uuid
    assert task_path.read_bytes() == task_source_before

    import json

    from typer.testing import CliRunner

    from taskledger.cli import app

    cli_plan = CliRunner().invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "repair",
            "relation",
            "--task-uuid",
            child_uuid,
            "--field",
            "parent_task_uuid",
        ],
    )
    assert cli_plan.exit_code == 0, cli_plan.stdout
    assert json.loads(cli_plan.stdout)["result"]["status"] == "dry_run"
    parent_applied = repair_task_relation(
        workspace,
        task_uuid=child_uuid,
        field="parent_task_uuid",
        apply=True,
        plan_id=str(parent_plan["plan_id"]),
        reason="Restore the authoritative parent UUID from its unique alias.",
    )
    assert parent_applied["status"] == "applied"
    updated_task, _ = read_markdown_front_matter(task_path)
    assert updated_task["parent_task_uuid"] == parent_uuid

    add_requirement(workspace, child.id, parent.id)
    requirement = load_requirements(workspace, child.id).requirements[0]
    assert requirement.id
    requirement_path = (
        paths.tasks_dir / child_uuid / "requirements" / f"{requirement.id}.md"
    )
    requirement_metadata, requirement_body = read_markdown_front_matter(
        requirement_path
    )
    requirement_metadata.pop("required_task_uuid", None)
    write_markdown_front_matter(
        requirement_path, requirement_metadata, requirement_body
    )

    required_plan = repair_task_relation(
        workspace,
        task_uuid=child_uuid,
        field="required_task_uuid",
        requirement_id=requirement.id,
    )
    assert required_plan["status"] == "dry_run"
    assert required_plan["target_task_uuid"] == parent_uuid
    changed_metadata, changed_body = read_markdown_front_matter(requirement_path)
    changed_metadata["required_status"] = "cancelled"
    write_markdown_front_matter(requirement_path, changed_metadata, changed_body)
    changed_source = requirement_path.read_bytes()
    with pytest.raises(LaunchError) as changed_plan:
        repair_task_relation(
            workspace,
            task_uuid=child_uuid,
            field="required_task_uuid",
            requirement_id=requirement.id,
            apply=True,
            plan_id=str(required_plan["plan_id"]),
            reason="The reviewed requirement source changed.",
        )
    assert changed_plan.value.code == "TASKLEDGER_REPAIR_PLAN_CHANGED"
    assert requirement_path.read_bytes() == changed_source

    refreshed_plan = repair_task_relation(
        workspace,
        task_uuid=child_uuid,
        field="required_task_uuid",
        requirement_id=requirement.id,
    )
    required_applied = repair_task_relation(
        workspace,
        task_uuid=child_uuid,
        field="required_task_uuid",
        requirement_id=requirement.id,
        apply=True,
        plan_id=str(refreshed_plan["plan_id"]),
        reason="Restore the required-task UUID after reviewing its source.",
    )
    assert required_applied["status"] == "applied"
    repaired_requirement, _ = read_markdown_front_matter(requirement_path)
    assert repaired_requirement["required_task_uuid"] == parent_uuid
    events = load_events(paths.events_dir)
    repair_events = [
        event
        for event in events
        if event.event == "repair.task_relation_uuid_backfilled"
    ]
    assert len(repair_events) == 2
    assert all(event.task_uuid == child_uuid for event in repair_events)


def test_relation_repair_refuses_ambiguous_identity_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import taskledger.storage.task_identity as identity_module

    workspace = _workspace(tmp_path)
    target = create_task(workspace, title="Target", description="", slug="target")
    child = create_task(workspace, title="Child", description="", slug="child")
    assert target.id and child.task_uuid
    paths = resolve_v2_paths(workspace)
    source_path = paths.tasks_dir / str(child.task_uuid) / "task.md"
    metadata, body = read_markdown_front_matter(source_path)
    metadata["parent_task_id"] = target.id
    metadata.pop("parent_task_uuid", None)
    write_markdown_front_matter(source_path, metadata, body)
    original = source_path.read_bytes()

    def ambiguous(*_args, **_kwargs):
        raise LaunchError(
            "Ambiguous legacy task reference.",
            code="TASKLEDGER_AMBIGUOUS_LEGACY_TASK_REF",
        )

    monkeypatch.setattr(identity_module, "task_identity_for_stored_ref", ambiguous)
    with pytest.raises(LaunchError) as caught:
        repair_task_relation(
            workspace,
            task_uuid=str(child.task_uuid),
            field="parent_task_uuid",
        )

    assert caught.value.code == "TASKLEDGER_RELATION_RESOLUTION_FAILED"
    assert caught.value.details["field"] == "parent_task_uuid"
    assert caught.value.details["source"] == str(source_path)
    assert source_path.read_bytes() == original


def test_bulk_allocation_repair_preflights_all_entries_before_moving(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths, shadowed_source, _migrated_dir, _migrated_uuid = (
        _shadowed_migrated_allocation(workspace)
    )
    blocked_source = paths.tasks_dir / "task-0014"
    blocked_source.mkdir()
    blocked_payload = blocked_source / "partial.bin"
    blocked_payload.write_bytes(b"keep blocked source")
    prior_quarantine = paths.ledger_dir / "_recovery" / "prior" / "task-0014"
    prior_quarantine.mkdir(parents=True)
    write_task_id_tombstone(
        paths,
        "task-0014",
        reason="Existing claimant blocks bulk repair.",
        quarantined_path=prior_quarantine,
    )

    dry_run = repair_allocations(workspace, all_allocations=True)
    entries = dry_run["incomplete_allocations"]
    assert dry_run["apply_safe"] is False
    assert {entry["repair_mode"] for entry in entries} == {
        "quarantine_shadowed_legacy_source",
        "blocked_identity_conflict",
    }
    with pytest.raises(LaunchError) as caught:
        repair_allocations(
            workspace,
            all_allocations=True,
            apply=True,
            plan_id=str(dry_run["plan_id"]),
            reason="Refuse partially safe bulk allocation repair.",
        )

    assert caught.value.code == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    assert shadowed_source.is_dir()
    assert blocked_source.is_dir()
    assert blocked_payload.read_bytes() == b"keep blocked source"
    assert not (paths.ledger_dir / "tombstones" / "task-0012.toml").exists()
    quarantine = paths.ledger_dir / "_recovery" / "incomplete-task-allocations"
    assert not (quarantine / "task-0012").exists()


def test_allocation_cli_failed_output_uses_physical_source_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from taskledger.api import repair as repair_api
    from taskledger.cli import app

    workspace = _workspace(tmp_path)
    monkeypatch.setattr(
        repair_api,
        "repair_allocations",
        lambda *_args, **_kwargs: {
            "kind": "task_allocation_repair",
            "status": "applied",
            "dry_run": False,
            "repaired": [],
            "failed": [{"source_id": "task-0019", "error": "injected failure"}],
        },
    )
    result = CliRunner().invoke(
        app,
        [
            "--root",
            str(workspace),
            "repair",
            "allocations",
            "--task-id",
            "task-0019",
            "--apply",
            "--plan-id",
            "reviewed-plan",
            "--reason",
            "test failure rendering",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "failed: task-0019: injected failure" in result.output


def test_task37_task38_task19_recovery_end_to_end(tmp_path: Path) -> None:
    from taskledger.domain.models import DependencyRequirement, TaskRecord
    from taskledger.services.doctor import (
        inspect_v2_indexes,
        inspect_v2_locks,
        inspect_v2_schema,
    )
    from taskledger.storage.indexes import rebuild_v2_indexes
    from taskledger.storage.task_store import list_tasks, load_requirements

    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    task37_uuid = "00000000-0000-7000-8000-000000000037"
    task38_uuid = "00000000-0000-7000-8000-000000000038"

    task37 = TaskRecord(
        id="task-0037",
        slug="task-0037",
        title="Task 37",
        body="Authoritative live task.",
        status_stage="draft",
        task_uuid=task37_uuid,
        created_at="2025-01-01T10:00:00+00:00",
    )
    task38 = TaskRecord(
        id="task-0038",
        slug="task-0038",
        title="Task 38",
        body="References task 37 by UUID.",
        status_stage="draft",
        task_uuid=task38_uuid,
        parent_task_id=task37.id,
        parent_task_uuid=task37_uuid,
        parent_relation="follow_up",
        created_at="2025-01-02T10:00:00+00:00",
    )
    for task in (task37, task38):
        bundle = paths.tasks_dir / str(task.task_uuid)
        bundle.mkdir(parents=True)
        metadata = task.to_dict()
        body = metadata.pop("body")
        metadata["legacy_task_id"] = task.id
        assert isinstance(body, str)
        write_markdown_front_matter(bundle / "task.md", metadata, body)

    requirement = DependencyRequirement(
        id="req-e2e",
        task_id=task37.id,
        required_task_id=task37.id,
        required_task_uuid=task37_uuid,
        parent_task_id=task38.id,
        parent_task_uuid=task38_uuid,
    )
    requirements_dir = paths.tasks_dir / task38_uuid / "requirements"
    requirements_dir.mkdir()
    write_markdown_front_matter(
        requirements_dir / "req-e2e.md", requirement.to_dict(), "Requires task 37."
    )

    old_quarantine = (
        paths.ledger_dir / "_recovery" / "incomplete-task-allocations" / "task-0037"
    )
    old_quarantine.mkdir(parents=True)
    recovery_payload = old_quarantine / "partial.bin"
    recovery_payload.write_bytes(b"original task-0019 physical source payload")
    write_task_id_tombstone(
        paths,
        "task-0037",
        reason="Earlier repair used the display alias instead of physical source ID.",
        quarantined_path=old_quarantine,
    )
    append_task_event(
        workspace,
        "*",
        "repair.task_allocation_quarantined",
        {
            "source_kind": "legacy_directory",
            "source_path": "tasks/task-0019",
            "legacy_task_id": "task-0019",
            "task_uuid": task37_uuid,
            "display_task_id": "task-0037",
            "quarantined_path": "_recovery/incomplete-task-allocations/task-0037",
            "tombstone_path": "tombstones/task-0037.toml",
        },
    )

    dry_run = reconcile_allocation_tombstone(
        workspace, source_id="task-0019", tombstone_id="task-0037"
    )
    assert dry_run["evidence_status"] == "verified_event"
    repaired = reconcile_allocation_tombstone(
        workspace,
        source_id="task-0019",
        tombstone_id="task-0037",
        apply=True,
        plan_id=str(dry_run["plan_id"]),
        reason="Retire the physical task-0019 source and preserve its old tombstone.",
    )
    assert repaired["status"] == "applied"
    assert (
        recovery_payload.read_bytes() == b"original task-0019 physical source payload"
    )
    assert not (paths.ledger_dir / "tombstones" / "task-0037.toml").exists()
    assert (paths.ledger_dir / "tombstones" / "task-0019.toml").is_file()

    inventory = task_identity_inventory(paths)
    task37_sources = [
        identity
        for identity in inventory.entries
        if identity.legacy_task_id == "task-0037"
    ]
    task19_sources = [
        identity
        for identity in inventory.entries
        if identity.legacy_task_id == "task-0019"
    ]
    assert len(task37_sources) == 1
    assert task37_sources[0].state == "live"
    assert str(task37_sources[0].task_uuid) == task37_uuid
    assert len(task19_sources) == 1
    assert task19_sources[0].state == "tombstone"

    tasks = list_tasks(workspace)
    child = next(task for task in tasks if task.task_uuid == task38_uuid)
    assert child.parent_task_uuid == task37_uuid
    requirement_after_repair = load_requirements(workspace, child.id).requirements[0]
    assert requirement_after_repair.required_task_uuid == task37_uuid
    assert requirement_after_repair.parent_task_uuid == task38_uuid

    rebuild_v2_indexes(paths)
    assert inspect_v2_indexes(workspace)["healthy"] is True
    doctor = inspect_v2_project(workspace)
    assert doctor["healthy"] is True, doctor
    assert inspect_v2_schema(workspace)["healthy"] is True
    assert inspect_v2_locks(workspace)["healthy"] is True
    audit = audit_allocation_repairs(workspace)
    audit_entries = audit["entries"]
    assert isinstance(audit_entries, list)
    assert audit_entries[0]["status"] == "reconciled"
    assert audit_entries[0]["physical_source_id"] == "task-0019"

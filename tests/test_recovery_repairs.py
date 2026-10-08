from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from taskledger.api.repair import (
    audit_allocation_repairs,
    reconcile_allocation_tombstone,
    repair_active_task,
    repair_allocations,
    repair_locks,
    repair_task_relation,
)
from taskledger.domain.active_state import ActiveTaskState
from taskledger.errors import LaunchError
from taskledger.services.allocation_recovery import (
    list_allocation_repair_transactions,
    plan_allocation_recovery,
    recover_allocation_repair_transaction,
)
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
    identity_mutation_lock,
    inspect_task_identity_conflicts,
    scan_task_identity_inventory,
    task_identity_inventory,
)
from taskledger.storage.task_ids import write_task_id_tombstone
from taskledger.storage.task_store import (
    load_active_task_state,
    read_active_task_state_raw,
    resolve_v2_paths,
    task_lock_path,
    task_markdown_path,
)
from taskledger.storage.yaml_store import write_yaml_object


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
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


def _shadowed_migrated_allocation_batch(
    workspace: Path, legacy_task_ids: tuple[str, ...]
) -> tuple[object, dict[str, Path], dict[str, Path], dict[str, bytes]]:
    paths = resolve_v2_paths(workspace)
    tasks = [
        create_task(
            workspace,
            title=f"Migrated task {task_id}",
            description="",
            slug=f"migrated-owner-{task_id}",
        )
        for task_id in legacy_task_ids
    ]
    project_uuid = load_project_uuid(
        workspace / ".ledger" / "taskledger" / "config.toml"
    )
    assert project_uuid is not None
    stale_sources: dict[str, Path] = {}
    migrated_dirs: dict[str, Path] = {}
    live_task_bytes: dict[str, bytes] = {}
    for task_id, task in zip(legacy_task_ids, tasks, strict=True):
        source_dir = paths.tasks_dir / str(task.task_uuid)
        task_path = source_dir / "task.md"
        metadata, body = read_markdown_front_matter(task_path)
        created_at = metadata["created_at"]
        assert isinstance(created_at, str)
        migrated_uuid = deterministic_legacy_task_uuid(
            project_uuid=project_uuid,
            ledger_ref=paths.ledger_ref,
            legacy_task_id=task_id,
            created_at=created_at,
        )
        metadata["id"] = task_id
        metadata["legacy_task_id"] = task_id
        metadata["task_uuid"] = str(migrated_uuid)
        write_markdown_front_matter(task_path, metadata, body)
        migrated_dir = paths.tasks_dir / str(migrated_uuid)
        source_dir.rename(migrated_dir)
        migrated_dirs[task_id] = migrated_dir
        live_task_bytes[task_id] = (migrated_dir / "task.md").read_bytes()

        stale_dir = paths.tasks_dir / task_id
        (stale_dir / "artifacts").mkdir(parents=True)
        (stale_dir / "artifacts" / "preserve.bin").write_bytes(
            f"artifact:{task_id}".encode()
        )
        (stale_dir / "plans").mkdir()
        (stale_dir / "plans" / "preserve.md").write_text(
            f"plan sidecar {task_id}\n", encoding="utf-8"
        )
        stale_sources[task_id] = stale_dir
    return paths, stale_sources, migrated_dirs, live_task_bytes


def test_identity_conflict_inspection_groups_all_sources_and_shares_mutation_lock(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    tasks = [
        create_task(
            workspace,
            title=f"Migrated task {number}",
            description="",
            slug=f"migrated-owner-{number}",
        )
        for number in (12, 13)
    ]
    project_uuid = load_project_uuid(
        workspace / ".ledger" / "taskledger" / "config.toml"
    )
    assert project_uuid is not None

    for task, number in zip(tasks, (12, 13), strict=True):
        legacy_id = f"task-{number:04d}"
        source_dir = paths.tasks_dir / str(task.task_uuid)
        task_path = source_dir / "task.md"
        metadata, body = read_markdown_front_matter(task_path)
        created_at = metadata["created_at"]
        assert isinstance(created_at, str)
        migrated_uuid = deterministic_legacy_task_uuid(
            project_uuid=project_uuid,
            ledger_ref=paths.ledger_ref,
            legacy_task_id=legacy_id,
            created_at=created_at,
        )
        metadata["id"] = legacy_id
        metadata["legacy_task_id"] = legacy_id
        metadata["task_uuid"] = str(migrated_uuid)
        write_markdown_front_matter(task_path, metadata, body)
        source_dir.rename(paths.tasks_dir / str(migrated_uuid))
        incomplete_dir = paths.tasks_dir / legacy_id
        incomplete_dir.mkdir()
        (incomplete_dir / "sidecar.bin").write_bytes(legacy_id.encode())

    conflicts = inspect_task_identity_conflicts(paths)
    legacy_conflicts = tuple(
        finding for finding in conflicts if finding["identity_kind"] == "legacy_task_id"
    )
    assert [finding["identity"] for finding in legacy_conflicts] == [
        "task-0012",
        "task-0013",
    ]
    assert all(len(finding["sources"]) == 2 for finding in legacy_conflicts)
    assert inspect_task_identity_conflicts(paths) == conflicts
    with pytest.raises(LaunchError, match="Task identity conflict"):
        scan_task_identity_inventory(paths)

    lock = identity_mutation_lock(paths)
    assert identity_mutation_lock(paths) is lock
    with lock, identity_mutation_lock(paths):
        pass


def test_allocation_repair_commits_twelve_shadowed_sources_as_one_transaction(
    tmp_path: Path,
) -> None:
    import json

    legacy_ids = (
        "task-0012",
        "task-0013",
        "task-0014",
        "task-0015",
        "task-0019",
        "task-0020",
        "task-0022",
        "task-0023",
        "task-0024",
        "task-0025",
        "task-0026",
        "task-0029",
    )
    workspace = _workspace(tmp_path)
    paths, stale_sources, migrated_dirs, live_task_bytes = (
        _shadowed_migrated_allocation_batch(workspace, legacy_ids)
    )

    dry_run = repair_allocations(workspace, all_allocations=True)
    entries = dry_run["incomplete_allocations"]
    assert isinstance(entries, list) and len(entries) == len(legacy_ids)
    assert dry_run["apply_safe"] is True
    assert all(
        entry["repair_mode"] == "quarantine_shadowed_legacy_source"
        and entry["planned_tombstone"] is None
        for entry in entries
    )

    result = repair_allocations(
        workspace,
        all_allocations=True,
        apply=True,
        plan_id=str(dry_run["plan_id"]),
        reason="Quarantine all reviewed stale migration allocations.",
    )
    assert result["status"] == "applied"
    assert result["attempted_count"] == 12
    assert result["repaired_count"] == 12
    assert result["failed_count"] == 0
    assert result["failed"] == []
    assert result["ledger_healthy"] is True
    assert result["remaining_conflicts"] == []
    assert result["transaction_id"]

    for task_id in legacy_ids:
        assert not stale_sources[task_id].exists()
        quarantine = (
            paths.ledger_dir / "_recovery" / "incomplete-task-allocations" / task_id
        )
        assert (quarantine / "artifacts" / "preserve.bin").read_bytes() == (
            f"artifact:{task_id}".encode()
        )
        assert (quarantine / "plans" / "preserve.md").read_bytes() == (
            f"plan sidecar {task_id}\n".encode()
        )
        assert (migrated_dirs[task_id] / "task.md").read_bytes() == live_task_bytes[
            task_id
        ]
        assert not (paths.ledger_dir / "tombstones" / f"{task_id}.toml").exists()

    inventory = scan_task_identity_inventory(paths)
    assert sum(identity.state == "live" for identity in inventory.entries) == 12
    journal_path = Path(str(result["journal_path"]))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == "committed"
    assert len(journal["actions"]) == 12
    events = [
        event
        for event in load_events(paths.events_dir)
        if event.event == "repair.task_allocation_quarantined"
        and event.data.get("transaction_id") == result["transaction_id"]
    ]
    assert len(events) == 12
    assert {event.data["action_index"] for event in events} == set(range(12))
    audit = audit_allocation_repairs(workspace)
    audited_ids = {entry["physical_source_id"] for entry in audit["entries"]}
    assert set(legacy_ids) <= audited_ids


def test_doctor_reports_all_conflict_groups_and_incomplete_scan_metadata(
    tmp_path: Path,
) -> None:
    legacy_ids = ("task-0012", "task-0013")
    workspace = _workspace(tmp_path)
    _shadowed_migrated_allocation_batch(workspace, legacy_ids)

    doctor = inspect_v2_project(workspace)
    diagnostics = doctor["diagnostics"]
    reported_ids = {
        item.get("identity")
        for item in diagnostics
        if item.get("phase") == "task_identity_conflicts"
    }
    strict_conflicts = [
        item
        for item in diagnostics
        if item.get("code") == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
        and item.get("phase") == "task_identity"
    ]
    assert len(strict_conflicts) == 1
    strict_details = strict_conflicts[0]["details"]
    assert isinstance(strict_details, dict)
    reported_ids.add(strict_details["legacy_task_id"])
    assert reported_ids == set(legacy_ids)
    assert doctor["counts_complete"] is False
    assert "task_runs" in doctor["skipped_scans"]
    assert len(doctor["incomplete_task_allocations"]) == 2
    assert any(
        "taskledger --json repair allocations --all" in hint
        for hint in doctor["repair_hints"]
    )


def test_allocation_batch_rolls_back_when_fourth_stage_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_ids = ("task-0012", "task-0013", "task-0014", "task-0015")
    workspace = _workspace(tmp_path)
    paths, stale_sources, migrated_dirs, live_task_bytes = (
        _shadowed_migrated_allocation_batch(workspace, legacy_ids)
    )
    dry_run = repair_allocations(workspace, all_allocations=True)
    original_rename = Path.rename
    stage_count = 0

    def fail_fourth_stage(source: Path, target: str | Path) -> Path:
        nonlocal stage_count
        if source.parent == paths.tasks_dir:
            stage_count += 1
            if stage_count == 4:
                raise OSError("injected failure at stage four")
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_fourth_stage)
    result = repair_allocations(
        workspace,
        all_allocations=True,
        apply=True,
        plan_id=str(dry_run["plan_id"]),
        reason="Exercise allocation transaction rollback.",
    )
    assert result["status"] == "rolled_back"
    assert result["repaired_count"] == 0
    assert result["failed_count"] == 1
    assert "injected failure at stage four" in result["failed"][0]["error"]
    for task_id in legacy_ids:
        assert stale_sources[task_id].is_dir()
        assert (migrated_dirs[task_id] / "task.md").read_bytes() == live_task_bytes[
            task_id
        ]
        assert not (
            paths.ledger_dir / "_recovery" / "incomplete-task-allocations" / task_id
        ).exists()
    journal = json.loads(Path(str(result["journal_path"])).read_text(encoding="utf-8"))
    assert journal["phase"] == "rolled_back"


def test_allocation_batch_preflight_rejects_one_unsafe_owner_without_moving_any(
    tmp_path: Path,
) -> None:
    legacy_ids = ("task-0012", "task-0013")
    workspace = _workspace(tmp_path)
    duplicate_task = create_task(
        workspace,
        title="Second legacy-ID owner",
        description="",
        slug="duplicate-legacy-owner",
    )
    paths, stale_sources, migrated_dirs, _ = _shadowed_migrated_allocation_batch(
        workspace, legacy_ids
    )
    duplicate_task_path = paths.tasks_dir / str(duplicate_task.task_uuid) / "task.md"
    metadata, body = read_markdown_front_matter(duplicate_task_path)
    metadata["id"] = "task-0013"
    metadata["legacy_task_id"] = "task-0013"
    write_markdown_front_matter(duplicate_task_path, metadata, body)
    dry_run = repair_allocations(workspace, all_allocations=True)
    assert dry_run["apply_safe"] is False
    with pytest.raises(LaunchError) as error:
        repair_allocations(
            workspace,
            all_allocations=True,
            apply=True,
            plan_id=str(dry_run["plan_id"]),
            reason="Attempt unsafe allocation batch.",
        )
    assert error.value.code == "TASKLEDGER_TASK_IDENTITY_CONFLICT"
    for task_id in legacy_ids:
        assert stale_sources[task_id].is_dir()
        assert migrated_dirs[task_id].is_dir()
        assert not (
            paths.ledger_dir / "_recovery" / "incomplete-task-allocations" / task_id
        ).exists()


def test_interrupted_allocation_transaction_requires_reviewed_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_ids = ("task-0012", "task-0013")
    workspace = _workspace(tmp_path)
    paths, stale_sources, _, _ = _shadowed_migrated_allocation_batch(
        workspace, legacy_ids
    )
    dry_run = repair_allocations(workspace, all_allocations=True)
    first_source = stale_sources[legacy_ids[0]]
    original_rename = Path.rename
    interrupted = False

    def crash_after_first_stage(source: Path, target: str | Path) -> Path:
        nonlocal interrupted
        result = original_rename(source, target)
        if source == first_source and not interrupted:
            interrupted = True
            raise SystemExit("simulated process interruption")
        return result

    monkeypatch.setattr(Path, "rename", crash_after_first_stage)
    with pytest.raises(SystemExit, match="simulated process interruption"):
        repair_allocations(
            workspace,
            all_allocations=True,
            apply=True,
            plan_id=str(dry_run["plan_id"]),
            reason="Exercise interrupted transaction recovery.",
        )
    monkeypatch.setattr(Path, "rename", original_rename)

    transactions = list_allocation_repair_transactions(paths)["transactions"]
    transaction_id = str(transactions[0]["transaction_id"])
    recovery = plan_allocation_recovery(paths, transaction_id)
    assert recovery["action"] == "rollback"
    assert recovery["phase"] == "staging"
    assert not first_source.exists()
    assert Path(str(recovery["actions"][0]["quarantine_path"])).is_dir()

    recovered = recover_allocation_repair_transaction(
        workspace,
        paths,
        transaction_id,
        apply=True,
        plan_id=str(recovery["plan_id"]),
        reason="Restore the interrupted allocation transaction.",
    )
    assert recovered["status"] == "rolled_back"
    assert first_source.is_dir()
    assert stale_sources[legacy_ids[1]].is_dir()
    journal = json.loads(
        Path(str(recovery["journal_path"])).read_text(encoding="utf-8")
    )
    assert journal["phase"] == "rolled_back"


def test_allocation_recovery_replays_missing_audit_events_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from taskledger.services import task_events

    legacy_ids = ("task-0012", "task-0013")
    workspace = _workspace(tmp_path)
    paths, _, _, _ = _shadowed_migrated_allocation_batch(workspace, legacy_ids)
    dry_run = repair_allocations(workspace, all_allocations=True)
    original_append = task_events.append_task_event
    failed_once = False

    def append_then_fail_once(*args: object, **kwargs: object) -> object:
        nonlocal failed_once
        event = original_append(*args, **kwargs)
        if not failed_once:
            failed_once = True
            raise OSError("injected audit append interruption")
        return event

    monkeypatch.setattr(task_events, "append_task_event", append_then_fail_once)
    result = repair_allocations(
        workspace,
        all_allocations=True,
        apply=True,
        plan_id=str(dry_run["plan_id"]),
        reason="Exercise audit replay after allocation commit.",
    )
    assert result["status"] == "audit_pending"
    transaction_id = str(result["transaction_id"])
    initial_events = [
        event
        for event in load_events(paths.events_dir)
        if event.event == "repair.task_allocation_quarantined"
        and event.data.get("transaction_id") == transaction_id
    ]
    assert len(initial_events) == 1

    recovery = plan_allocation_recovery(paths, transaction_id)
    assert recovery["action"] == "replay_audit"
    recovered = recover_allocation_repair_transaction(
        workspace,
        paths,
        transaction_id,
        apply=True,
        plan_id=str(recovery["plan_id"]),
        reason="Replay the remaining allocation audit events.",
    )
    assert recovered["status"] == "committed"
    final_events = [
        event
        for event in load_events(paths.events_dir)
        if event.event == "repair.task_allocation_quarantined"
        and event.data.get("transaction_id") == transaction_id
    ]
    assert len(final_events) == 2
    assert {event.data["action_index"] for event in final_events} == {0, 1}


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
    runner = CliRunner()
    args = [
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
    ]
    result = runner.invoke(app, args)
    assert result.exit_code != 0, result.output
    assert "failed: task-0019: injected failure" in result.output
    assert "0 committed" in result.output

    json_result = runner.invoke(app, [*args[:2], "--json", *args[2:]])
    assert json_result.exit_code != 0, json_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["details"]["failed"][0]["source_id"] == "task-0019"
    assert payload["error"]["details"]["attempted_count"] == 1


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


def test_active_task_recovery_clears_only_proven_missing_reference_with_backup(
    tmp_path: Path,
) -> None:
    import shutil
    from base64 import b64decode

    workspace = _workspace(tmp_path)
    task = create_task(workspace, title="Lost task", description="", slug="lost-task")
    activate_task(workspace, task.id, reason="test setup")
    paths = resolve_v2_paths(workspace)
    original_bytes = paths.active_task_path.read_bytes()
    shutil.rmtree(paths.tasks_dir / task.task_uuid)

    doctor = inspect_v2_project(workspace)
    active_diagnostics = [
        item
        for item in doctor["diagnostics"]
        if item.get("code") == "ACTIVE_TASK_REFERENCE_MISSING"
    ]
    assert len(active_diagnostics) == 1, doctor["diagnostics"]
    assert active_diagnostics[0]["task_uuid"] == task.task_uuid

    plan = repair_active_task(workspace, action="clear")
    assert plan["apply_safe"] is True, plan["blocked_reasons"]
    assert plan["inspection"]["classification"] == "missing"
    result = repair_active_task(
        workspace,
        action="clear",
        apply=True,
        plan_id=str(plan["plan_id"]),
        reason="Clear the reviewed active pointer to a missing task record.",
    )
    assert result["status"] == "applied"
    assert not paths.active_task_path.exists()
    backup = json.loads(Path(str(result["backup_path"])).read_text(encoding="utf-8"))
    assert b64decode(backup["original_bytes_base64"]) == original_bytes
    assert backup["sha256"] == plan["active_task_sha256"]
    assert (
        json.loads(Path(str(result["journal_path"])).read_text(encoding="utf-8"))[
            "phase"
        ]
        == "committed"
    )
    assert any(
        event.event == "repair.active_task_cleared"
        and event.data.get("transaction_id") == result["transaction_id"]
        for event in load_events(paths.events_dir)
    )


def test_active_task_recovery_cli_uses_reviewed_plan_and_reports_success(
    tmp_path: Path,
) -> None:
    import shutil

    from typer.testing import CliRunner

    from taskledger.cli import app

    workspace = _workspace(tmp_path)
    task = create_task(workspace, title="Lost task", description="", slug="lost-task")
    activate_task(workspace, task.id, reason="test setup")
    paths = resolve_v2_paths(workspace)
    shutil.rmtree(paths.tasks_dir / task.task_uuid)

    runner = CliRunner()
    preview = runner.invoke(
        app,
        ["--root", str(workspace), "--json", "repair", "active-task"],
    )
    assert preview.exit_code == 0, preview.stdout
    preview_payload = json.loads(preview.stdout)
    plan = preview_payload["result"]
    assert plan["kind"] == "active_task_repair"
    assert plan["apply_safe"] is True

    applied = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "--json",
            "repair",
            "active-task",
            "--apply",
            "--plan-id",
            str(plan["plan_id"]),
            "--reason",
            "Clear the reviewed pointer to the missing task.",
        ],
    )
    assert applied.exit_code == 0, applied.stdout
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["ok"] is True
    assert applied_payload["result"]["status"] == "applied"
    assert Path(applied_payload["result"]["backup_path"]).exists()
    assert not paths.active_task_path.exists()


def test_active_task_recovery_requires_safe_clear_and_explicit_rebind(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    first = create_task(workspace, title="Owner one", description="", slug="owner-one")
    second = create_task(workspace, title="Owner two", description="", slug="owner-two")
    paths = resolve_v2_paths(workspace)
    for task in (first, second):
        task_path = paths.tasks_dir / task.task_uuid / "task.md"
        metadata, body = read_markdown_front_matter(task_path)
        metadata["id"] = "task-0012"
        metadata["legacy_task_id"] = "task-0012"
        write_markdown_front_matter(task_path, metadata, body)
    historical_uuid = str(first.task_uuid)
    write_yaml_object(
        paths.active_task_path,
        ActiveTaskState(
            task_id="task-0012",
            previous_task_id="task-0009",
            previous_task_uuid=historical_uuid,
        ).to_dict(),
    )
    original_bytes = paths.active_task_path.read_bytes()

    clear_plan = repair_active_task(workspace, action="clear")
    assert clear_plan["inspection"]["classification"] == "ambiguous"
    assert clear_plan["apply_safe"] is False
    with pytest.raises(LaunchError):
        repair_active_task(
            workspace,
            action="clear",
            apply=True,
            plan_id=str(clear_plan["plan_id"]),
            reason="Refuse ambiguous active pointer clearing.",
        )

    rebind_plan = repair_active_task(
        workspace, action="rebind", target_uuid=second.task_uuid
    )
    assert rebind_plan["apply_safe"] is True, rebind_plan["blocked_reasons"]
    result = repair_active_task(
        workspace,
        action="rebind",
        target_uuid=second.task_uuid,
        apply=True,
        plan_id=str(rebind_plan["plan_id"]),
        reason="Rebind to the explicitly reviewed UUID owner.",
    )
    assert result["status"] == "applied"
    rebound = read_active_task_state_raw(paths)
    assert rebound is not None
    assert rebound.task_uuid == second.task_uuid
    assert rebound.previous_task_id == "task-0009"
    assert rebound.previous_task_uuid == historical_uuid
    backup = json.loads(Path(str(result["backup_path"])).read_text(encoding="utf-8"))
    assert base64.b64decode(backup["original_bytes_base64"]) == original_bytes
    assert any(
        event.event == "repair.active_task_rebound"
        and event.data.get("transaction_id") == result["transaction_id"]
        for event in load_events(paths.events_dir)
    )

    valid_workspace = _workspace(tmp_path / "valid")
    valid_task = create_task(
        valid_workspace, title="Valid pointer", description="", slug="valid-pointer"
    )
    activate_task(valid_workspace, valid_task.id, reason="test setup")
    valid_plan = repair_active_task(valid_workspace, action="clear")
    assert valid_plan["inspection"]["classification"] == "valid"
    assert valid_plan["apply_safe"] is False

    numeric_workspace = _workspace(tmp_path / "numeric")
    numeric_task = create_task(
        numeric_workspace,
        title="Display alias owner",
        description="",
        slug="numeric-alias-owner",
    )
    numeric_paths = resolve_v2_paths(numeric_workspace)
    write_yaml_object(
        numeric_paths.active_task_path,
        ActiveTaskState(task_id=numeric_task.id).to_dict(),
    )
    numeric_plan = repair_active_task(numeric_workspace, action="clear")
    assert numeric_plan["inspection"]["classification"] == "resolution_blocked"
    assert numeric_plan["apply_safe"] is False


def test_active_task_repair_blocks_running_run_and_lock_and_rejects_changed_yaml(
    tmp_path: Path,
) -> None:
    import shutil

    workspace = _workspace(tmp_path)
    task = create_task(workspace, title="Running task", description="", slug="running")
    activate_task(workspace, task.id, reason="test setup")
    start_planning(workspace, task.id)
    paths = resolve_v2_paths(workspace)
    task_markdown_path(paths, task.id).unlink()
    protected_plan = repair_active_task(workspace, action="clear")
    assert protected_plan["inspection"]["classification"] == "missing"
    assert protected_plan["inspection"]["protected"] is True
    assert protected_plan["apply_safe"] is False

    missing_workspace = _workspace(tmp_path / "changed")
    lost = create_task(missing_workspace, title="Lost", description="", slug="lost")
    activate_task(missing_workspace, lost.id, reason="test setup")
    missing_paths = resolve_v2_paths(missing_workspace)
    original = missing_paths.active_task_path.read_bytes()
    shutil.rmtree(missing_paths.tasks_dir / lost.task_uuid)
    reviewed = repair_active_task(missing_workspace, action="clear")
    missing_paths.active_task_path.write_bytes(original + b"# external change\n")
    with pytest.raises(LaunchError) as error:
        repair_active_task(
            missing_workspace,
            action="clear",
            apply=True,
            plan_id=str(reviewed["plan_id"]),
            reason="Reject changed active-task YAML.",
        )
    assert error.value.code == "TASKLEDGER_REPAIR_PLAN_CHANGED"
    assert (
        missing_paths.active_task_path.read_bytes() == original + b"# external change\n"
    )


def test_malformed_active_task_yaml_is_diagnosed_and_never_cleared(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    malformed = b"task_id: [unterminated\xff"
    paths.active_task_path.write_bytes(malformed)

    doctor = inspect_v2_project(workspace)
    assert any(
        item.get("code") == "ACTIVE_TASK_STATE_MALFORMED"
        for item in doctor["diagnostics"]
    )
    plan = repair_active_task(workspace, action="clear")
    assert plan["inspection"]["classification"] == "malformed"
    assert plan["apply_safe"] is False
    with pytest.raises(LaunchError):
        repair_active_task(
            workspace,
            action="clear",
            apply=True,
            plan_id=str(plan["plan_id"]),
            reason="Do not discard malformed pointer bytes.",
        )
    assert paths.active_task_path.read_bytes() == malformed

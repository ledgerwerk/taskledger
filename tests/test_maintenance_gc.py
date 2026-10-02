from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.api.maintenance import garbage_collect
from taskledger.cli import app
from taskledger.errors import LaunchError
from taskledger.services.task_lifecycle import activate_task, record_completed_task
from taskledger.services.tasks import create_task, start_planning
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.task_store import (
    list_runs_from_paths,
    resolve_v2_paths,
    save_run,
    task_artifacts_dir,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_canonical_project_state(workspace, create_sibling_store=True)
    return workspace


def _recorded_task(workspace: Path, slug: str = "finished") -> str:
    result = record_completed_task(
        workspace,
        title="Completed task",
        summary="Recorded completion for maintenance tests.",
        slug=slug,
        changes=(("src.py", "edit", "Changed the test fixture."),),
    )
    task_id = result["task_id"]
    assert isinstance(task_id, str)
    return task_id


def _make_old(path: Path, *, days: int = 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("garbage-candidate", encoding="utf-8")
    old_time = path.stat().st_mtime - days * 86400
    os.utime(path, (old_time, old_time))


def test_gc_marks_referenced_files_and_applies_only_reported_old_artifacts(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    task_id = _recorded_task(workspace)
    paths = resolve_v2_paths(workspace)
    artifact_root = task_artifacts_dir(paths, task_id)
    old_unreferenced = artifact_root / "old-unreferenced.log"
    old_referenced = artifact_root / "old-referenced.log"
    young_unreferenced = artifact_root / "young-unreferenced.log"
    _make_old(old_unreferenced)
    _make_old(old_referenced)
    young_unreferenced.write_text("keep", encoding="utf-8")

    run = next(
        run
        for run in list_runs_from_paths(paths, task_id)
        if run.run_type == "implementation"
    )
    reference = old_referenced.relative_to(paths.project_dir).as_posix()
    save_run(workspace, replace(run, artifact_refs=(reference,)))

    dry_run = garbage_collect(workspace, scope="artifacts", older_than="30d")
    candidates = dry_run["candidates"]
    assert isinstance(candidates, list)
    assert [item["path"] for item in candidates] == [str(old_unreferenced)]
    expected_bytes = old_unreferenced.stat().st_size
    assert dry_run["bytes_reclaimable"] == expected_bytes

    with pytest.raises(LaunchError, match="requires --reason"):
        garbage_collect(workspace, scope="artifacts", older_than="30d", apply=True)
    assert old_unreferenced.is_file()

    applied = garbage_collect(
        workspace,
        scope="artifacts",
        older_than="30d",
        apply=True,
        reason="Remove unreferenced terminal-task output after retention.",
    )
    assert applied["status"] == "applied"
    assert applied["files_reclaimed"] == 1
    assert applied["bytes_reclaimed"] == expected_bytes
    assert not old_unreferenced.exists()
    assert old_referenced.is_file()
    assert young_unreferenced.is_file()
    audit_path = paths.ledger_dir / str(applied["audit_path"])
    assert audit_path.is_file()


def test_gc_runtime_snapshot_requires_terminal_summarized_run_and_retention(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    task_id = _recorded_task(workspace)
    paths = resolve_v2_paths(workspace)
    run = next(
        run
        for run in list_runs_from_paths(paths, task_id)
        if run.run_type == "implementation"
    )
    snapshot = (
        paths.runtime_root
        / "checkouts"
        / paths.ledger_ref
        / "workspace-snapshots"
        / task_id
        / f"{run.run_id}.workspace-snapshot.json"
    )
    _make_old(snapshot, days=20)
    snapshot_ref = snapshot.relative_to(paths.runtime_root).as_posix()
    snapshot_ref = f"runtime/{snapshot_ref}"
    save_run(
        workspace,
        replace(
            run,
            workspace_snapshot_ref=snapshot_ref,
            workspace_content_hash="content-hash",
            workspace_paths_hash="paths-hash",
            workspace_snapshot_format="snapshot-v1",
        ),
    )

    dry_run = garbage_collect(workspace, scope="runtime")
    candidates = dry_run["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 1
    assert candidates[0]["path"] == str(snapshot)
    assert candidates[0]["reference_status"] == "terminal run summary retained"

    applied = garbage_collect(
        workspace,
        scope="runtime",
        apply=True,
        reason="Prune detailed terminal snapshot after retention.",
    )
    assert applied["files_reclaimed"] == 1
    assert not snapshot.exists()
    updated_run = next(
        run
        for run in list_runs_from_paths(paths, task_id)
        if run.run_id == snapshot.stem.removesuffix(".workspace-snapshot")
    )
    assert updated_run.workspace_content_hash == "content-hash"
    assert updated_run.workspace_paths_hash == "paths-hash"


def test_gc_preserves_active_task_artifacts_and_rejects_symlink_escape(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    active_task = create_task(workspace, title="Active", description="", slug="active")
    activate_task(workspace, active_task.id, reason="test setup")
    start_planning(workspace, active_task.id)
    paths = resolve_v2_paths(workspace)
    active_artifact = task_artifacts_dir(paths, active_task.id) / "active.log"
    _make_old(active_artifact)
    assert (
        garbage_collect(workspace, scope="artifacts", older_than="1d")["candidates"]
        == []
    )

    terminal_id = _recorded_task(workspace, slug="terminal")
    terminal_root = task_artifacts_dir(paths, terminal_id)
    old_candidate = terminal_root / "stale.log"
    _make_old(old_candidate)
    outside = tmp_path / "outside.log"
    _make_old(outside)
    terminal_root.mkdir(parents=True, exist_ok=True)
    escape = terminal_root / "escape.log"
    escape.symlink_to(outside)

    dry_run = garbage_collect(workspace, scope="artifacts", older_than="1d")
    unsafe_paths = dry_run["unsafe_paths"]
    assert isinstance(unsafe_paths, list)
    assert str(escape) in unsafe_paths
    with pytest.raises(LaunchError, match="unsafe paths"):
        garbage_collect(
            workspace,
            scope="artifacts",
            older_than="1d",
            apply=True,
            reason="Attempt unsafe cleanup for regression coverage.",
        )
    assert outside.is_file()
    with pytest.raises(LaunchError, match="canonical task ID"):
        garbage_collect(workspace, scope="artifacts", task_id="../outside")


def test_gc_removes_only_old_quarantined_cache_generations(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    paths = resolve_v2_paths(workspace)
    quarantine = paths.indexes_dir.with_name(
        f"{paths.indexes_dir.name}.quarantine-test-generation"
    )
    cache_file = quarantine / "old-index.json"
    _make_old(cache_file, days=10)
    old_time = cache_file.stat().st_mtime
    os.utime(quarantine, (old_time, old_time))

    dry_run = garbage_collect(workspace, scope="cache")
    candidates = dry_run["candidates"]
    assert isinstance(candidates, list)
    assert [candidate["path"] for candidate in candidates] == [str(quarantine)]

    applied = garbage_collect(workspace, scope="cache", apply=True)
    assert applied["status"] == "applied"
    assert applied["files_reclaimed"] == 1
    assert not quarantine.exists()


def test_gc_cli_is_dry_run_by_default_and_emits_json(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.chdir(workspace)

    result = CliRunner().invoke(
        app, ["--json", "maintenance", "gc", "--scope", "cache"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["status"] == "dry_run"

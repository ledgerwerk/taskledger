from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from taskledger.api.storage import storage_set, storage_where
from taskledger.cli import app
from taskledger.errors import CacheRecoveryFailed, LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.services.tasks import create_task
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import (
    load_project_context,
    require_mutable_project_context,
)
from taskledger.storage.task_store import list_tasks, task_markdown_path

runner = CliRunner()


def _init_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    project = tmp_path / "project"
    project.mkdir()
    context, _ = init_canonical_project_state(project, project_name="cache-test")
    return project, context


def _create_task(project: Path, title: str):
    return create_task(
        project,
        title=title,
        slug=title.lower().replace(" ", "-"),
        description="cache recovery test",
    )


def _expected_indexes(context) -> tuple[Path, ...]:
    return (
        context.paths.task_index_path,
        context.paths.active_locks_index_path,
        context.paths.sidecar_index_path,
        context.paths.introductions_index_path,
        context.paths.dependencies_index_path,
    )


def _clear_machine_local_mounts(context) -> None:
    for root in (
        context.paths.runtime_root,
        context.paths.logs_root,
        context.paths.indexes_root,
    ):
        if root.exists():
            shutil.rmtree(root)


def test_reinit_recovers_non_empty_unbound_cache_before_first_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    stale_root = context.paths.indexes_root
    (stale_root / ".ledger-project.toml").unlink()
    (stale_root / "legacy-index.json").write_text(
        '{"legacy": true}\n',
        encoding="utf-8",
    )

    reloaded, _ = init_canonical_project_state(project, project_name="cache-test")

    quarantines = sorted(stale_root.parent.glob("indexes.quarantine-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "legacy-index.json").read_text(
        encoding="utf-8"
    ) == '{"legacy": true}\n'
    assert (reloaded.paths.indexes_root / ".ledger-project.toml").is_file()
    assert reloaded.cache_recovery is not None
    assert reloaded.cache_recovery.action == "quarantined_rebuilt"

    task = _create_task(project, "first task after pull")
    assert task.id == "task-0001"
    assert len(list_tasks(project)) == 1


def test_cross_machine_init_recovers_local_cache_and_preserves_external_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pc_a = tmp_path / "pc-a"
    project_a = pc_a / "project"
    project_a.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_a / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_a / "xdg-data"))
    context_a, _ = init_canonical_project_state(
        project_a,
        project_name="cache-test",
        data_storage="external",
        external_root="../ledger",
    )
    existing_task = _create_task(project_a, "existing durable task")
    assert existing_task.id == "task-0001"

    pc_b = tmp_path / "pc-b"
    pc_b.mkdir()
    project_b = pc_b / "project"
    shutil.copytree(project_a, project_b)
    shutil.copytree(pc_a / "ledger", pc_b / "ledger")
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_b / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_b / "xdg-data"))

    before_init = load_project_context(project_b, require_initialized=False)
    stale_root = before_init.paths.indexes_root
    _clear_machine_local_mounts(before_init)
    stale_root.mkdir(parents=True)
    (stale_root / "stale-cache.json").write_text("stale\n", encoding="utf-8")

    reloaded, _ = init_canonical_project_state(project_b, project_name="cache-test")

    assert reloaded.project_uuid == context_a.project_uuid
    assert reloaded.paths.data_root == (
        pc_b / "ledger" / "taskledger" / reloaded.project_uuid / "data"
    )
    assert reloaded.paths.tasks_dir.is_dir()
    assert reloaded.paths.events_dir.is_dir()
    assert reloaded.paths.runtime_root.is_dir()
    assert reloaded.cache_recovery is not None
    assert reloaded.cache_recovery.action == "quarantined_rebuilt"
    assert reloaded.cache_recovery.quarantine_path is not None
    assert (reloaded.cache_recovery.quarantine_path / "stale-cache.json").read_text(
        encoding="utf-8"
    ) == "stale\n"

    next_task = _create_task(project_b, "next durable task")
    assert next_task.id == "task-0002"
    assert len(list_tasks(project_b)) == 2


def test_missing_cache_supports_two_consecutive_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    shutil.rmtree(context.paths.indexes_root)

    _create_task(project, "first mutation")
    _create_task(project, "second mutation")

    assert (context.paths.indexes_root / ".ledger-project.toml").is_file()
    assert all(path.is_file() for path in _expected_indexes(context))
    assert load_project_context(project).storage_validation.valid is True


def test_read_only_access_does_not_bootstrap_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    shutil.rmtree(context.paths.indexes_root)

    read_context = load_project_context(project, require_initialized=False)
    assert list_tasks(project) == []
    assert read_context.paths.indexes_root == context.paths.indexes_root
    assert not context.paths.indexes_root.exists()


def test_non_empty_unbound_cache_is_quarantined_and_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    _create_task(project, "canonical task")
    old_index = context.paths.task_index_path.read_text(encoding="utf-8")
    (context.paths.indexes_root / ".ledger-project.toml").unlink()

    _create_task(project, "recovered task")

    quarantines = sorted(context.paths.indexes_root.parent.glob("indexes.quarantine-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "ledgers" / "main" / "tasks.json").read_text(
        encoding="utf-8"
    ) == old_index
    assert (context.paths.indexes_root / ".ledger-project.toml").is_file()
    assert len(list_tasks(project)) == 2


def test_repair_index_recovers_and_reports_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    _create_task(project, "repair task")
    (context.paths.indexes_root / ".ledger-project.toml").unlink()

    result = runner.invoke(app, ["--root", str(project), "--json", "repair", "index"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    recovery = payload["result"]["cache_recovery"]
    assert recovery["action"] == "quarantined_rebuilt"
    assert Path(recovery["quarantine_path"]).is_dir()
    assert "Traceback" not in result.stdout


def test_valid_binding_rebuilds_evicted_derived_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    _create_task(project, "eviction task")
    for path in _expected_indexes(context):
        path.unlink()

    _create_task(project, "rebuilt task")

    assert all(path.is_file() for path in _expected_indexes(context))


def test_persistent_binding_failure_does_not_quarantine_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    _create_task(project, "persistent failure")
    marker = context.paths.data_root / ".ledger-project.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            f'project_uuid = "{context.project_uuid}"',
            f'project_uuid = "{uuid4()}"',
        ),
        encoding="utf-8",
    )
    (context.paths.indexes_root / ".ledger-project.toml").unlink()

    for local_root in (context.paths.runtime_root, context.paths.logs_root):
        shutil.rmtree(local_root)
    with pytest.raises(LaunchError, match="data"):
        _create_task(project, "blocked mutation")

    assert context.paths.indexes_root.exists()
    assert not list(context.paths.indexes_root.parent.glob("indexes.quarantine-*"))
    assert not context.paths.runtime_root.exists()
    assert not context.paths.logs_root.exists()


def test_foreign_cache_binding_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    _create_task(project, "foreign cache")
    marker = context.paths.indexes_root / ".ledger-project.toml"
    original = marker.read_text(encoding="utf-8")
    marker.write_text(
        original.replace(
            f'project_uuid = "{context.project_uuid}"',
            f'project_uuid = "{uuid4()}"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(LaunchError, match="binding mismatch"):
        _create_task(project, "blocked foreign cache")

    assert marker.read_text(encoding="utf-8") != original
    assert not list(context.paths.indexes_root.parent.glob("indexes.quarantine-*"))


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unavailable")
def test_symlink_cache_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    target = tmp_path / "cache-target"
    target.mkdir()
    shutil.rmtree(context.paths.indexes_root)
    context.paths.indexes_root.symlink_to(target, target_is_directory=True)

    with pytest.raises(LaunchError):
        _create_task(project, "blocked symlink")

    assert context.paths.indexes_root.is_symlink()


def test_storage_set_indexes_cache_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _ = _init_project(tmp_path, monkeypatch)

    result = storage_set(project, mount="indexes", storage="cache", target="local")

    assert result["unchanged"] is True
    with pytest.raises(LaunchError, match="fixed to cache"):
        storage_set(project, mount="indexes", storage="project", target="local")


def test_rebuild_failure_is_structured_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    shutil.rmtree(context.paths.indexes_root)

    def fail_rebuild(_paths):
        raise OSError("read-only cache")

    from taskledger.storage import indexes

    monkeypatch.setattr(indexes, "rebuild_v2_indexes", fail_rebuild)
    with pytest.raises(CacheRecoveryFailed) as error:
        _create_task(project, "failed rebuild")

    assert error.value.code == "TASKLEDGER_CACHE_RECOVERY_FAILED"
    assert error.value.details["operation"] == "rebuild"


def test_doctor_suggests_automatic_recovery_for_unbound_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    (context.paths.indexes_root / ".ledger-project.toml").unlink()
    stale_file = context.paths.indexes_root / "stale-cache.json"
    stale_file.write_text("stale\n", encoding="utf-8")

    report = inspect_v2_project(project)

    recovery_hints = [
        hint
        for hint in report["repair_hints"]
        if "Indexes cache is unbound but appears recoverable" in hint
    ]
    assert len(recovery_hints) == 1
    assert "write command" in recovery_hints[0]
    assert "taskledger repair index" in recovery_hints[0]
    assert stale_file.read_text(encoding="utf-8") == "stale\n"
    assert not list(context.paths.indexes_root.parent.glob("indexes.quarantine-*"))


def test_doctor_explains_missing_machine_local_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    shutil.rmtree(context.paths.runtime_root)
    shutil.rmtree(context.paths.logs_root)

    report = inspect_v2_project(project)

    assert any(
        "Machine-local Taskledger state is absent" in hint
        and "next write will initialize" in hint
        for hint in report["repair_hints"]
    )
    assert not context.paths.runtime_root.exists()
    assert not context.paths.logs_root.exists()


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unavailable")
@pytest.mark.parametrize(
    "invalidity",
    ["foreign_cache", "symlink_root", "symlink_marker", "persistent_binding"],
)
def test_doctor_omits_recovery_hint_for_unsafe_cache_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalidity: str,
) -> None:
    project, context = _init_project(tmp_path, monkeypatch)
    indexes_root = context.paths.indexes_root
    marker = indexes_root / ".ledger-project.toml"

    if invalidity == "foreign_cache":
        original = marker.read_text(encoding="utf-8")
        marker.write_text(
            original.replace(
                f'project_uuid = "{context.project_uuid}"',
                f'project_uuid = "{uuid4()}"',
            ),
            encoding="utf-8",
        )
    elif invalidity == "symlink_root":
        target = tmp_path / "cache-target"
        target.mkdir()
        shutil.rmtree(indexes_root)
        indexes_root.symlink_to(target, target_is_directory=True)
    elif invalidity == "symlink_marker":
        target_marker = tmp_path / "foreign-marker.toml"
        target_marker.write_text(marker.read_text(encoding="utf-8"), encoding="utf-8")
        marker.unlink()
        marker.symlink_to(target_marker)
    else:
        data_marker = context.paths.data_root / ".ledger-project.toml"
        original = data_marker.read_text(encoding="utf-8")
        data_marker.write_text(
            original.replace(
                f'project_uuid = "{context.project_uuid}"',
                f'project_uuid = "{uuid4()}"',
            ),
            encoding="utf-8",
        )
        marker.unlink()
        (indexes_root / "stale-cache.json").write_text("stale\n", encoding="utf-8")

    report = inspect_v2_project(project)

    assert not any(
        "Indexes cache is unbound but appears recoverable" in hint
        for hint in report["repair_hints"]
    )


@pytest.mark.parametrize("mount_state", ["missing", "empty"])
def test_local_state_recovery_initializes_missing_or_empty_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mount_state: str,
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    roots = (original.paths.runtime_root, original.paths.logs_root)
    for root in roots:
        shutil.rmtree(root)
        if mount_state == "empty":
            root.mkdir(parents=True)

    context = load_project_context(project, require_initialized=False)
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    recovery = ensure_local_state_for_mutation(context)

    assert recovery is not None
    assert {item.mount for item in recovery.recoveries} == {"runtime", "logs"}
    assert all((root / ".ledger-project.toml").is_file() for root in roots)
    assert context.paths.runtime_root.joinpath("checkouts", "main").is_dir()
    assert context.paths.events_dir.is_dir()
    assert context.paths.agent_logs_dir.is_dir()
    assert (
        ensure_local_state_for_mutation(
            load_project_context(project, require_initialized=False)
        )
        is None
    )


@pytest.mark.parametrize("mount_name", ["runtime", "logs"])
def test_local_state_recovery_rejects_non_empty_unbound_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mount_name: str,
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    roots = {"runtime": original.paths.runtime_root, "logs": original.paths.logs_root}
    for root in roots.values():
        shutil.rmtree(root)
    unsafe_root = roots[mount_name]
    unsafe_root.mkdir(parents=True)
    unknown = unsafe_root / "unknown.txt"
    unknown.write_text("preserve me\n", encoding="utf-8")

    context = load_project_context(project, require_initialized=False)
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    with pytest.raises(LaunchError) as error:
        ensure_local_state_for_mutation(context)

    assert error.value.code == "TASKLEDGER_LOCAL_STATE_RECOVERY_UNSAFE"
    assert error.value.details["mount"] == mount_name
    assert error.value.details["reason"] == "non_empty_unbound"
    assert error.value.remediation
    assert unknown.read_text(encoding="utf-8") == "preserve me\n"
    assert not (roots["runtime"] / ".ledger-project.toml").exists()
    assert not (roots["logs"] / ".ledger-project.toml").exists()


@pytest.mark.parametrize("mount_name", ["runtime", "logs"])
def test_local_state_recovery_rejects_foreign_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mount_name: str,
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    root = {
        "runtime": original.paths.runtime_root,
        "logs": original.paths.logs_root,
    }[mount_name]
    marker = root / ".ledger-project.toml"
    content = marker.read_text(encoding="utf-8")
    foreign_content = content.replace(
        f'project_uuid = "{original.project_uuid}"',
        f'project_uuid = "{uuid4()}"',
    )
    marker.write_text(foreign_content, encoding="utf-8")
    context = load_project_context(project, require_initialized=False)
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    with pytest.raises(LaunchError) as error:
        ensure_local_state_for_mutation(context)

    assert error.value.code == "TASKLEDGER_LOCAL_STATE_RECOVERY_UNSAFE"
    assert marker.read_text(encoding="utf-8") == foreign_content


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unavailable")
@pytest.mark.parametrize("symlink_kind", ["root", "marker"])
def test_local_state_recovery_rejects_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symlink_kind: str,
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    context = load_project_context(project, require_initialized=False)
    root = original.paths.runtime_root
    target = tmp_path / "local-state-target"
    target.mkdir()
    if symlink_kind == "root":
        shutil.rmtree(root)
        root.symlink_to(target, target_is_directory=True)
    else:
        marker = root / ".ledger-project.toml"
        marker.unlink()
        marker.symlink_to(target / "binding.toml")
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    with pytest.raises(LaunchError) as error:
        ensure_local_state_for_mutation(context)

    assert error.value.code == "TASKLEDGER_LOCAL_STATE_RECOVERY_UNSAFE"
    if symlink_kind == "root":
        assert root.is_symlink()
    else:
        assert (root / ".ledger-project.toml").is_symlink()


def test_invalid_data_binding_blocks_local_state_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    data_marker = original.paths.data_root / ".ledger-project.toml"
    data_marker.write_text(
        data_marker.read_text(encoding="utf-8").replace(
            f'project_uuid = "{original.project_uuid}"',
            f'project_uuid = "{uuid4()}"',
        ),
        encoding="utf-8",
    )
    for root in (original.paths.runtime_root, original.paths.logs_root):
        shutil.rmtree(root)
    context = load_project_context(project, require_initialized=False)
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    with pytest.raises(LaunchError) as error:
        ensure_local_state_for_mutation(context)

    assert error.value.code == "TASKLEDGER_STORAGE_BINDING_INVALID"
    assert not original.paths.runtime_root.exists()
    assert not original.paths.logs_root.exists()


def test_concurrent_local_state_recovery_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    for root in (original.paths.runtime_root, original.paths.logs_root):
        shutil.rmtree(root)
    context = load_project_context(project, require_initialized=False)
    from taskledger.storage.local_state import ensure_local_state_for_mutation

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                ensure_local_state_for_mutation,
                (context, context),
            )
        )

    assert sum(result is not None for result in results) == 1
    assert all(
        (root / ".ledger-project.toml").is_file()
        for root in (original.paths.runtime_root, original.paths.logs_root)
    )


def test_mutable_context_recovers_local_mounts_and_cache_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, original = _init_project(tmp_path, monkeypatch)
    existing = _create_task(project, "durable task before local recovery")
    assert existing.id == "task-0001"
    for root in (original.paths.runtime_root, original.paths.logs_root):
        shutil.rmtree(root)
    indexes_root = original.paths.indexes_root
    (indexes_root / ".ledger-project.toml").unlink()
    stale_cache = indexes_root / "stale-cache.json"
    stale_cache.write_text("stale\n", encoding="utf-8")

    context = require_mutable_project_context(project)

    assert context.local_state_recovery is not None
    assert {item.mount for item in context.local_state_recovery.recoveries} == {
        "runtime",
        "logs",
    }
    assert context.cache_recovery is not None
    assert context.cache_recovery.action == "quarantined_rebuilt"
    assert context.cache_recovery.quarantine_path is not None
    assert (context.cache_recovery.quarantine_path / "stale-cache.json").read_text(
        encoding="utf-8"
    ) == "stale\n"
    assert (original.paths.runtime_root / ".ledger-project.toml").is_file()
    assert (original.paths.logs_root / ".ledger-project.toml").is_file()
    assert len(list_tasks(project)) == 1


def test_cross_machine_first_task_mutation_recovers_local_state_without_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pc_a = tmp_path / "pc-a"
    project_a = pc_a / "project"
    project_a.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_a / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_a / "xdg-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(pc_a / "local-appdata"))
    context_a, _ = init_canonical_project_state(
        project_a,
        project_name="cross-machine-test",
        data_storage="external",
        external_root="../ledger",
    )
    existing = _create_task(project_a, "existing durable task")
    assert existing.id == "task-0001"

    pc_b = tmp_path / "pc-b"
    pc_b.mkdir()
    project_b = pc_b / "project"
    shutil.copytree(project_a, project_b)
    shutil.copytree(pc_a / "ledger", pc_b / "ledger")
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_b / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_b / "xdg-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(pc_b / "local-appdata"))

    before = load_project_context(project_b, require_initialized=False)
    _clear_machine_local_mounts(before)
    assert not before.paths.runtime_root.exists()
    assert not before.paths.logs_root.exists()
    assert not before.paths.indexes_root.exists()
    existing_task_file = task_markdown_path(before.paths, existing.id)
    existing_task_bytes = existing_task_file.read_bytes()
    before.paths.indexes_root.mkdir(parents=True)
    stale_cache = before.paths.indexes_root / "stale-cache.json"
    stale_cache.write_text("stale\n", encoding="utf-8")

    next_task = _create_task(project_b, "next durable task")

    assert next_task.id == "task-0002"
    assert len(list_tasks(project_b)) == 2
    assert existing_task_file.read_bytes() == existing_task_bytes
    after = load_project_context(project_b)
    assert (after.paths.runtime_root / ".ledger-project.toml").is_file()
    assert (after.paths.logs_root / ".ledger-project.toml").is_file()
    assert after.paths.events_dir.is_dir()
    assert all(path.is_file() for path in _expected_indexes(after))
    quarantines = sorted(after.paths.indexes_root.parent.glob("indexes.quarantine-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "stale-cache.json").read_text(
        encoding="utf-8"
    ) == "stale\n"
    assert context_a.project_uuid == after.project_uuid


def test_cross_machine_harness_set_bootstraps_local_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pc_a = tmp_path / "pc-a"
    project_a = pc_a / "project"
    project_a.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_a / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_a / "xdg-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(pc_a / "local-appdata"))
    init_canonical_project_state(
        project_a,
        project_name="cross-machine-harness-test",
        data_storage="external",
        external_root="../ledger",
    )
    assert _create_task(project_a, "existing durable task").id == "task-0001"

    pc_b = tmp_path / "pc-b"
    pc_b.mkdir()
    project_b = pc_b / "project"
    shutil.copytree(project_a, project_b)
    shutil.copytree(pc_a / "ledger", pc_b / "ledger")
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_b / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_b / "xdg-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(pc_b / "local-appdata"))

    before = load_project_context(project_b, require_initialized=False)
    _clear_machine_local_mounts(before)
    assert not before.paths.runtime_root.exists()
    assert not before.paths.logs_root.exists()
    result = runner.invoke(
        app,
        [
            "--root",
            str(project_b),
            "harness",
            "set",
            "--name",
            "pi",
            "--kind",
            "agent_harness",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    after = load_project_context(project_b)
    assert after.paths.harness_path.is_file()
    assert (after.paths.runtime_root / ".ledger-project.toml").is_file()
    assert (after.paths.logs_root / ".ledger-project.toml").is_file()
    assert after.paths.events_dir.is_dir()
    assert _create_task(project_b, "next durable task").id == "task-0002"


def test_cross_machine_read_only_commands_do_not_bootstrap_local_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pc_a = tmp_path / "pc-a"
    project_a = pc_a / "project"
    project_a.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_a / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_a / "xdg-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(pc_a / "local-appdata"))
    init_canonical_project_state(
        project_a,
        project_name="cross-machine-read-test",
        data_storage="external",
        external_root="../ledger",
    )
    _create_task(project_a, "existing durable task")

    pc_b = tmp_path / "pc-b"
    pc_b.mkdir()
    project_b = pc_b / "project"
    shutil.copytree(project_a, project_b)
    shutil.copytree(pc_a / "ledger", pc_b / "ledger")
    monkeypatch.setenv("XDG_CACHE_HOME", str(pc_b / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(pc_b / "xdg-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(pc_b / "local-appdata"))

    context = load_project_context(project_b, require_initialized=False)
    _clear_machine_local_mounts(context)
    assert list_tasks(project_b)
    location = storage_where(project_b)
    assert location["kind"] == "storage_location_report"
    mounts = location["mounts"]
    assert mounts["runtime"]["initialized"] is False
    assert mounts["logs"]["initialized"] is False
    assert mounts["indexes"]["initialized"] is False
    assert inspect_v2_project(project_b)

    assert not context.paths.runtime_root.exists()
    assert not context.paths.logs_root.exists()
    assert not context.paths.indexes_root.exists()

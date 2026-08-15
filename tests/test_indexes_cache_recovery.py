from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from taskledger.api.storage import storage_set
from taskledger.cli import app
from taskledger.errors import CacheRecoveryFailed, LaunchError
from taskledger.services.tasks import create_task
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_context import load_project_context
from taskledger.storage.task_store import list_tasks

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

    result = runner.invoke(app, ["--cwd", str(project), "--json", "repair", "index"])

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

    with pytest.raises(LaunchError, match="data"):
        _create_task(project, "blocked mutation")

    assert context.paths.indexes_root.exists()
    assert not list(context.paths.indexes_root.parent.glob("indexes.quarantine-*"))


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

    import taskledger.storage.indexes as indexes

    monkeypatch.setattr(indexes, "rebuild_v2_indexes", fail_rebuild)
    with pytest.raises(CacheRecoveryFailed) as error:
        _create_task(project, "failed rebuild")

    assert error.value.code == "TASKLEDGER_CACHE_RECOVERY_FAILED"
    assert error.value.details["operation"] == "rebuild"

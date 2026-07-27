from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.errors import LaunchError, TaskledgerRegistrationMissing
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.paths import (
    load_project_locator,
    probe_taskledger_project,
)
from taskledger.storage.project_context import load_project_context
from taskledger.storage.task_store import list_tasks, resolve_v2_paths

runner = CliRunner()


def _write_unregistered_manifest(root: Path) -> None:
    ledger_dir = root / ".ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger.toml").write_text(
        """schema_version = 3

[project]
uuid = "9ec5f921-b2c6-41db-8ffd-bea03b583741"
name = "releaseledger"

[ledgers.releaseledger.mounts.data]
storage = "project"

[ledgers.releaseledger.mounts.indexes]
storage = "cache"
""",
        encoding="utf-8",
    )


def test_unregistered_canonical_project_never_falls_back_to_legacy(
    tmp_path: Path,
) -> None:
    _write_unregistered_manifest(tmp_path)
    config = tmp_path / ".ledger" / "taskledger" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        "config_version = 3\n[ledger]\ncode = 'tl'\nname = 'taskledger'\n",
        encoding="utf-8",
    )
    (tmp_path / ".taskledger").mkdir()
    (tmp_path / "taskledger.toml").write_text("ledger_ref = 'main'\n", encoding="utf-8")

    probe = probe_taskledger_project(tmp_path)
    locator = load_project_locator(tmp_path)

    assert probe.source == "canonical"
    assert probe.registration_present is False
    assert probe.orphan_config_present is True
    assert locator.source == "canonical"
    assert locator.workspace_root == tmp_path
    assert locator.config_path == config
    assert locator.taskledger_dir == tmp_path / ".ledger" / "taskledger"

    with pytest.raises(TaskledgerRegistrationMissing) as raised:
        load_project_context(tmp_path, require_initialized=False)
    assert raised.value.code == "TASKLEDGER_REGISTRATION_MISSING"
    assert raised.value.details["manifest_path"] == str(
        tmp_path / ".ledger" / "ledger.toml"
    )

    with pytest.raises(TaskledgerRegistrationMissing):
        resolve_v2_paths(tmp_path)
    assert not (tmp_path / ".taskledger" / "ledgers").exists()


def test_nested_invocation_uses_parent_canonical_boundary(tmp_path: Path) -> None:
    _write_unregistered_manifest(tmp_path)
    nested = tmp_path / "src" / "package"
    nested.mkdir(parents=True)

    probe = probe_taskledger_project(nested)
    locator = load_project_locator(nested)

    assert probe.project_root == tmp_path
    assert locator.workspace_root == tmp_path
    with pytest.raises(TaskledgerRegistrationMissing):
        list_tasks(nested)


def _tree_snapshot(root: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = None if path.is_dir() else path.read_bytes()
    return snapshot


@pytest.mark.parametrize(
    "argv",
    [
        ["--version"],
        ["usage"],
        ["status"],
        ["task", "active"],
        ["task", "list"],
        ["actor", "whoami"],
        ["next-action"],
        ["doctor"],
        ["storage", "where"],
        ["config", "show"],
    ],
)
def test_read_commands_do_not_initialize_canonical_unregistered_project(
    tmp_path: Path,
    argv: list[str],
) -> None:
    _write_unregistered_manifest(tmp_path)
    before = _tree_snapshot(tmp_path)

    result = runner.invoke(app, ["--root", str(tmp_path), *argv])

    assert result.exit_code in {0, 1, 5, 6}
    assert _tree_snapshot(tmp_path) == before
    assert not (tmp_path / ".taskledger").exists()
    assert not (tmp_path / "taskledger.toml").exists()
    assert not (tmp_path / ".taskledger.toml").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["actor", "set", "--type", "agent", "--name", "agent"],
        ["harness", "set", "--name", "harness"],
        ["task", "create", "blocked"],
        ["plan", "start"],
    ],
)
def test_mutations_stop_before_writing_unregistered_canonical_project(
    tmp_path: Path,
    argv: list[str],
) -> None:
    _write_unregistered_manifest(tmp_path)
    before = _tree_snapshot(tmp_path)

    result = runner.invoke(app, ["--root", str(tmp_path), *argv])

    if isinstance(result.exception, TaskledgerRegistrationMissing):
        assert result.exception.code == "TASKLEDGER_REGISTRATION_MISSING"
    else:
        assert isinstance(result.exception, SystemExit)
        assert result.exit_code == 6
    assert _tree_snapshot(tmp_path) == before
    assert not (tmp_path / ".taskledger").exists()
    assert not (tmp_path / "taskledger.toml").exists()


def test_doctor_reports_orphan_shadow_and_split_brain_state(tmp_path: Path) -> None:
    _write_unregistered_manifest(tmp_path)
    config_dir = tmp_path / ".ledger" / "taskledger"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("config_version = 3\n", encoding="utf-8")
    legacy_task = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks" / "task-0001"
    legacy_task.mkdir(parents=True)
    (legacy_task / "task.md").write_text("legacy\n", encoding="utf-8")
    canonical_task = config_dir / "data" / "ledgers" / "main" / "tasks" / "task-0002"
    canonical_task.mkdir(parents=True)
    (canonical_task / "task.md").write_text("canonical\n", encoding="utf-8")

    result = runner.invoke(app, ["--root", str(tmp_path), "--json", "doctor"])

    assert result.exit_code == 0, result.stdout
    output = result.stdout
    assert "TASKLEDGER_ORPHAN_CANONICAL_CONFIG" in output
    assert "TASKLEDGER_SHADOW_LEGACY_PROJECT" in output
    assert "TASKLEDGER_SPLIT_BRAIN" in output


def test_true_legacy_project_still_resolves_without_canonical_manifest(
    tmp_path: Path,
) -> None:
    (tmp_path / ".taskledger").mkdir()
    (tmp_path / ".taskledger" / "storage.yaml").write_text(
        "created: true\n", encoding="utf-8"
    )
    (tmp_path / "taskledger.toml").write_text(
        "config_version = 2\ntaskledger_dir = '.taskledger'\n",
        encoding="utf-8",
    )

    probe = probe_taskledger_project(tmp_path)
    locator = load_project_locator(tmp_path)

    assert probe.source == "legacy"
    assert locator.source in {"toml", "legacy"}
    assert locator.taskledger_dir == tmp_path / ".taskledger"


def test_canonical_init_reuses_manifest_identity_and_valid_orphan_config(
    tmp_path: Path,
) -> None:
    _write_unregistered_manifest(tmp_path)
    config_dir = tmp_path / ".ledger" / "taskledger"
    config_dir.mkdir()
    config_text = "config_version = 3\n\n[ledger]\ncode = 'tl'\nname = 'taskledger'\n"
    config_path = config_dir / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")
    marker_path = config_dir / ".ledger-project.toml"
    marker_path.write_text(
        """schema_version = 1
layout_version = 3
project_uuid = "9ec5f921-b2c6-41db-8ffd-bea03b583741"
tool = "taskledger"
mount = "config"
storage = "project"
""",
        encoding="utf-8",
    )

    context, _ = init_canonical_project_state(tmp_path, data_storage="project")

    assert context.project_uuid == "9ec5f921-b2c6-41db-8ffd-bea03b583741"
    assert config_path.read_text(encoding="utf-8") == config_text
    assert marker_path.exists()
    manifest = (tmp_path / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    assert "[ledgers.releaseledger.mounts.data]" in manifest
    assert "[ledgers.taskledger.mounts.data]" in manifest


@pytest.mark.parametrize(
    "config_text,marker_uuid,expected_code",
    [
        ("config_version = 2\n", None, "TASKLEDGER_ORPHAN_CONFIG_INVALID"),
        (
            "config_version = 3\n[ledger]\ncode = 'tl'\nname = 'taskledger'\n",
            "00000000-0000-0000-0000-000000000000",
            "TASKLEDGER_CONFIG_BINDING_INVALID",
        ),
    ],
)
def test_canonical_init_rejects_invalid_or_foreign_orphan_without_manifest_write(
    tmp_path: Path,
    config_text: str,
    marker_uuid: str | None,
    expected_code: str,
) -> None:
    _write_unregistered_manifest(tmp_path)
    manifest_path = tmp_path / ".ledger" / "ledger.toml"
    original_manifest = manifest_path.read_text(encoding="utf-8")
    config_dir = tmp_path / ".ledger" / "taskledger"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    if marker_uuid is not None:
        (config_dir / ".ledger-project.toml").write_text(
            "schema_version = 1\nlayout_version = 3\n"
            f'project_uuid = "{marker_uuid}"\n'
            'tool = "taskledger"\nmount = "config"\nstorage = "project"\n',
            encoding="utf-8",
        )

    with pytest.raises(LaunchError) as raised:
        init_canonical_project_state(tmp_path, data_storage="project")

    assert raised.value.code == expected_code
    assert manifest_path.read_text(encoding="utf-8") == original_manifest
    assert not (tmp_path / ".ledger" / "taskledger" / "data").exists()

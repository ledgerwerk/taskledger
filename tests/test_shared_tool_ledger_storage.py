from __future__ import annotations

import json
from pathlib import Path

from ledgercore import (
    locate_ledger_project,
    parse_ledger_local_config,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)
from ledgercore.layout import PlatformRoots
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_binding import read_project_binding


def test_shared_sibling_base_isolated_by_ledger_and_project_uuid(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sibling = tmp_path / "ledger"
    sibling.mkdir()
    (sibling / ".ledger-store").write_text("store\n", encoding="utf-8")

    context, _ = init_canonical_project_state(project, project_name="demo")
    project_uuid = context.project_uuid
    binding = read_project_binding(context.paths.data_root)
    assert binding is not None
    assert binding.project_name == "demo"
    other_project = tmp_path / "other"
    other_project.mkdir()
    other_context, _ = init_canonical_project_state(other_project, project_name="other")
    assert other_context.project_uuid != project_uuid
    assert other_context.paths.data_root == (
        sibling / "taskledger" / other_context.project_uuid
    )

    manifest = parse_ledger_project_manifest(
        {
            "schema_version": 2,
            "project": {"uuid": project_uuid, "name": "demo"},
            "ledgers": {
                "taskledger": {
                    "config": {
                        "location": "project",
                        "path": "task/config.toml",
                    },
                    "mounts": {
                        "data": {
                            "storage": "workspace",
                            "scope": "project",
                            "path": f"taskledger/{project_uuid}",
                        },
                        "indexes": {
                            "storage": "cache",
                            "scope": "checkout",
                            "path": "taskledger-indexes",
                        },
                    },
                },
                "planledger": {
                    "config": {
                        "location": "project",
                        "path": "plan/config.toml",
                    },
                    "mounts": {
                        "data": {
                            "storage": "workspace",
                            "scope": "project",
                            "path": f"planledger/{project_uuid}",
                        }
                    },
                },
                "archledger": {
                    "config": {
                        "location": "project",
                        "path": "arch/config.toml",
                    },
                    "mounts": {
                        "data": {
                            "storage": "workspace",
                            "scope": "project",
                            "path": f"archledger/{project_uuid}",
                        }
                    },
                },
            },
        }
    )
    local = parse_ledger_local_config(
        {"schema_version": 1, "storage": {"workspace": {"provider": "sibling-ledger"}}},
        project_root=project,
    )
    roots = PlatformRoots(
        project.parent / "platform-data",
        project.parent / "platform-cache",
    )
    locator = locate_ledger_project(project, default=True)
    assert locator is not None

    for ledger_name, directory in (
        ("taskledger", "taskledger"),
        ("planledger", "planledger"),
        ("archledger", "archledger"),
    ):
        layout = resolve_ledger_layout(
            locator,
            manifest,
            ledger_name,
            local_config=local,
            platform_roots=roots,
        )
        assert (
            layout.mounts["data"].path == (sibling / directory / project_uuid).resolve()
        )
        assert layout.mounts["data"].path.exists() is (ledger_name == "taskledger")


def test_missing_shared_sibling_store_has_human_and_json_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = CliRunner()

    human = runner.invoke(app, ["--cwd", str(workspace), "init"])
    assert human.exit_code == 6
    assert "TASKLEDGER_SIBLING_ROOT_MISSING" in human.output

    machine = runner.invoke(app, ["--cwd", str(workspace), "--json", "init"])
    assert machine.exit_code == 6
    payload = json.loads(machine.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "TASKLEDGER_SIBLING_ROOT_MISSING"

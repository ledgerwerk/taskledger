from __future__ import annotations

import json
from pathlib import Path

from taskledger.api.project import init_project
from taskledger.api.storage import (
    storage_clear_override,
    storage_path,
    storage_set,
    storage_validate,
    storage_where,
)
from taskledger.storage.init import init_canonical_project_state


def test_storage_v3_reports_and_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project)

    report = storage_where(project)
    assert report["kind"] == "storage_location_report"
    assert report["schema_version"] == 2
    assert report["mounts"]["data"]["storage"] == "external"  # type: ignore[index]
    assert str(storage_path(project, "data")["path"]).endswith("/data")
    assert str(storage_path(project, "indexes")["path"]).endswith("/indexes")
    assert storage_validate(project)["valid"] is True
    text = json.dumps(report)
    assert "sibling-ledger" not in text
    assert "workspace_provider" not in text
    assert "task/config.toml" not in text
    assert set(report["mounts"]) == {"data", "runtime", "logs", "indexes"}  # type: ignore[arg-type]
    assert report["mounts"]["runtime"]["storage"] == "user-data"  # type: ignore[index]
    assert report["mounts"]["logs"]["storage"] == "user-data"  # type: ignore[index]
    assert str(storage_path(project, "runtime")["path"]).endswith("/runtime")
    assert str(storage_path(project, "logs")["path"]).endswith("/logs")


def test_storage_v3_local_override_and_clear(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project)

    local = storage_set(
        project,
        mount="data",
        storage="user-data",
        target="local",
    )
    assert local["mounts"]["data"]["storage"] == "user-data"  # type: ignore[index]
    assert (project / ".ledger/ledger.local.toml").exists()

    committed = storage_clear_override(project, mount="data")
    assert committed["mounts"]["data"]["storage"] == "external"  # type: ignore[index]


def test_init_local_storage_override_preserves_shared_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = init_project(
        project, data_storage="user-data", local_storage_override=True
    )

    manifest = (project / ".ledger/ledger.toml").read_text(encoding="utf-8")
    local = (project / ".ledger/ledger.local.toml").read_text(encoding="utf-8")
    assert 'storage = "external"' in manifest
    assert 'storage = "user-data"' in local
    assert result["mounts"]["data"]["storage"] == "user-data"  # type: ignore[index]

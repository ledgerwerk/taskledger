from __future__ import annotations

from pathlib import Path

import ledgercore

from taskledger.storage.ledgercore_backend import (
    DATA_MOUNT,
    INDEX_MOUNT,
    TOOL_NAME,
    ensure_taskledger_ledger_registration,
)


def test_ledgercore_dependency_is_050_and_adapter_exports_contract() -> None:
    version = tuple(int(part) for part in ledgercore.__version__.split(".")[:2])
    assert version >= (0, 5)
    assert TOOL_NAME == "taskledger"
    assert (DATA_MOUNT, INDEX_MOUNT) == ("data", "indexes")


def test_registration_preserves_other_tools(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / ".ledger" / "ledger.toml"
    manifest.parent.mkdir()
    manifest.write_text(
        """schema_version = 3

[project]
uuid = "081c7c05-2d10-42b7-9b37-3d814c2f400a"
name = "shared"

[ledgers.other.mounts.data]
storage = "project"

""",
        encoding="utf-8",
    )

    result = ensure_taskledger_ledger_registration(
        project,
        project_uuid="081c7c05-2d10-42b7-9b37-3d814c2f400a",
        project_name="shared",
    )

    assert set(result.ledgers) == {"other", "taskledger"}
    text = manifest.read_text(encoding="utf-8")
    assert "[ledgers.other.mounts.data]" in text
    assert "[ledgers.taskledger.mounts.data]" in text
    assert 'storage = "external"' in text
    assert 'root = "../ledger"' in text

from __future__ import annotations

from pathlib import Path

from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.task_store import TaskledgerStoragePaths, resolve_v2_paths


def ensure_project_layout(workspace_root: Path) -> TaskledgerStoragePaths:
    if not (workspace_root / ".ledger" / "ledger.toml").is_file():
        init_canonical_project_state(workspace_root, data_storage="project")
    return resolve_v2_paths(workspace_root)

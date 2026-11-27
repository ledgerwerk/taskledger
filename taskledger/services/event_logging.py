from __future__ import annotations

from pathlib import Path

from taskledger.storage.project_config import (
    load_project_config_overrides,
    merge_project_config,
)
from taskledger.storage.project_context import resolve_project_paths


def event_logging_enabled(workspace_root: Path) -> bool:
    paths = resolve_project_paths(workspace_root)
    overrides = load_project_config_overrides(paths)
    return merge_project_config(overrides).event_logging.enabled

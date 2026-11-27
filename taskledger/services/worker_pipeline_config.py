from __future__ import annotations

from pathlib import Path

from taskledger.storage.paths import probe_taskledger_project
from taskledger.storage.project_config import (
    load_project_config_overrides,
    merge_project_config,
)
from taskledger.storage.project_context import resolve_project_paths
from taskledger.storage.worker_pipeline_config import WorkerPipelineConfig


def load_worker_pipeline_config(
    workspace_root: Path,
) -> WorkerPipelineConfig | None:
    if probe_taskledger_project(workspace_root).source == "none":
        return None
    paths = resolve_project_paths(workspace_root)
    overrides = load_project_config_overrides(paths)
    return merge_project_config(overrides).worker_pipeline

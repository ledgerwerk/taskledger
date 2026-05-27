from __future__ import annotations

import importlib
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.storage.paths import resolve_project_paths
from taskledger.storage.project_config import (
    get_project_config_value,
    load_project_config_document,
    set_project_config_value,
)

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    tomllib = importlib.import_module("tomli")


def config_list(workspace_root: Path) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    document = load_project_config_document(paths.config_path)
    return {
        "kind": "project_config",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "config": document,
    }


def config_get(workspace_root: Path, *, key: str) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    value = get_project_config_value(paths.config_path, key)
    return {
        "kind": "project_config_value",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "value": value,
    }


def config_set(workspace_root: Path, *, key: str, value_text: str) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    value = parse_config_value_text(value_text)
    before: object = None
    try:
        before = get_project_config_value(paths.config_path, key)
    except LaunchError as exc:
        if "Config key not found" not in str(exc):
            raise
    set_project_config_value(paths.config_path, key, value)
    after = get_project_config_value(paths.config_path, key)
    return {
        "kind": "project_config_updated",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "previous_value": before,
        "value": after,
    }


def parse_config_value_text(value_text: str) -> object:
    stripped = value_text.strip()
    if not stripped:
        return ""
    try:
        parsed = tomllib.loads(f"value = {stripped}")
    except Exception:
        return value_text
    if not isinstance(parsed, dict) or "value" not in parsed:
        raise LaunchError("Failed to parse config value.")
    return parsed["value"]


__all__ = [
    "config_list",
    "config_get",
    "config_set",
    "parse_config_value_text",
]

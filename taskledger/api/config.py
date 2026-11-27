from __future__ import annotations

import importlib
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.storage.project_config_schema import (
    PROJECT_CONFIG_KEY_SCHEMA as _CONFIG_KEY_HELP,
)
from taskledger.storage.project_config_schema import (
    ConfigKeyHelp,
)
from taskledger.storage.project_context import (
    load_project_context,
    resolve_project_paths,
)

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    tomllib = importlib.import_module("tomli")


def config_list(workspace_root: Path) -> dict[str, object]:
    context = load_project_context(workspace_root, require_initialized=False)
    try:
        document = tomllib.loads(context.config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(
            f"Invalid canonical project config {context.config_path}: {exc}"
        ) from exc
    return {
        "kind": "project_config",
        "workspace_root": str(context.project_root),
        "config_path": str(context.config_path),
        "config": document,
    }


def config_get(workspace_root: Path, *, key: str) -> dict[str, object]:
    context = load_project_context(workspace_root, require_initialized=False)
    document = config_list(workspace_root)["config"]
    value: object = document
    for segment in key.split("."):
        if not isinstance(value, dict) or segment not in value:
            raise LaunchError(f"Config key not found: {key}")
        value = value[segment]
    return {
        "kind": "project_config_value",
        "workspace_root": str(context.project_root),
        "config_path": str(context.config_path),
        "key": key,
        "value": value,
    }


def config_keys(workspace_root: Path) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    keys = [
        entry.to_dict() for entry in sorted(_CONFIG_KEY_HELP, key=lambda item: item.key)
    ]
    return {
        "kind": "project_config_keys",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "keys": keys,
    }


def config_describe(workspace_root: Path, *, key: str) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    matched = _match_config_help_entry(key)
    if matched is None:
        raise LaunchError(
            f"Config key help not found: {key}. "
            "Run `taskledger config keys` to list supported key names."
        )
    value: object = None
    has_value = False
    try:
        value = config_get(workspace_root, key=key)["value"]
        has_value = True
    except LaunchError as exc:
        if "Config key not found" not in str(exc):
            raise
    return {
        "kind": "project_config_key_help",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "schema_key": matched.key,
        "description": matched.description,
        "value_type": matched.value_type,
        "allowed_values": list(matched.allowed_values),
        "default_value": matched.default_value,
        "mutable": matched.mutable,
        "has_explicit_value": has_value,
        "value": value,
    }


def config_set(workspace_root: Path, *, key: str, value_text: str) -> dict[str, object]:
    context = load_project_context(workspace_root)
    paths = resolve_project_paths(workspace_root)
    value = parse_config_value_text(value_text)
    before: object = None
    try:
        before = config_get(workspace_root, key=key)["value"]
    except LaunchError as exc:
        if "Config key not found" not in str(exc):
            raise
    # Enforce immutability before branching between modes.
    help_entry = _match_config_help_entry(key)
    if help_entry is None:
        raise LaunchError(f"Unsupported project config key '{key}'.")
    _validate_config_key_value(key, help_entry, value)
    if not help_entry.mutable:
        raise LaunchError(
            f"Config key {key} is immutable. "
            "Use the dedicated repair or topology command."
        )
    if key in {
        "config_version",
        "taskledger_dir",
        "project_uuid",
        "project_name",
        "ledger_ref",
        "ledger_parent_ref",
        "ledger_next_task_number",
        "ledger_branch_guard",
    }:
        raise LaunchError(
            f"Config key {key} cannot be edited in canonical mode; "
            "topology and ledger state are managed separately."
        )
    from tomlkit import dumps, parse, table

    from taskledger.storage.atomic import atomic_write_text

    try:
        document = parse(context.config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(
            f"Invalid canonical project config {context.config_path}: {exc}"
        ) from exc
    target = document
    segments = key.split(".")
    for segment in segments[:-1]:
        if segment not in target:
            target[segment] = table()
        target = target[segment]
    target[segments[-1]] = value
    from taskledger.storage.project_config import _validate_project_config_overrides

    _validate_project_config_overrides(
        tomllib.loads(dumps(document)), context.config_path
    )
    atomic_write_text(context.config_path, dumps(document))
    after = config_get(workspace_root, key=key)["value"]
    return {
        "kind": "project_config_updated",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "previous_value": before,
        "value": after,
    }


def config_unset(workspace_root: Path, *, key: str) -> dict[str, object]:
    context = load_project_context(workspace_root)
    paths = resolve_project_paths(workspace_root)
    before: object = None
    try:
        before = config_get(workspace_root, key=key)["value"]
    except LaunchError:
        # Key doesn't exist, nothing to unset
        return {
            "kind": "project_config_updated",
            "workspace_root": str(paths.workspace_root),
            "config_path": str(paths.config_path),
            "key": key,
            "previous_value": None,
            "value": None,
        }
    # Check immutability
    help_entry = _match_config_help_entry(key)
    if help_entry is not None and not help_entry.mutable:
        raise LaunchError(
            f"Config key {key} is immutable. "
            "Use the dedicated repair or topology command."
        )
    if key in {
        "config_version",
        "taskledger_dir",
        "project_uuid",
        "project_name",
        "ledger_ref",
        "ledger_parent_ref",
        "ledger_next_task_number",
        "ledger_branch_guard",
    }:
        raise LaunchError(
            f"Config key {key} cannot be edited in canonical mode; "
            "topology and ledger state are managed separately."
        )
    from tomlkit import dumps, parse

    from taskledger.storage.atomic import atomic_write_text

    try:
        document = parse(context.config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaunchError(
            f"Invalid canonical project config {context.config_path}: {exc}"
        ) from exc
    segments = key.split(".")
    target = document
    for segment in segments[:-1]:
        if segment not in target:
            return {
                "kind": "project_config_updated",
                "workspace_root": str(paths.workspace_root),
                "config_path": str(paths.config_path),
                "key": key,
                "previous_value": before,
                "value": None,
            }
        target = target[segment]
    if segments[-1] in target:
        del target[segments[-1]]
        atomic_write_text(context.config_path, dumps(document))
    return {
        "kind": "project_config_updated",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "previous_value": before,
        "value": None,
    }


def parse_config_value_text(value_text: str) -> object:
    stripped = value_text.strip()
    if not stripped:
        return ""
    try:
        parsed = tomllib.loads(f"value = {stripped}")
    except tomllib.TOMLDecodeError:
        return value_text
    if not isinstance(parsed, dict) or "value" not in parsed:
        raise LaunchError("Failed to parse config value.")
    return parsed["value"]


def _match_config_help_entry(key: str) -> ConfigKeyHelp | None:
    normalized = key.strip()
    if not normalized:
        return None
    for entry in _CONFIG_KEY_HELP:
        if _config_key_matches_pattern(normalized, entry.key):
            return entry
    return None


def _validate_config_key_value(key: str, entry: ConfigKeyHelp, value: object) -> None:
    value_type = entry.value_type
    valid = True
    if value_type == "boolean":
        valid = isinstance(value, bool)
    elif value_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif value_type == "integer|null":
        valid = value is None or (
            isinstance(value, int) and not isinstance(value, bool)
        )
    elif value_type == "string":
        valid = isinstance(value, str)
    elif value_type == "string|null":
        valid = value is None or isinstance(value, str)
    elif value_type == "array[string]":
        valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif value_type == "array[table]":
        valid = isinstance(value, list) and all(
            isinstance(item, dict) for item in value
        )
    elif value_type == "table":
        valid = isinstance(value, dict)
    if not valid:
        raise LaunchError(f"Config key {key} must be a {value_type}.")
    if entry.allowed_values and value not in entry.allowed_values:
        allowed = ", ".join(entry.allowed_values)
        raise LaunchError(f"Config key {key} must be one of: {allowed}.")


def _config_key_matches_pattern(key: str, pattern: str) -> bool:
    key_segments = tuple(segment for segment in key.split(".") if segment)
    pattern_segments = tuple(segment for segment in pattern.split(".") if segment)
    if len(key_segments) != len(pattern_segments):
        return False
    for key_segment, pattern_segment in zip(
        key_segments,
        pattern_segments,
        strict=True,
    ):
        if pattern_segment in {"<profile>", "<artifact>", "[]"}:
            continue
        if pattern_segment.endswith("[]"):
            literal = pattern_segment[:-2]
            if key_segment != literal:
                return False
            continue
        if pattern_segment.startswith("<") and pattern_segment.endswith(">"):
            continue
        if key_segment != pattern_segment:
            return False
    return True


__all__ = [
    "config_describe",
    "config_get",
    "config_keys",
    "config_list",
    "config_set",
    "parse_config_value_text",
]

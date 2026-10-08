"""YAML I/O wrappers backed by ledgercore.yamlio.

All taskledger production YAML reads/writes should go through these
wrappers so that ledgercore exception types never leak into service
or CLI code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from ledgercore.errors import YamlStoreError
from ledgercore.yamlio import load_yaml_object as _load_yaml_object
from ledgercore.yamlio import write_yaml as _write_yaml

from taskledger.errors import LaunchError


def load_yaml_object(
    path: Path,
    label: str,
    *,
    missing: Literal["error", "empty"] = "error",
    empty: Literal["error", "empty"] = "empty",
) -> dict[str, object]:
    try:
        return _load_yaml_object(path, label=label, missing=missing, empty=empty)
    except YamlStoreError as exc:
        raise LaunchError(f"Invalid {label} {path}: {exc}") from exc


def load_yaml_object_bytes(
    contents: bytes, label: str, source: Path
) -> dict[str, object]:
    """Parse UTF-8 YAML bytes with the same mapping contract as file reads."""
    import yaml

    try:
        text = contents.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LaunchError(f"Invalid {label} {source}: expected UTF-8 YAML.") from exc
    if not text.strip():
        raise LaunchError(f"Invalid {label} {source}: YAML document is empty.")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LaunchError(f"Invalid {label} {source}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise LaunchError(
            f"Invalid {label} {source}: expected YAML mapping, got "
            f"{type(data).__name__}."
        )
    return data


def write_yaml_object(
    path: Path,
    payload: Mapping[str, object],
    *,
    sort_keys: bool = False,
) -> None:
    try:
        _write_yaml(path, payload, atomic=True, sort_keys=sort_keys)
    except YamlStoreError as exc:
        raise LaunchError(f"Failed to write {path}: {exc}") from exc

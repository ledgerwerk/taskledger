"""Taskledger-owned structural mutation of the shared Ledger manifest."""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from filelock import FileLock
from ledgercore import (
    atomic_create_text,
    atomic_write_text,
    parse_ledger_project_manifest,
)
from ledgercore.errors import LedgerLayoutError
from tomlkit import dumps, parse, table

from taskledger.errors import LaunchError
from taskledger.storage.project_context import (
    CANONICAL_LEDGER_NAME,
    canonical_mount_specs,
)

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover
    tomllib = importlib.import_module("tomli")


@dataclass(frozen=True, slots=True)
class ManifestMutationResult:
    manifest_path: Path
    project_uuid: str
    project_name: str | None
    changed: bool
    created: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_path": str(self.manifest_path),
            "project_uuid": self.project_uuid,
            "project_name": self.project_name,
            "changed": self.changed,
            "created": self.created,
        }


def _registration_document(project_uuid: str) -> dict[str, Any]:
    return {
        "config": {"location": "project", "path": "task/config.toml"},
        "mounts": {
            name: {
                "storage": storage,
                **({"scope": scope} if scope is not None else {}),
                "path": path,
            }
            for name, (storage, scope, path) in canonical_mount_specs(
                project_uuid
            ).items()
        },
    }


def _expected_registration(project_uuid: str) -> dict[str, Any]:
    return {CANONICAL_LEDGER_NAME: _registration_document(project_uuid)}


def _manifest_dict(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": document.get("schema_version"),
        "project": dict(document.get("project", {})),
        "storage": dict(document.get("storage", {})),
        "ledgers": dict(document.get("ledgers", {})),
    }


def _validate_bytes(path: Path, contents: str) -> dict[str, Any]:
    try:
        document = tomllib.loads(contents)
        parse_ledger_project_manifest(document)
    except (ValueError, LedgerLayoutError) as exc:
        raise LaunchError(
            f"Invalid Ledger manifest {path} after mutation: {exc}"
        ) from exc
    return cast(dict[str, Any], document)


def _ensure_project_defaults(
    doc: Any, *, project_uuid: str, project_name: str | None
) -> None:
    doc["schema_version"] = 2
    project = doc.setdefault("project", table())
    project["uuid"] = project_uuid
    if project_name is not None:
        project["name"] = project_name
    storage = doc.setdefault("storage", table())
    workspace = storage.setdefault("workspace", table())
    workspace.setdefault("default_provider", "user-data")
    workspace.setdefault("namespace", "ledgerwerk")
    cache = storage.setdefault("cache", table())
    cache.setdefault("default_provider", "user-cache")
    cache.setdefault("namespace", "ledgerwerk")


def _registration_matches(existing: Any, project_uuid: str) -> bool:
    if existing is None:
        return False
    expected = _registration_document(project_uuid)
    config = existing.get("config") if hasattr(existing, "get") else None
    if (
        config is None
        or config.get("location") != "project"
        or config.get("path") != "task/config.toml"
    ):
        return False
    mounts = existing.get("mounts") if hasattr(existing, "get") else None
    if mounts is None:
        return False
    actual = {
        name: {
            "storage": mounts[name].get("storage"),
            **({"scope": mounts[name].get("scope")} if "scope" in mounts[name] else {}),
            "path": mounts[name].get("path"),
        }
        for name in mounts
    }
    return bool(actual == expected["mounts"])


def _recognized_legacy_registration(existing: Any) -> bool:
    if not hasattr(existing, "get") or existing.get("config") is None:
        return False
    config = existing["config"]
    if config.get("location") != "project" or config.get("path") != "task/config.toml":
        return False
    mounts = existing.get("mounts")
    if not isinstance(mounts, Mapping):
        return False
    values = {
        name: {key: mount.get(key) for key in ("storage", "scope", "path")}
        for name, mount in mounts.items()
    }
    data = values.get("data")
    indexes = values.get("indexes")
    if isinstance(data, Mapping) and isinstance(indexes, Mapping):
        data_path = data.get("path")
        prefix = "task/taskledger/"
        try:
            uuid.UUID(str(data_path).removeprefix(prefix))
        except ValueError:
            pass
        else:
            if (
                isinstance(data_path, str)
                and data_path.startswith(prefix)
                and data.get("storage") == "workspace"
                and data.get("scope") == "project"
                and indexes.get("storage") == "cache"
                and indexes.get("scope") == "checkout"
                and indexes.get("path") == "task/taskledger-indexes"
            ):
                return True
    repository_local = {
        "data": {"storage": "repository", "scope": None, "path": "task/taskledger"},
        "indexes": {
            "storage": "cache",
            "scope": "checkout",
            "path": "task/taskledger-indexes",
        },
    }
    split_checkout = {
        "data": {"storage": "workspace", "scope": "checkout", "path": "task/data"},
        "logs": {"storage": "workspace", "scope": "checkout", "path": "task/logs"},
        "indexes": {"storage": "cache", "scope": "checkout", "path": "task/indexes"},
    }
    direct_sibling_legacy = {
        "data": {
            "storage": "workspace",
            "scope": "project",
            "path": "task/taskledger",
        },
        "indexes": {
            "storage": "cache",
            "scope": "checkout",
            "path": "task/taskledger-indexes",
        },
    }
    direct_sibling = {
        "data": {
            "storage": "workspace",
            "scope": "project",
            "path": "taskledger",
        },
        "indexes": {
            "storage": "cache",
            "scope": "checkout",
            "path": "taskledger-indexes",
        },
    }
    return values in (
        repository_local,
        split_checkout,
        direct_sibling_legacy,
        direct_sibling,
    )


def _conflict(existing: Any, project_uuid: str) -> str | None:
    if existing is None or _recognized_legacy_registration(existing):
        return None
    config = existing.get("config") if hasattr(existing, "get") else None
    if config is None or config.get("location") != "project":
        return "ledgers.taskledger.config.location"
    if config.get("path") != "task/config.toml":
        return "ledgers.taskledger.config.path"
    mounts = existing.get("mounts") if hasattr(existing, "get") else {}
    if not isinstance(mounts, Mapping):
        return "ledgers.taskledger.mounts"
    specs = canonical_mount_specs(project_uuid)
    if set(mounts) != set(specs):
        return "ledgers.taskledger.mounts"
    for name, (storage, scope, path) in specs.items():
        expected_values = {"storage": storage, "path": path}
        if scope is not None:
            expected_values["scope"] = scope
        for key, expected in expected_values.items():
            if mounts[name].get(key) != expected:
                return f"ledgers.taskledger.mounts.{name}.{key}"
        if scope is None and "scope" in mounts[name]:
            return f"ledgers.taskledger.mounts.{name}.scope"
    return None


def _set_registration(doc: Any, project_uuid: str) -> None:
    specs = canonical_mount_specs(project_uuid)
    ledgers = doc.setdefault("ledgers", table())
    registration = ledgers.setdefault(CANONICAL_LEDGER_NAME, table())
    config = registration.setdefault("config", table())
    config["location"] = "project"
    config["path"] = "task/config.toml"
    mounts = registration.setdefault("mounts", table())
    for name in list(mounts):
        if name not in specs:
            del mounts[name]
    for name, (storage, scope, path) in specs.items():
        mount = mounts.setdefault(name, table())
        mount["storage"] = storage
        if scope is None:
            mount.pop("scope", None)
        else:
            mount["scope"] = scope
        mount["path"] = path


def ensure_taskledger_registration(
    project_root: Path,
    *,
    project_uuid: str,
    project_name: str | None = None,
) -> ManifestMutationResult:
    """Create or merge the exact Taskledger registration under a process lock."""
    try:
        normalized_uuid = str(uuid.UUID(project_uuid))
    except (ValueError, AttributeError) as exc:
        raise LaunchError(f"Invalid project UUID {project_uuid!r}.") from exc
    root = project_root.expanduser().resolve()
    ledger_dir = root / ".ledger"
    manifest_path = ledger_dir / "ledger.toml"
    lock = FileLock(str(manifest_path) + ".lock")
    with lock:
        if not manifest_path.exists():
            ledger_dir.mkdir(parents=True, exist_ok=True)
            doc = table()
            _ensure_project_defaults(
                doc, project_uuid=normalized_uuid, project_name=project_name
            )
            _set_registration(doc, normalized_uuid)
            contents = dumps(doc)
            _validate_bytes(manifest_path, contents)
            try:
                atomic_create_text(manifest_path, contents)
                created = True
                changed = True
            except FileExistsError:
                contents = manifest_path.read_text(encoding="utf-8")
                _validate_bytes(manifest_path, contents)
                created = False
                changed = False
            else:
                return ManifestMutationResult(
                    manifest_path, normalized_uuid, project_name, changed, created
                )
        current = manifest_path.read_text(encoding="utf-8")
        try:
            raw = tomllib.loads(current)
            manifest = parse_ledger_project_manifest(raw)
        except (OSError, ValueError, LedgerLayoutError) as exc:
            raise LaunchError(
                f"Invalid existing Ledger manifest {manifest_path}: {exc}"
            ) from exc
        if manifest.project_uuid != normalized_uuid:
            raise LaunchError(
                f"Project UUID conflict in {manifest_path}: expected "
                f"{normalized_uuid}, actual {manifest.project_uuid}."
                f"actual {manifest.project_uuid}."
            )
        if project_name is not None and manifest.project_name not in {
            None,
            project_name,
        }:
            raise LaunchError(
                f"Project name conflict in {manifest_path}: expected "
                f"{project_name!r}, actual {manifest.project_name!r}."
                f"actual {manifest.project_name!r}."
            )
        existing_doc = parse(current)
        existing = existing_doc.get("ledgers", {}).get(CANONICAL_LEDGER_NAME)
        if _registration_matches(existing, normalized_uuid):
            return ManifestMutationResult(
                manifest_path, normalized_uuid, manifest.project_name, False, False
            )
        conflict = _conflict(existing, normalized_uuid)
        if conflict:
            actual = "missing" if existing is None else "conflicting value"
            raise LaunchError(
                "Taskledger is already registered with a conflicting mount or config:\n"
                f"  {conflict}\n  expected: canonical Taskledger registration\n"
                f"  actual: {actual}\n"
                "Refusing to rewrite the shared Ledger manifest."
            )
        _ensure_project_defaults(
            existing_doc,
            project_uuid=normalized_uuid,
            project_name=project_name or manifest.project_name,
        )
        _set_registration(existing_doc, normalized_uuid)
        contents = dumps(existing_doc)
        _validate_bytes(manifest_path, contents)
        atomic_write_text(manifest_path, contents)
        reread = manifest_path.read_text(encoding="utf-8")
        _validate_bytes(manifest_path, reread)
        return ManifestMutationResult(
            manifest_path,
            normalized_uuid,
            project_name or manifest.project_name,
            True,
            False,
        )


__all__ = ["ManifestMutationResult", "ensure_taskledger_registration"]


def upgrade_taskledger_registration(
    project_root: Path,
    *,
    expected_project_uuid: str,
) -> ManifestMutationResult:
    """Upgrade a recognized superseded Taskledger registration."""
    return ensure_taskledger_registration(
        project_root, project_uuid=expected_project_uuid
    )


__all__ = [
    "ManifestMutationResult",
    "ensure_taskledger_registration",
    "upgrade_taskledger_registration",
]

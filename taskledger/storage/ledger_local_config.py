"""Safe mutation of the shared Ledgercore machine-local configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock
from tomlkit import dumps, parse, table

from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text


@dataclass(frozen=True, slots=True)
class LedgerLocalMutationResult:
    path: Path
    changed: bool
    provider: str


def ensure_sibling_workspace_provider(
    project_root: Path,
) -> LedgerLocalMutationResult:
    """Require the shared local configuration to select sibling-ledger."""
    root = project_root.expanduser().resolve()
    path = root / ".ledger" / "ledger.local.toml"
    lock = FileLock(str(path) + ".lock")
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                document: Any = parse(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LaunchError(f"Invalid Ledger local config {path}: {exc}") from exc
        else:
            document = table()
            document["schema_version"] = 1

        storage = document.setdefault("storage", table())
        workspace = storage.get("workspace")
        if workspace is None:
            workspace = table()
            storage["workspace"] = workspace
        if not hasattr(workspace, "get"):
            raise LaunchError(
                f"Ledger local storage.workspace must be a table in {path}."
            )

        configured_root = workspace.get("root")
        configured_provider = workspace.get("provider")
        if configured_root is not None and configured_provider is not None:
            raise LaunchError(
                "TASKLEDGER_WORKSPACE_ROOT_CONFLICT: Ledger local config cannot "
                "contain both storage.workspace.root and provider."
            )
        if configured_root is not None:
            raise LaunchError(
                "TASKLEDGER_WORKSPACE_ROOT_CONFLICT: Taskledger authoritative "
                "storage has a fixed sibling-ledger location. Remove "
                "storage.workspace.root."
            )
        if configured_provider is not None and configured_provider != "sibling-ledger":
            raise LaunchError(
                "TASKLEDGER_WORKSPACE_PROVIDER_CONFLICT: Taskledger requires "
                "storage.workspace.provider = 'sibling-ledger'."
            )
        if configured_provider == "sibling-ledger":
            return LedgerLocalMutationResult(path, False, "sibling-ledger")

        workspace["provider"] = "sibling-ledger"
        atomic_write_text(path, dumps(document))
        return LedgerLocalMutationResult(path, True, "sibling-ledger")


__all__ = ["LedgerLocalMutationResult", "ensure_sibling_workspace_provider"]

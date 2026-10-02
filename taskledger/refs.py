from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ledgercore.errors import IdFormatError
from ledgercore.refs import LedgerResourceRef, parse_resource_ref

from taskledger.errors import LaunchError
from taskledger.storage.ledger_config import load_ledger_identity
from taskledger.storage.paths import load_project_locator

TASKLEDGER_RESOURCE_KINDS = frozenset(
    {
        "task",
        "todo",
        "ac",
        "q",
        "run",
        "change",
        "check",
        "review",
        "handoff",
        "cle",
        "req",
        "intro",
    }
)


@dataclass(frozen=True)
class RefContext:
    ledger_code: str
    allowed_ledgers: frozenset[str]


def ref_context_for_workspace(workspace_root: Path) -> RefContext:
    locator = load_project_locator(workspace_root)
    identity = load_ledger_identity(locator.config_path)
    return RefContext(
        ledger_code=identity.code,
        allowed_ledgers=frozenset({identity.code}),
    )


def parse_taskledger_ref(
    workspace_root: Path,
    value: str,
    *,
    allowed_kinds: set[str] | None = None,
) -> LedgerResourceRef:
    ctx = ref_context_for_workspace(workspace_root)
    try:
        return parse_resource_ref(
            value,
            default_ledger=ctx.ledger_code,
            allowed_ledgers=set(ctx.allowed_ledgers),
            allowed_kinds=allowed_kinds or set(TASKLEDGER_RESOURCE_KINDS),
        )
    except IdFormatError as exc:
        raise LaunchError(f"Invalid taskledger resource ref {value!r}: {exc}") from exc


def local_id_from_ref(workspace_root: Path, value: str, *, kind: str) -> str:
    return parse_taskledger_ref(workspace_root, value, allowed_kinds={kind}).local_id


def global_ref_for_local_id(
    workspace_root: Path, local_id: str, *, context: RefContext | None = None
) -> str:
    ctx = context or ref_context_for_workspace(workspace_root)
    try:
        return parse_resource_ref(local_id, default_ledger=ctx.ledger_code).global_ref
    except IdFormatError as exc:
        raise LaunchError(f"Invalid local resource id {local_id!r}: {exc}") from exc


def file_ref_for_local_id(
    workspace_root: Path, local_id: str, *, context: RefContext | None = None
) -> str:
    ctx = context or ref_context_for_workspace(workspace_root)
    try:
        return parse_resource_ref(local_id, default_ledger=ctx.ledger_code).file_ref
    except IdFormatError as exc:
        raise LaunchError(f"Invalid local resource id {local_id!r}: {exc}") from exc

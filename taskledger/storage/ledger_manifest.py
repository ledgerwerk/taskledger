"""Deprecated compatibility facade for Ledgercore manifest mutation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from taskledger.storage.ledgercore_backend import ensure_taskledger_ledger_registration


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


def ensure_taskledger_registration(
    project_root: Path,
    *,
    project_uuid: str,
    project_name: str,
) -> ManifestMutationResult:
    manifest_path = project_root / ".ledger" / "ledger.toml"
    before = manifest_path.read_bytes() if manifest_path.exists() else None
    manifest = ensure_taskledger_ledger_registration(
        project_root,
        project_uuid=project_uuid,
        project_name=project_name,
    )
    after = manifest_path.read_bytes()
    return ManifestMutationResult(
        manifest_path=manifest_path,
        project_uuid=manifest.project_uuid,
        project_name=manifest.project_name,
        changed=before != after,
        created=before is None,
    )


def upgrade_taskledger_registration(
    project_root: Path,
    *,
    project_uuid: str | None = None,
    project_name: str | None = None,
    expected_project_uuid: str | None = None,
) -> ManifestMutationResult:
    return ensure_taskledger_registration(
        project_root,
        project_uuid=project_uuid or expected_project_uuid or "",
        project_name=project_name or project_root.name,
    )


__all__ = [
    "ManifestMutationResult",
    "ensure_taskledger_registration",
    "upgrade_taskledger_registration",
]

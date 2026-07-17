"""Deprecated local-layout facade.

Schema-3 local mount overrides are written by Ledgercore. This compatibility
function no longer writes provider-specific configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LedgerLocalMutationResult:
    path: Path
    changed: bool
    created: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "changed": self.changed,
            "created": self.created,
        }


def ensure_sibling_workspace_provider(
    project_root: Path,
) -> LedgerLocalMutationResult:
    """Return the local overlay path without creating provider topology."""
    return LedgerLocalMutationResult(
        project_root / ".ledger" / "ledger.local.toml", False, False
    )


__all__ = ["LedgerLocalMutationResult", "ensure_sibling_workspace_provider"]

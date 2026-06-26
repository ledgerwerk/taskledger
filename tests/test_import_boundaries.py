"""Boundary tests enforcing import discipline for taskledger production code.

These tests prevent slow regression back to direct yaml/json/hashlib/ledgercore
imports outside the documented facades.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _python_files() -> list[Path]:
    """Return all production .py files under taskledger/."""
    return sorted(
        p for p in Path("taskledger").rglob("*.py") if "__pycache__" not in p.parts
    )


def _relative(path: Path) -> str:
    return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# Direct `import yaml` allowlist
# ---------------------------------------------------------------------------
# These files may import yaml directly. All others should use
# taskledger.storage.yaml_store instead.
# ---------------------------------------------------------------------------
YAML_IMPORT_ALLOWLIST: set[str] = {
    # unique-key YAML rejection in bulk answer input
    "taskledger/cli_question.py",
    # string front matter parsing (until ledgercore has string parser)
    "taskledger/services/tasks.py",
    # string front matter rendering (until ledgercore has string renderer)
    "taskledger/services/plan_editing.py",
    # editable plan input preflight parser/validator (plan check + plan input issues)
    "taskledger/services/plan_input.py",
    # lock exclusive-create yaml dump (until ledgercore has atomic_create_yaml)
    "taskledger/storage/locks.py",
    # legacy migration tolerance
    "taskledger/storage/migrations.py",
    # lock import in exchange (same pattern as locks.py)
    "taskledger/exchange.py",
}


class TestYamlImportBoundary:
    def test_direct_yaml_imports_are_whitelisted(self) -> None:
        """Direct `import yaml` is only allowed in documented exceptions."""
        violations: list[str] = []
        for path in _python_files():
            rel = _relative(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Import):
                    continue
                for alias in node.names:
                    if alias.name == "yaml" and rel not in YAML_IMPORT_ALLOWLIST:
                        violations.append(f"{rel}:{node.lineno}")

        assert not violations, (
            "Direct `import yaml` found outside allowlist:\n"
            + "\n".join(f"  {v}" for v in sorted(violations))
            + "\n\nAllowed files:\n"
            + "\n".join(f"  {f}" for f in sorted(YAML_IMPORT_ALLOWLIST))
            + "\n\nUse taskledger.storage.yaml_store instead."
        )


# ---------------------------------------------------------------------------
# Direct ledgercore import allowlist (outside storage/ids/refs/time facades)
# ---------------------------------------------------------------------------
# Storage modules and facade modules (ids.py, refs.py, timeutils.py) may
# import ledgercore directly. Other modules should go through the facades.
# ---------------------------------------------------------------------------
LEDGERCORE_IMPORT_ALLOWLIST: set[str] = {
    # Facades
    "taskledger/ids.py",
    "taskledger/refs.py",
    "taskledger/timeutils.py",
    # Storage wrappers
    "taskledger/storage/atomic.py",
    "taskledger/storage/common.py",
    "taskledger/storage/frontmatter.py",
    "taskledger/storage/paths.py",
    "taskledger/storage/ledger_config.py",
    "taskledger/storage/project_config.py",
    "taskledger/storage/project_identity.py",
    "taskledger/storage/yaml_store.py",
}


class TestLedgercoreImportBoundary:
    def test_direct_ledgercore_imports_are_whitelisted(self) -> None:
        """Direct ledgercore imports outside storage/facade modules are
        only allowed in documented exceptions."""
        violations: list[str] = []
        for path in _python_files():
            rel = _relative(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module and node.module.startswith("ledgercore"):
                    # Allow if the file itself is in the allowlist
                    if rel not in LEDGERCORE_IMPORT_ALLOWLIST:
                        violations.append(f"{rel}:{node.lineno} (from {node.module})")

        assert not violations, (
            "Direct ledgercore import found outside allowlist:\n"
            + "\n".join(f"  {v}" for v in sorted(violations))
            + "\n\nAllowed files:\n"
            + "\n".join(f"  {f}" for f in sorted(LEDGERCORE_IMPORT_ALLOWLIST))
            + "\n\nUse taskledger.ids, taskledger.refs, taskledger.storage.*"
            + " facades instead."
        )

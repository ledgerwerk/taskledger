"""Runtime provenance for Taskledger installations.

Reports executable paths, imported package locations, versions, and
available migration commands so that operators and agents can verify
the running code matches the expected source.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from taskledger.compat.ledgercore import (
    LEDGERCORE_REQUIREMENT,
    inspect_ledgercore_version,
    ledgercore_is_compatible,
)


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """Snapshot of the running Taskledger runtime environment."""

    taskledger_version: str
    taskledger_commit: str | None
    taskledger_package_file: str
    taskledger_cli_file: str
    taskledger_migrate_file: str
    python_executable: str
    argv0: str
    console_script: str
    ledgercore_version: str | None
    ledgercore_package_file: str | None
    ledgercore_module_version: str | None
    ledgercore_distribution_version: str | None
    ledgercore_version_mismatch: bool
    ledgercore_required: str
    ledgercore_compatible: bool
    migration_contract_version: int
    available_migrate_commands: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "taskledger_runtime",
            "taskledger_version": self.taskledger_version,
            "taskledger_commit": self.taskledger_commit,
            "taskledger_package_file": self.taskledger_package_file,
            "taskledger_cli_file": self.taskledger_cli_file,
            "taskledger_migrate_file": self.taskledger_migrate_file,
            "python_executable": self.python_executable,
            "argv0": self.argv0,
            "console_script": self.console_script,
            "ledgercore_version": self.ledgercore_version,
            "ledgercore_package_file": self.ledgercore_package_file,
            "ledgercore_module_version": self.ledgercore_module_version,
            "ledgercore_distribution_version": self.ledgercore_distribution_version,
            "ledgercore_version_mismatch": self.ledgercore_version_mismatch,
            "ledgercore_required": self.ledgercore_required,
            "ledgercore_compatible": self.ledgercore_compatible,
            "migration_contract_version": self.migration_contract_version,
            "available_migrate_commands": list(self.available_migrate_commands),
        }

    def human_summary(self) -> str:
        lines = [
            "TASKLEDGER RUNTIME",
            "",
            "Taskledger",
            f"  version: {self.taskledger_version}",
            f"  package: {self.taskledger_package_file}",
            f"  cli: {self.taskledger_cli_file}",
            f"  migrate: {self.taskledger_migrate_file}",
            "",
            "Runtime",
            f"  python: {self.python_executable}",
            f"  argv0: {self.argv0}",
            f"  console_script: {self.console_script}",
            "",
            "Ledgercore",
            f"  version: {self.ledgercore_version or 'unknown'}",
            f"  package: {self.ledgercore_package_file or 'unknown'}",
            f"  module_version: {self.ledgercore_module_version or 'unknown'}",
            (
                "  distribution_version: "
                f"{self.ledgercore_distribution_version or 'unknown'}"
            ),
            f"  version_mismatch: {self.ledgercore_version_mismatch}",
            f"  required: {self.ledgercore_required}",
            f"  compatible: {self.ledgercore_compatible}",
            "",
            "Migration",
            f"  contract_version: {self.migration_contract_version}",
            f"  commands: {', '.join(self.available_migrate_commands)}",
        ]
        return "\n".join(lines)


def _resolve_commit(version: str) -> str | None:
    """Extract git commit hash from dev version strings."""
    if "+" not in version:
        return None
    suffix = version.split("+", 1)[1]
    # Format is like g5273c8e0b or g5273c8e0b.d20260727
    parts = suffix.split(".")
    git_part = parts[0]
    if git_part.startswith("g") and len(git_part) >= 7:
        return git_part[1:]
    return None


def collect_runtime_info() -> RuntimeInfo:
    """Collect runtime provenance from the currently imported modules."""
    import taskledger
    import taskledger.cli as cli_module
    import taskledger.cli_migrate as migrate_module

    version = taskledger.__version__
    commit = _resolve_commit(version)

    ledgercore_info = inspect_ledgercore_version()

    # Discover available migrate commands from the typer app
    available_commands: list[str] = []
    try:
        from taskledger.cli_migrate import migrate_app

        if hasattr(migrate_app, "registered_commands"):
            for cmd in migrate_app.registered_commands:
                if hasattr(cmd, "name") and cmd.name is not None:
                    available_commands.append(str(cmd.name))
        # Also check for commands registered via callback
        if hasattr(migrate_app, "commands"):
            available_commands.extend(migrate_app.commands.keys())
    except (ImportError, AttributeError):
        pass

    # Fallback: known commands from the source
    if not available_commands:
        available_commands = ["inspect", "status", "plan", "apply"]

    # Console script detection
    argv0 = sys.argv[0] if sys.argv else ""
    console_script = ""
    if "taskledger" in Path(argv0).name:
        console_script = argv0

    return RuntimeInfo(
        taskledger_version=version,
        taskledger_commit=commit,
        taskledger_package_file=str(Path(taskledger.__file__).resolve()),
        taskledger_cli_file=str(Path(cli_module.__file__).resolve()),
        taskledger_migrate_file=str(Path(migrate_module.__file__).resolve()),
        python_executable=sys.executable,
        argv0=argv0,
        console_script=console_script,
        ledgercore_version=ledgercore_info.module_version,
        ledgercore_package_file=ledgercore_info.package_file,
        ledgercore_module_version=ledgercore_info.module_version,
        ledgercore_distribution_version=ledgercore_info.distribution_version,
        ledgercore_version_mismatch=ledgercore_info.version_mismatch,
        ledgercore_required=LEDGERCORE_REQUIREMENT,
        ledgercore_compatible=ledgercore_is_compatible(ledgercore_info),
        migration_contract_version=3,
        available_migrate_commands=tuple(sorted(set(available_commands))),
    )


__all__ = ["RuntimeInfo", "collect_runtime_info"]

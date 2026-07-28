"""Ledgercore 0.6.0 compatibility boundary.

This module provides:
- Strict public-API imports from ledgercore
- Minimum version validation
- Structured error translation (preserves codes)
- Typed wrappers for CLI envelopes and migration APIs

Rules:
- No getattr fallback that silently changes semantics
- No import of private names beginning with _
- No parsing of Ledgercore journal TOML inside Taskledger
- Fail at startup or command invocation with a precise dependency error
  when the required public API is unavailable
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- Version check ---

_LEDGERCORE_MIN_VERSION = (0, 6, 0)
_LEDGERCORE_MAX_VERSION_EXCL = (0, 7, 0)


def _parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a version string like '0.6.0' into a tuple."""
    parts = version_str.strip().split(".")
    if len(parts) < 3:
        raise ValueError(f"Invalid version string: {version_str!r}")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise ValueError(f"Invalid version string: {version_str!r}") from None


def require_ledgercore_060() -> None:
    """Verify that the installed Ledgercore version satisfies >=0.6.0,<0.7.0.

    Raises:
        RuntimeError: If Ledgercore is missing or version is incompatible.
    """
    try:
        import ledgercore

        version_str = getattr(ledgercore, "__version__", None)
        if version_str is None:
            raise RuntimeError(
                "Ledgercore is installed but has no __version__ attribute. "
                "Taskledger requires ledgercore>=0.6.0,<0.7.0."
            )
        version = _parse_version(version_str)
        if version < _LEDGERCORE_MIN_VERSION:
            raise RuntimeError(
                f"Taskledger requires ledgercore>=0.6.0,<0.7.0, "
                f"but found {version_str}."
            )
        if version >= _LEDGERCORE_MAX_VERSION_EXCL:
            raise RuntimeError(
                f"Taskledger requires ledgercore>=0.6.0,<0.7.0, "
                f"but found {version_str}."
            )
    except ImportError:
        raise RuntimeError(
            "Taskledger requires ledgercore>=0.6.0,<0.7.0, but it is not installed. "
            "Install it with: pip install 'ledgercore>=0.6.0,<0.7.0'"
        ) from None


# --- Public API imports ---


def _import_cli_apis() -> dict[str, Any]:
    """Import and return the public CLI APIs from Ledgercore."""
    try:
        from ledgercore.cli import (
            CLIError,
            CLIWarning,
            CommandInventory,
            CommandMetadata,
            CommonCLIState,
            ErrorEnvelope,
            ExitCode,
            SuccessEnvelope,
            deprecated_command_warning,
            deprecated_option_warning,
        )

        return {
            "CLIError": CLIError,
            "CLIWarning": CLIWarning,
            "CommandInventory": CommandInventory,
            "CommandMetadata": CommandMetadata,
            "CommonCLIState": CommonCLIState,
            "ErrorEnvelope": ErrorEnvelope,
            "ExitCode": ExitCode,
            "SuccessEnvelope": SuccessEnvelope,
            "deprecated_command_warning": deprecated_command_warning,
            "deprecated_option_warning": deprecated_option_warning,
        }
    except ImportError as e:
        raise RuntimeError(
            f"Taskledger requires ledgercore.cli but import failed: {e}"
        ) from e


def _import_migration_apis() -> dict[str, Any]:
    """Import and return the public migration APIs from Ledgercore."""
    try:
        from ledgercore.migration import (
            DestinationKind,
            DestinationPolicy,
            DestinationState,
            MigrationStrategy,
            RecoveryAssessment,
            StorageDestinationInspection,
            StorageFingerprint,
            StorageMigrationHooks,
            StorageMigrationItem,
            StorageMigrationPlan,
            StorageMigrationPlanValidation,
            StorageMigrationResult,
            execute_storage_migration,
            fingerprint_storage_directory,
            inspect_storage_migration,
            inspect_storage_migration_destination,
            recover_storage_migration,
            validate_storage_migration_plan,
        )

        return {
            "DestinationKind": DestinationKind,
            "DestinationPolicy": DestinationPolicy,
            "DestinationState": DestinationState,
            "MigrationStrategy": MigrationStrategy,
            "RecoveryAssessment": RecoveryAssessment,
            "StorageDestinationInspection": StorageDestinationInspection,
            "StorageFingerprint": StorageFingerprint,
            "StorageMigrationHooks": StorageMigrationHooks,
            "StorageMigrationItem": StorageMigrationItem,
            "StorageMigrationPlan": StorageMigrationPlan,
            "StorageMigrationPlanValidation": StorageMigrationPlanValidation,
            "StorageMigrationResult": StorageMigrationResult,
            "execute_storage_migration": execute_storage_migration,
            "fingerprint_storage_directory": fingerprint_storage_directory,
            "inspect_storage_migration": inspect_storage_migration,
            "inspect_storage_migration_destination": (
                inspect_storage_migration_destination
            ),
            "recover_storage_migration": recover_storage_migration,
            "validate_storage_migration_plan": validate_storage_migration_plan,
        }
    except ImportError as e:
        raise RuntimeError(
            f"Taskledger requires ledgercore.migration but import failed: {e}"
        ) from e


# --- Cached imports ---

_cli_apis: dict[str, Any] | None = None
_migration_apis: dict[str, Any] | None = None


def get_cli_apis() -> dict[str, Any]:
    """Get the CLI APIs, importing and validating on first call."""
    global _cli_apis
    if _cli_apis is None:
        require_ledgercore_060()
        _cli_apis = _import_cli_apis()
    return _cli_apis


def get_migration_apis() -> dict[str, Any]:
    """Get the migration APIs, importing and validating on first call."""
    global _migration_apis
    if _migration_apis is None:
        require_ledgercore_060()
        _migration_apis = _import_migration_apis()
    return _migration_apis


# --- Typed wrappers ---


def make_cli_success_envelope(
    *,
    command: str = "",
    result: Mapping[str, object] | None = None,
    events: tuple[Mapping[str, object], ...] = (),
    warnings: tuple[Any, ...] = (),
) -> Any:
    """Create a Ledgercore SuccessEnvelope with Taskledger defaults."""
    apis = get_cli_apis()
    return apis["SuccessEnvelope"](
        schema="ledgerwerk.cli.v1",
        ok=True,
        tool="taskledger",
        command=command,
        result=result or {},
        events=events,
        warnings=_coerce_cli_warnings(warnings, apis["CLIWarning"]),
    )


def make_cli_error_envelope(
    *,
    command: str = "",
    error: Mapping[str, object] | None = None,
    events: tuple[Mapping[str, object], ...] = (),
    warnings: tuple[Any, ...] = (),
) -> Any:
    """Create a Ledgercore ErrorEnvelope with Taskledger defaults."""
    apis = get_cli_apis()
    return apis["ErrorEnvelope"](
        schema="ledgerwerk.cli.v1",
        ok=False,
        tool="taskledger",
        command=command,
        error=error or {},
        events=events,
        warnings=_coerce_cli_warnings(warnings, apis["CLIWarning"]),
    )


def _coerce_cli_warnings(
    warnings: tuple[Any, ...],
    warning_type: type[Any],
) -> tuple[Any, ...]:
    """Normalize Taskledger warning strings for Ledgercore's typed envelope."""
    normalized: list[Any] = []
    for warning in warnings:
        if isinstance(warning, warning_type):
            normalized.append(warning)
        else:
            normalized.append(
                warning_type(code="taskledger_warning", message=str(warning))
            )
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class TaskledgerCLIState:
    """Taskledger wrapper around Ledgercore's CommonCLIState."""

    common: Any  # CommonCLIState
    requested_root: Path
    resolved_root: Path | None
    no_log: bool

    @property
    def cwd(self) -> Path:
        """Return the resolved root or fall back to requested root."""
        return self.resolved_root or self.requested_root

    @property
    def json_output(self) -> bool:
        """Return whether JSON output is requested."""
        return bool(self.common.json_output)


def make_cli_state(
    *,
    root: Path,
    json_output: bool = False,
    quiet: bool = False,
    verbose: bool = False,
) -> TaskledgerCLIState:
    """Create a TaskledgerCLIState wrapping CommonCLIState."""
    apis = get_cli_apis()
    common = apis["CommonCLIState"](
        tool="taskledger",
        root=root,
        json_output=json_output,
        quiet=quiet,
        verbose=verbose,
    )
    return TaskledgerCLIState(
        common=common,
        requested_root=root,
        resolved_root=None,
        no_log=False,
    )


# --- Migration wrappers ---


def inspect_destination(
    path: Path,
) -> Any:
    """Inspect a storage destination."""
    apis = get_migration_apis()
    return apis["inspect_storage_migration_destination"](path)


def fingerprint_source(path: Path) -> Any:
    """Fingerprint a storage directory."""
    apis = get_migration_apis()
    return apis["fingerprint_storage_directory"](path)


def validate_plan(plan: Any) -> Any:
    """Validate a storage migration plan."""
    apis = get_migration_apis()
    return apis["validate_storage_migration_plan"](plan)


def execute_plan(
    plan: Any,
    *,
    hooks: Any | None = None,
) -> Any:
    """Execute a storage migration plan."""
    apis = get_migration_apis()
    return apis["execute_storage_migration"](plan, hooks=hooks)


def analyze_recovery(journal_path: Path) -> Any:
    """Analyze recovery options for a migration journal."""
    apis = get_migration_apis()
    return apis["recover_storage_migration"](journal_path, analyze_only=True)


def recover_plan(
    journal_path: Path,
    *,
    policy: str = "auto",
    hooks: Any | None = None,
) -> Any:
    """Recover a failed migration."""
    apis = get_migration_apis()
    return apis["recover_storage_migration"](journal_path, policy=policy, hooks=hooks)


# --- Error translation ---


def translate_ledgercore_error(
    exc: Exception,
    *,
    command: str = "",
) -> dict[str, object]:
    """Translate a Ledgercore exception into a structured error dict.

    Preserves the underlying code and context rather than collapsing.
    """
    ledgercore_code = getattr(exc, "code", None) or type(exc).__name__
    structured_fields: dict[str, object] = {}

    # Extract structured fields if available
    for field in ("details", "context", "path", "expected", "actual"):
        value = getattr(exc, field, None)
        if value is not None:
            structured_fields[field] = value

    return {
        "code": f"taskledger_{ledgercore_code}".lower(),
        "message": str(exc),
        "details": {
            "domain_code": f"TASKLEDGER_{ledgercore_code}",
            "ledgercore_code": ledgercore_code,
            "ledgercore_error_type": type(exc).__name__,
            **structured_fields,
        },
        "remediation": _get_remediation(ledgercore_code),
    }


def _get_remediation(code: str) -> list[str]:
    """Get remediation hints for common error codes."""
    remediations = {
        "StorageMigrationError": [
            "Check migration journal for details.",
            "Run `taskledger migrate recover` if a journal exists.",
        ],
        "StorageBindingError": [
            "Verify the storage binding configuration.",
            "Run `taskledger storage where` to inspect current bindings.",
        ],
    }
    return remediations.get(code, [])

"""Project-level config and layout scan for doctor."""

from __future__ import annotations

from pathlib import Path


def scan_project_config(
    *,
    workspace_root: Path,
    errors: list[str],
    repair_hints: list[str],
) -> None:
    """Validate canonical project configuration and storage bindings."""
    from taskledger.storage.index_cache import has_recoverable_unbound_indexes_cache
    from taskledger.storage.project_config import load_canonical_project_config
    from taskledger.storage.project_context import load_project_context

    context = load_project_context(workspace_root, require_initialized=False)
    load_canonical_project_config(context.config_path)
    if context.project_uuid is None:
        errors.append("Ledger manifest has no project UUID.")
    if not context.paths.data_root.exists():
        errors.append(f"Missing canonical data mount: {context.paths.data_root}.")
    elif not context.paths.storage_meta_path.exists():
        errors.append(
            f"Missing storage.yaml in canonical data mount: {context.paths.data_root}."
        )
    if context.storage_validation is not None:
        for result in context.storage_validation.results:
            if not result.valid:
                errors.append(
                    result.reason or f"Invalid storage binding: {result.path}"
                )
    if has_recoverable_unbound_indexes_cache(context):
        repair_hints.append(
            "Indexes cache is unbound but appears recoverable. A write command "
            "will rebuild it automatically. For explicit repair, run "
            "`taskledger repair index`."
        )
    if context.layout is None:
        return
    missing_local_mounts = [
        name
        for name in ("runtime", "logs")
        if name in context.layout.mounts
        and not context.layout.mounts[name].path.exists()
    ]
    if missing_local_mounts:
        repair_hints.append(
            "Machine-local Taskledger state is absent. This is normal after "
            "moving the project to a new machine. The next write will "
            "initialize local runtime/log bindings."
        )


def scan_canonical_boundary(workspace_root: Path) -> dict[str, object]:
    """Report canonical registration and shadow-project state without writes."""
    from taskledger.storage.paths import probe_taskledger_project

    probe = probe_taskledger_project(workspace_root)
    if probe.source != "canonical" or probe.manifest_path is None:
        return {
            "diagnostics": [],
            "warnings": [],
            "errors": [],
            "repair_hints": [],
        }

    canonical_root = probe.project_root
    legacy_root = canonical_root / ".taskledger"
    canonical_tool_root = canonical_root / ".ledger" / "taskledger"

    def record_count(root: Path) -> int:
        if not root.exists():
            return 0
        return sum(1 for path in root.glob("**/task-*/task.md") if path.is_file())

    canonical_count = record_count(canonical_tool_root)
    legacy_count = record_count(legacy_root)
    diagnostics: list[dict[str, object]] = []
    warnings: list[str] = []
    errors: list[str] = []
    repair_hints = [
        "Back up canonical and legacy roots before any recovery.",
        "Register Taskledger with `taskledger init`, then inspect both histories.",
        (
            "Do not auto-delete or merge shadow records; migrate explicitly after "
            "verification."
        ),
    ]

    if not probe.registration_present and probe.orphan_config_present:
        message = (
            "Canonical Taskledger config is orphaned: "
            f"{probe.tool_config_path}. The manifest does not register taskledger."
        )
        warnings.append(message)
        diagnostics.append(
            {
                "severity": "warning",
                "code": "TASKLEDGER_ORPHAN_CANONICAL_CONFIG",
                "message": message,
                "details": {
                    "canonical_root": str(canonical_root),
                    "manifest_path": str(probe.manifest_path),
                    "config_path": str(probe.tool_config_path),
                    "registration_present": False,
                },
            }
        )

    if legacy_root.is_dir() and (legacy_root / "ledgers").is_dir():
        message = f"Legacy Taskledger shadow project detected at {legacy_root}."
        warnings.append(message)
        diagnostics.append(
            {
                "severity": "warning",
                "code": "TASKLEDGER_SHADOW_LEGACY_PROJECT",
                "message": message,
                "details": {
                    "canonical_root": str(canonical_tool_root),
                    "legacy_root": str(legacy_root),
                    "canonical_task_records": canonical_count,
                    "legacy_task_records": legacy_count,
                    "canonical_active_state": str(
                        canonical_tool_root
                        / "data"
                        / "ledgers"
                        / "main"
                        / "active-task.yaml"
                    ),
                    "legacy_active_state": str(
                        legacy_root / "ledgers" / "main" / "active-task.yaml"
                    ),
                },
            }
        )

    if canonical_count and legacy_count:
        message = "Canonical and legacy Taskledger roots both contain task records."
        errors.append(message)
        diagnostics.append(
            {
                "severity": "error",
                "code": "TASKLEDGER_SPLIT_BRAIN",
                "message": message,
                "details": {
                    "canonical_root": str(canonical_tool_root),
                    "legacy_root": str(legacy_root),
                    "canonical_task_records": canonical_count,
                    "legacy_task_records": legacy_count,
                },
            }
        )

    return {
        "diagnostics": diagnostics,
        "warnings": warnings,
        "errors": errors,
        "repair_hints": repair_hints if diagnostics else [],
    }

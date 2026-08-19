"""Project-level config and layout scan for doctor."""

from __future__ import annotations

from pathlib import Path

from taskledger.storage.paths import ProjectLocator, ProjectPaths


def scan_project_config(  # noqa: C901
    *,
    workspace_root: Path,
    resolved_paths: ProjectPaths,
    locator: ProjectLocator,
    errors: list[str],
    warnings: list[str],
    repair_hints: list[str],
) -> None:
    """Scan project configuration, legacy state, and storage layout."""
    from taskledger.storage.ledgercore_backend import locate_taskledger_project
    from taskledger.storage.project_config import load_canonical_project_config
    from taskledger.storage.project_context import load_project_context

    discovered = locate_taskledger_project(workspace_root)
    try:
        context = load_project_context(workspace_root, require_initialized=False)
    except Exception as exc:  # noqa: BLE001
        if discovered is not None and not discovered.is_legacy:
            errors.append(str(exc))
            return
        context = None
    if context is not None and context.mode == "canonical":
        try:
            load_canonical_project_config(context.config_path)
            if context.project_uuid is None:
                errors.append("Ledger manifest has no project UUID.")
            if not context.paths.data_root.exists():
                errors.append(
                    f"Missing canonical data mount: {context.paths.data_root}."
                )
            elif not context.paths.storage_meta_path.exists():
                errors.append(
                    "Missing storage.yaml in canonical data mount: "
                    f"{context.paths.data_root}."
                )
            if context.storage_validation is not None:
                for result in context.storage_validation.results:
                    if not result.valid:
                        errors.append(
                            result.reason or f"Invalid storage binding: {result.path}"
                        )
            if context.legacy_locator is not None:
                warnings.append(
                    "Verified legacy Taskledger files remain at "
                    f"{context.legacy_locator.taskledger_dir}; canonical mode is "
                    "active and legacy files are read-only."
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        return

    from taskledger.storage.paths import (
        DEFAULT_TASKLEDGER_DIR_NAME,
        PROJECT_CONFIG_FILENAMES,
    )

    config_candidates = [
        resolved_paths.workspace_root / filename
        for filename in PROJECT_CONFIG_FILENAMES
    ]
    if all(candidate.exists() for candidate in config_candidates):
        warnings.append(
            "Both taskledger.toml and .taskledger.toml exist; using .taskledger.toml."
        )
    if (
        locator.source == "legacy"
        and (resolved_paths.taskledger_dir / "project.toml").exists()
    ):
        warnings.append(
            "Legacy config location: .taskledger/project.toml. "
            "Move it to taskledger.toml before release."
        )

    # Config validation
    if resolved_paths.config_path.exists():
        try:
            from taskledger.storage.project_config import load_project_config_document

            load_project_config_document(resolved_paths.config_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    # Project UUID check
    if resolved_paths.config_path.exists():
        try:
            from taskledger.storage.project_identity import load_project_uuid

            project_uuid = load_project_uuid(resolved_paths.config_path)
            if project_uuid is None:
                errors.append(
                    "Project config has no project_uuid."
                    " Run 'taskledger init' or 'taskledger migrate apply'"
                    " to generate one and commit the config change."
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Invalid project_uuid: {exc}")

    # Ledger config check
    if resolved_paths.config_path.exists():
        try:
            from taskledger.storage.ledger_config import load_ledger_config

            ledger = load_ledger_config(resolved_paths.config_path)
            ledger_dir = resolved_paths.taskledger_dir / "ledgers" / ledger.ref
            if not ledger_dir.exists():
                repair_hints.append(
                    f"Ledger directory missing: {ledger_dir}."
                    " Run: taskledger init or taskledger ledger switch."
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Invalid ledger config: {exc}")

    # Legacy unscoped state check
    for legacy_name in (
        "tasks",
        "events",
        "indexes",
        "intros",
        "releases",
        "active-task.yaml",
    ):
        legacy_path = resolved_paths.taskledger_dir / legacy_name
        if legacy_path.exists():
            warnings.append(
                f"Legacy unscoped state at {legacy_path}."
                " Run: taskledger migrate branch-scoped-ledgers."
            )

    if not resolved_paths.taskledger_dir.exists():
        errors.append(
            "Configured taskledger_dir does not exist: "
            f"{resolved_paths.taskledger_dir}."
        )

    storage_meta_path = resolved_paths.taskledger_dir / "storage.yaml"
    if resolved_paths.taskledger_dir.exists() and not storage_meta_path.exists():
        errors.append(
            f"Missing storage.yaml in taskledger_dir: {resolved_paths.taskledger_dir}."
        )

    nested_storage_dir = resolved_paths.taskledger_dir / DEFAULT_TASKLEDGER_DIR_NAME
    if (
        resolved_paths.taskledger_dir
        != resolved_paths.workspace_root / DEFAULT_TASKLEDGER_DIR_NAME
        and nested_storage_dir.exists()
    ):
        warnings.append(
            "Configured taskledger_dir contains a nested .taskledger directory."
        )
        repair_hints.append(
            "Move taskledger state to the configured root and remove the nested "
            ".taskledger directory."
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

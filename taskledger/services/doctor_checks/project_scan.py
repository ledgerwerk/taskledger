"""Project-level config and layout scan for doctor."""

from __future__ import annotations

from pathlib import Path

from taskledger.storage.paths import ProjectLocator, ProjectPaths


def scan_project_config(
    *,
    workspace_root: Path,
    resolved_paths: ProjectPaths,
    locator: ProjectLocator,
    errors: list[str],
    warnings: list[str],
    repair_hints: list[str],
) -> None:
    """Scan project configuration, legacy state, and storage layout."""

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
        except Exception as exc:
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
        except Exception as exc:
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
        except Exception as exc:
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

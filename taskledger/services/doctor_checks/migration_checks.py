"""Legacy migration and orphan directory scans for doctor."""

from __future__ import annotations

from taskledger.domain.models import TaskRecord
from taskledger.storage.task_store import V2Paths


def scan_migration_state(
    *,
    tasks: list[TaskRecord],
    paths: V2Paths,
    errors: list[str],
    warnings: list[str],
    repair_hints: list[str],
) -> None:
    """Scan for legacy sidecars and orphan slug directories."""
    from taskledger.storage.task_store import task_dir

    # Detect orphan slug directories (empty dirs matching task slugs)
    task_slugs = {task.slug for task in tasks if task.slug}
    for child in paths.tasks_dir.iterdir():
        if (
            child.is_dir()
            and not child.name.startswith("task-")
            and child.name in task_slugs
            and not (child / "task.md").exists()
        ):
            is_empty = not any(child.iterdir())
            if is_empty:
                warnings.append(f"Orphan empty slug directory: {child.name}/")
                repair_hints.append(
                    "Remove orphan directory with `taskledger repair task-dirs`."
                )
            else:
                warnings.append(
                    f"Legacy slug sidecar directory retained: {child.name}/"
                )

    # Detect unsupported pre-release legacy YAML sidecars.
    legacy_sidecar_found = False
    for task in tasks:
        sidecar_dirs = [task_dir(paths, task.id)]
        if task.slug and task.slug != task.id:
            sidecar_dirs.append(paths.tasks_dir / task.slug)
        for sidecar_dir in sidecar_dirs:
            for legacy_name in (
                "todos.yaml",
                "links.yaml",
                "requirements.yaml",
            ):
                legacy_path = sidecar_dir / legacy_name
                if not legacy_path.exists():
                    continue
                legacy_sidecar_found = True
                warnings.append(
                    f"Unsupported pre-release legacy sidecar retained: {legacy_path}."
                )
    if legacy_sidecar_found:
        repair_hints.append(
            "Run a one-off migration script for pre-release sidecars "
            "or remove the legacy YAML sidecars after confirming their "
            "contents are obsolete."
        )

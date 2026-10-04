# Derived index files
#
# Index files under .taskledger/indexes/ are derived caches.
# They are rebuilt from canonical Markdown/YAML records by 'taskledger reindex'.
# They may be plain JSON arrays with no version metadata.
# They are never the authoritative source of truth.
# 'doctor indexes' checks staleness but not schema mismatches as migration blockers.

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar

if TYPE_CHECKING:
    from taskledger.storage.project_context import TaskledgerProjectContext

from taskledger import timing as _timing
from taskledger.domain.models import (
    ActiveActorState,
    ActiveHarnessState,
    ActiveTaskState,
    CodeChangeRecord,
    CodeReviewRecord,
    DependencyRequirement,
    FileLink,
    ImplementationCheckRecord,
    IntroductionRecord,
    LinkCollection,
    PlanRecord,
    QuestionRecord,
    ReleaseRecord,
    RequirementCollection,
    TaskHandoffRecord,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
    TodoCollection,
)
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
)
from taskledger.domain.task import is_archived_task
from taskledger.errors import ActiveTaskNotFound, LaunchError, NoActiveTask
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.frontmatter import (
    normalize_front_matter_newlines,
    read_markdown_front_matter,
    write_markdown_front_matter,
)
from taskledger.storage.locks import read_lock, remove_lock, update_lock, write_lock
from taskledger.storage.paths import ProjectPaths
from taskledger.storage.yaml_store import load_yaml_object, write_yaml_object
from taskledger.timeutils import utc_now_iso

T = TypeVar("T")


def _list_records(
    directory: Path,
    *,
    pattern: str,
    loader: Callable[[Path], T],
    sort_key: Callable[[T], Any] | None = None,
) -> list[T]:
    """Generic sidecar record enumerator: list files matching *pattern*, load, sort."""
    if not directory.exists():
        return []
    records: list[T] = []
    for path in sorted(directory.glob(pattern)):
        try:
            records.append(loader(path))
        except LaunchError as exc:
            logging.getLogger(__name__).warning(
                "Skipping malformed record %s: %s", path, exc
            )
    if sort_key is not None:
        records.sort(key=sort_key)
    return records


TaskVisibility = Literal["visible", "archived", "all"]


def _link_id_from_path(path: str) -> str:
    """Generate a deterministic link id from the path."""
    from taskledger.storage.common import content_hash as lc_content_hash

    digest = lc_content_hash(path)
    assert digest is not None
    return f"link-{digest[:8]}"


def _requirement_id_from_task(task_id: str) -> str:
    """Generate a deterministic requirement id from the required task id."""
    import re

    match = re.match(r"task-(\d+)", task_id)
    if match:
        return f"req-{match.group(1)}"
    return f"req-{task_id}"


@dataclass(slots=True, frozen=True)
class V2Paths:
    workspace_root: Path
    taskledger_root: Path
    runtime_root: Path
    ledger_ref: str
    ledger_dir: Path
    project_dir: Path  # alias for ledger_dir
    introductions_dir: Path
    releases_dir: Path
    tasks_dir: Path
    plans_dir: Path
    questions_dir: Path
    runs_dir: Path
    changes_dir: Path
    events_dir: Path
    indexes_dir: Path
    active_task_path: Path
    actor_path: Path
    harness_path: Path
    active_locks_index_path: Path
    dependencies_index_path: Path
    introductions_index_path: Path


def v2_paths_from_context(context: TaskledgerProjectContext) -> V2Paths:
    """Derive V2Paths from an already-loaded project context.

    This avoids re-loading the context when it is already available,
    e.g. from a command-scoped runtime.
    """
    if context.mode == "canonical":
        taskledger_root = context.paths.data_root
        ledger_dir = context.paths.ledger_data_dir
        indexes_dir = context.paths.ledger_indexes_dir
        return V2Paths(
            workspace_root=context.project_root,
            taskledger_root=taskledger_root,
            runtime_root=context.paths.runtime_root,
            ledger_ref=context.ledger_state.ref,
            ledger_dir=ledger_dir,
            project_dir=ledger_dir,
            introductions_dir=context.paths.introductions_dir,
            releases_dir=context.paths.releases_dir,
            tasks_dir=context.paths.tasks_dir,
            plans_dir=ledger_dir / "plans",
            questions_dir=ledger_dir / "questions",
            runs_dir=ledger_dir / "runs",
            changes_dir=ledger_dir / "changes",
            events_dir=context.paths.events_dir,
            indexes_dir=indexes_dir,
            active_task_path=context.paths.active_task_path,
            actor_path=context.paths.actor_path,
            harness_path=context.paths.harness_path,
            active_locks_index_path=context.paths.active_locks_index_path,
            dependencies_index_path=context.paths.dependencies_index_path,
            introductions_index_path=context.paths.introductions_index_path,
        )
    return _resolve_legacy_v2_paths(context.project_root)


def resolve_v2_paths(workspace_root: Path) -> V2Paths:
    from taskledger.errors import LaunchError
    from taskledger.storage.paths import probe_taskledger_project
    from taskledger.storage.project_context import load_project_context

    probe = probe_taskledger_project(workspace_root)
    if probe.source == "none":
        raise LaunchError(
            "TASKLEDGER_NOT_INITIALIZED: Taskledger is not initialized for this "
            "project. Run `taskledger init`.",
            code="TASKLEDGER_NOT_INITIALIZED",
            remediation=["Run `taskledger init`"],
            details={"project_root": str(probe.project_root)},
        )
    context = load_project_context(workspace_root, require_initialized=False)
    return v2_paths_from_context(context)


def _resolve_legacy_v2_paths(workspace_root: Path) -> V2Paths:
    from taskledger.storage.ledger_config import load_ledger_config
    from taskledger.storage.paths import load_project_locator

    locator = load_project_locator(workspace_root)
    taskledger_root = locator.taskledger_dir
    config = load_ledger_config(locator.config_path)
    ledger_dir = taskledger_root / "ledgers" / config.ref
    indexes_dir = ledger_dir / "indexes"
    return V2Paths(
        workspace_root=workspace_root,
        taskledger_root=taskledger_root,
        runtime_root=taskledger_root,
        ledger_ref=config.ref,
        ledger_dir=ledger_dir,
        project_dir=ledger_dir,
        introductions_dir=ledger_dir / "intros",
        releases_dir=ledger_dir / "releases",
        tasks_dir=ledger_dir / "tasks",
        plans_dir=ledger_dir / "plans",
        questions_dir=ledger_dir / "questions",
        runs_dir=ledger_dir / "runs",
        changes_dir=ledger_dir / "changes",
        events_dir=ledger_dir / "events",
        indexes_dir=indexes_dir,
        active_task_path=ledger_dir / "active-task.yaml",
        actor_path=taskledger_root / "actor.yaml",
        harness_path=taskledger_root / "harness.yaml",
        active_locks_index_path=indexes_dir / "active_locks.json",
        dependencies_index_path=indexes_dir / "dependencies.json",
        introductions_index_path=indexes_dir / "introductions.json",
    )


def initialize_legacy_v2_layout(workspace_root: Path) -> V2Paths:
    """Explicitly initialize the historical legacy layout for compatibility."""
    try:
        paths = resolve_v2_paths(workspace_root)
    except LaunchError:
        from taskledger.storage.paths import probe_taskledger_project

        if probe_taskledger_project(workspace_root).source == "canonical":
            raise
        # This side effect is reserved for explicit legacy init/fixtures.
        paths = _resolve_legacy_v2_paths(workspace_root)
    for directory in (
        paths.project_dir,
        paths.introductions_dir,
        paths.releases_dir,
        paths.tasks_dir,
        paths.events_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if not (paths.taskledger_root / "storage.yaml").exists():
        from taskledger.storage.meta import StorageMeta
        from taskledger.storage.yaml_store import write_yaml_object

        write_yaml_object(
            paths.taskledger_root / "storage.yaml",
            StorageMeta(created_with_taskledger="legacy").to_dict(),
        )
    # Indexes are a rebuildable cache. Legacy mode keeps the historical eager
    # files; canonical mode creates them only when an index writer requests it.
    if paths.indexes_dir == paths.ledger_dir / "indexes":
        paths.indexes_dir.mkdir(parents=True, exist_ok=True)
        for index_path in (
            paths.active_locks_index_path,
            paths.dependencies_index_path,
            paths.introductions_index_path,
        ):
            if not index_path.exists():
                atomic_write_text(index_path, "[]\n")
    return paths


def require_v2_layout(workspace_root: Path) -> V2Paths:
    """Resolve an initialized layout without creating directories or indexes."""
    paths = resolve_v2_paths(workspace_root)
    required = (paths.project_dir, paths.tasks_dir, paths.events_dir)
    missing = [path for path in required if not path.exists()]
    if missing:
        raise LaunchError(
            "Project state is not initialized. Missing: "
            + ", ".join(str(path) for path in missing)
            + ". Run `taskledger init`."
        )
    return paths


def ensure_v2_layout(workspace_root: Path) -> V2Paths:
    """Compatibility alias for explicit legacy initialization only."""
    from taskledger.storage.paths import probe_taskledger_project

    if probe_taskledger_project(workspace_root).source == "canonical":
        from taskledger.storage.project_context import require_mutable_project_context

        require_mutable_project_context(workspace_root, allow_legacy=False)
        return require_v2_layout(workspace_root)
    return initialize_legacy_v2_layout(workspace_root)


def list_tasks(workspace_root: Path) -> list[TaskRecord]:
    return list_tasks_from_paths(resolve_v2_paths(workspace_root))


def list_tasks_from_paths(paths: V2Paths) -> list[TaskRecord]:
    from taskledger.storage.task_identity import task_identity_inventory

    inventory = task_identity_inventory(paths)
    tasks = [
        _load_task(
            identity.path / "task.md",
            paths=paths,
            task_id=identity.task_id,
            task_uuid=str(identity.task_uuid),
        )
        for identity in inventory.entries
        if (identity.path / "task.md").is_file()
    ]
    return sorted(tasks, key=lambda item: item.id)


def list_tasks_by_visibility(
    workspace_root: Path,
    *,
    visibility: TaskVisibility = "visible",
) -> list[TaskRecord]:
    return list_tasks_by_visibility_from_paths(
        resolve_v2_paths(workspace_root), visibility=visibility
    )


def list_tasks_by_visibility_from_paths(
    paths: V2Paths,
    *,
    visibility: TaskVisibility = "visible",
) -> list[TaskRecord]:
    tasks = list_tasks_from_paths(paths)
    if visibility == "all":
        return tasks
    if visibility == "archived":
        return [task for task in tasks if is_archived_task(task)]
    return [task for task in tasks if not is_archived_task(task)]


def resolve_task(
    workspace_root: Path,
    ref: str,
    *,
    include_archived: bool = False,
) -> TaskRecord:
    normalized_ref = ref.strip().lower()
    normalized_id = (
        normalized_ref
        if len(normalized_ref) == 36 and normalized_ref.count("-") == 4
        else _normalize_resource_ref(workspace_root, normalized_ref, "task")
    )

    # Direct-path: if the normalized ref is a task ID, try reading just that file.
    if normalized_id.startswith("task-") or (
        len(normalized_ref) == 36 and normalized_ref.count("-") == 4
    ):
        paths = resolve_v2_paths(workspace_root)
        from taskledger.storage.task_identity import task_identity_for_ref

        try:
            identity = task_identity_for_ref(paths, normalized_id)
        except LaunchError:
            identity = None
        if identity is not None:
            path = identity.path / "task.md"
            if path.exists():
                task = _load_task(
                    path,
                    task_id=identity.task_id,
                    task_uuid=str(identity.task_uuid),
                )
                if include_archived or not is_archived_task(task):
                    return task
    # If this input looks like a global/file ref and parsing failed, surface that error.
    if _looks_like_global_ref(normalized_ref) and not normalized_id.startswith("task-"):
        raise LaunchError(f"Task not found: {ref}")

    # Fallback: full scan for slug lookup or archived ID miss.
    tasks = list_tasks(workspace_root)
    for task in tasks:
        if task.id == ref or task.id == normalized_id:
            return task
    visible_matches = [
        task
        for task in tasks
        if not is_archived_task(task) and task.slug == normalized_ref
    ]
    if len(visible_matches) == 1:
        return visible_matches[0]
    if len(visible_matches) > 1:
        raise LaunchError(f"Duplicate visible task slug: {ref}")
    if not include_archived:
        raise LaunchError(f"Task not found: {ref}")
    archived_matches = [
        task for task in tasks if is_archived_task(task) and task.slug == normalized_ref
    ]
    if len(archived_matches) == 1:
        return archived_matches[0]
    if len(archived_matches) > 1:
        ids = ", ".join(sorted(task.id for task in archived_matches))
        raise LaunchError(f"Archived task slug is ambiguous: {ref}. Use one of: {ids}")
    raise LaunchError(f"Task not found: {ref}")


def load_active_task_state(workspace_root: Path) -> ActiveTaskState | None:
    return load_active_task_state_from_paths(resolve_v2_paths(workspace_root))


def load_active_task_state_from_paths(
    paths: V2Paths,
) -> ActiveTaskState | None:
    if not paths.active_task_path.exists():
        return None
    payload = load_yaml_object(
        paths.active_task_path, "active task state", missing="empty"
    )
    state = ActiveTaskState.from_dict(payload)
    from taskledger.storage.task_identity import (
        AMBIGUOUS_LEGACY_TASK_REF,
        task_identity_for_stored_ref,
    )

    try:
        identity = task_identity_for_stored_ref(
            paths, task_id=state.task_id, task_uuid=state.task_uuid
        )
    except LaunchError as exc:
        if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
            raise
        identity = None
    if identity is not None:
        state = replace(
            state, task_id=identity.task_id, task_uuid=str(identity.task_uuid)
        )
    if state.previous_task_uuid or state.previous_task_id:
        try:
            previous = task_identity_for_stored_ref(
                paths,
                task_id=state.previous_task_id or "",
                task_uuid=state.previous_task_uuid,
            )
        except LaunchError as exc:
            if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                raise
            previous = None
        if previous is not None:
            state = replace(
                state,
                previous_task_id=previous.task_id,
                previous_task_uuid=str(previous.task_uuid),
            )
    return state


def save_active_task_state(
    workspace_root: Path,
    state: ActiveTaskState,
) -> ActiveTaskState:
    paths = require_v2_layout(workspace_root)
    from taskledger.storage.task_identity import (
        AMBIGUOUS_LEGACY_TASK_REF,
        task_identity_for_stored_ref,
    )

    try:
        identity = task_identity_for_stored_ref(
            paths, task_id=state.task_id, task_uuid=state.task_uuid
        )
    except LaunchError as exc:
        if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
            raise
    else:
        state = replace(
            state, task_id=identity.task_id, task_uuid=str(identity.task_uuid)
        )
    if state.previous_task_uuid or state.previous_task_id:
        try:
            previous = task_identity_for_stored_ref(
                paths,
                task_id=state.previous_task_id or "",
                task_uuid=state.previous_task_uuid,
            )
        except LaunchError as exc:
            from taskledger.storage.task_identity import AMBIGUOUS_LEGACY_TASK_REF

            if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                raise
            previous = None
        if previous is not None:
            state = replace(
                state,
                previous_task_id=previous.task_id,
                previous_task_uuid=str(previous.task_uuid),
            )
    write_yaml_object(paths.active_task_path, state.to_dict())
    return state


def clear_active_task_state(workspace_root: Path) -> ActiveTaskState | None:
    paths = require_v2_layout(workspace_root)
    state = load_active_task_state(workspace_root)
    if paths.active_task_path.exists():
        paths.active_task_path.unlink()
    return state


def load_actor_state(workspace_root: Path) -> ActiveActorState | None:
    paths = resolve_v2_paths(workspace_root)
    if not paths.actor_path.exists():
        return None
    payload = load_yaml_object(paths.actor_path, "actor state", missing="empty")
    return ActiveActorState.from_dict(payload)


def save_actor_state(
    workspace_root: Path,
    state: ActiveActorState,
) -> ActiveActorState:
    paths = require_v2_layout(workspace_root)
    write_yaml_object(paths.actor_path, state.to_dict())
    return state


def clear_actor_state(workspace_root: Path) -> ActiveActorState | None:
    paths = require_v2_layout(workspace_root)
    state = load_actor_state(workspace_root)
    if paths.actor_path.exists():
        paths.actor_path.unlink()
    return state


def load_harness_state(workspace_root: Path) -> ActiveHarnessState | None:
    paths = resolve_v2_paths(workspace_root)
    if not paths.harness_path.exists():
        return None
    payload = load_yaml_object(paths.harness_path, "harness state", missing="empty")
    return ActiveHarnessState.from_dict(payload)


def save_harness_state(
    workspace_root: Path,
    state: ActiveHarnessState,
) -> ActiveHarnessState:
    paths = require_v2_layout(workspace_root)
    write_yaml_object(paths.harness_path, state.to_dict())
    return state


def clear_harness_state(workspace_root: Path) -> ActiveHarnessState | None:
    paths = require_v2_layout(workspace_root)
    state = load_harness_state(workspace_root)
    if paths.harness_path.exists():
        paths.harness_path.unlink()
    return state


def resolve_active_task(workspace_root: Path) -> TaskRecord:
    state = load_active_task_state(workspace_root)
    if state is None:
        raise NoActiveTask()
    try:
        return resolve_task(workspace_root, state.task_uuid or state.task_id)
    except LaunchError as exc:
        raise ActiveTaskNotFound(
            f"Active task points to missing task: {state.task_id}",
            details={"task_id": state.task_id},
            task_id=state.task_id,
        ) from exc


def resolve_task_or_active(
    workspace_root: Path,
    ref: str | None = None,
    *,
    include_archived: bool = False,
) -> TaskRecord:
    if ref is not None and ref.strip():
        return resolve_task(
            workspace_root,
            ref,
            include_archived=include_archived,
        )
    return resolve_active_task(workspace_root)


def save_task(workspace_root: Path, task: TaskRecord) -> TaskRecord:
    return save_task_from_paths(require_v2_layout(workspace_root), task)


def save_task_from_paths(paths: V2Paths, task: TaskRecord) -> TaskRecord:
    if task.task_uuid is None:
        from taskledger.storage.task_identity import (
            allocate_task_identity,
            task_identity_for_ref,
        )

        try:
            identity = task_identity_for_ref(paths, task.id)
        except LaunchError:
            allocation = allocate_task_identity(paths)
            task = replace(
                task,
                id=allocation.task_id,
                task_uuid=str(allocation.task_uuid),
            )
        else:
            task = replace(
                task,
                id=identity.task_id,
                task_uuid=str(identity.task_uuid),
            )
    from taskledger.storage.task_identity import (
        invalidate_task_identity_inventory,
        task_path_for_uuid,
    )

    bundle_dir = (
        task_path_for_uuid(paths, task.task_uuid)
        if task.task_uuid is not None
        else task_dir(paths, task.id)
    )
    _ensure_task_bundle(paths, task.id, bundle_dir=bundle_dir)
    path = bundle_dir / "task.md"
    metadata = task.to_dict()
    metadata.pop("todos", None)
    metadata.pop("file_links", None)
    metadata.pop("requirements", None)
    _write_markdown_record(path, metadata, task.body)
    invalidate_task_identity_inventory()
    with _timing.stage("derived_index_update"):
        try:
            from taskledger.storage.task_index import update_task_index_entry

            update_task_index_entry(paths, task)
        except Exception:
            logging.getLogger(__name__).debug(
                "Failed to update task index for %s", task.id, exc_info=True
            )
    return task


def list_introductions(workspace_root: Path) -> list[IntroductionRecord]:
    return list_introductions_from_paths(resolve_v2_paths(workspace_root))


def list_introductions_from_paths(paths: V2Paths) -> list[IntroductionRecord]:
    return sorted(
        [_load_intro(path) for path in paths.introductions_dir.glob("intro-*.md")],
        key=lambda item: item.id,
    )


def _normalize_release(paths: V2Paths, release: ReleaseRecord) -> ReleaseRecord:
    from taskledger.storage.task_identity import (
        AMBIGUOUS_LEGACY_TASK_REF,
        task_identity_for_stored_ref,
    )

    try:
        identity = task_identity_for_stored_ref(
            paths,
            task_id=release.boundary_task_id,
            task_uuid=release.boundary_task_uuid,
        )
    except LaunchError as exc:
        if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
            raise
        return release
    return replace(
        release,
        boundary_task_id=identity.task_id,
        boundary_task_uuid=str(identity.task_uuid),
    )


def list_releases(workspace_root: Path) -> list[ReleaseRecord]:
    return list_releases_from_paths(resolve_v2_paths(workspace_root))


def list_releases_from_paths(paths: V2Paths) -> list[ReleaseRecord]:
    return sorted(
        [
            _normalize_release(paths, _load_release(path))
            for path in paths.releases_dir.glob("*.md")
        ],
        key=lambda item: (task_numeric_sort_key(item.boundary_task_id), item.version),
    )


def resolve_release(workspace_root: Path, version: str) -> ReleaseRecord:
    paths = resolve_v2_paths(workspace_root)
    path = release_markdown_path(paths, version)
    if not path.exists():
        raise LaunchError(f"Release not found: {version}")
    return _normalize_release(paths, _load_release(path))


def save_release(workspace_root: Path, release: ReleaseRecord) -> ReleaseRecord:
    paths = require_v2_layout(workspace_root)
    release = _normalize_release(paths, release)
    path = release_markdown_path(paths, release.version)
    if path.exists():
        raise LaunchError(f"Release version already exists: {release.version}")
    _write_markdown_record(path, release.to_dict(), release.note or "")
    return release


def resolve_introduction(workspace_root: Path, ref: str) -> IntroductionRecord:
    return resolve_introduction_from_paths(resolve_v2_paths(workspace_root), ref)


def resolve_introduction_from_paths(paths: V2Paths, ref: str) -> IntroductionRecord:
    normalized_ref = ref.strip().lower()
    for intro in list_introductions_from_paths(paths):
        if intro.id == ref or intro.slug == normalized_ref:
            return intro
    raise LaunchError(f"Introduction not found: {ref}")


def save_introduction(
    workspace_root: Path, introduction: IntroductionRecord
) -> IntroductionRecord:
    return save_introduction_from_paths(require_v2_layout(workspace_root), introduction)


def save_introduction_from_paths(
    paths: V2Paths, introduction: IntroductionRecord
) -> IntroductionRecord:
    path = paths.introductions_dir / f"{introduction.id}.md"
    _write_markdown_record(path, introduction.to_dict(), introduction.body)
    from taskledger.storage.indexes import (
        mark_index_dirty,
        update_introduction_index_entry,
    )

    try:
        update_introduction_index_entry(paths, introduction)
    except Exception:
        mark_index_dirty(paths, "introductions")
        logging.getLogger(__name__).debug(
            "Failed to update introduction index for %s",
            introduction.id,
            exc_info=True,
        )
    return introduction


def rewrite_task_refs(task_dir: Path, old_task_id: str, new_task_id: str) -> None:
    """Rewrite old_task_id -> new_task_id in all .md files under task_dir.

    Parses front matter, updates:
    - ``id`` when its current value equals old_task_id
    - ``task_id`` always set to new_task_id (adds it if missing)

    Falls back to plain string replacement for files that cannot be parsed.
    """
    if old_task_id == new_task_id:
        return
    for md_file in sorted(task_dir.rglob("*.md")):
        try:
            metadata, body = read_markdown_front_matter(md_file)
            if metadata.get("id") == old_task_id:
                metadata["id"] = new_task_id
            metadata["task_id"] = new_task_id
            write_markdown_front_matter(md_file, metadata, body)
        except Exception:  # noqa: BLE001
            # Fall back to plain string replacement for unparseable files.
            content = md_file.read_text(encoding="utf-8")
            if old_task_id in content:
                content = content.replace(old_task_id, new_task_id)
                md_file.write_text(content, encoding="utf-8")


def list_plans(workspace_root: Path, task_id: str) -> list[PlanRecord]:
    paths = resolve_v2_paths(workspace_root)
    return list_plans_from_paths(paths, task_id)


def list_plans_from_paths(paths: V2Paths, task_id: str) -> list[PlanRecord]:
    directory = task_plans_dir(paths, task_id)
    return _list_records(
        directory,
        pattern="plan-v*.md",
        loader=_load_plan,
        sort_key=lambda item: item.plan_version,
    )


def save_plan(workspace_root: Path, plan: PlanRecord) -> PlanRecord:
    paths = require_v2_layout(workspace_root)
    path = plan_markdown_path(paths, plan.task_id, plan.plan_version)
    if path.exists():
        raise LaunchError(
            f"Plan version already exists: {plan.task_id} v{plan.plan_version}"
        )
    _write_markdown_record(path, plan.to_dict(), plan.body)
    return plan


def overwrite_plan(workspace_root: Path, plan: PlanRecord) -> PlanRecord:
    paths = require_v2_layout(workspace_root)
    path = plan_markdown_path(paths, plan.task_id, plan.plan_version)
    _write_markdown_record(path, plan.to_dict(), plan.body)
    return plan


def resolve_plan(
    workspace_root: Path,
    task_id: str,
    *,
    version: int | None = None,
) -> PlanRecord:
    plans = list_plans(workspace_root, task_id)
    if not plans:
        raise LaunchError(f"No plans found for task {task_id}")
    if version is None:
        return plans[-1]
    for plan in plans:
        if plan.plan_version == version:
            return plan
    raise LaunchError(f"Plan version not found for task {task_id}: {version}")


def list_questions(workspace_root: Path, task_id: str) -> list[QuestionRecord]:
    paths = resolve_v2_paths(workspace_root)
    return list_questions_from_paths(paths, task_id)


def list_questions_from_paths(paths: V2Paths, task_id: str) -> list[QuestionRecord]:
    directory = task_questions_dir(paths, task_id)
    return _list_records(
        directory,
        pattern="q-*.md",
        loader=_load_question,
        sort_key=lambda item: item.id,
    )


def resolve_question(
    workspace_root: Path, task_id: str, question_id: str
) -> QuestionRecord:
    normalized_id = _normalize_resource_ref(workspace_root, question_id, "q")
    for question in list_questions(workspace_root, task_id):
        if question.id == question_id or question.id == normalized_id:
            return question
    raise LaunchError(f"Question not found: {question_id}")


def save_question(workspace_root: Path, question: QuestionRecord) -> QuestionRecord:
    paths = require_v2_layout(workspace_root)
    path = question_markdown_path(paths, question.task_id, question.id)
    _write_markdown_record(path, question.to_dict(), _render_question_body(question))
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        questions = list_questions_from_paths(paths, question.task_id)
        update_sidecar_summary(paths, question.task_id, questions=questions)
    except Exception:
        from taskledger.storage.indexes import mark_index_dirty

        mark_index_dirty(paths, "sidecar_index", task_id=question.task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            question.task_id,
            exc_info=True,
        )
    return question


def list_runs(workspace_root: Path, task_id: str) -> list[TaskRunRecord]:
    paths = resolve_v2_paths(workspace_root)
    return list_runs_from_paths(paths, task_id)


def list_runs_from_paths(paths: V2Paths, task_id: str) -> list[TaskRunRecord]:
    directory = task_runs_dir(paths, task_id)
    return _list_records(
        directory, pattern="*.md", loader=_load_run, sort_key=lambda item: item.run_id
    )


def resolve_run(workspace_root: Path, task_id: str, run_id: str) -> TaskRunRecord:
    normalized_id = _normalize_resource_ref(workspace_root, run_id, "run")
    for run in list_runs(workspace_root, task_id):
        if run.run_id == run_id or run.run_id == normalized_id:
            return run
    raise LaunchError(f"Run not found: {run_id}")


def save_run(workspace_root: Path, run: TaskRunRecord) -> TaskRunRecord:
    paths = require_v2_layout(workspace_root)
    path = run_markdown_path(paths, run.task_id, run.run_id)
    _write_markdown_record(path, run.to_dict(), _render_run_body(run))
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        runs = list_runs_from_paths(paths, run.task_id)
        update_sidecar_summary(paths, run.task_id, runs=runs)
    except Exception:
        from taskledger.storage.indexes import mark_index_dirty

        mark_index_dirty(paths, "sidecar_index", task_id=run.task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            run.task_id,
            exc_info=True,
        )
    return run


def list_changes(workspace_root: Path, task_id: str) -> list[CodeChangeRecord]:
    paths = resolve_v2_paths(workspace_root)
    return list_changes_from_paths(paths, task_id)


def list_changes_from_paths(paths: V2Paths, task_id: str) -> list[CodeChangeRecord]:
    directory = task_changes_dir(paths, task_id)
    return _list_records(
        directory,
        pattern="change-*.md",
        loader=_load_change,
        sort_key=lambda item: item.change_id,
    )


def save_change(workspace_root: Path, change: CodeChangeRecord) -> CodeChangeRecord:
    paths = require_v2_layout(workspace_root)
    path = change_markdown_path(paths, change.task_id, change.change_id)
    _write_markdown_record(path, change.to_dict(), change.summary)
    return change


def resolve_change(
    workspace_root: Path, task_id: str, change_id: str
) -> CodeChangeRecord:
    normalized_id = _normalize_resource_ref(workspace_root, change_id, "change")
    for change in list_changes(workspace_root, task_id):
        if change.change_id == change_id or change.change_id == normalized_id:
            return change
    raise LaunchError(f"Change not found: {change_id}")


def list_checks(workspace_root: Path, task_id: str) -> list[ImplementationCheckRecord]:
    return list_checks_from_paths(resolve_v2_paths(workspace_root), task_id)


def list_checks_from_paths(
    paths: V2Paths, task_id: str
) -> list[ImplementationCheckRecord]:
    directory = task_checks_dir(paths, task_id)
    return sorted(
        [_load_check(path) for path in directory.glob("check-*.md")],
        key=lambda check: check.check_id,
    )


def save_check(
    workspace_root: Path,
    check: ImplementationCheckRecord,
) -> ImplementationCheckRecord:
    paths = require_v2_layout(workspace_root)
    path = check_markdown_path(paths, check.task_id, check.check_id)
    _write_markdown_record(path, check.to_dict(), "")
    return check


def resolve_check(
    workspace_root: Path, task_id: str, check_id: str
) -> ImplementationCheckRecord:
    normalized_id = _normalize_resource_ref(workspace_root, check_id, "check")
    for check in list_checks(workspace_root, task_id):
        if check.check_id == check_id or check.check_id == normalized_id:
            return check
    raise LaunchError(f"Check not found: {check_id}")


def list_code_reviews(workspace_root: Path, task_id: str) -> list[CodeReviewRecord]:
    return list_code_reviews_from_paths(resolve_v2_paths(workspace_root), task_id)


def list_code_reviews_from_paths(
    paths: V2Paths, task_id: str
) -> list[CodeReviewRecord]:
    directory = task_reviews_dir(paths, task_id)
    return sorted(
        [_load_code_review(path) for path in directory.glob("review-*.md")],
        key=lambda item: item.review_id,
    )


def save_code_review(
    workspace_root: Path,
    review: CodeReviewRecord,
) -> CodeReviewRecord:
    paths = require_v2_layout(workspace_root)
    path = code_review_markdown_path(paths, review.task_id, review.review_id)
    _write_markdown_record(path, review.to_dict(), review.body)
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        reviews = list_code_reviews_from_paths(paths, review.task_id)
        latest_impl_run = _task_latest_impl_run_from_paths(paths, review.task_id)
        update_sidecar_summary(
            paths,
            review.task_id,
            reviews=reviews,
            latest_implementation_run=latest_impl_run,
        )
    except Exception:
        from taskledger.storage.indexes import mark_index_dirty

        mark_index_dirty(paths, "sidecar_index", task_id=review.task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            review.task_id,
            exc_info=True,
        )
    return review


def resolve_code_review(
    workspace_root: Path,
    task_id: str,
    review_ref: str,
) -> CodeReviewRecord:
    normalized_id = _normalize_resource_ref(workspace_root, review_ref, "review")
    for review in list_code_reviews(workspace_root, task_id):
        if review.review_id == review_ref or review.review_id == normalized_id:
            return review
    raise LaunchError(f"Code review not found: {review_ref}")


def load_lock_records(workspace_root: Path) -> list[TaskLock]:
    """Load all readable lock files (no expiry filter)."""
    paths = resolve_v2_paths(workspace_root)
    return load_lock_records_from_paths(paths)


def load_lock_records_from_paths(paths: V2Paths) -> list[TaskLock]:
    """Load all readable lock files from resolved paths (no expiry filter)."""
    from taskledger.storage.task_identity import (
        AMBIGUOUS_LEGACY_TASK_REF,
        task_identity_for_stored_ref,
    )

    locks: list[TaskLock] = []
    lock_dir = paths.runtime_root / "checkouts" / paths.ledger_ref / "locks"
    lock_paths = list(lock_dir.glob("*.yaml"))
    # Read bundle-local locks during the compatibility window.
    lock_paths.extend(paths.tasks_dir.glob("*/lock.yaml"))
    for path in sorted(lock_paths):
        lock = read_lock(path)
        if lock is None:
            continue
        path_ref = path.parent.name if path.name == "lock.yaml" else path.stem
        path_uuid = (
            path_ref if len(path_ref) == 36 and path_ref.count("-") == 4 else None
        )
        try:
            identity = task_identity_for_stored_ref(
                paths,
                task_id=lock.task_id,
                task_uuid=lock.task_uuid or path_uuid,
            )
        except LaunchError as exc:
            if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                raise
            locks.append(lock)
            continue
        locks.append(
            replace(
                lock,
                task_id=identity.task_id,
                task_uuid=str(identity.task_uuid),
            )
        )
    return locks


# Compatibility alias retained during transition.
load_active_locks_from_paths = load_lock_records_from_paths


def load_active_locks(workspace_root: Path) -> list[TaskLock]:
    """Load non-expired locks only (compatibility wrapper)."""
    from taskledger.storage.locks import lock_is_expired

    return [
        lock for lock in load_lock_records(workspace_root) if not lock_is_expired(lock)
    ]


def load_todos(workspace_root: Path, task_id: str) -> TodoCollection:
    paths = resolve_v2_paths(workspace_root)
    return load_todos_from_paths(paths, task_id)


def load_todos_from_paths(paths: V2Paths, task_id: str) -> TodoCollection:
    directory = task_todos_dir(paths, task_id)
    records = sorted(
        [_load_record(p, TaskTodo.from_dict) for p in directory.glob("todo-*.md")],
        key=lambda t: t.id,
    )
    return TodoCollection(task_id=task_id, todos=tuple(records))


def save_todos(workspace_root: Path, collection: TodoCollection) -> TodoCollection:
    paths = require_v2_layout(workspace_root)
    _ensure_task_bundle(paths, collection.task_id)
    directory = task_todos_dir(paths, collection.task_id)
    directory.mkdir(parents=True, exist_ok=True)
    keep_ids = set()
    now = utc_now_iso()
    for todo in collection.todos:
        keep_ids.add(todo.id)
        metadata = todo.to_dict()
        metadata["task_id"] = collection.task_id
        metadata["file_version"] = TASKLEDGER_V2_FILE_VERSION
        metadata["schema_version"] = TASKLEDGER_SCHEMA_VERSION
        metadata["object_type"] = "todo"
        if "updated_at" not in metadata or metadata["updated_at"] is None:
            metadata["updated_at"] = now
        body = todo.text
        path = todo_markdown_path(paths, collection.task_id, todo.id)
        _write_markdown_record(path, metadata, body)
    # Remove stale files
    for path in directory.glob("todo-*.md"):
        if path.stem not in keep_ids:
            path.unlink()
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        update_sidecar_summary(paths, collection.task_id, todos=list(collection.todos))
    except Exception:
        from taskledger.storage.indexes import mark_index_dirty

        mark_index_dirty(paths, "sidecar_index", task_id=collection.task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            collection.task_id,
            exc_info=True,
        )
    return collection


def load_links(workspace_root: Path, task_id: str) -> LinkCollection:
    paths = resolve_v2_paths(workspace_root)
    directory = task_links_dir(paths, task_id)
    records = sorted(
        [_load_record(p, FileLink.from_dict) for p in directory.glob("link-*.md")],
        key=lambda lk: lk.id or "",
    )
    return LinkCollection(task_id=task_id, links=tuple(records))


def save_links(workspace_root: Path, collection: LinkCollection) -> LinkCollection:
    paths = require_v2_layout(workspace_root)
    _ensure_task_bundle(paths, collection.task_id)
    directory = task_links_dir(paths, collection.task_id)
    directory.mkdir(parents=True, exist_ok=True)
    keep_ids = set()
    now = utc_now_iso()
    for link in collection.links:
        link_id = link.id or _link_id_from_path(link.path)
        keep_ids.add(link_id)
        metadata = link.to_dict()
        metadata["id"] = link_id
        metadata["task_id"] = collection.task_id
        metadata["file_version"] = TASKLEDGER_V2_FILE_VERSION
        metadata["schema_version"] = TASKLEDGER_SCHEMA_VERSION
        metadata["object_type"] = "link"
        if metadata.get("created_at") is None:
            metadata["created_at"] = now
        if metadata.get("updated_at") is None:
            metadata["updated_at"] = now
        body = link.path
        path = link_markdown_path(paths, collection.task_id, link_id)
        _write_markdown_record(path, metadata, body)
    # Remove stale files
    for path in directory.glob("link-*.md"):
        if path.stem not in keep_ids:
            path.unlink()
    return collection


def load_requirements(workspace_root: Path, task_id: str) -> RequirementCollection:
    return load_requirements_from_paths(resolve_v2_paths(workspace_root), task_id)


def load_requirements_from_paths(paths: V2Paths, task_id: str) -> RequirementCollection:
    directory = task_requirements_dir(paths, task_id)
    records = sorted(
        [
            _load_record(p, DependencyRequirement.from_dict)
            for p in directory.glob("req-*.md")
        ],
        key=lambda r: r.id or "",
    )
    from taskledger.storage.task_identity import (
        AMBIGUOUS_LEGACY_TASK_REF,
        task_identity_for_stored_ref,
    )

    normalized: list[DependencyRequirement] = []
    for requirement in records:
        try:
            required = task_identity_for_stored_ref(
                paths,
                task_id=requirement.required_task_id or requirement.task_id,
                task_uuid=requirement.required_task_uuid,
            )
        except LaunchError as exc:
            if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                raise
            normalized_requirement = requirement
        else:
            normalized_requirement = replace(
                requirement,
                task_id=required.task_id,
                required_task_id=required.task_id,
                required_task_uuid=str(required.task_uuid),
            )
        if (
            normalized_requirement.parent_task_uuid
            or normalized_requirement.parent_task_id
        ):
            try:
                parent = task_identity_for_stored_ref(
                    paths,
                    task_id=normalized_requirement.parent_task_id or "",
                    task_uuid=normalized_requirement.parent_task_uuid,
                )
            except LaunchError as exc:
                if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                    raise
            else:
                normalized_requirement = replace(
                    normalized_requirement,
                    parent_task_id=parent.task_id,
                    parent_task_uuid=str(parent.task_uuid),
                )
        normalized.append(normalized_requirement)
    return RequirementCollection(task_id=task_id, requirements=tuple(normalized))


def save_requirements(
    workspace_root: Path, collection: RequirementCollection
) -> RequirementCollection:
    return save_requirements_from_paths(require_v2_layout(workspace_root), collection)


def save_requirements_from_paths(
    paths: V2Paths, collection: RequirementCollection
) -> RequirementCollection:
    _ensure_task_bundle(paths, collection.task_id)
    directory = task_requirements_dir(paths, collection.task_id)
    directory.mkdir(parents=True, exist_ok=True)
    keep_ids = set()
    now = utc_now_iso()
    for req in collection.requirements:
        req_id = req.id or _requirement_id_from_task(req.task_id)
        keep_ids.add(req_id)
        metadata = req.to_dict()
        metadata["id"] = req_id
        metadata["task_id"] = collection.task_id
        metadata["required_task_id"] = req.required_task_id or req.task_id
        metadata["file_version"] = TASKLEDGER_V2_FILE_VERSION
        metadata["schema_version"] = TASKLEDGER_SCHEMA_VERSION
        metadata["object_type"] = "requirement"
        if metadata.get("created_at") is None:
            metadata["created_at"] = now
        if metadata.get("updated_at") is None:
            metadata["updated_at"] = now
        body = (
            f"Requires {req.required_task_id or req.task_id}"
            f" to be {req.required_status}."
        )
        path = requirement_markdown_path(paths, collection.task_id, req_id)
        _write_markdown_record(path, metadata, body)
    for path in directory.glob("req-*.md"):
        if path.stem not in keep_ids:
            path.unlink()

    from taskledger.storage.indexes import (
        mark_index_dirty,
        update_dependency_index_entry,
    )

    try:
        update_dependency_index_entry(
            paths,
            collection.task_id,
            [req.required_task_id or req.task_id for req in collection.requirements],
        )
    except Exception:
        mark_index_dirty(paths, "dependencies", task_id=collection.task_id)
        logging.getLogger(__name__).debug(
            "Failed to update dependency index for %s",
            collection.task_id,
            exc_info=True,
        )
    return collection


def task_dir(paths: V2Paths, task_id: str) -> Path:
    from taskledger.storage.task_identity import task_identity_for_ref

    return task_identity_for_ref(paths, task_id).path


def task_markdown_path(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "task.md"


def task_lock_path(paths: V2Paths, task_id: str) -> Path:
    from taskledger.storage.task_identity import task_uuid_from_ref

    lock_dir = paths.runtime_root / "checkouts" / paths.ledger_ref / "locks"
    try:
        lock_name = str(task_uuid_from_ref(paths, task_id))
    except LaunchError:
        lock_name = task_id
    uuid_path = lock_dir / f"{lock_name}.yaml"
    legacy_path = lock_dir / f"{task_id}.yaml"
    if not uuid_path.exists() and task_id.startswith("task-") and legacy_path.exists():
        return legacy_path
    return uuid_path


def task_todos_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "todos"


def task_links_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "links"


def task_requirements_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "requirements"


def task_todos_path(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "todos.yaml"


def task_links_path(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "links.yaml"


def task_requirements_path(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "requirements.yaml"


def todo_markdown_path(paths: V2Paths, task_id: str, todo_id: str) -> Path:
    return task_todos_dir(paths, task_id) / f"{todo_id}.md"


def link_markdown_path(paths: V2Paths, task_id: str, link_id: str) -> Path:
    return task_links_dir(paths, task_id) / f"{link_id}.md"


def requirement_markdown_path(paths: V2Paths, task_id: str, req_id: str) -> Path:
    return task_requirements_dir(paths, task_id) / f"{req_id}.md"


def task_plans_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "plans"


def task_questions_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "questions"


def task_runs_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "runs"


def task_changes_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "changes"


def task_checks_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "checks"


def task_reviews_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "reviews"


def task_artifacts_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "artifacts"


def task_audit_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "audit"


def task_handoffs_dir(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "handoffs"


def handoff_markdown_path(paths: V2Paths, task_id: str, handoff_id: str) -> Path:
    return task_handoffs_dir(paths, task_id) / f"{handoff_id}.md"


def release_filename(version: str) -> str:
    normalized = version.strip()
    if not normalized:
        raise LaunchError("Release version must not be empty.")
    if normalized != version or any(char.isspace() for char in normalized):
        raise LaunchError("Release version must not contain whitespace.")
    if "/" in normalized or "\\" in normalized:
        raise LaunchError("Release version must not contain path separators.")
    if any(ord(char) < 32 for char in normalized):
        raise LaunchError("Release version must not contain control characters.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", normalized):
        raise LaunchError(f"Unsupported release version: {version}")
    return f"{normalized}.md"


def release_markdown_path(paths: V2Paths | ProjectPaths, version: str) -> Path:
    return paths.releases_dir / release_filename(version)


def plan_markdown_path(paths: V2Paths, task_id: str, version: int) -> Path:
    return task_plans_dir(paths, task_id) / f"plan-v{version}.md"


def question_markdown_path(paths: V2Paths, task_id: str, question_id: str) -> Path:
    return task_questions_dir(paths, task_id) / f"{question_id}.md"


def run_markdown_path(paths: V2Paths, task_id: str, run_id: str) -> Path:
    return task_runs_dir(paths, task_id) / f"{run_id}.md"


def change_markdown_path(paths: V2Paths, task_id: str, change_id: str) -> Path:
    return task_changes_dir(paths, task_id) / f"{change_id}.md"


def check_markdown_path(paths: V2Paths, task_id: str, check_id: str) -> Path:
    return task_checks_dir(paths, task_id) / f"{check_id}.md"


def code_review_markdown_path(paths: V2Paths, task_id: str, review_id: str) -> Path:
    return task_reviews_dir(paths, task_id) / f"{review_id}.md"


def _load_task(
    path: Path,
    *,
    paths: V2Paths | None = None,
    task_id: str | None = None,
    task_uuid: str | None = None,
) -> TaskRecord:
    task = _load_record(path, TaskRecord.from_dict)
    from taskledger.ids import parse_uuid7

    if paths is not None and (task_id is None or task_uuid is None):
        from taskledger.storage.task_identity import task_identity_inventory

        resolved_path = path.parent.resolve()
        identity = next(
            (
                item
                for item in task_identity_inventory(paths).entries
                if item.path.resolve() == resolved_path
            ),
            None,
        )
        if identity is not None:
            task_id = task_id or identity.task_id
            task_uuid = task_uuid or str(identity.task_uuid)
    if task_uuid is None:
        try:
            task_uuid = str(parse_uuid7(path.parent.name))
        except ValueError:
            task_uuid = task.task_uuid
    if task_id is None and task_uuid is not None and paths is not None:
        from taskledger.storage.task_identity import task_id_for_uuid

        task_id = task_id_for_uuid(paths, task_uuid)
    task = replace(
        task,
        id=task_id or task.id,
        task_uuid=task_uuid or task.task_uuid,
    )
    if paths is not None and (task.parent_task_uuid or task.parent_task_id):
        from taskledger.storage.task_identity import (
            AMBIGUOUS_LEGACY_TASK_REF,
            task_identity_for_stored_ref,
        )

        try:
            parent = task_identity_for_stored_ref(
                paths,
                task_id=task.parent_task_id or "",
                task_uuid=task.parent_task_uuid,
            )
        except LaunchError as exc:
            if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
                raise
        else:
            task = replace(
                task,
                parent_task_id=parent.task_id,
                parent_task_uuid=str(parent.task_uuid),
            )
    return task


def _load_intro(path: Path) -> IntroductionRecord:
    return _load_record(path, IntroductionRecord.from_dict)


def _load_release(path: Path) -> ReleaseRecord:
    return _load_record(path, ReleaseRecord.from_dict)


def _load_plan(path: Path) -> PlanRecord:
    return _load_record(path, PlanRecord.from_dict)


def _load_question(path: Path) -> QuestionRecord:
    return _load_record(path, QuestionRecord.from_dict)


def _load_run(path: Path) -> TaskRunRecord:
    return _load_record(path, TaskRunRecord.from_dict)


def _load_change(path: Path) -> CodeChangeRecord:
    return _load_record(path, CodeChangeRecord.from_dict)


def _load_check(path: Path) -> ImplementationCheckRecord:
    return _load_record(path, ImplementationCheckRecord.from_dict)


def _load_code_review(path: Path) -> CodeReviewRecord:
    return _load_record(path, CodeReviewRecord.from_dict)


def _load_record(path: Path, parser: Callable[[dict[str, object]], T]) -> T:
    metadata, body = read_markdown_front_matter(path)
    metadata["body"] = normalize_front_matter_newlines(body).rstrip("\n")
    metadata = _ensure_schema_compat(metadata)
    return parser(metadata)


def _ensure_schema_compat(record: dict) -> dict:
    """Ensure record schema is compatible."""
    version = record.get("schema_version", 1)
    if version > TASKLEDGER_SCHEMA_VERSION:
        raise LaunchError(
            f"Record schema too new: {version} "
            f"(current max: {TASKLEDGER_SCHEMA_VERSION}). "
            "Please upgrade taskledger."
        )
    return record


def _write_markdown_record(path: Path, metadata: dict[str, object], body: str) -> None:
    metadata = dict(metadata)
    metadata.pop("body", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_front_matter(path, metadata, body.rstrip() + "\n")


def _task_latest_impl_run(workspace_root: Path, task_id: str) -> str | None:
    """Get latest_implementation_run from a task record."""
    return _task_latest_impl_run_from_paths(resolve_v2_paths(workspace_root), task_id)


def _task_latest_impl_run_from_paths(paths: V2Paths, task_id: str) -> str | None:
    try:
        task = _load_task(task_markdown_path(paths, task_id), paths=paths)
        return task.latest_implementation_run
    except Exception:  # noqa: BLE001
        return None


def _ensure_task_bundle(
    paths: V2Paths, task_id: str, *, bundle_dir: Path | None = None
) -> None:
    root = bundle_dir if bundle_dir is not None else task_dir(paths, task_id)
    for directory in (
        root,
        root / "plans",
        root / "questions",
        root / "todos",
        root / "links",
        root / "requirements",
        root / "runs",
        root / "changes",
        root / "checks",
        root / "reviews",
        root / "artifacts",
        root / "audit",
        root / "handoffs",
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _normalize_numeric_ref(ref: str, prefix: str) -> str:
    from taskledger.ids import normalize_numeric_ref

    return normalize_numeric_ref(ref, prefix)


def task_numeric_sort_key(task_id: str) -> tuple[int, str]:
    from taskledger.ids import numeric_id_sort_key

    return numeric_id_sort_key(task_id, prefix="task")


def _looks_like_global_ref(value: str) -> bool:
    if ":" in value:
        return True
    if value.upper().startswith("TL-"):
        return True
    return (
        re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]{0,2}[-_][a-zA-Z]+[-_]\d+", value) is not None
    )


def _normalize_resource_ref(workspace_root: Path, ref: str, kind: str) -> str:
    from taskledger.refs import local_id_from_ref

    normalized = ref.strip().lower()
    try:
        return local_id_from_ref(workspace_root, normalized, kind=kind)
    except LaunchError:
        if _looks_like_global_ref(normalized):
            raise
        return _normalize_numeric_ref(normalized, kind)


def _render_question_body(question: QuestionRecord) -> str:
    lines = ["## Question", "", question.question.strip()]
    lines.extend(["", "## Answer", "", (question.answer or "").strip()])
    return "\n".join(lines).rstrip() + "\n"


def _render_run_body(run: TaskRunRecord) -> str:
    lines: list[str] = ["## Summary", "", (run.summary or "").strip()]
    if run.run_type == "validation":
        lines.extend(["", "## Checks", ""])
        for check in run.checks:
            mark = "x" if check.status == "pass" else " "
            lines.append(f"- [{mark}] {check.name}")
        lines.extend(["", "## Evidence", ""])
        for entry in run.evidence:
            lines.append(f"- {entry}")
        lines.extend(["", "## Recommendation", "", (run.recommendation or "").strip()])
    return "\n".join(lines).rstrip() + "\n"


def list_handoffs(workspace_root: Path, task_id: str) -> list[TaskHandoffRecord]:
    handoffs, errors = list_handoffs_with_errors(workspace_root, task_id)
    if errors:
        raise LaunchError(errors[0])
    return handoffs


def list_handoffs_from_paths(paths: V2Paths, task_id: str) -> list[TaskHandoffRecord]:
    handoffs, errors = list_handoffs_with_errors_from_paths(paths, task_id)
    if errors:
        raise LaunchError(errors[0])
    return handoffs


def list_handoffs_with_errors(
    workspace_root: Path,
    task_id: str,
) -> tuple[list[TaskHandoffRecord], list[str]]:
    return list_handoffs_with_errors_from_paths(
        resolve_v2_paths(workspace_root), task_id
    )


def list_handoffs_with_errors_from_paths(
    paths: V2Paths,
    task_id: str,
) -> tuple[list[TaskHandoffRecord], list[str]]:
    handoffs_dir = task_handoffs_dir(paths, task_id)
    if not handoffs_dir.exists():
        return [], []
    result: list[TaskHandoffRecord] = []
    errors: list[str] = []
    for md_file in handoffs_dir.glob("*.md"):
        try:
            metadata, _ = read_markdown_front_matter(md_file)
            metadata = dict(metadata)
            metadata["context_body"] = ""
            handoff = TaskHandoffRecord.from_dict(metadata)
            result.append(handoff)
        except Exception as exc:  # noqa: BLE001
            label = _path_label(paths.workspace_root, md_file)
            errors.append(f"Malformed handoff record {label}: {exc}")
    return sorted(result, key=lambda handoff: handoff.created_at), errors


def resolve_handoff(
    workspace_root: Path, task_id: str, handoff_ref: str
) -> TaskHandoffRecord:
    paths = resolve_v2_paths(workspace_root)
    normalized_id = _normalize_resource_ref(workspace_root, handoff_ref, "handoff")
    path = handoff_markdown_path(paths, task_id, normalized_id)
    if not path.exists():
        raise LaunchError(f"Handoff not found: {handoff_ref}")
    metadata, body = read_markdown_front_matter(path)
    metadata = dict(metadata)
    metadata["context_body"] = body or str(metadata.get("context_body") or "")
    return TaskHandoffRecord.from_dict(metadata)


def _path_label(workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def save_handoff(workspace_root: Path, handoff: TaskHandoffRecord) -> Path:
    paths = resolve_v2_paths(workspace_root)
    handoffs_dir = task_handoffs_dir(paths, handoff.task_id)
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    path = handoff_markdown_path(paths, handoff.task_id, handoff.handoff_id)
    metadata = handoff.to_dict()
    metadata.pop("context_body", None)
    content = handoff.context_body or ""
    _write_markdown_record(path, metadata, content)
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        handoffs = list_handoffs_from_paths(paths, handoff.task_id)
        update_sidecar_summary(paths, handoff.task_id, handoffs=handoffs)
    except Exception:
        from taskledger.storage.indexes import mark_index_dirty

        mark_index_dirty(paths, "sidecar_index", task_id=handoff.task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            handoff.task_id,
            exc_info=True,
        )
    return path


def resolve_lock(workspace_root: Path, task_id: str) -> TaskLock | None:
    """Resolve a lock by task ID."""
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task_id)
    lock = read_lock(lock_path)
    if lock is None:
        return None
    try:
        from taskledger.storage.task_identity import (
            AMBIGUOUS_LEGACY_TASK_REF,
            task_identity_for_stored_ref,
        )

        identity = task_identity_for_stored_ref(
            paths, task_id=lock.task_id, task_uuid=lock.task_uuid
        )
    except LaunchError as exc:
        if exc.code == AMBIGUOUS_LEGACY_TASK_REF:
            raise
        return lock
    return replace(lock, task_id=identity.task_id, task_uuid=str(identity.task_uuid))


def save_lock(workspace_root: Path, task_id: str, lock: TaskLock) -> Path:
    """Save a lock record and update its derived index entries."""
    return save_lock_from_paths(resolve_v2_paths(workspace_root), task_id, lock)


def save_lock_from_paths(
    paths: V2Paths,
    task_id: str,
    lock: TaskLock,
    *,
    create_only: bool = False,
) -> Path:
    try:
        from taskledger.storage.task_identity import task_identity_for_ref

        identity = task_identity_for_ref(paths, lock.task_uuid or task_id)
    except LaunchError:
        pass
    else:
        task_id = identity.task_id
        lock = replace(
            lock, task_id=identity.task_id, task_uuid=str(identity.task_uuid)
        )
    lock_path = task_lock_path(paths, task_id)
    if create_only:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        write_lock(lock_path, lock)
    elif lock_path.exists():
        update_lock(lock_path, lock)
    else:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        write_lock(lock_path, lock)

    from taskledger.storage.indexes import (
        mark_index_dirty,
        update_active_lock_index_entry,
    )
    from taskledger.storage.sidecar_index import update_sidecar_summary

    try:
        update_active_lock_index_entry(paths, lock)
    except Exception:
        mark_index_dirty(paths, "active_locks", task_id=task_id)
        logging.getLogger(__name__).debug(
            "Failed to update active-lock index for %s", task_id, exc_info=True
        )
    try:
        update_sidecar_summary(paths, task_id, lock=lock)
    except Exception:
        mark_index_dirty(paths, "sidecar_index", task_id=task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s", task_id, exc_info=True
        )
    return lock_path


def remove_lock_from_paths(paths: V2Paths, task_id: str) -> None:
    lock_path = task_lock_path(paths, task_id)
    remove_lock(lock_path)

    from taskledger.storage.indexes import (
        mark_index_dirty,
        remove_active_lock_index_entry,
    )
    from taskledger.storage.sidecar_index import update_sidecar_summary

    try:
        remove_active_lock_index_entry(paths, task_id)
    except Exception:
        mark_index_dirty(paths, "active_locks", task_id=task_id)
        logging.getLogger(__name__).debug(
            "Failed to update active-lock index for %s", task_id, exc_info=True
        )
    try:
        update_sidecar_summary(paths, task_id, lock=None)
    except Exception:
        mark_index_dirty(paths, "sidecar_index", task_id=task_id)
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s", task_id, exc_info=True
        )

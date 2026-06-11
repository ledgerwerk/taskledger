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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

import yaml

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
from taskledger.storage.locks import read_lock, update_lock, write_lock
from taskledger.storage.paths import ProjectPaths
from taskledger.timeutils import utc_now_iso

T = TypeVar("T")
TaskVisibility = Literal["visible", "archived", "all"]


def _link_id_from_path(path: str) -> str:
    """Generate a deterministic link id from the path."""
    import hashlib

    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]
    return f"link-{digest}"


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


def resolve_v2_paths(workspace_root: Path) -> V2Paths:
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


def ensure_v2_layout(workspace_root: Path) -> V2Paths:
    paths = resolve_v2_paths(workspace_root)
    for directory in (
        paths.project_dir,
        paths.introductions_dir,
        paths.releases_dir,
        paths.tasks_dir,
        paths.events_dir,
        paths.indexes_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    for index_path in (
        paths.active_locks_index_path,
        paths.dependencies_index_path,
        paths.introductions_index_path,
    ):
        if index_path.exists():
            continue
        atomic_write_text(index_path, "[]\n")
    return paths


def list_tasks(workspace_root: Path) -> list[TaskRecord]:
    paths = ensure_v2_layout(workspace_root)
    return sorted(
        [_load_task(path) for path in paths.tasks_dir.glob("task-*/task.md")],
        key=lambda item: item.id,
    )


def list_tasks_by_visibility(
    workspace_root: Path,
    *,
    visibility: TaskVisibility = "visible",
) -> list[TaskRecord]:
    tasks = list_tasks(workspace_root)
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
    normalized_id = _normalize_numeric_ref(normalized_ref, "task")

    # Direct-path: if the normalized ref is a task ID, try reading just that file.
    if normalized_id.startswith("task-"):
        paths = resolve_v2_paths(workspace_root)
        path = task_markdown_path(paths, normalized_id)
        if path.exists():
            task = _load_task(path)
            if include_archived or not is_archived_task(task):
                return task

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
    paths = ensure_v2_layout(workspace_root)
    if not paths.active_task_path.exists():
        return None
    try:
        payload = yaml.safe_load(paths.active_task_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LaunchError(f"Invalid active task state: {exc}") from exc
    if not isinstance(payload, dict):
        raise LaunchError("Invalid active task state: expected mapping.")
    return ActiveTaskState.from_dict(payload)


def save_active_task_state(
    workspace_root: Path,
    state: ActiveTaskState,
) -> ActiveTaskState:
    paths = ensure_v2_layout(workspace_root)
    _write_yaml(paths.active_task_path, state.to_dict())
    return state


def clear_active_task_state(workspace_root: Path) -> ActiveTaskState | None:
    paths = ensure_v2_layout(workspace_root)
    state = load_active_task_state(workspace_root)
    if paths.active_task_path.exists():
        paths.active_task_path.unlink()
    return state


def load_actor_state(workspace_root: Path) -> ActiveActorState | None:
    paths = ensure_v2_layout(workspace_root)
    if not paths.actor_path.exists():
        return None
    try:
        payload = yaml.safe_load(paths.actor_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LaunchError(f"Invalid actor state: {exc}") from exc
    if not isinstance(payload, dict):
        raise LaunchError("Invalid actor state: expected mapping.")
    return ActiveActorState.from_dict(payload)


def save_actor_state(
    workspace_root: Path,
    state: ActiveActorState,
) -> ActiveActorState:
    paths = ensure_v2_layout(workspace_root)
    _write_yaml(paths.actor_path, state.to_dict())
    return state


def clear_actor_state(workspace_root: Path) -> ActiveActorState | None:
    paths = ensure_v2_layout(workspace_root)
    state = load_actor_state(workspace_root)
    if paths.actor_path.exists():
        paths.actor_path.unlink()
    return state


def load_harness_state(workspace_root: Path) -> ActiveHarnessState | None:
    paths = ensure_v2_layout(workspace_root)
    if not paths.harness_path.exists():
        return None
    try:
        payload = yaml.safe_load(paths.harness_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LaunchError(f"Invalid harness state: {exc}") from exc
    if not isinstance(payload, dict):
        raise LaunchError("Invalid harness state: expected mapping.")
    return ActiveHarnessState.from_dict(payload)


def save_harness_state(
    workspace_root: Path,
    state: ActiveHarnessState,
) -> ActiveHarnessState:
    paths = ensure_v2_layout(workspace_root)
    _write_yaml(paths.harness_path, state.to_dict())
    return state


def clear_harness_state(workspace_root: Path) -> ActiveHarnessState | None:
    paths = ensure_v2_layout(workspace_root)
    state = load_harness_state(workspace_root)
    if paths.harness_path.exists():
        paths.harness_path.unlink()
    return state


def resolve_active_task(workspace_root: Path) -> TaskRecord:
    state = load_active_task_state(workspace_root)
    if state is None:
        raise NoActiveTask()
    try:
        return resolve_task(workspace_root, state.task_id)
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
    paths = ensure_v2_layout(workspace_root)
    _ensure_task_bundle(paths, task.id)
    path = task_markdown_path(paths, task.id)
    if path.parent.name != task.id:
        raise LaunchError(f"Task id/path mismatch for {task.id}")
    metadata = task.to_dict()
    metadata.pop("todos", None)
    metadata.pop("file_links", None)
    metadata.pop("requirements", None)
    _write_markdown_record(path, metadata, task.body)
    # Write-through: update the derived task index.
    try:
        from taskledger.storage.task_index import update_task_index_entry

        update_task_index_entry(paths, task)
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to update task index for %s", task.id, exc_info=True
        )
    return task


def list_introductions(workspace_root: Path) -> list[IntroductionRecord]:
    paths = ensure_v2_layout(workspace_root)
    return sorted(
        [_load_intro(path) for path in paths.introductions_dir.glob("intro-*.md")],
        key=lambda item: item.id,
    )


def list_releases(workspace_root: Path) -> list[ReleaseRecord]:
    paths = ensure_v2_layout(workspace_root)
    return sorted(
        [_load_release(path) for path in paths.releases_dir.glob("*.md")],
        key=lambda item: (task_numeric_sort_key(item.boundary_task_id), item.version),
    )


def resolve_release(workspace_root: Path, version: str) -> ReleaseRecord:
    paths = ensure_v2_layout(workspace_root)
    path = release_markdown_path(paths, version)
    if not path.exists():
        raise LaunchError(f"Release not found: {version}")
    return _load_release(path)


def save_release(workspace_root: Path, release: ReleaseRecord) -> ReleaseRecord:
    paths = ensure_v2_layout(workspace_root)
    path = release_markdown_path(paths, release.version)
    if path.exists():
        raise LaunchError(f"Release version already exists: {release.version}")
    _write_markdown_record(path, release.to_dict(), release.note or "")
    return release


def resolve_introduction(workspace_root: Path, ref: str) -> IntroductionRecord:
    normalized_ref = ref.strip().lower()
    for intro in list_introductions(workspace_root):
        if intro.id == ref or intro.slug == normalized_ref:
            return intro
    raise LaunchError(f"Introduction not found: {ref}")


def save_introduction(
    workspace_root: Path, introduction: IntroductionRecord
) -> IntroductionRecord:
    paths = ensure_v2_layout(workspace_root)
    path = paths.introductions_dir / f"{introduction.id}.md"
    _write_markdown_record(path, introduction.to_dict(), introduction.body)
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
        except Exception:
            # Fall back to plain string replacement for unparseable files.
            content = md_file.read_text(encoding="utf-8")
            if old_task_id in content:
                content = content.replace(old_task_id, new_task_id)
                md_file.write_text(content, encoding="utf-8")


def list_plans(workspace_root: Path, task_id: str) -> list[PlanRecord]:
    paths = ensure_v2_layout(workspace_root)
    directory = task_plans_dir(paths, task_id)
    plans: list[PlanRecord] = []
    for path in directory.glob("plan-v*.md"):
        try:
            plans.append(_load_plan(path))
        except LaunchError as exc:
            logging.warning("Skipping malformed plan file %s: %s", path, exc)
    return sorted(plans, key=lambda item: item.plan_version)


def save_plan(workspace_root: Path, plan: PlanRecord) -> PlanRecord:
    paths = ensure_v2_layout(workspace_root)
    path = plan_markdown_path(paths, plan.task_id, plan.plan_version)
    if path.exists():
        raise LaunchError(
            f"Plan version already exists: {plan.task_id} v{plan.plan_version}"
        )
    _write_markdown_record(path, plan.to_dict(), plan.body)
    return plan


def overwrite_plan(workspace_root: Path, plan: PlanRecord) -> PlanRecord:
    paths = ensure_v2_layout(workspace_root)
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
    paths = ensure_v2_layout(workspace_root)
    directory = task_questions_dir(paths, task_id)
    return sorted(
        [_load_question(path) for path in directory.glob("q-*.md")],
        key=lambda item: item.id,
    )


def resolve_question(
    workspace_root: Path, task_id: str, question_id: str
) -> QuestionRecord:
    normalized_id = _normalize_numeric_ref(question_id, "q")
    for question in list_questions(workspace_root, task_id):
        if question.id == question_id or question.id == normalized_id:
            return question
    raise LaunchError(f"Question not found: {question_id}")


def save_question(workspace_root: Path, question: QuestionRecord) -> QuestionRecord:
    paths = ensure_v2_layout(workspace_root)
    path = question_markdown_path(paths, question.task_id, question.id)
    _write_markdown_record(path, question.to_dict(), _render_question_body(question))
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        questions = list_questions(workspace_root, question.task_id)
        update_sidecar_summary(paths, question.task_id, questions=questions)
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            question.task_id,
            exc_info=True,
        )
    return question


def list_runs(workspace_root: Path, task_id: str) -> list[TaskRunRecord]:
    paths = ensure_v2_layout(workspace_root)
    directory = task_runs_dir(paths, task_id)
    return sorted(
        [_load_run(path) for path in directory.glob("*.md")],
        key=lambda item: item.run_id,
    )


def resolve_run(workspace_root: Path, task_id: str, run_id: str) -> TaskRunRecord:
    normalized_id = _normalize_numeric_ref(run_id, "run")
    for run in list_runs(workspace_root, task_id):
        if run.run_id == run_id or run.run_id == normalized_id:
            return run
    raise LaunchError(f"Run not found: {run_id}")


def save_run(workspace_root: Path, run: TaskRunRecord) -> TaskRunRecord:
    paths = ensure_v2_layout(workspace_root)
    path = run_markdown_path(paths, run.task_id, run.run_id)
    _write_markdown_record(path, run.to_dict(), _render_run_body(run))
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        runs = list_runs(workspace_root, run.task_id)
        update_sidecar_summary(paths, run.task_id, runs=runs)
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            run.task_id,
            exc_info=True,
        )
    return run


def list_changes(workspace_root: Path, task_id: str) -> list[CodeChangeRecord]:
    paths = ensure_v2_layout(workspace_root)
    directory = task_changes_dir(paths, task_id)
    return sorted(
        [_load_change(path) for path in directory.glob("change-*.md")],
        key=lambda item: item.change_id,
    )


def save_change(workspace_root: Path, change: CodeChangeRecord) -> CodeChangeRecord:
    paths = ensure_v2_layout(workspace_root)
    path = change_markdown_path(paths, change.task_id, change.change_id)
    _write_markdown_record(path, change.to_dict(), change.summary)
    return change


def resolve_change(
    workspace_root: Path, task_id: str, change_id: str
) -> CodeChangeRecord:
    normalized_id = _normalize_numeric_ref(change_id, "change")
    for change in list_changes(workspace_root, task_id):
        if change.change_id == change_id or change.change_id == normalized_id:
            return change
    raise LaunchError(f"Change not found: {change_id}")


def list_checks(workspace_root: Path, task_id: str) -> list[ImplementationCheckRecord]:
    paths = resolve_v2_paths(workspace_root)
    directory = task_checks_dir(paths, task_id)
    return sorted(
        [_load_check(path) for path in directory.glob("check-*.md")],
        key=lambda c: c.check_id,
    )


def save_check(
    workspace_root: Path,
    check: ImplementationCheckRecord,
) -> ImplementationCheckRecord:
    paths = ensure_v2_layout(workspace_root)
    path = check_markdown_path(paths, check.task_id, check.check_id)
    _write_markdown_record(path, check.to_dict(), "")
    return check


def resolve_check(
    workspace_root: Path, task_id: str, check_id: str
) -> ImplementationCheckRecord:
    normalized_id = _normalize_numeric_ref(check_id, "check")
    for check in list_checks(workspace_root, task_id):
        if check.check_id == check_id or check.check_id == normalized_id:
            return check
    raise LaunchError(f"Check not found: {check_id}")


def list_code_reviews(workspace_root: Path, task_id: str) -> list[CodeReviewRecord]:
    paths = ensure_v2_layout(workspace_root)
    directory = task_reviews_dir(paths, task_id)
    return sorted(
        [_load_code_review(path) for path in directory.glob("review-*.md")],
        key=lambda item: item.review_id,
    )


def save_code_review(
    workspace_root: Path,
    review: CodeReviewRecord,
) -> CodeReviewRecord:
    paths = ensure_v2_layout(workspace_root)
    path = code_review_markdown_path(paths, review.task_id, review.review_id)
    _write_markdown_record(path, review.to_dict(), review.body)
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        reviews = list_code_reviews(workspace_root, review.task_id)
        latest_impl_run = _task_latest_impl_run(workspace_root, review.task_id)
        update_sidecar_summary(
            paths,
            review.task_id,
            reviews=reviews,
            latest_implementation_run=latest_impl_run,
        )
    except Exception:
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
    normalized_id = _normalize_numeric_ref(review_ref, "review")
    for review in list_code_reviews(workspace_root, task_id):
        if review.review_id == review_ref or review.review_id == normalized_id:
            return review
    raise LaunchError(f"Code review not found: {review_ref}")


def load_active_locks(workspace_root: Path) -> list[TaskLock]:
    paths = ensure_v2_layout(workspace_root)
    locks: list[TaskLock] = []
    for path in sorted(paths.tasks_dir.glob("task-*/lock.yaml")):
        lock = read_lock(path)
        if lock is not None:
            locks.append(lock)
    return locks


def load_todos(workspace_root: Path, task_id: str) -> TodoCollection:
    paths = ensure_v2_layout(workspace_root)
    directory = task_todos_dir(paths, task_id)
    records = sorted(
        [_load_record(p, TaskTodo.from_dict) for p in directory.glob("todo-*.md")],
        key=lambda t: t.id,
    )
    return TodoCollection(task_id=task_id, todos=tuple(records))


def save_todos(workspace_root: Path, collection: TodoCollection) -> TodoCollection:
    paths = ensure_v2_layout(workspace_root)
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
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            collection.task_id,
            exc_info=True,
        )
    return collection


def load_links(workspace_root: Path, task_id: str) -> LinkCollection:
    paths = ensure_v2_layout(workspace_root)
    directory = task_links_dir(paths, task_id)
    records = sorted(
        [_load_record(p, FileLink.from_dict) for p in directory.glob("link-*.md")],
        key=lambda lk: lk.id or "",
    )
    return LinkCollection(task_id=task_id, links=tuple(records))


def save_links(workspace_root: Path, collection: LinkCollection) -> LinkCollection:
    paths = ensure_v2_layout(workspace_root)
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
    paths = ensure_v2_layout(workspace_root)
    directory = task_requirements_dir(paths, task_id)
    records = sorted(
        [
            _load_record(p, DependencyRequirement.from_dict)
            for p in directory.glob("req-*.md")
        ],
        key=lambda r: r.id or "",
    )
    return RequirementCollection(task_id=task_id, requirements=tuple(records))


def save_requirements(
    workspace_root: Path, collection: RequirementCollection
) -> RequirementCollection:
    paths = ensure_v2_layout(workspace_root)
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
    # Remove stale files
    for path in directory.glob("req-*.md"):
        if path.stem not in keep_ids:
            path.unlink()
    return collection


def task_dir(paths: V2Paths, task_id: str) -> Path:
    return paths.tasks_dir / task_id


def task_markdown_path(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "task.md"


def task_lock_path(paths: V2Paths, task_id: str) -> Path:
    return task_dir(paths, task_id) / "lock.yaml"


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


def _load_task(path: Path) -> TaskRecord:
    return _load_record(path, TaskRecord.from_dict)


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
    try:
        task = resolve_task(workspace_root, task_id)
        return task.latest_implementation_run
    except Exception:
        return None


def _ensure_task_bundle(paths: V2Paths, task_id: str) -> None:
    for directory in (
        task_dir(paths, task_id),
        task_plans_dir(paths, task_id),
        task_questions_dir(paths, task_id),
        task_todos_dir(paths, task_id),
        task_links_dir(paths, task_id),
        task_requirements_dir(paths, task_id),
        task_runs_dir(paths, task_id),
        task_changes_dir(paths, task_id),
        task_reviews_dir(paths, task_id),
        task_artifacts_dir(paths, task_id),
        task_audit_dir(paths, task_id),
        task_handoffs_dir(paths, task_id),
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump(payload, sort_keys=False))


def _normalize_numeric_ref(ref: str, prefix: str) -> str:
    raw_prefix = f"{prefix}-"
    if not ref.startswith(raw_prefix):
        return ref
    suffix = ref.removeprefix(raw_prefix)
    if not suffix.isdigit():
        return ref
    return f"{prefix}-{int(suffix):04d}"


def task_numeric_sort_key(task_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"task-(\d+)", task_id)
    if match is None:
        return (10**9, task_id)
    return (int(match.group(1)), task_id)


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


def list_handoffs_with_errors(
    workspace_root: Path,
    task_id: str,
) -> tuple[list[TaskHandoffRecord], list[str]]:
    paths = resolve_v2_paths(workspace_root)
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
        except Exception as exc:
            label = _path_label(workspace_root, md_file)
            errors.append(f"Malformed handoff record {label}: {exc}")
    return sorted(result, key=lambda h: h.created_at), errors


def resolve_handoff(
    workspace_root: Path, task_id: str, handoff_ref: str
) -> TaskHandoffRecord:
    paths = resolve_v2_paths(workspace_root)
    path = handoff_markdown_path(paths, task_id, handoff_ref)
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

        handoffs = list_handoffs(workspace_root, handoff.task_id)
        update_sidecar_summary(paths, handoff.task_id, handoffs=handoffs)
    except Exception:
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
    return read_lock(lock_path)


def save_lock(workspace_root: Path, task_id: str, lock: TaskLock) -> Path:
    """Save a lock record (creates if new, updates if exists)."""
    paths = resolve_v2_paths(workspace_root)
    lock_path = task_lock_path(paths, task_id)
    if lock_path.exists():
        update_lock(lock_path, lock)
    else:
        write_lock(lock_path, lock)
    # Write-through sidecar index.
    try:
        from taskledger.storage.sidecar_index import update_sidecar_summary

        update_sidecar_summary(paths, task_id, lock=lock)
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to update sidecar index for %s",
            task_id,
            exc_info=True,
        )
    return lock_path

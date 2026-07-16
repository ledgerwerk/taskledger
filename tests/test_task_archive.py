from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app

runner = CliRunner()


def _json_output(result) -> dict[str, object]:
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


def _init(tmp_path: Path) -> None:
    shutil.rmtree(tmp_path.parent / "ledger", ignore_errors=True)
    result = runner.invoke(
        app, ["--cwd", str(tmp_path), "init", "--create-sibling-store"]
    )
    assert result.exit_code == 0, result.stdout


def _record_done(tmp_path: Path, *, title: str, slug: str) -> str:
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "record",
            title,
            "--slug",
            slug,
            "--description",
            title,
            "--summary",
            f"Complete {title}",
            "--allow-empty-record",
            "--reason",
            "test",
        ],
    )
    payload = _json_output(result)
    task_id = payload["result"]["task_id"]
    assert isinstance(task_id, str)
    return task_id


def _create_task(tmp_path: Path, *, title: str, slug: str) -> str:
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "create",
            title,
            "--slug",
            slug,
        ],
    )
    payload = _json_output(result)
    task_id = payload["result"]["id"]
    assert isinstance(task_id, str)
    return task_id


def _archive(tmp_path: Path, ref: str, *, force: bool = False) -> None:
    args = [
        "--cwd",
        str(tmp_path),
        "task",
        "archive",
        ref,
        "--reason",
        "Hide historical work",
    ]
    if force:
        args.append("--force")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout


# sw: f=specs/behavior/features/task_archive/archive.feature
# sw: s=@bdd-task-archive-archive-hides-task-from-default-list
def test_archive_hides_task_from_default_list(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = _record_done(tmp_path, title="Legacy task", slug="legacy-task")
    _archive(tmp_path, task_id)

    result = runner.invoke(app, ["--cwd", str(tmp_path), "task", "list"])
    assert result.exit_code == 0, result.stdout
    assert "legacy-task" not in result.stdout

    archived = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "list", "--archived"],
    )
    assert archived.exit_code == 0, archived.stdout
    assert "legacy-task" in archived.stdout
    assert "archived" in archived.stdout


# sw: f=specs/behavior/features/task_archive/archive.feature
# sw: s=@bdd-task-archive-archived-slug-can-be-reused-and-archived-slug-can-be-ambiguous
def test_archived_slug_can_be_reused_and_archived_slug_can_be_ambiguous(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    first = _record_done(tmp_path, title="No log feature v1", slug="no-log-feature")
    _archive(tmp_path, first)

    second = _record_done(tmp_path, title="No log feature v2", slug="no-log-feature")
    _archive(tmp_path, second)

    archived = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "list",
            "--archived",
            "--slug",
            "no-log-feature",
        ],
    )
    assert archived.exit_code == 0, archived.stdout
    assert first in archived.stdout
    assert second in archived.stdout

    ambiguous = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "show",
            "no-log-feature",
            "--include-archived",
        ],
    )
    assert ambiguous.exit_code != 0
    assert "ambiguous" in ambiguous.output.lower()


# sw: f=specs/behavior/features/task_archive/archive.feature
# sw: s=@bdd-task-archive-unarchive-rejects-visible-slug-conflict-and-accepts-new-slug
def test_unarchive_rejects_visible_slug_conflict_and_accepts_new_slug(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    archived_task = _record_done(tmp_path, title="Feature", slug="same-slug")
    _archive(tmp_path, archived_task)

    _create_task(tmp_path, title="New active feature", slug="same-slug")

    conflict = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "unarchive",
            archived_task,
            "--reason",
            "Need it back",
        ],
    )
    assert conflict.exit_code != 0
    assert "slug" in conflict.output.lower()

    restored = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "unarchive",
            archived_task,
            "--reason",
            "Need it back",
            "--slug",
            "same-slug-archived",
        ],
    )
    assert restored.exit_code == 0, restored.stdout


# sw: f=specs/behavior/features/task_archive/archive.feature
# sw: s=@bdd-task-archive-archiving-all-tasks-does-not-reset-next-task-number
def test_archiving_all_tasks_does_not_reset_next_task_number(tmp_path: Path) -> None:
    _init(tmp_path)
    first = _record_done(tmp_path, title="Done one", slug="done-one")
    _archive(tmp_path, first)

    second = _create_task(tmp_path, title="Only visible now", slug="only-visible")
    assert second == "task-0002"


# sw: f=specs/behavior/features/task_archive/archive.feature
# sw: s=@bdd-task-archive-archived-task-mutation-is-rejected-and-exact-id-still-reads
def test_archived_task_mutation_is_rejected_and_exact_id_still_reads(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    task_id = _record_done(
        tmp_path,
        title="Immutable archived",
        slug="immutable-archived",
    )
    _archive(tmp_path, task_id)

    activate = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "activate", task_id],
    )
    assert activate.exit_code != 0
    assert "Cannot activate archived task" in activate.output

    show = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "show", task_id],
    )
    assert show.exit_code == 0, show.stdout
    assert "immutable-archived" in show.stdout


# AC1: archived state is visible in task show
def test_task_show_exact_id_marks_archived_task(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = _record_done(tmp_path, title="Old", slug="old")
    _archive(tmp_path, task_id)

    show = runner.invoke(app, ["--cwd", str(tmp_path), "task", "show", task_id])
    assert show.exit_code == 0, show.stdout
    assert "visibility: archived" in show.stdout
    assert "archived_at:" in show.stdout

    show_json = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "show", task_id],
    )
    payload = json.loads(show_json.stdout)
    assert payload["result"]["task"]["archived"] is True
    assert payload["result"]["task"]["visibility"] == "archived"


# AC1: visible task shows visibility: visible
def test_task_show_visible_task_has_visibility_visible(tmp_path: Path) -> None:
    _init(tmp_path)
    _record_done(tmp_path, title="Active", slug="active")

    show = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "show", "active"],
    )
    assert show.exit_code == 0, show.stdout
    assert "visibility: visible" in show.stdout

    show_json = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "show",
            "active",
        ],
    )
    payload = json.loads(show_json.stdout)
    assert payload["result"]["task"]["archived"] is False
    assert payload["result"]["task"]["visibility"] == "visible"


# AC2: archive no-op reports no change
def test_archive_already_archived_task_reports_noop(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = _record_done(tmp_path, title="Already archived", slug="already-archived")
    _archive(tmp_path, task_id)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "archive",
            task_id,
            "--reason",
            "again",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "was already archived" in result.stdout
    assert "no changes" in result.stdout


# AC2: unarchive visible task reports no-op
def test_unarchive_visible_task_reports_noop(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = _record_done(tmp_path, title="Already visible", slug="already-visible")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "unarchive",
            task_id,
            "--reason",
            "test",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "was not archived" in result.stdout
    assert "no changes" in result.stdout


# AC3: can validate returns false for archived task
def test_can_validate_archived_implemented_task_is_false(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)
    _archive(tmp_path, task_id, force=True)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "can", "validate", "--task", task_id],
    )

    payload = json.loads(result.stdout)
    assert payload["result"]["ok"] is False
    blockers = payload["result"]["blocking"]
    assert any(b["kind"] == "archived_task" for b in blockers)


# AC3: next-action reports archived for archived task
def test_next_action_archived_task_reports_archived(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = _record_done(tmp_path, title="Archived done", slug="archived-done")
    _archive(tmp_path, task_id)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "next-action",
            "--task",
            task_id,
        ],
    )
    payload = json.loads(result.stdout)
    assert payload["result"]["action"] == "archived"
    assert payload["result"]["reason"] == "Task is archived and read-only."


# AC4: non-terminal unarchive requires --reopen-for-work
def test_unarchive_implemented_task_requires_recovery_mode(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)
    _archive(tmp_path, task_id, force=True)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "unarchive",
            task_id,
            "--reason",
            "Need to inspect old task",
        ],
    )

    assert result.exit_code != 0
    assert "non-terminal archived task" in result.output
    assert "--reopen-for-work" in result.output


# AC4: --reopen-for-work blocks direct validation
def test_unarchive_implemented_reopen_for_work_blocks_direct_validation(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    task_id = _prepare_implemented_task(tmp_path)
    _archive(tmp_path, task_id, force=True)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "unarchive",
            task_id,
            "--reason",
            "Need to redo stale work",
            "--reopen-for-work",
        ],
    )
    assert result.exit_code == 0, result.stdout

    # Check status is failed_validation now
    show_json = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "show", task_id],
    )
    payload = json.loads(show_json.stdout)
    assert payload["result"]["task"]["status_stage"] == "failed_validation"

    can = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "can", "validate", "--task", task_id],
    )
    payload = json.loads(can.stdout)
    assert payload["result"]["ok"] is False


# Helper for implemented tasks
def _prepare_implemented_task(tmp_path: Path) -> str:
    """Create and drive a task through plan -> approve -> implement finish."""
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "create",
            "Implemented task",
            "--slug",
            "implemented-task",
        ],
    )
    payload = _json_output(result)
    task_id = payload["result"]["id"]
    assert isinstance(task_id, str)

    # Activate
    runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "activate", task_id],
    )

    # Start planning
    runner.invoke(
        app,
        ["--cwd", str(tmp_path), "plan", "start", "--task", task_id],
    )

    # Create a concrete plan file and upsert
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(
        "---\n"
        "goal: Test\n"
        "files:\n"
        '  - "@taskledger/cli.py"\n'
        "test_commands:\n"
        '  - "pytest -q"\n'
        "acceptance_criteria:\n"
        "  - id: ac-0001\n"
        "    text: Feature works correctly\n"
        "    mandatory: true\n"
        "todos:\n"
        "  - id: plan-todo-0001\n"
        '    text: "Edit @taskledger/cli.py to add feature"\n'
        "    mandatory: true\n"
        "---\n"
        "## Plan body\n",
        encoding="utf-8",
    )
    upsert_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "upsert",
            "--file",
            str(plan_file),
            "--task",
            task_id,
        ],
    )
    assert upsert_result.exit_code == 0, upsert_result.output

    # Approve
    approve_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "accept",
            "--version",
            "1",
            "--task",
            task_id,
            "--note",
            "Approved for test",
            "--allow-lint-errors",
        ],
    )
    assert approve_result.exit_code == 0, approve_result.output

    # Start and finish implementation
    impl_start = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "implement", "start", "--task", task_id],
    )
    assert impl_start.exit_code == 0, impl_start.output

    # Get the materialized todo ID and mark it done
    todo_status = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "todo", "status", "--task", task_id],
    )
    todo_payload = json.loads(todo_status.stdout)
    todo_id = todo_payload["result"]["open_todos"][0]
    todo_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "todo",
            "done",
            todo_id,
            "--evidence",
            "Done",
            "--task",
            task_id,
        ],
    )
    assert todo_result.exit_code == 0, todo_result.output

    impl_finish = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "implement",
            "finish",
            "--task",
            task_id,
            "--summary",
            "Done",
        ],
    )
    assert impl_finish.exit_code == 0, impl_finish.output

    return task_id

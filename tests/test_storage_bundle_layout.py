from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.indexes import rebuild_v2_indexes
from taskledger.storage.task_store import (
    ensure_v2_layout,
    list_plans,
    resolve_v2_paths,
    rewrite_task_refs,
)
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _json(result) -> dict[str, object]:
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _init_project(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _removed_index_paths(tmp_path: Path) -> tuple[Path, Path]:
    indexes_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "indexes"
    return (
        indexes_dir / "plan_versions.json",
        indexes_dir / "latest_runs.json",
    )


def _prepare_task_with_plan(
    tmp_path: Path,
    *,
    slug: str,
    approve: bool = False,
    start_implementation: bool = False,
) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                slug,
                "--description",
                "Exercise canonical plan and run scans.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(tmp_path), "task", "activate", slug]).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    plan_text = """---
goal: Verify canonical plan and run scans.
acceptance_criteria:
  - id: ac-0001
    text: Canonical records drive task commands.
todos:
  - id: todo-0001
    text: Exercise canonical read paths.
---

# Plan

Use task bundles instead of derived task, plan, and run indexes.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "propose", "--text", plan_text],
        ).exit_code
        == 0
    )
    if not approve and not start_implementation:
        return
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Ready to implement.",
            ],
        ).exit_code
        == 0
    )
    if start_implementation:
        assert (
            runner.invoke(
                app,
                ["--cwd", str(tmp_path), "implement", "start"],
            ).exit_code
            == 0
        )


# specmason: req=REQ-0051 ac=AC-0551
def test_task_create_uses_task_bundle_layout(tmp_path: Path) -> None:
    _init_project(tmp_path)

    project_dir = tmp_path / ".taskledger" / "ledgers" / "main"
    assert (project_dir / "intros").is_dir()
    assert (project_dir / "releases").is_dir()
    assert (project_dir / "tasks").is_dir()
    assert (project_dir / "events").is_dir()
    assert (project_dir / "indexes").is_dir()
    for legacy_name in (
        "items",
        "memories",
        "contexts",
        "stages",
        "workflows",
    ):
        assert not (project_dir / legacy_name).exists()

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "bundle-layout",
            "--description",
            "Verify the bundle layout.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    task_dir = project_dir / "tasks" / "task-0001"
    assert (task_dir / "task.md").is_file()
    assert (task_dir / "todos").is_dir()
    assert (task_dir / "links").is_dir()
    assert (task_dir / "requirements").is_dir()
    assert not (task_dir / "todos.yaml").exists()
    assert not (task_dir / "links.yaml").exists()
    assert not (task_dir / "requirements.yaml").exists()
    assert (task_dir / "plans").is_dir()
    assert (task_dir / "questions").is_dir()
    assert (task_dir / "runs").is_dir()
    assert (task_dir / "changes").is_dir()
    assert (task_dir / "artifacts").is_dir()
    assert (task_dir / "audit").is_dir()

    # Empty collections should produce no per-record files
    assert list((task_dir / "todos").glob("todo-*.md")) == []
    assert list((task_dir / "links").glob("link-*.md")) == []
    assert list((task_dir / "requirements").glob("req-*.md")) == []


# specmason: req=REQ-0051 ac=AC-0553
def test_task_list_scans_task_markdown_without_indexes(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "scan-layout",
            "--description",
            "Listing should scan task bundles.",
        ],
    )

    indexes_dir = tmp_path / ".taskledger" / "indexes"
    for path in indexes_dir.glob("*.json"):
        path.unlink()

    result = runner.invoke(app, ["--cwd", str(tmp_path), "task", "list"])
    assert result.exit_code == 0, result.stdout
    assert "scan-layout" in result.stdout


# specmason: req=REQ-0051 ac=AC-0552
def test_task_list_ignores_removed_legacy_indexes(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "legacy-indexes",
                "--description",
                "Listing should ignore legacy removed indexes.",
            ],
        ).exit_code
        == 0
    )
    for path in _removed_index_paths(tmp_path):
        path.write_text("{not valid json", encoding="utf-8")

    result = runner.invoke(app, ["--cwd", str(tmp_path), "task", "list"])
    assert result.exit_code == 0, result.stdout
    assert "legacy-indexes" in result.stdout


# specmason: req=REQ-0051 ac=AC-0552
def test_ensure_v2_layout_does_not_create_removed_indexes(tmp_path: Path) -> None:
    ensure_v2_layout(tmp_path)
    for path in _removed_index_paths(tmp_path):
        assert not path.exists()


# specmason: req=REQ-0051 ac=AC-0552
def test_plan_list_does_not_need_removed_indexes(tmp_path: Path) -> None:
    _prepare_task_with_plan(tmp_path, slug="plan-scan")
    for path in _removed_index_paths(tmp_path):
        path.unlink(missing_ok=True)

    payload = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "plan", "list"])
    )
    assert payload["result"]["plans"][0]["plan_version"] == 1


# specmason: req=REQ-0051 ac=AC-0552
def test_implement_status_does_not_need_removed_indexes(tmp_path: Path) -> None:
    _prepare_task_with_plan(
        tmp_path,
        slug="run-scan",
        approve=True,
        start_implementation=True,
    )
    for path in _removed_index_paths(tmp_path):
        path.unlink(missing_ok=True)

    payload = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "implement", "status"])
    )
    assert payload["result"]["task_id"] == "task-0001"
    assert payload["result"]["total"] == 1
    assert payload["result"]["done"] == 0


# specmason: req=REQ-0051 ac=AC-0552
def test_reindex_does_not_create_removed_indexes(tmp_path: Path) -> None:
    ensure_v2_layout(tmp_path)
    paths = resolve_v2_paths(tmp_path)

    rebuild_v2_indexes(paths)

    for path in _removed_index_paths(tmp_path):
        assert not path.exists()


# specmason: req=REQ-0051 ac=AC-0550
def test_task_create_no_orphan_slug_directory(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "slug-orphan-check",
            "--description",
            "No empty slug dir should appear.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    tasks_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks"
    child_names = [p.name for p in tasks_dir.iterdir()]
    # Only the canonical task-NNNN directory should exist
    assert child_names == ["task-0001"], f"unexpected directories: {child_names}"
    assert not (tasks_dir / "slug-orphan-check").exists()


# specmason: req=REQ-0051 ac=AC-0546
def test_repair_task_dirs_removes_orphans(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "orphan-parent",
            "--description",
            "Create a task then add an orphan dir.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    tasks_dir = tmp_path / ".taskledger" / "ledgers" / "main" / "tasks"
    # Manually create an empty slug-like directory
    (tasks_dir / "orphan-parent").mkdir()
    assert (tasks_dir / "orphan-parent").exists()

    result = runner.invoke(app, ["--cwd", str(tmp_path), "repair", "task-dirs"])
    assert result.exit_code == 0, result.stdout
    assert "1" in result.stdout
    assert not (tasks_dir / "orphan-parent").exists()


# specmason: req=REQ-0051 ac=AC-0545
def test_list_plans_skips_malformed_plan_files(tmp_path: Path) -> None:
    """list_plans should skip plan files with missing required fields."""
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "test task",
            "--description",
            "Task with a broken plan.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    paths = ensure_v2_layout(tmp_path)
    plans_dir = paths.tasks_dir / "task-0001" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    # Write a plan file missing task_id
    broken_plan = plans_dir / "plan-v1.md"
    broken_plan.write_text(
        "---\nschema_version: 1\nobject_type: plan\nversion: 1\n---\n\nBroken body.\n",
        encoding="utf-8",
    )

    # Should not raise; should return empty list since plan is malformed
    plans = list_plans(tmp_path, "task-0001")
    assert len(plans) == 0


# specmason: req=REQ-0051 ac=AC-0544
def test_list_plans_loads_valid_plan_with_malformed_sibling(tmp_path: Path) -> None:
    """list_plans loads valid plans even when a sibling plan is malformed."""
    _init_project(tmp_path)
    from taskledger.domain.models import PlanRecord
    from taskledger.storage.task_store import (
        save_plan,
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "test task",
            "--description",
            "Task with a mixed set of plans.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    paths = ensure_v2_layout(tmp_path)
    plans_dir = paths.tasks_dir / "task-0001" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    # Write a malformed plan first (version 1)
    (plans_dir / "plan-v1.md").write_text(
        "---\nschema_version: 1\nobject_type: plan\nversion: 1\n---\n\nBroken.\n",
        encoding="utf-8",
    )

    # Write a valid plan (version 2) via save_plan
    valid_plan = PlanRecord(
        task_id="task-0001",
        plan_version=2,
        body="Valid body.",
        status="proposed",
    )
    save_plan(tmp_path, valid_plan)

    plans = list_plans(tmp_path, "task-0001")
    assert len(plans) == 1
    assert plans[0].plan_version == 2


# specmason: req=REQ-0051 ac=AC-0549
def test_rewrite_task_refs_updates_id_and_task_id(tmp_path: Path) -> None:
    """rewrite_task_refs updates id and task_id in all child records."""
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "test task",
            "--description",
            "Task for renumbering test.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    paths = ensure_v2_layout(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"

    # Create a plan with task_id
    plans_dir = task_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "plan-v1.md").write_text(
        "---\nschema_version: 1\nobject_type: plan\n"
        "task_id: task-0001\nplan_version: 1\n"
        "version: 1\nstatus: proposed\n---\n\nBody.\n",
        encoding="utf-8",
    )

    # Create a question with id matching old task_id
    questions_dir = task_dir / "questions"
    questions_dir.mkdir(parents=True, exist_ok=True)
    (questions_dir / "q-0001.md").write_text(
        "---\nid: task-0001\ntask_id: task-0001\nquestion: Test?\nstatus: open\n---\n",
        encoding="utf-8",
    )

    rewrite_task_refs(task_dir, "task-0001", "task-0005")

    # Verify plan file was updated
    from taskledger.storage.frontmatter import read_markdown_front_matter

    plan_meta, _ = read_markdown_front_matter(plans_dir / "plan-v1.md")
    assert plan_meta["task_id"] == "task-0005"

    # Verify question id and task_id were updated
    q_meta, _ = read_markdown_front_matter(questions_dir / "q-0001.md")
    assert q_meta["id"] == "task-0005"
    assert q_meta["task_id"] == "task-0005"


# specmason: req=REQ-0051 ac=AC-0547
def test_rewrite_task_refs_adds_missing_task_id(tmp_path: Path) -> None:
    """rewrite_task_refs adds task_id when it is missing from front matter."""
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "test task",
            "--description",
            "Task for renumbering test.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    paths = ensure_v2_layout(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"

    # Create a plan file missing task_id
    plans_dir = task_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "plan-v1.md").write_text(
        "---\nschema_version: 1\nobject_type: plan\n"
        "plan_version: 1\nversion: 1\nstatus: proposed\n---\n\nBody.\n",
        encoding="utf-8",
    )

    rewrite_task_refs(task_dir, "task-0001", "task-0003")

    from taskledger.storage.frontmatter import read_markdown_front_matter

    plan_meta, _ = read_markdown_front_matter(plans_dir / "plan-v1.md")
    assert plan_meta["task_id"] == "task-0003"


# specmason: req=REQ-0051 ac=AC-0548
def test_rewrite_task_refs_noop_on_same_id(tmp_path: Path) -> None:
    """rewrite_task_refs does nothing when old and new IDs match."""
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "test task",
            "--description",
            "Task for renumbering test.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    paths = ensure_v2_layout(tmp_path)
    task_dir = paths.tasks_dir / "task-0001"

    plans_dir = task_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "plan-v1.md").write_text(
        "---\nschema_version: 1\nobject_type: plan\n"
        "task_id: task-0001\nplan_version: 1\n"
        "version: 1\nstatus: proposed\n---\n\nBody.\n",
        encoding="utf-8",
    )

    rewrite_task_refs(task_dir, "task-0001", "task-0001")

    from taskledger.storage.frontmatter import read_markdown_front_matter

    plan_meta, _ = read_markdown_front_matter(plans_dir / "plan-v1.md")
    assert plan_meta["task_id"] == "task-0001"

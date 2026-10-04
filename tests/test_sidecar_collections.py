from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.task_store import (
    load_requirements,
    resolve_task,
    resolve_v2_paths,
)


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--root", str(tmp_path), "init"])
    assert result.exit_code == 0


# specmason: req=REQ-0050 ac=AC-0543
def test_todos_links_and_requirements_use_per_record_markdown(tmp_path: Path) -> None:
    _init_project(tmp_path)

    runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "task",
            "create",
            "dependency-task",
            "--description",
            "Dependency target.",
        ],
    )
    runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "task",
            "create",
            "sidecar-task",
            "--description",
            "Verify sidecar-backed collections.",
        ],
    )

    runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "todo",
            "add",
            "--task",
            "sidecar-task",
            "--text",
            "Write sidecar test.",
        ],
    )
    runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "file",
            "add",
            "--task",
            "sidecar-task",
            "--path",
            "README.md",
            "--kind",
            "doc",
        ],
    )
    runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "require",
            "add",
            "dependency-task",
            "--task",
            "sidecar-task",
        ],
    )

    task = resolve_task(tmp_path, "sidecar-task")
    dependency = resolve_task(tmp_path, "dependency-task")
    requirement = load_requirements(tmp_path, task.id).requirements[0]
    assert requirement.required_task_id == dependency.id
    assert requirement.required_task_uuid == dependency.task_uuid
    assert requirement.parent_task_id == task.id
    assert requirement.parent_task_uuid == task.task_uuid
    task_dir = resolve_v2_paths(tmp_path).tasks_dir / (task.task_uuid or "")
    task_markdown = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "todos:" not in task_markdown
    assert "file_links:" not in task_markdown
    assert "requirements:" not in task_markdown

    # Per-record directories exist, YAML sidecars do not
    assert (task_dir / "todos").is_dir()
    assert (task_dir / "links").is_dir()
    assert (task_dir / "requirements").is_dir()
    assert not (task_dir / "todos.yaml").exists()
    assert not (task_dir / "links.yaml").exists()
    assert not (task_dir / "requirements.yaml").exists()

    # Check per-record Markdown files
    todo_files = list((task_dir / "todos").glob("todo-*.md"))
    assert len(todo_files) == 1
    todo_text = todo_files[0].read_text(encoding="utf-8")
    assert "Write sidecar test." in todo_text
    assert "object_type: todo" in todo_text

    link_files = list((task_dir / "links").glob("link-*.md"))
    assert len(link_files) == 1
    link_text = link_files[0].read_text(encoding="utf-8")
    assert "README.md" in link_text
    assert "object_type: link" in link_text

    req_files = list((task_dir / "requirements").glob("req-*.md"))
    assert len(req_files) == 1
    req_text = req_files[0].read_text(encoding="utf-8")
    assert "task-0001" in req_text
    assert "object_type: requirement" in req_text

    result = runner.invoke(
        app, ["--root", str(tmp_path), "task", "show", "--task", "sidecar-task"]
    )
    assert result.exit_code == 0, result.output
    assert "sidecar-task" in result.output

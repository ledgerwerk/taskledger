from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.frontmatter import read_markdown_front_matter
from tests.support.builders import (
    create_done_task as build_done_task,
)
from tests.support.builders import (
    init_workspace,
)

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    runner_factory = cast(Any, CliRunner)
    try:
        return cast(CliRunner, runner_factory(mix_stderr=False))
    except TypeError:
        return cast(CliRunner, runner_factory())


runner = _make_runner()


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.stdout
    payload = cast(dict[str, Any], json.loads(result.stdout))
    assert payload["ok"] is True
    return payload


def _init_project(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _plan_text(title: str) -> str:
    return f"""---
goal: Ship {title}.
acceptance_criteria:
  - id: ac-0001
    text: "{title} works."
todos:
  - id: todo-0001
    text: "Implement {title}."
    validation_hint: "python -c \\"print('ok')\\""
---

# Plan

Ship {title}.
"""


def _create_done_task(
    tmp_path: Path,
    *,
    title: str,
    slug: str,
    labels: tuple[str, ...] = (),
) -> str:
    return build_done_task(
        tmp_path,
        title=title,
        slug=slug,
        description=f"{title} summary.",
        labels=labels,
        plan_text=_plan_text(title),
        validation_evidence="python -c print('ok')",
        validation_summary=f"Validated {title}.",
        change_path="taskledger/services/releases.py",
        change_summary=f"Implemented {title}.",
        implement_summary=f"Implemented {title}.",
        approve_note="Approved.",
    )


# specmason: req=REQ-0046 ac=AC-0520
def test_release_tag_persists_release_record(tmp_path: Path) -> None:
    _init_project(tmp_path)
    task_id = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "tag",
            "0.4.1",
            "--at-task",
            task_id,
            "--note",
            "0.4.1 released",
        ],
    )
    assert result.exit_code == 0, result.stdout

    path = tmp_path / ".taskledger" / "ledgers" / "main" / "releases" / "0.4.1.md"
    metadata, _ = read_markdown_front_matter(path)
    assert metadata["object_type"] == "release"
    assert metadata["version"] == "0.4.1"
    assert metadata["boundary_task_id"] == task_id


# specmason: req=REQ-0046 ac=AC-0522
def test_release_tag_rejects_non_done_boundary(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "create",
            "Not done yet",
            "--slug",
            "not-done-yet",
            "--description",
            "Still in draft.",
        ],
    )
    assert result.exit_code == 0

    tag_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "tag",
            "0.4.1",
            "--at-task",
            "not-done-yet",
        ],
    )
    assert tag_result.exit_code != 0
    assert "done tasks" in tag_result.stdout or "done tasks" in tag_result.stderr


# specmason: req=REQ-0046 ac=AC-0521
def test_release_tag_rejects_duplicate_version(tmp_path: Path) -> None:
    _init_project(tmp_path)
    task_id = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "release",
                "tag",
                "0.4.1",
                "--at-task",
                task_id,
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "tag",
            "0.4.1",
            "--at-task",
            task_id,
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.stdout or "already exists" in result.stderr


# specmason: req=REQ-0046 ac=AC-0518
def test_release_list_is_sorted_by_boundary_task(tmp_path: Path) -> None:
    _init_project(tmp_path)
    first = _create_done_task(
        tmp_path, title="First release boundary", slug="first-release-boundary"
    )
    second = _create_done_task(
        tmp_path, title="Second release boundary", slug="second-release-boundary"
    )

    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.2", "--at-task", second],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", first],
        ).exit_code
        == 0
    )

    result = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "release", "list"])
    )
    versions = [item["version"] for item in result["result"]["releases"]]
    assert versions == ["0.4.1", "0.4.2"]


# specmason: req=REQ-0046 ac=AC-0519
def test_release_show_returns_persisted_record(tmp_path: Path) -> None:
    _init_project(tmp_path)
    task_id = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "release",
                "tag",
                "0.4.1",
                "--at-task",
                task_id,
                "--note",
                "0.4.1 released",
            ],
        ).exit_code
        == 0
    )

    result = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "release", "show", "0.4.1"],
        )
    )
    release = result["result"]["release"]
    assert release["version"] == "0.4.1"
    assert release["boundary_task_id"] == task_id
    assert release["note"] == "0.4.1 released"


# specmason: req=REQ-0046 ac=AC-0509
# specmason: req=REQ-0046 ac=AC-0510
# specmason: req=REQ-0046 ac=AC-0511
# specmason: req=REQ-0046 ac=AC-0512
# specmason: req=REQ-0046 ac=AC-0513
# specmason: req=REQ-0046 ac=AC-0514
# specmason: req=REQ-0046 ac=AC-0515
# specmason: req=REQ-0046 ac=AC-0516
# specmason: req=REQ-0046 ac=AC-0517
def test_release_changelog_subcommand_is_not_registered(tmp_path: Path) -> None:
    """release changelog was removed; release tag/list/show remain."""
    _init_project(tmp_path)
    _create_done_task(tmp_path, title="Release boundary", slug="release-boundary")
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "release", "changelog", "0.4.2", "--since", "0.4.1"],
    )
    assert result.exit_code != 0
    assert (
        "No such command" in result.output
        or "Got unexpected extra argument" in result.output
    )

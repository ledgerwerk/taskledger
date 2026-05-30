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
    create_failed_validation_task as build_failed_validation_task,
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


def _create_failed_validation_task(tmp_path: Path, *, title: str, slug: str) -> str:
    return build_failed_validation_task(
        tmp_path,
        title=title,
        slug=slug,
        description=f"{title} summary.",
        plan_text=_plan_text(title),
        todo_evidence="python -c print('ok')",
        failure_evidence="python -c print('fail')",
        validation_summary=f"Validation failed for {title}.",
        change_path="taskledger/services/releases.py",
        change_summary=f"Implemented {title}.",
        implement_summary=f"Implemented {title}.",
        approve_note="Approved.",
    )


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


def test_release_changelog_filters_done_tasks_and_reports_omitted(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    done_one = _create_done_task(
        tmp_path,
        title="Improve dashboard refresh stability",
        slug="dashboard-refresh-stability",
        labels=("ui", "serve"),
    )
    failed = _create_failed_validation_task(
        tmp_path,
        title="Dashboard polish",
        slug="dashboard-polish",
    )
    done_two = _create_done_task(
        tmp_path,
        title="Improve changelog rendering",
        slug="improve-changelog-rendering",
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", boundary],
        ).exit_code
        == 0
    )

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "changelog",
                "0.4.2",
                "--since",
                "0.4.1",
                "--until-task",
                done_two,
            ],
        )
    )
    payload = result["result"]
    assert payload["kind"] == "release_changelog_context"
    assert [item["task_id"] for item in payload["tasks"]] == [done_one, done_two]
    assert payload["omitted_task_count"] == 1
    assert payload["omitted_tasks"][0]["task_id"] == failed
    assert payload["omitted_tasks"][0]["status_stage"] == "failed_validation"


def test_release_changelog_markdown_includes_instruction_and_evidence(
    tmp_path: Path,
) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    included = _create_done_task(
        tmp_path,
        title="Improve dashboard refresh stability",
        slug="dashboard-refresh-stability",
        labels=("ui", "serve"),
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", boundary],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "changelog",
            "0.4.2",
            "--since",
            "0.4.1",
            "--until-task",
            included,
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert f"# Changelog source for {tmp_path.name} 0.4.2" in result.stdout
    expected_line = f"Write a concise human changelog for {tmp_path.name} version 0.4.2"
    assert expected_line in result.stdout
    assert "## LLM instruction" in result.stdout
    assert "Improve dashboard refresh stability" in result.stdout
    assert "Implementation summary:" in result.stdout
    assert "Relevant changes:" in result.stdout
    assert "Evidence:" in result.stdout
    assert "python -c print('ok')" in result.stdout


def test_release_changelog_supports_bootstrap_since_task(tmp_path: Path) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    included = _create_done_task(
        tmp_path,
        title="Improve changelog rendering",
        slug="improve-changelog-rendering",
    )

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "changelog",
                "0.4.2",
                "--since-task",
                boundary,
                "--until-task",
                included,
            ],
        )
    )
    payload = result["result"]
    assert payload["since_version"] is None
    assert payload["since_task_id"] == boundary
    assert payload["tasks"][0]["task_id"] == included


def test_release_changelog_markdown_uses_project_name(tmp_path: Path) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    included = _create_done_task(
        tmp_path,
        title="Improve dashboard refresh stability",
        slug="dashboard-refresh-stability",
        labels=("ui", "serve"),
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", boundary],
        ).exit_code
        == 0
    )

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "changelog",
                "0.4.2",
                "--since",
                "0.4.1",
                "--until-task",
                included,
            ],
        )
    )
    payload = result["result"]
    assert payload["project_name"] == tmp_path.name


def test_release_changelog_from_task_is_inclusive(tmp_path: Path) -> None:
    _init_project(tmp_path)
    first = _create_done_task(tmp_path, title="First task", slug="first-task")
    second = _create_done_task(tmp_path, title="Second task", slug="second-task")

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "changelog",
                "0.4.2",
                "--from-task",
                first,
                "--until-task",
                second,
            ],
        )
    )
    payload = result["result"]
    assert payload["range_mode"] == "inclusive_task_range"
    assert payload["from_task_id"] == first
    task_ids = [task["task_id"] for task in payload["tasks"]]
    assert first in task_ids
    assert second in task_ids


def test_release_changelog_from_task_rejects_multiple_selectors(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "changelog",
            "0.4.2",
            "--since",
            "0.4.1",
            "--from-task",
            "task-0001",
        ],
    )
    assert result.exit_code != 0


def test_release_changelog_fail_on_omitted(tmp_path: Path) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    _create_done_task(tmp_path, title="Done task", slug="done-task")
    failed = _create_failed_validation_task(
        tmp_path, title="Failed task", slug="failed-task"
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", boundary],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "changelog",
            "0.4.2",
            "--since",
            "0.4.1",
            "--until-task",
            failed,
            "--fail-on-omitted",
        ],
    )
    assert result.exit_code != 0
    omitted_text = (
        result.stdout if "Omitted tasks found" in result.stdout else result.stderr
    )
    assert "Omitted tasks found" in omitted_text


def test_release_changelog_include_status_implemented(tmp_path: Path) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    _create_done_task(tmp_path, title="Done task", slug="done-task")
    failed = _create_failed_validation_task(
        tmp_path, title="Failed task", slug="failed-task"
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", boundary],
        ).exit_code
        == 0
    )

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "changelog",
                "0.4.2",
                "--since",
                "0.4.1",
                "--until-task",
                failed,
                "--include-status",
                "done",
                "--include-status",
                "failed_validation",
            ],
        )
    )
    payload = result["result"]
    assert "failed_validation" in payload["included_statuses"]
    task_ids = [task["task_id"] for task in payload["tasks"]]
    assert failed in task_ids
    assert payload["warnings"]


def test_release_changelog_target_changelog_and_release_date(tmp_path: Path) -> None:
    _init_project(tmp_path)
    boundary = _create_done_task(
        tmp_path, title="Release boundary", slug="release-boundary"
    )
    included = _create_done_task(
        tmp_path,
        title="Improve dashboard refresh stability",
        slug="dashboard-refresh-stability",
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "release", "tag", "0.4.1", "--at-task", boundary],
        ).exit_code
        == 0
    )

    # Test with target changelog and release date in json mode
    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "changelog",
                "0.4.2",
                "--since",
                "0.4.1",
                "--until-task",
                included,
                "--target-changelog",
                "CHANGELOG.md",
                "--release-date",
                "2026-05-30",
            ],
        )
    )
    payload = result["result"]
    assert payload["target_changelog"] == "CHANGELOG.md"
    assert payload["release_date"] == "2026-05-30"

    # Test markdown output includes guidance
    md_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "changelog",
            "0.4.2",
            "--since",
            "0.4.1",
            "--until-task",
            included,
            "--target-changelog",
            "CHANGELOG.md",
            "--release-date",
            "2026-05-30",
        ],
    )
    assert md_result.exit_code == 0
    assert "## Changelog edit guidance" in md_result.stdout
    assert "Target changelog: CHANGELOG.md" in md_result.stdout
    assert "Use release date: 2026-05-30" in md_result.stdout

    # Test without release date says not to invent one
    md_result2 = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "changelog",
            "0.4.2",
            "--since",
            "0.4.1",
            "--until-task",
            included,
        ],
    )
    assert md_result2.exit_code == 0
    assert "## Changelog edit guidance" not in md_result2.stdout


def test_release_changelog_include_status_rejects_unknown(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "release",
            "changelog",
            "0.4.2",
            "--since",
            "0.4.1",
            "--include-status",
            "not_a_status",
        ],
    )
    assert result.exit_code != 0

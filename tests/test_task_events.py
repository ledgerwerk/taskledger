from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _enable_event_logging(tmp_path: Path) -> None:
    config_path = tmp_path / ".ledger" / "taskledger" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n[event_logging]\nenabled = true\n",
        encoding="utf-8",
    )


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0


def _json(result) -> dict[str, object]:
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


def _create_and_activate_task(tmp_path: Path, slug: str = "test-task") -> None:
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Test task",
                "--slug",
                slug,
                "--description",
                "A test task.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", slug],
        ).exit_code
        == 0
    )


# sw: f=specs/behavior/features/task_events/events.feature
# sw: s=@bdd-task-events-task-events-human-output
def test_task_events_human_output(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_event_logging(tmp_path)
    _create_and_activate_task(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "events"],
    )
    assert result.exit_code == 0
    assert "EVENTS" in result.output
    assert "task.created" in result.output


# sw: f=specs/behavior/features/task_events/events.feature
# sw: s=@bdd-task-events-task-events-json-output
def test_task_events_json_output(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_event_logging(tmp_path)
    _create_and_activate_task(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "events"],
    )
    payload = _json(result)
    assert payload["result_type"] == "event_list"
    items = payload["result"]["items"]
    assert isinstance(items, list)
    assert len(items) > 0
    event = items[0]
    assert "event" in event
    assert "ts" in event
    assert "actor" in event


# sw: f=specs/behavior/features/task_events/events.feature
# sw: s=@bdd-task-events-task-events-all
def test_task_events_all(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_event_logging(tmp_path)
    _create_and_activate_task(tmp_path, "task-a")
    _create_and_activate_task(tmp_path, "task-b")

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "events", "--all"],
    )
    assert result.exit_code == 0
    assert "task.created" in result.output


# sw: f=specs/behavior/features/task_events/events.feature
# sw: s=@bdd-task-events-task-events-limit
def test_task_events_limit(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_event_logging(tmp_path)
    _create_and_activate_task(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "events", "--limit", "1"],
    )
    assert result.exit_code == 0
    lines = [
        line
        for line in result.output.strip().splitlines()
        if line.strip()
        and not line.startswith("EVENTS")
        and not line.startswith("TIMESTAMP")
    ]
    assert len(lines) <= 1


# sw: f=specs/behavior/features/task_events/events.feature
# sw: s=@bdd-task-events-task-events-empty
def test_task_events_empty(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _create_and_activate_task(tmp_path)

    # filter by a non-existent task slug
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "events", "--task", "no-such-task"],
    )
    # should error because no active task matches
    assert result.exit_code != 0


# sw: f=specs/behavior/features/task_events/events.feature
# sw: s=@bdd-task-events-task-events-with-explicit-task-ref
def test_task_events_with_explicit_task_ref(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_event_logging(tmp_path)
    _create_and_activate_task(tmp_path, "target-task")
    # deactivate so active task is gone, then use --task
    runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "deactivate", "--reason", "done"],
    )

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "events", "--task", "target-task"],
    )
    assert result.exit_code == 0
    assert "EVENTS" in result.output

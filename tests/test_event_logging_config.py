from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.project_context import load_project_context


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0


def _data_root(tmp_path: Path) -> Path:
    context = load_project_context(tmp_path)
    return context.paths.data_root


def _disable_event_logging(tmp_path: Path) -> None:
    config_path = tmp_path / ".ledger" / "taskledger" / "config.toml"
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text + "\n[event_logging]\nenabled = false\n",
        encoding="utf-8",
    )


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


# -- default-on tests --


# sw: f=specs/behavior/features/event_logging_config/event-logging-config.feature
# sw: s=@bdd-event-logging-config-runtime-events-enabled-by-default
def test_runtime_events_enabled_by_default_writes_events(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _create_and_activate_task(tmp_path)

    event_files = sorted(
        (_data_root(tmp_path) / "ledgers" / "main").glob("**/events/*.ndjson")
    )
    assert event_files

    events = []
    for path in event_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    assert any(e["event"] == "task.created" for e in events)


# sw: f=specs/behavior/features/event_logging_config/event-logging-config.feature
# sw: s=@bdd-event-logging-config-task-events-reads-default-action-events
def test_task_events_reads_default_action_events(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _create_and_activate_task(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "events"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["result"]["items"]) > 0


# sw: f=specs/behavior/features/event_logging_config/event-logging-config.feature
# sw: s=@bdd-event-logging-config-lock-break-writes-events-by-default
def test_lock_break_writes_events_by_default(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "lock-test",
                "--description",
                "Test lock break events.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "lock-test"]
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "lock",
            "break",
            "--task",
            "lock-test",
            "--reason",
            "test",
        ],
    )
    assert result.exit_code == 0

    event_files = sorted(
        (_data_root(tmp_path) / "ledgers" / "main").glob("**/events/*.ndjson")
    )
    assert event_files
    events = []
    for path in event_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    assert any(e["event"] == "repair.lock_broken" for e in events)


# -- opt-out tests --


# sw: f=specs/behavior/features/event_logging_config/event-logging-config.feature
# sw: s=@bdd-event-logging-config-false-disables-new-action-events
def test_event_logging_false_disables_new_action_events(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _disable_event_logging(tmp_path)
    _create_and_activate_task(tmp_path)

    event_files = sorted(
        (_data_root(tmp_path) / "ledgers" / "main").glob("**/events/*.ndjson")
    )
    assert event_files == []

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "events"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["items"] == []


# sw: f=specs/behavior/features/event_logging_config/event-logging-config.feature
# sw: s=@bdd-event-logging-config-existing-events-readable-after-disable
def test_existing_events_readable_after_disable(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _create_and_activate_task(tmp_path)

    # Verify events were written (default-on)
    event_files = sorted(
        (_data_root(tmp_path) / "ledgers" / "main").glob("**/events/*.ndjson")
    )
    assert len(event_files) > 0

    # Disable event logging
    _disable_event_logging(tmp_path)

    # Create another task - should not produce new events beyond what already exists
    initial_count = sum(
        len(line.strip().splitlines())
        for p in event_files
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Second task",
                "--slug",
                "second-task",
                "--description",
                "After disable.",
            ],
        ).exit_code
        == 0
    )

    # Old events still readable
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "task", "events", "--all"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["result"]["items"]) >= initial_count

    # The new task create should NOT have added events
    second_task_events = [
        item
        for item in payload["result"]["items"]
        if item.get("task_id") == "task-0002"
    ]
    assert second_task_events == []

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.project_context import load_project_context


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


def _data_root(tmp_path: Path) -> Path:
    context = load_project_context(tmp_path)
    return context.paths.data_root


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


# specmason: req=REQ-0031 ac=AC-0358
def test_break_lock_writes_audit_file_and_repair_event(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _enable_event_logging(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "lock-audit",
                "--description",
                "Exercise broken lock auditing.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "lock-audit"]
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
            "lock-audit",
            "--reason",
            "recover stale planning lock",
        ],
    )
    payload = _json(result)
    assert result.exit_code == 0
    assert payload["ok"] is True
    assert payload["result"]["audit_path"].startswith(
        "tasks/task-0001/audit/broken-lock-"
    )

    project_dir = _data_root(tmp_path) / "ledgers" / "main"
    audit_path = project_dir / payload["result"]["audit_path"]
    audit_payload = yaml.safe_load(audit_path.read_text(encoding="utf-8"))
    assert audit_payload["broken_reason"] == "recover stale planning lock"
    assert audit_payload["broken_by"]["actor_type"] == "agent"

    events = [
        json.loads(line)
        for path in sorted((project_dir / "events").glob("*.ndjson"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "repair.lock_broken" for event in events)


# specmason: req=REQ-0031 ac=AC-0359
def test_stale_lock_blocks_new_run_until_explicit_break(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "stale-lock",
                "--description",
                "Exercise stale lock handling.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "stale-lock"]
        ).exit_code
        == 0
    )

    lock_path = (
        _data_root(tmp_path) / "ledgers" / "main" / "tasks" / "task-0001" / "lock.yaml"
    )
    lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock_payload["expires_at"] = "2000-01-01T00:00:00+00:00"
    lock_path.write_text(
        yaml.safe_dump(lock_payload, sort_keys=False), encoding="utf-8"
    )

    blocked = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "plan", "start", "--task", "stale-lock"],
    )
    blocked_payload = _json(blocked)
    assert blocked.exit_code != 0
    assert blocked_payload["ok"] is False
    assert "expired" in blocked_payload["error"]["message"]

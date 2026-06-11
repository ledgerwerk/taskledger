from __future__ import annotations

import json

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.trace import build_task_trace
from tests.support.builders import create_implemented_task, init_workspace

runner = CliRunner()


def test_trace_task_basic_fields(tmp_path) -> None:
    init_workspace(tmp_path)
    task_id = create_implemented_task(tmp_path)

    payload = build_task_trace(tmp_path, task_id)

    assert payload["schema"] == "taskledger.trace.v1"
    assert payload["producer"] == "taskledger"
    assert payload["subject"] == {"type": "task", "id": task_id}
    assert payload["task_ids"] == [task_id]
    assert payload["ac_ids"] == ["ac-0001"]
    assert "link_refs" in payload
    assert "source_refs" in payload
    assert "evidence_refs" in payload


def test_trace_cli_format_json_is_raw_json(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    init_workspace(tmp_path)
    task_id = create_implemented_task(tmp_path)

    result = runner.invoke(app, ["trace", task_id, "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema"] == "taskledger.trace.v1"
    assert payload["task_ids"] == [task_id]

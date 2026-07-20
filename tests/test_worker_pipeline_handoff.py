from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _append_pipeline_config(path: Path) -> None:
    config = """
[worker_pipeline]
enabled = true
name = "tdd-four-context"
mode = "guided"

[[worker_pipeline.steps]]
id = "planner"
lifecycle_stage = "planning"
base_context = "planner"

[[worker_pipeline.steps]]
id = "tester"
label = "Test Writer"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "check"
description = "Add failing tests first."
"""
    current = path.read_text(encoding="utf-8")
    path.write_text(f"{current.rstrip()}\n\n{config.strip()}\n", encoding="utf-8")


def _setup_active_task(workspace: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(workspace), "init"]).exit_code == 0
    _append_pipeline_config(workspace / ".ledger" / "taskledger" / "config.toml")
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "Worker handoff task",
                "--slug",
                "worker-handoff",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "task", "activate", "worker-handoff"],
        ).exit_code
        == 0
    )


# specmason: req=REQ-0074 ac=AC-0818
def test_worker_handoff_stores_worker_step_id_sparse(tmp_path: Path) -> None:
    _setup_active_task(tmp_path)

    worker_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "handoff",
            "create",
            "--worker",
            "tester",
            "--summary",
            "Add failing tests only.",
        ],
    )
    assert worker_result.exit_code == 0, worker_result.stdout
    worker_payload = _json(worker_result)["result"]
    assert worker_payload["worker_step_id"] == "tester"
    assert worker_payload["mode"] == "implementation"
    assert worker_payload["context_for"] == "implementer"
    worker_handoff_path = tmp_path / str(worker_payload["context_path"])
    assert "worker_step_id: tester" in worker_handoff_path.read_text(encoding="utf-8")

    normal_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "handoff",
            "create",
            "--mode",
            "implementation",
            "--summary",
            "Regular implementation handoff.",
        ],
    )
    assert normal_result.exit_code == 0, normal_result.stdout
    normal_payload = _json(normal_result)["result"]
    assert "worker_step_id" not in normal_payload
    normal_handoff_path = tmp_path / str(normal_payload["context_path"])
    assert "worker_step_id:" not in normal_handoff_path.read_text(encoding="utf-8")


# specmason: req=REQ-0074 ac=AC-0817
def test_worker_handoff_rejects_conflicting_mode_override(tmp_path: Path) -> None:
    _setup_active_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "handoff",
            "create",
            "--worker",
            "tester",
            "--mode",
            "validation",
        ],
    )

    assert result.exit_code != 0
    output = f"{result.stdout}{getattr(result, 'stderr', '')}"
    assert "requires mode 'implementation'" in output


# specmason: req=REQ-0074 ac=AC-0816
def test_worker_handoff_rejects_conflicting_context_override(tmp_path: Path) -> None:
    _setup_active_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "handoff",
            "create",
            "--worker",
            "tester",
            "--for",
            "validator",
        ],
    )

    assert result.exit_code != 0
    output = f"{result.stdout}{getattr(result, 'stderr', '')}"
    assert "requires context 'implementer'" in output

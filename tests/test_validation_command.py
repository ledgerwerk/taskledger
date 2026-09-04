from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.task_store import resolve_v2_paths
from tests.support.builders import create_implemented_task, init_workspace

runner = CliRunner()


def _json(result: object) -> dict[str, object]:
    return json.loads(result.stdout)


def _prepare_implemented(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    create_implemented_task(tmp_path, slug="validation-command")


def _start_validation(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "validate", "start"])
    assert result.exit_code == 0, result.stdout


def test_validate_command_requires_active_validation_run(tmp_path: Path) -> None:
    _prepare_implemented(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "command",
            "--",
            sys.executable,
            "-c",
            "print('probe')",
        ],
    )

    assert result.exit_code != 0
    assert "active run" in f"{result.stdout}{getattr(result, 'stderr', '')}"


def test_validate_command_captures_output_and_does_not_create_check(
    tmp_path: Path,
) -> None:
    _prepare_implemented(tmp_path)
    _start_validation(tmp_path)

    result = runner.invoke(
        app,
        [
            "--json",
            "--cwd",
            str(tmp_path),
            "validate",
            "command",
            "--",
            sys.executable,
            "-c",
            "import sys; print('stdout'); print('stderr', file=sys.stderr)",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = _json(result)
    command = payload["result"]
    assert isinstance(command, dict)
    assert command["kind"] == "validation_command"
    assert command["exit_code"] == 0
    assert command["cwd"] == str(tmp_path.resolve())
    assert command["stdout"] == "stdout\n"
    assert command["stderr"] == "stderr\n"
    assert command["artifact_path"] is None

    status = runner.invoke(
        app,
        ["--json", "--cwd", str(tmp_path), "validate", "status"],
    )
    assert status.exit_code == 0, status.stdout
    status_result = _json(status)["result"]["result"]
    assert isinstance(status_result, dict)
    assert status_result["criteria"][0]["latest_status"] == "not_run"


def test_validate_command_failed_exit_and_allow_failure(tmp_path: Path) -> None:
    _prepare_implemented(tmp_path)
    _start_validation(tmp_path)
    command = [
        "--cwd",
        str(tmp_path),
        "validate",
        "command",
        "--",
        sys.executable,
        "-c",
        "raise SystemExit(6)",
    ]

    failed = runner.invoke(app, command)
    assert failed.exit_code == 6
    assert "ran validation command exit=6" in failed.stdout

    allowed = runner.invoke(app, [*command[:4], "--allow-failure", *command[4:]])
    assert allowed.exit_code == 0, allowed.stdout

    run = runner.invoke(
        app,
        ["--json", "--cwd", str(tmp_path), "validate", "show"],
    )
    assert run.exit_code == 0, run.stdout
    run_data = _json(run)["result"]["run"]
    assert isinstance(run_data, dict)
    assert run_data["checks"] == []
    assert any("exit 6" in item for item in run_data["worklog"])


def test_validate_command_stores_large_output_artifact(tmp_path: Path) -> None:
    _prepare_implemented(tmp_path)
    _start_validation(tmp_path)

    result = runner.invoke(
        app,
        [
            "--json",
            "--cwd",
            str(tmp_path),
            "validate",
            "command",
            "--",
            sys.executable,
            "-c",
            "print('x' * 5001)",
        ],
    )

    assert result.exit_code == 0, result.stdout
    command = _json(result)["result"]
    assert isinstance(command, dict)
    artifact_path = command["artifact_path"]
    assert isinstance(artifact_path, str)
    assert (resolve_v2_paths(tmp_path).project_dir / artifact_path).exists()

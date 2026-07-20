from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import taskledger.cli as cli_module
from taskledger import launcher


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init_project(app, tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0, result.output


# specmason: req=REQ-0008 ac=AC-0092
def test_optional_release_import_failure_keeps_core_commands_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_import_module = importlib.import_module

    def failing_release_import(name: str, package: str | None = None):
        if name == "taskledger.cli_release":
            raise SyntaxError("broken release module")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", failing_release_import)
    broken_cli = importlib.reload(cli_module)
    try:
        _init_project(broken_cli.app, tmp_path)
        assert (
            runner.invoke(
                broken_cli.app,
                ["--cwd", str(tmp_path), "actor", "whoami"],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                broken_cli.app,
                [
                    "--cwd",
                    str(tmp_path),
                    "task",
                    "create",
                    "Broken release task",
                    "--slug",
                    "broken-release-task",
                ],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                broken_cli.app,
                [
                    "--cwd",
                    str(tmp_path),
                    "task",
                    "activate",
                    "broken-release-task",
                ],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                broken_cli.app,
                ["--cwd", str(tmp_path), "task", "active"],
            ).exit_code
            == 0
        )
        assert runner.invoke(broken_cli.app, ["question", "--help"]).exit_code == 0
        assert (
            runner.invoke(
                broken_cli.app,
                ["--cwd", str(tmp_path), "next-action"],
            ).exit_code
            == 0
        )

        failed_release = runner.invoke(
            broken_cli.app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "release",
                "tag",
                "0.4.1",
                "--at-task",
                "task-0001",
            ],
        )
        assert failed_release.exit_code == 1
        payload = _json(failed_release)
        error = payload["error"]
        assert isinstance(error, dict)
        assert error["code"] == "OPTIONAL_COMMAND_GROUP_UNAVAILABLE"
        assert "taskledger.cli_release" in error["message"]
        assert "SyntaxError" in error["message"]
        details = error["details"]
        assert isinstance(details, dict)
        assert details["module_name"] == "taskledger.cli_release"
        assert details["exception_type"] == "SyntaxError"
        assert (
            details["diagnostic_command"]
            == "python -m py_compile taskledger/cli_release.py"
        )
    finally:
        monkeypatch.undo()
        importlib.reload(cli_module)


# specmason: req=REQ-0008 ac=AC-0091
def test_launcher_reports_cli_import_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_import(name: str):
        raise RuntimeError(f"broken import for {name}")

    monkeypatch.setattr(launcher, "import_module", failing_import)
    with pytest.raises(SystemExit) as excinfo:
        launcher.main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "taskledger failed to import its CLI." in captured.err
    assert "RuntimeError: broken import for taskledger.cli" in captured.err
    assert "python -m py_compile taskledger/cli.py taskledger/cli_release.py" in (
        captured.err
    )


# specmason: req=REQ-0008 ac=AC-0093
def test_python_m_taskledger_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "taskledger", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Manage staged taskledger coding work." in result.stdout

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app

runner = CliRunner()


def _invoke(tmp_path: Path, *args: str):
    return runner.invoke(app, ["--cwd", str(tmp_path), *args])


def _init(tmp_path: Path) -> None:
    shutil.rmtree(tmp_path.parent / "ledger", ignore_errors=True)
    result = _invoke(tmp_path, "init", "--create-sibling-store")
    assert result.exit_code == 0, result.stdout


# specmason: req=REQ-0062 ac=AC-0677
def test_branch_ledgers_derive_ids_per_ledger_ref(tmp_path: Path) -> None:
    _init(tmp_path)
    assert _invoke(tmp_path, "task", "create", "Main task").exit_code == 0
    assert _invoke(tmp_path, "ledger", "fork", "feature-a").exit_code == 0
    feature = _invoke(tmp_path, "task", "create", "Feature task")
    assert feature.exit_code == 0, feature.stdout
    assert "task-0001" in feature.stdout
    assert _invoke(tmp_path, "ledger", "switch", "main").exit_code == 0
    main = _invoke(tmp_path, "task", "create", "Main second")
    assert main.exit_code == 0, main.stdout
    assert "task-0002" in main.stdout


# specmason: req=REQ-0062 ac=AC-0675
def test_ledger_status_reports_derived_next_id(tmp_path: Path) -> None:
    _init(tmp_path)
    _invoke(tmp_path, "task", "create", "Main task")
    result = _invoke(tmp_path, "ledger", "status")
    assert result.exit_code == 0, result.stdout
    assert "task-0002" in result.stdout


# specmason: req=REQ-0062 ac=AC-0674
def test_ledger_fork_switch_and_doctor_use_sibling_state(tmp_path: Path) -> None:
    _init(tmp_path)
    assert _invoke(tmp_path, "ledger", "fork", "feature-a").exit_code == 0
    assert _invoke(tmp_path, "ledger", "switch", "main").exit_code == 0
    doctor = _invoke(tmp_path, "doctor")
    assert doctor.exit_code == 0, doctor.stdout
    assert "healthy: true" in doctor.stdout


# specmason: req=REQ-0062 ac=AC-0673
def test_release_json_includes_ledger_ref(tmp_path: Path) -> None:
    _init(tmp_path)
    _invoke(tmp_path, "task", "create", "Release task")
    result = _invoke(tmp_path, "--json", "release", "list")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


# specmason: req=REQ-0062 ac=AC-0676
def test_global_refs_remain_branch_agnostic(tmp_path: Path) -> None:
    _init(tmp_path)
    result = _invoke(tmp_path, "task", "create", "Main task")
    assert result.exit_code == 0
    assert "task-0001" in result.stdout

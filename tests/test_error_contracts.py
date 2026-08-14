from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.errors import InvalidPromptError, LaunchError, ValidationError


def test_stable_storage_error_has_storage_exit_code() -> None:
    error = LaunchError("TASKLEDGER_SIBLING_ROOT_MISSING: /tmp/ledger")

    assert error.code == "TASKLEDGER_SIBLING_ROOT_MISSING"
    assert error.exit_code == 4  # CONFLICT
    assert error.taskledger_exit_code == 4  # CONFLICT


def test_native_error_families_use_canonical_ledgerwerk_exit_codes() -> None:
    cases = [
        (LaunchError("TASKLEDGER_PROJECT_NOT_FOUND: missing"), 3),
        (LaunchError("TASKLEDGER_SIBLING_ROOT_MISSING: missing"), 4),
        (ValidationError("criterion failed"), 1),
        (InvalidPromptError("bad input"), 2),
        (LaunchError("external process failed", exit_code=5), 5),
    ]

    for error, expected in cases:
        assert error.exit_code == expected
        assert 0 <= error.exit_code <= 5


def test_canonical_sync_error_has_usage_exit_code() -> None:
    error = LaunchError("TASKLEDGER_CANONICAL_SYNC_PATH_FIXED: fixed")

    assert error.code == "TASKLEDGER_CANONICAL_SYNC_PATH_FIXED"
    assert error.exit_code == 2


def test_init_json_initializes_default_storage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = CliRunner().invoke(
        app,
        ["--cwd", str(workspace), "--json", "init"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["kind"] == "taskledger_init"

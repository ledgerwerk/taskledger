from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _json(result) -> dict[str, object]:
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0, result.stdout


def test_config_list_and_get_json(tmp_path: Path) -> None:
    _init_project(tmp_path)

    listed = runner.invoke(app, ["--cwd", str(tmp_path), "--json", "config", "list"])
    assert listed.exit_code == 0, listed.stdout
    listed_payload = _json(listed)
    assert listed_payload["ok"] is True
    assert listed_payload["result_type"] == "project_config"
    result = listed_payload["result"]
    assert result["kind"] == "project_config"
    assert result["config_path"] == str(tmp_path / "taskledger.toml")
    assert isinstance(result["config"], dict)

    gotten = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "config", "get", "config_version"],
    )
    assert gotten.exit_code == 0, gotten.stdout
    gotten_payload = _json(gotten)
    assert gotten_payload["ok"] is True
    assert gotten_payload["result_type"] == "project_config_value"
    assert gotten_payload["result"]["value"] == 2


def test_config_set_updates_prompt_profile_numbers(tmp_path: Path) -> None:
    _init_project(tmp_path)

    set_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "config",
            "set",
            "prompt_profiles.planning.max_required_questions",
            "3",
        ],
    )
    assert set_result.exit_code == 0, set_result.stdout
    payload = _json(set_result)
    assert payload["ok"] is True
    assert payload["result_type"] == "project_config_updated"
    assert payload["result"]["value"] == 3

    get_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "config",
            "get",
            "prompt_profiles.planning.max_required_questions",
        ],
    )
    assert get_result.exit_code == 0, get_result.stdout
    assert _json(get_result)["result"]["value"] == 3


def test_config_set_parses_bare_string_value(tmp_path: Path) -> None:
    _init_project(tmp_path)

    set_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "config",
            "set",
            "prompt_profiles.planning.question_policy",
            "always_before_plan",
        ],
    )
    assert set_result.exit_code == 0, set_result.stdout

    get_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "config",
            "get",
            "prompt_profiles.planning.question_policy",
        ],
    )
    assert get_result.exit_code == 0, get_result.stdout
    assert _json(get_result)["result"]["value"] == "always_before_plan"


def test_config_set_rejects_invalid_values_with_json_error(tmp_path: Path) -> None:
    _init_project(tmp_path)

    first_set = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "config",
            "set",
            "prompt_profiles.planning.max_required_questions",
            "3",
        ],
    )
    assert first_set.exit_code == 0, first_set.stdout

    invalid_set = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "config",
            "set",
            "prompt_profiles.planning.max_required_questions",
            "0",
        ],
    )
    assert invalid_set.exit_code == 1
    error_payload = _json(invalid_set)
    assert error_payload["ok"] is False
    assert "must be positive" in error_payload["error"]["message"]

    get_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "config",
            "get",
            "prompt_profiles.planning.max_required_questions",
        ],
    )
    assert get_result.exit_code == 0, get_result.stdout
    assert _json(get_result)["result"]["value"] == 3


def test_config_get_missing_key_returns_error(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "config", "get", "does.not.exist"],
    )
    assert result.exit_code == 1
    payload = _json(result)
    assert payload["ok"] is False
    assert "Config key not found" in payload["error"]["message"]


def test_config_set_rejects_reserved_keys(tmp_path: Path) -> None:
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "config", "set", "taskledger_dir", "other"],
    )
    assert result.exit_code == 1
    payload = _json(result)
    assert payload["ok"] is False
    assert "cannot edit taskledger_dir" in payload["error"]["message"]


def test_config_set_handles_inline_section_comments(tmp_path: Path) -> None:
    _init_project(tmp_path)
    config_path = tmp_path / "taskledger.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[prompt_profiles.planning] # keep note\nmax_required_questions = 5\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "config",
            "set",
            "prompt_profiles.planning.question_policy",
            "always_before_plan",
        ],
    )
    assert result.exit_code == 0, result.stdout

    updated = config_path.read_text(encoding="utf-8")
    assert "[prompt_profiles.planning] # keep note" in updated
    assert (
        len(
            re.findall(
                r"(?m)^\[prompt_profiles\.planning\](?:\s*#.*)?$",
                updated,
            )
        )
        == 1
    )

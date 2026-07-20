"""Tests for actor/harness storage, resolution priority, and CLI commands."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.models import ActiveActorState, ActiveHarnessState
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_actor, resolve_harness
from taskledger.storage.task_store import (
    clear_actor_state,
    clear_harness_state,
    load_actor_state,
    load_harness_state,
    resolve_v2_paths,
    save_actor_state,
    save_harness_state,
)

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0


# --- Storage layer tests ---


# specmason: req=REQ-0002 ac=AC-0036
def test_save_and_load_actor_state(tmp_path: Path) -> None:
    _init_project(tmp_path)
    state = ActiveActorState(
        actor_type="agent",
        actor_name="test-agent",
        role="implementer",
        tool="test-tool",
        session_id="sess-1",
    )
    save_actor_state(tmp_path, state)

    loaded = load_actor_state(tmp_path)
    assert loaded is not None
    assert loaded.actor_type == "agent"
    assert loaded.actor_name == "test-agent"
    assert loaded.role == "implementer"
    assert loaded.tool == "test-tool"
    assert loaded.session_id == "sess-1"


# specmason: req=REQ-0002 ac=AC-0011
def test_load_actor_state_missing(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert load_actor_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0011
def test_clear_actor_state(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_actor_state(tmp_path, ActiveActorState(actor_type="user", actor_name="bob"))
    cleared = clear_actor_state(tmp_path)
    assert cleared is not None
    assert cleared.actor_name == "bob"
    assert load_actor_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0011
def test_clear_actor_state_missing(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert clear_actor_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0037
def test_save_and_load_harness_state(tmp_path: Path) -> None:
    _init_project(tmp_path)
    state = ActiveHarnessState(
        name="test-harness",
        kind="agent_harness",
        session_id="sess-2",
    )
    save_harness_state(tmp_path, state)

    loaded = load_harness_state(tmp_path)
    assert loaded is not None
    assert loaded.name == "test-harness"
    assert loaded.kind == "agent_harness"
    assert loaded.session_id == "sess-2"


# specmason: req=REQ-0002 ac=AC-0012
def test_load_harness_state_missing(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert load_harness_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0012
def test_clear_harness_state(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_harness_state(tmp_path, ActiveHarnessState(name="my-harness"))
    cleared = clear_harness_state(tmp_path)
    assert cleared is not None
    assert cleared.name == "my-harness"
    assert load_harness_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0012
def test_clear_harness_state_missing(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert clear_harness_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0010
def test_actor_state_yaml_on_disk(tmp_path: Path) -> None:
    _init_project(tmp_path)
    state = ActiveActorState(actor_type="user", actor_name="alice", role="planner")
    save_actor_state(tmp_path, state)

    paths = resolve_v2_paths(tmp_path)
    actor_path = paths.actor_path
    assert actor_path.exists()
    data = yaml.safe_load(actor_path.read_text())
    assert data["object_type"] == "active_actor"
    assert data["actor_type"] == "user"
    assert data["actor_name"] == "alice"


# specmason: req=REQ-0002 ac=AC-0025
def test_harness_state_yaml_on_disk(tmp_path: Path) -> None:
    _init_project(tmp_path)
    state = ActiveHarnessState(name="ci-runner", kind="ci")
    save_harness_state(tmp_path, state)

    paths = resolve_v2_paths(tmp_path)
    harness_path = paths.harness_path
    assert harness_path.exists()
    data = yaml.safe_load(harness_path.read_text())
    assert data["object_type"] == "active_harness"
    assert data["name"] == "ci-runner"


# specmason: req=REQ-0002 ac=AC-0009
def test_actor_state_roundtrip(tmp_path: Path) -> None:
    _init_project(tmp_path)
    original = ActiveActorState(
        actor_type="agent",
        actor_name="bot",
        role="validator",
        tool="ci",
        session_id="s-1",
    )
    save_actor_state(tmp_path, original)
    loaded = load_actor_state(tmp_path)
    assert loaded == original


# specmason: req=REQ-0002 ac=AC-0024
def test_harness_state_roundtrip(tmp_path: Path) -> None:
    _init_project(tmp_path)
    original = ActiveHarnessState(
        name="harness-a",
        kind="manual",
        session_id="s-2",
    )
    save_harness_state(tmp_path, original)
    loaded = load_harness_state(tmp_path)
    assert loaded == original


# --- Resolution priority tests ---


# specmason: req=REQ-0002 ac=AC-0031
def test_resolve_actor_uses_stored_when_no_env_vars(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_actor_state(
        tmp_path,
        ActiveActorState(
            actor_type="user",
            actor_name="stored-user",
            role="reviewer",
        ),
    )

    actor = resolve_actor(workspace_root=tmp_path)
    assert actor.actor_name == "stored-user"
    assert actor.role == "reviewer"


# specmason: req=REQ-0002 ac=AC-0029
def test_resolve_actor_env_overrides_stored(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_actor_state(
        tmp_path,
        ActiveActorState(
            actor_type="user",
            actor_name="stored-user",
        ),
    )

    env = {
        "TASKLEDGER_ACTOR_TYPE": "system",
        "TASKLEDGER_ACTOR_NAME": "env-actor",
    }
    with _env_vars(env):
        actor = resolve_actor(workspace_root=tmp_path)
    assert actor.actor_name == "env-actor"
    assert actor.actor_type == "system"


# specmason: req=REQ-0002 ac=AC-0030
def test_resolve_actor_explicit_overrides_all(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_actor_state(
        tmp_path,
        ActiveActorState(
            actor_type="user",
            actor_name="stored-user",
        ),
    )

    env = {
        "TASKLEDGER_ACTOR_TYPE": "system",
        "TASKLEDGER_ACTOR_NAME": "env-actor",
    }
    with _env_vars(env):
        actor = resolve_actor(
            actor_type="agent",
            actor_name="explicit",
            workspace_root=tmp_path,
        )
    assert actor.actor_name == "explicit"
    assert actor.actor_type == "agent"


# specmason: req=REQ-0002 ac=AC-0029
def test_resolve_actor_no_workspace_no_stored() -> None:
    """Without workspace_root, stored state is not checked."""
    actor = resolve_actor()
    # Should not crash, falls through to auto-detect or default
    assert actor.actor_type in ("agent", "user", "system")


# specmason: req=REQ-0002 ac=AC-0035
def test_resolve_harness_uses_stored_when_no_env_vars(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_harness_state(
        tmp_path,
        ActiveHarnessState(
            name="stored-harness",
            kind="ci",
        ),
    )

    harness = resolve_harness(workspace_root=tmp_path)
    assert harness.name == "stored-harness"
    assert harness.kind == "ci"


# specmason: req=REQ-0002 ac=AC-0033
def test_resolve_harness_env_overrides_stored(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_harness_state(tmp_path, ActiveHarnessState(name="stored-harness"))

    env = {"TASKLEDGER_HARNESS": "env-harness"}
    with _env_vars(env):
        harness = resolve_harness(workspace_root=tmp_path)
    assert harness.name == "env-harness"


# specmason: req=REQ-0002 ac=AC-0034
def test_resolve_harness_explicit_overrides_all(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_harness_state(tmp_path, ActiveHarnessState(name="stored-harness"))

    env = {"TASKLEDGER_HARNESS": "env-harness"}
    with _env_vars(env):
        harness = resolve_harness(name="explicit", workspace_root=tmp_path)
    assert harness.name == "explicit"


# specmason: req=REQ-0002 ac=AC-0028
def test_resolve_actor_after_clear(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_actor_state(
        tmp_path,
        ActiveActorState(
            actor_type="user",
            actor_name="to-clear",
        ),
    )
    clear_actor_state(tmp_path)
    actor = resolve_actor(workspace_root=tmp_path)
    assert actor.actor_name != "to-clear"


# specmason: req=REQ-0002 ac=AC-0032
def test_resolve_harness_after_clear(tmp_path: Path) -> None:
    _init_project(tmp_path)
    save_harness_state(tmp_path, ActiveHarnessState(name="to-clear"))
    clear_harness_state(tmp_path)
    harness = resolve_harness(workspace_root=tmp_path)
    assert harness.name != "to-clear"


# --- CLI command tests ---


# specmason: req=REQ-0002 ac=AC-0016
# specmason: req=REQ-0002 ac=AC-0017
def test_cli_actor_set(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "actor",
            "set",
            "--type",
            "agent",
            "--name",
            "cli-agent",
            "--role",
            "implementer",
        ],
    )
    assert result.exit_code == 0
    assert "Actor set: agent:cli-agent" in result.output
    assert "Role: implementer" in result.output

    # Verify persisted
    state = load_actor_state(tmp_path)
    assert state is not None
    assert state.actor_name == "cli-agent"


# specmason: req=REQ-0002 ac=AC-0016
# specmason: req=REQ-0002 ac=AC-0017
def test_cli_actor_set_json(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--json",
            "--cwd",
            str(tmp_path),
            "actor",
            "set",
            "--type",
            "user",
            "--name",
            "json-user",
        ],
    )
    assert result.exit_code == 0
    assert '"actor_set"' in result.output
    assert '"json-user"' in result.output


# specmason: req=REQ-0002 ac=AC-0013
# specmason: req=REQ-0002 ac=AC-0014
# specmason: req=REQ-0002 ac=AC-0015
def test_cli_actor_clear(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "actor",
            "set",
            "--type",
            "agent",
            "--name",
            "will-clear",
        ],
    )
    result = runner.invoke(app, ["--cwd", str(tmp_path), "actor", "clear"])
    assert result.exit_code == 0
    assert "Actor cleared." in result.output
    assert load_actor_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0013
# specmason: req=REQ-0002 ac=AC-0014
def test_cli_actor_clear_empty(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(app, ["--cwd", str(tmp_path), "actor", "clear"])
    assert result.exit_code == 0
    assert "No stored actor to clear." in result.output


# specmason: req=REQ-0002 ac=AC-0013
# specmason: req=REQ-0002 ac=AC-0015
def test_cli_actor_clear_json(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "actor",
            "set",
            "--type",
            "agent",
            "--name",
            "will-clear",
        ],
    )
    result = runner.invoke(
        app,
        [
            "--json",
            "--cwd",
            str(tmp_path),
            "actor",
            "clear",
        ],
    )
    assert result.exit_code == 0
    assert '"actor_clear"' in result.output


# specmason: req=REQ-0002 ac=AC-0020
# specmason: req=REQ-0002 ac=AC-0021
def test_cli_harness_set(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "harness",
            "set",
            "--name",
            "cli-harness",
            "--kind",
            "agent_harness",
        ],
    )
    assert result.exit_code == 0
    assert "Harness set: cli-harness (agent_harness)" in result.output

    state = load_harness_state(tmp_path)
    assert state is not None
    assert state.name == "cli-harness"


# specmason: req=REQ-0002 ac=AC-0020
# specmason: req=REQ-0002 ac=AC-0021
def test_cli_harness_set_json(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "--json",
            "--cwd",
            str(tmp_path),
            "harness",
            "set",
            "--name",
            "json-harness",
        ],
    )
    assert result.exit_code == 0
    assert '"harness_set"' in result.output
    assert '"json-harness"' in result.output


# specmason: req=REQ-0002 ac=AC-0018
# specmason: req=REQ-0002 ac=AC-0019
def test_cli_harness_clear(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "harness",
            "set",
            "--name",
            "will-clear",
        ],
    )
    result = runner.invoke(app, ["--cwd", str(tmp_path), "harness", "clear"])
    assert result.exit_code == 0
    assert "Harness cleared." in result.output
    assert load_harness_state(tmp_path) is None


# specmason: req=REQ-0002 ac=AC-0018
# specmason: req=REQ-0002 ac=AC-0019
def test_cli_harness_clear_empty(tmp_path: Path) -> None:
    _init_project(tmp_path)
    result = runner.invoke(app, ["--cwd", str(tmp_path), "harness", "clear"])
    assert result.exit_code == 0
    assert "No stored harness to clear." in result.output


# specmason: req=REQ-0002 ac=AC-0023
def test_cli_whoami_uses_stored(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "actor",
            "set",
            "--type",
            "agent",
            "--name",
            "stored-whoami",
        ],
    )
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "harness",
            "set",
            "--name",
            "stored-harness-whoami",
        ],
    )

    result = runner.invoke(app, ["--cwd", str(tmp_path), "actor", "whoami"])
    assert result.exit_code == 0
    assert "stored-whoami" in result.output
    assert "stored-harness-whoami" in result.output


# specmason: req=REQ-0002 ac=AC-0022
def test_cli_whoami_json_uses_stored(tmp_path: Path) -> None:
    _init_project(tmp_path)
    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "actor",
            "set",
            "--type",
            "agent",
            "--name",
            "json-whoami",
        ],
    )

    result = runner.invoke(
        app,
        [
            "--json",
            "--cwd",
            str(tmp_path),
            "actor",
            "whoami",
        ],
    )
    assert result.exit_code == 0
    assert '"json-whoami"' in result.output


# --- Model serialization tests ---


# specmason: req=REQ-0002 ac=AC-0009
# specmason: req=REQ-0002 ac=AC-0026
# specmason: req=REQ-0002 ac=AC-0027
def test_active_actor_state_from_dict_rejects_bad_type() -> None:
    import pytest

    with pytest.raises(LaunchError):
        ActiveActorState.from_dict({"object_type": "wrong", "schema_version": 1})


# specmason: req=REQ-0002 ac=AC-0024
def test_active_harness_state_from_dict_rejects_bad_type() -> None:
    import pytest

    with pytest.raises(LaunchError):
        ActiveHarnessState.from_dict({"object_type": "wrong", "schema_version": 1})


# --- Helpers ---


class _env_vars:
    """Context manager to temporarily set environment variables."""

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self._old: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for k, v in self.env.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, *args: object) -> None:
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

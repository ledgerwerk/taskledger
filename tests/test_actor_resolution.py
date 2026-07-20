"""Tests for actor resolution with PID scope and harness context."""

from __future__ import annotations

import os

import pytest

from taskledger.domain.actor import ActorRef
from taskledger.services.actors import resolve_actor


class TestActorRefPidScope:
    # specmason: req=REQ-0003 ac=AC-0049
    def test_round_trip_command_pid_and_pid_scope(self) -> None:
        a = ActorRef(
            actor_type="agent",
            actor_name="pi",
            tool="pi",
            session_id="s1",
            pid=None,
            command_pid=123,
            pid_scope="unverifiable_harness",
        )
        d = a.to_dict()
        b = ActorRef.from_dict(d)
        assert b.pid is None
        assert b.command_pid == 123
        assert b.pid_scope == "unverifiable_harness"

    # specmason: req=REQ-0003 ac=AC-0050
    def test_round_trip_owner_pid_scope(self) -> None:
        a = ActorRef(
            pid=99999,
            command_pid=123,
            pid_scope="owner",
        )
        d = a.to_dict()
        b = ActorRef.from_dict(d)
        assert b.pid == 99999
        assert b.command_pid == 123
        assert b.pid_scope == "owner"

    # specmason: req=REQ-0003 ac=AC-0044
    def test_missing_pid_scope_is_none(self) -> None:
        a = ActorRef(pid=123)
        d = a.to_dict()
        # Simulate old record without pid_scope field.
        del d["pid_scope"]
        del d["command_pid"]
        b = ActorRef.from_dict(d)
        assert b.pid == 123
        assert b.pid_scope is None
        assert b.command_pid is None

    # specmason: req=REQ-0003 ac=AC-0043
    def test_invalid_pid_scope_is_ignored(self) -> None:
        d = ActorRef(pid=123).to_dict()
        d["pid_scope"] = "invalid_value"
        b = ActorRef.from_dict(d)
        assert b.pid_scope is None


class TestResolveActorHarnessContext:
    # specmason: req=REQ-0003 ac=AC-0048
    def test_pi_context_without_owner_pid_stores_none_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PI_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_SESSION_ID", "pi-session-1")

        actor = resolve_actor()

        assert actor.actor_name == "pi"
        assert actor.tool == "pi"
        assert actor.session_id == "pi-session-1"
        assert actor.pid is None
        assert actor.command_pid == os.getpid()
        assert actor.pid_scope == "unverifiable_harness"

    # specmason: req=REQ-0003 ac=AC-0047
    def test_pi_context_with_owner_pid_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PI_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_SESSION_ID", "pi-session-1")
        monkeypatch.setenv("TASKLEDGER_OWNER_PID", "12345")

        actor = resolve_actor()

        assert actor.pid == 12345
        assert actor.command_pid == os.getpid()
        assert actor.pid_scope == "owner"

    # specmason: req=REQ-0003 ac=AC-0041
    def test_harness_pid_alias_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PI_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_HARNESS_PID", "54321")

        actor = resolve_actor()

        assert actor.pid == 54321
        assert actor.pid_scope == "owner"

    # specmason: req=REQ-0003 ac=AC-0046
    def test_owner_pid_takes_priority_over_harness_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PI_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_OWNER_PID", "111")
        monkeypatch.setenv("TASKLEDGER_HARNESS_PID", "222")

        actor = resolve_actor()

        assert actor.pid == 111

    # specmason: req=REQ-0003 ac=AC-0038
    def test_codex_context_without_owner_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_SESSION_ID", "codex-s1")

        actor = resolve_actor()

        assert actor.actor_name == "codex"
        assert actor.tool == "codex"
        assert actor.pid is None
        assert actor.pid_scope == "unverifiable_harness"

    # specmason: req=REQ-0003 ac=AC-0045
    def test_opencode_context_without_owner_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENCODE_VERSION", "1")

        actor = resolve_actor()

        assert actor.actor_name == "opencode"
        assert actor.pid is None
        assert actor.pid_scope == "unverifiable_harness"

    # specmason: req=REQ-0003 ac=AC-0040
    def test_env_actor_with_harness_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TASKLEDGER_ACTOR_TYPE", "agent")
        monkeypatch.setenv("TASKLEDGER_ACTOR_NAME", "my-agent")
        monkeypatch.setenv("TASKLEDGER_SESSION_ID", "session-1")

        actor = resolve_actor()

        assert actor.actor_name == "my-agent"
        assert actor.pid is None
        assert actor.command_pid == os.getpid()
        assert actor.pid_scope == "unverifiable_harness"

    # specmason: req=REQ-0003 ac=AC-0039
    def test_default_agent_gets_command_pid_as_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Clear all harness env vars.
        for var in [
            "PI_VERSION",
            "CODEX_VERSION",
            "OPENCODE_VERSION",
            "TASKLEDGER_SESSION_ID",
            "TASKLEDGER_HARNESS",
            "TASKLEDGER_ACTOR_TYPE",
            "TASKLEDGER_ACTOR_NAME",
            "GITHUB_ACTIONS",
            "GITHUB_RUN_ID",
        ]:
            monkeypatch.delenv(var, raising=False)

        actor = resolve_actor()

        assert actor.pid == os.getpid()
        assert actor.pid_scope == "owner"

    # specmason: req=REQ-0003 ac=AC-0042
    def test_invalid_owner_pid_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PI_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_OWNER_PID", "not-a-number")

        actor = resolve_actor()

        assert actor.pid is None
        assert actor.pid_scope == "unverifiable_harness"

    # specmason: req=REQ-0003 ac=AC-0051
    def test_zero_owner_pid_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PI_VERSION", "1")
        monkeypatch.setenv("TASKLEDGER_OWNER_PID", "0")

        actor = resolve_actor()

        assert actor.pid is None
        assert actor.pid_scope == "unverifiable_harness"

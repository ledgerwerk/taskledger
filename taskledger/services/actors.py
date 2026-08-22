"""Actor and harness identity resolution."""

from __future__ import annotations

import getpass
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from taskledger.domain.models import (
    ActiveActorState,
    ActiveHarnessState,
    ActorRef,
    HarnessRef,
)
from taskledger.domain.states import (
    normalize_actor_role,
    normalize_actor_type,
    normalize_harness_kind,
)
from taskledger.ids import next_project_id
from taskledger.storage.task_store import load_actor_state, load_harness_state


def _int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _owner_pid_from_env() -> int | None:
    return _int_env("TASKLEDGER_OWNER_PID") or _int_env("TASKLEDGER_HARNESS_PID")


def _is_harness_context(*, session_id: str | None, harness_id: str | None) -> bool:
    return bool(
        session_id
        or harness_id
        or os.getenv("TASKLEDGER_HARNESS")
        or os.getenv("PI_VERSION")
        or os.getenv("CODEX_VERSION")
        or os.getenv("OPENCODE_VERSION")
    )


def _resolve_pids(
    *,
    tool: str | None,
    session_id: str | None,
    harness_id: str | None,
) -> tuple[int | None, int | None, Literal["owner", "command", "unverifiable_harness"]]:
    """Return (pid, command_pid, pid_scope) based on context."""
    command_pid = os.getpid()
    owner_pid = _owner_pid_from_env()
    harness_context = _is_harness_context(session_id=session_id, harness_id=harness_id)
    if owner_pid is not None:
        return owner_pid, command_pid, "owner"
    if harness_context:
        return None, command_pid, "unverifiable_harness"
    return command_pid, command_pid, "owner"


@dataclass(frozen=True, slots=True)
class DetectedHarness:
    """Live harness identity detected from the current process environment."""

    name: str
    kind: Literal["agent_harness", "manual", "ci", "unknown"]
    session_id: str | None = None


def detect_live_harness() -> DetectedHarness | None:
    """Detect a provider harness without consulting persisted project state."""
    taskledger_harness = os.getenv("TASKLEDGER_HARNESS")
    if taskledger_harness:
        return DetectedHarness(
            name=taskledger_harness,
            kind="agent_harness",
            session_id=os.getenv("TASKLEDGER_SESSION_ID"),
        )
    if os.getenv("OPENCODE_VERSION"):
        return DetectedHarness(
            "opencode", "agent_harness", os.getenv("TASKLEDGER_SESSION_ID")
        )
    if os.getenv("CODEX_VERSION"):
        return DetectedHarness(
            "codex", "agent_harness", os.getenv("TASKLEDGER_SESSION_ID")
        )
    if os.getenv("PI_VERSION"):
        return DetectedHarness(
            "pi",
            "agent_harness",
            os.getenv("PI_SESSION_ID") or os.getenv("TASKLEDGER_SESSION_ID"),
        )
    if os.getenv("GITHUB_ACTIONS") == "true":
        return DetectedHarness("github-actions", "ci", os.getenv("GITHUB_RUN_ID"))
    return None


def _stored_harness_compatible(
    stored: HarnessRef | ActiveHarnessState, detected: DetectedHarness
) -> bool:
    if stored.name != detected.name:
        return False
    return not (
        stored.session_id
        and detected.session_id
        and stored.session_id != detected.session_id
    )


def _stored_actor_compatible(
    stored: ActorRef | ActiveActorState, detected: DetectedHarness
) -> bool:
    known_tools = {"codex", "opencode", "pi", "github-actions"}
    stored_tool = stored.tool or (
        stored.actor_name if stored.actor_name in known_tools else None
    )
    if stored_tool and stored_tool != detected.name:
        return False
    return not (
        stored.session_id
        and detected.session_id
        and stored.session_id != detected.session_id
    )


def resolve_effective_identity(
    workspace_root: Path,
    *,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
    cwd: Path | None = None,
    role: str | None = None,
) -> tuple[ActorRef, HarnessRef]:
    """Resolve actor and harness together for a workspace-scoped mutation."""
    resolved_harness = harness or resolve_harness(
        session_id=actor.session_id if actor else None,
        cwd=cwd or workspace_root,
        workspace_root=workspace_root,
    )
    resolved_actor = actor or resolve_actor(
        role=role,
        session_id=resolved_harness.session_id,
        harness_id=resolved_harness.harness_id,
        workspace_root=workspace_root,
    )
    return resolved_actor, resolved_harness


def resolve_actor(
    *,
    actor_type: str | None = None,
    actor_name: str | None = None,
    role: str | None = None,
    tool: str | None = None,
    session_id: str | None = None,
    harness_id: str | None = None,
    workspace_root: Path | None = None,
) -> ActorRef:
    """
    Resolve actor identity with fallback order:
    1. Explicit parameters
    2. Environment variables
    3. Stored state (actor.yaml)
    4. Auto-detect from environment
    5. Safe default
    """

    # 1. Use explicit params if provided
    if actor_type and actor_name:
        pid, command_pid, pid_scope = _resolve_pids(
            tool=tool,
            session_id=session_id,
            harness_id=harness_id,
        )
        return ActorRef(
            actor_type=normalize_actor_type(actor_type),
            actor_name=actor_name,
            role=normalize_actor_role(role) if role else None,
            tool=tool,
            session_id=session_id,
            harness_id=harness_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    # 2. Check environment variables
    env_actor_type = os.getenv("TASKLEDGER_ACTOR_TYPE")
    env_actor_name = os.getenv("TASKLEDGER_ACTOR_NAME")
    env_role = os.getenv("TASKLEDGER_ACTOR_ROLE")
    env_harness = os.getenv("TASKLEDGER_HARNESS")
    env_session_id = os.getenv("TASKLEDGER_SESSION_ID")
    resolved_role = env_role or role

    if env_actor_type or env_actor_name:
        resolved_session_id = env_session_id or session_id
        resolved_harness_id = harness_id or env_harness
        pid, command_pid, pid_scope = _resolve_pids(
            tool=tool,
            session_id=resolved_session_id,
            harness_id=resolved_harness_id,
        )
        return ActorRef(
            actor_type=normalize_actor_type(env_actor_type or actor_type or "agent"),
            actor_name=env_actor_name or actor_name or "taskledger",
            role=normalize_actor_role(resolved_role) if resolved_role else None,
            tool=tool,
            session_id=resolved_session_id,
            harness_id=resolved_harness_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    # 3. Prefer a live provider identity over incompatible persisted state.
    detected = detect_live_harness()
    if workspace_root is not None:
        stored = load_actor_state(workspace_root)
        if stored is not None and (
            detected is None or _stored_actor_compatible(stored, detected)
        ):
            resolved_session_id = (
                stored.session_id
                or session_id
                or (detected.session_id if detected else None)
            )
            resolved_tool = stored.tool or tool
            pid, command_pid, pid_scope = _resolve_pids(
                tool=resolved_tool,
                session_id=resolved_session_id,
                harness_id=harness_id,
            )
            return ActorRef(
                actor_type=stored.actor_type,
                actor_name=stored.actor_name,
                role=stored.role,
                tool=resolved_tool,
                session_id=resolved_session_id,
                harness_id=harness_id,
                host=socket.gethostname(),
                pid=pid,
                command_pid=command_pid,
                pid_scope=pid_scope,
            )

    # 4. Auto-detect from environment
    if os.getenv("OPENCODE_VERSION"):
        resolved_session_id = session_id or os.getenv("TASKLEDGER_SESSION_ID")
        pid, command_pid, pid_scope = _resolve_pids(
            tool="opencode",
            session_id=resolved_session_id,
            harness_id=harness_id,
        )
        return ActorRef(
            actor_type="agent",
            actor_name="opencode",
            tool="opencode",
            session_id=resolved_session_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    if os.getenv("CODEX_VERSION"):
        resolved_session_id = session_id or os.getenv("TASKLEDGER_SESSION_ID")
        pid, command_pid, pid_scope = _resolve_pids(
            tool="codex",
            session_id=resolved_session_id,
            harness_id=harness_id,
        )
        return ActorRef(
            actor_type="agent",
            actor_name="codex",
            tool="codex",
            session_id=resolved_session_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    if os.getenv("PI_VERSION"):
        resolved_session_id = (
            session_id
            or os.getenv("PI_SESSION_ID")
            or os.getenv("TASKLEDGER_SESSION_ID")
        )
        pid, command_pid, pid_scope = _resolve_pids(
            tool="pi",
            session_id=resolved_session_id,
            harness_id=harness_id,
        )
        return ActorRef(
            actor_type="agent",
            actor_name="pi",
            tool="pi",
            session_id=resolved_session_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    if os.getenv("GITHUB_ACTIONS") == "true":
        resolved_session_id = session_id or os.getenv("GITHUB_RUN_ID")
        pid, command_pid, pid_scope = _resolve_pids(
            tool="github-actions",
            session_id=resolved_session_id,
            harness_id=harness_id,
        )
        return ActorRef(
            actor_type="system",
            actor_name="github-actions",
            tool="github-actions",
            session_id=resolved_session_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    if sys.stdin.isatty() and not any(
        [
            os.getenv("OPENCODE_VERSION"),
            os.getenv("CODEX_VERSION"),
            os.getenv("PI_VERSION"),
            os.getenv("GITHUB_ACTIONS"),
        ]
    ):
        pid, command_pid, pid_scope = _resolve_pids(
            tool=None,
            session_id=session_id,
            harness_id=harness_id,
        )
        return ActorRef(
            actor_type="user",
            actor_name=getpass.getuser() or "user",
            session_id=session_id,
            host=socket.gethostname(),
            pid=pid,
            command_pid=command_pid,
            pid_scope=pid_scope,
        )

    # 5. Safe default
    pid, command_pid, pid_scope = _resolve_pids(
        tool=tool,
        session_id=session_id,
        harness_id=harness_id,
    )
    return ActorRef(
        actor_type="agent",
        actor_name="taskledger",
        tool=tool,
        session_id=session_id,
        host=socket.gethostname(),
        pid=pid,
        command_pid=command_pid,
        pid_scope=pid_scope,
    )


def resolve_harness(
    *,
    name: str | None = None,
    kind: str | None = None,
    session_id: str | None = None,
    cwd: Path | None = None,
    workspace_root: Path | None = None,
) -> HarnessRef:
    """
    Resolve harness identity with fallback order:
    1. Explicit parameters
    2. Environment variables
    3. Stored state (harness.yaml)
    4. Auto-detect from environment
    5. Safe default
    """

    # Use explicit params if provided
    if name:
        harness_id = next_project_id("harness", [])
        return HarnessRef(
            harness_id=harness_id,
            name=name,
            kind=normalize_harness_kind(kind or "unknown"),
            session_id=session_id,
            working_directory=str(cwd) if cwd else None,
        )

    # Check environment
    env_harness = os.getenv("TASKLEDGER_HARNESS")
    if env_harness:
        harness_id = next_project_id("harness", [])
        return HarnessRef(
            harness_id=harness_id,
            name=env_harness,
            kind=normalize_harness_kind(kind or "unknown"),
            session_id=session_id or os.getenv("TASKLEDGER_SESSION_ID"),
            working_directory=str(cwd) if cwd else None,
        )

    detected = detect_live_harness()

    # Check stored state when it is compatible with the current live session.
    if workspace_root is not None:
        stored = load_harness_state(workspace_root)
        if stored is not None and (
            detected is None or _stored_harness_compatible(stored, detected)
        ):
            harness_id = next_project_id("harness", [])
            return HarnessRef(
                harness_id=harness_id,
                name=stored.name,
                kind=stored.kind,
                session_id=stored.session_id
                or session_id
                or (detected.session_id if detected else None),
                working_directory=str(cwd) if cwd else None,
            )

    # Auto-detect
    if os.getenv("PI_VERSION"):
        harness_id = next_project_id("harness", [])
        return HarnessRef(
            harness_id=harness_id,
            name="pi",
            kind="agent_harness",
            session_id=session_id
            or os.getenv("PI_SESSION_ID")
            or os.getenv("TASKLEDGER_SESSION_ID"),
            working_directory=str(cwd) if cwd else None,
        )

    if os.getenv("OPENCODE_VERSION"):
        harness_id = next_project_id("harness", [])
        return HarnessRef(
            harness_id=harness_id,
            name="opencode",
            kind="agent_harness",
            session_id=session_id or os.getenv("TASKLEDGER_SESSION_ID"),
        )

    if os.getenv("CODEX_VERSION"):
        harness_id = next_project_id("harness", [])
        return HarnessRef(
            harness_id=harness_id,
            name="codex",
            kind="agent_harness",
            session_id=session_id or os.getenv("TASKLEDGER_SESSION_ID"),
        )

    if os.getenv("GITHUB_ACTIONS") == "true":
        harness_id = next_project_id("harness", [])
        return HarnessRef(
            harness_id=harness_id,
            name="github-actions",
            kind="ci",
            session_id=session_id or os.getenv("GITHUB_RUN_ID"),
        )

    # Default
    harness_id = next_project_id("harness", [])
    return HarnessRef(
        harness_id=harness_id,
        name="unknown",
        kind="unknown",
        session_id=session_id,
        working_directory=str(cwd) if cwd else None,
    )

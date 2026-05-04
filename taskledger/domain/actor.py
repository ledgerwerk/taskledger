from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from taskledger.domain._model_utils import (
    _int_value,
    _optional_list_string,
    _optional_string,
    _require_contract,
    _string_value,
)
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    normalize_actor_role,
    normalize_actor_type,
    normalize_harness_kind,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class ActorRef:
    actor_type: Literal["agent", "user", "system"] = "agent"
    actor_name: str = "taskledger"
    tool: str | None = None
    session_id: str | None = None
    host: str | None = None
    pid: int | None = None
    actor_id: str | None = None
    role: (
        Literal["planner", "implementer", "validator", "reviewer", "operator"] | None
    ) = None
    harness_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "actor_type": self.actor_type,
            "actor_name": self.actor_name,
            "tool": self.tool,
            "session_id": self.session_id,
            "host": self.host,
            "pid": self.pid,
            "actor_id": self.actor_id,
            "role": self.role,
            "harness_id": self.harness_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> ActorRef:
        if not isinstance(data, dict):
            return cls()
        raw_actor_type = _optional_string(data.get("actor_type")) or "agent"
        actor_type = normalize_actor_type(raw_actor_type)
        pid = data.get("pid")
        raw_role = _optional_string(data.get("role"))
        role = normalize_actor_role(raw_role) if raw_role else None
        return cls(
            actor_type=actor_type,
            actor_name=_optional_string(data.get("actor_name")) or "taskledger",
            tool=_optional_string(data.get("tool")),
            session_id=_optional_string(data.get("session_id")),
            host=_optional_string(data.get("host")),
            pid=pid if isinstance(pid, int) else None,
            actor_id=_optional_string(data.get("actor_id")),
            role=role,
            harness_id=_optional_string(data.get("harness_id")),
        )


@dataclass(slots=True, frozen=True)
class HarnessRef:
    harness_id: str
    name: str
    kind: Literal["agent_harness", "manual", "ci", "unknown"] = "unknown"
    session_id: str | None = None
    working_directory: str | None = None
    command: str | None = None
    version: str | None = None
    capabilities: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now_iso)
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "harness"

    def to_dict(self) -> dict[str, object]:
        return {
            "harness_id": self.harness_id,
            "name": self.name,
            "kind": self.kind,
            "session_id": self.session_id,
            "working_directory": self.working_directory,
            "command": self.command,
            "version": self.version,
            "capabilities": self.capabilities,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
        }

    @classmethod
    def from_dict(cls, data: object) -> HarnessRef:
        if not isinstance(data, dict):
            raise LaunchError("Invalid harness data: expected mapping")
        _require_contract(data, expected_object_type="harness")
        return cls(
            harness_id=_string_value(data, "harness_id"),
            name=_string_value(data, "name"),
            kind=normalize_harness_kind(
                _optional_string(data.get("kind")) or "unknown"
            ),
            session_id=_optional_string(data.get("session_id")),
            working_directory=_optional_string(data.get("working_directory")),
            command=_optional_string(data.get("command")),
            version=_optional_string(data.get("version")),
            capabilities=tuple(_optional_list_string(data.get("capabilities")) or []),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            schema_version=_int_value(data, "schema_version"),
        )

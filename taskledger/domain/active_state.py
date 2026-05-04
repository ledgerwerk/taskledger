from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from taskledger.domain._model_utils import (
    _int_value,
    _optional_string,
    _require_contract,
    _string_value,
)
from taskledger.domain.actor import ActorRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    normalize_actor_role,
    normalize_actor_type,
    normalize_harness_kind,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class ActiveTaskState:
    task_id: str
    activated_at: str = field(default_factory=utc_now_iso)
    activated_by: ActorRef = field(default_factory=ActorRef)
    reason: str | None = None
    previous_task_id: str | None = None
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "active_task"
    file_version: str = TASKLEDGER_V2_FILE_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "task_id": self.task_id,
            "activated_at": self.activated_at,
            "activated_by": self.activated_by.to_dict(),
            "reason": self.reason,
            "previous_task_id": self.previous_task_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> ActiveTaskState:
        if not isinstance(data, dict):
            raise LaunchError("Invalid active task state: expected mapping.")
        _require_contract(data, expected_object_type="active_task")
        return cls(
            task_id=_string_value(data, "task_id"),
            activated_at=_optional_string(data.get("activated_at")) or utc_now_iso(),
            activated_by=ActorRef.from_dict(data.get("activated_by")),
            reason=_optional_string(data.get("reason")),
            previous_task_id=_optional_string(data.get("previous_task_id")),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
        )


@dataclass(slots=True, frozen=True)
class ActiveActorState:
    actor_type: Literal["agent", "user", "system"] = "agent"
    actor_name: str = "taskledger"
    role: (
        Literal["planner", "implementer", "validator", "reviewer", "operator"] | None
    ) = None
    tool: str | None = None
    session_id: str | None = None
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "active_actor"
    file_version: str = TASKLEDGER_V2_FILE_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "actor_type": self.actor_type,
            "actor_name": self.actor_name,
            "role": self.role,
            "tool": self.tool,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> ActiveActorState:
        if not isinstance(data, dict):
            raise LaunchError("Invalid active actor state: expected mapping.")
        _require_contract(data, expected_object_type="active_actor")
        raw_role = _optional_string(data.get("role"))
        return cls(
            actor_type=normalize_actor_type(
                _optional_string(data.get("actor_type")) or "agent"
            ),
            actor_name=_optional_string(data.get("actor_name")) or "taskledger",
            role=normalize_actor_role(raw_role) if raw_role else None,
            tool=_optional_string(data.get("tool")),
            session_id=_optional_string(data.get("session_id")),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
        )


@dataclass(slots=True, frozen=True)
class ActiveHarnessState:
    name: str = "unknown"
    kind: Literal["agent_harness", "manual", "ci", "unknown"] = "unknown"
    session_id: str | None = None
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "active_harness"
    file_version: str = TASKLEDGER_V2_FILE_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "name": self.name,
            "kind": self.kind,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> ActiveHarnessState:
        if not isinstance(data, dict):
            raise LaunchError("Invalid active harness state: expected mapping.")
        _require_contract(data, expected_object_type="active_harness")
        raw_kind = _optional_string(data.get("kind"))
        return cls(
            name=_optional_string(data.get("name")) or "unknown",
            kind=normalize_harness_kind(raw_kind) if raw_kind else "unknown",
            session_id=_optional_string(data.get("session_id")),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
        )

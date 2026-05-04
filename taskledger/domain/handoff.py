from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from taskledger.domain._model_utils import (
    _int_value,
    _optional_string,
    _require_contract,
    _string_value,
)
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    ContextFor,
    ContextFormat,
    ContextScope,
    normalize_actor_type,
    normalize_context_for,
    normalize_context_format,
    normalize_context_scope,
    normalize_handoff_mode,
    normalize_handoff_status,
    normalize_lock_policy,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class TaskHandoffRecord:
    handoff_id: str
    task_id: str
    mode: Literal["planning", "implementation", "validation", "review", "full"]
    context_for: ContextFor | None = field(default=None)
    scope: ContextScope = field(default="task")
    todo_id: str | None = field(default=None)
    focus_run_id: str | None = field(default=None)
    context_format: ContextFormat = field(default="markdown")
    context_hash: str | None = field(default=None)
    generated_at: str | None = field(default=None)

    status: Literal["open", "claimed", "closed", "cancelled"] = field(default="open")
    lock_policy: Literal["none", "retain", "release", "transfer"] = field(
        default="none"
    )
    context_body: str = field(default="")
    file_version: str = field(default=TASKLEDGER_V2_FILE_VERSION)
    schema_version: int = field(default=TASKLEDGER_SCHEMA_VERSION)
    object_type: str = field(default="handoff")

    created_from_harness: HarnessRef | None = field(default=None)
    intended_actor_type: Literal["agent", "user", "system"] | None = field(default=None)
    intended_actor_name: str | None = field(default=None)
    intended_harness: str | None = field(default=None)
    source_run_id: str | None = field(default=None)
    resumes_run_id: str | None = field(default=None)
    claim_run_id: str | None = field(default=None)
    released_lock_id: str | None = field(default=None)
    claimed_at: str | None = field(default=None)
    claimed_by: ActorRef | None = field(default=None)
    claimed_in_harness: HarnessRef | None = field(default=None)
    summary: str | None = field(default=None)
    next_action: str | None = field(default=None)

    created_at: str = field(default_factory=utc_now_iso)
    created_by: ActorRef = field(default_factory=ActorRef)

    def to_dict(self) -> dict[str, object]:
        return {
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "mode": self.mode,
            "context_for": self.context_for,
            "scope": self.scope,
            "todo_id": self.todo_id,
            "focus_run_id": self.focus_run_id,
            "context_format": self.context_format,
            "context_hash": self.context_hash,
            "generated_at": self.generated_at,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by.to_dict(),
            "created_from_harness": self.created_from_harness.to_dict()
            if self.created_from_harness
            else None,
            "intended_actor_type": self.intended_actor_type,
            "intended_actor_name": self.intended_actor_name,
            "intended_harness": self.intended_harness,
            "source_run_id": self.source_run_id,
            "resumes_run_id": self.resumes_run_id,
            "claim_run_id": self.claim_run_id,
            "lock_policy": self.lock_policy,
            "released_lock_id": self.released_lock_id,
            "claimed_at": self.claimed_at,
            "claimed_by": self.claimed_by.to_dict() if self.claimed_by else None,
            "claimed_in_harness": self.claimed_in_harness.to_dict()
            if self.claimed_in_harness
            else None,
            "summary": self.summary,
            "next_action": self.next_action,
            "context_body": self.context_body,
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
        }

    @classmethod
    def from_dict(cls, data: object) -> TaskHandoffRecord:
        if not isinstance(data, dict):
            raise LaunchError("Invalid handoff record: expected mapping")
        _require_contract(data, expected_object_type="handoff")
        return cls(
            handoff_id=_string_value(data, "handoff_id"),
            task_id=_string_value(data, "task_id"),
            mode=normalize_handoff_mode(_string_value(data, "mode")),
            context_for=(
                normalize_context_for(v)
                if (v := _optional_string(data.get("context_for")))
                else None
            ),
            scope=normalize_context_scope(
                _optional_string(data.get("scope")) or "task"
            ),
            todo_id=_optional_string(data.get("todo_id")),
            focus_run_id=_optional_string(data.get("focus_run_id")),
            context_format=normalize_context_format(
                _optional_string(data.get("context_format")) or "markdown"
            ),
            context_hash=_optional_string(data.get("context_hash")),
            generated_at=_optional_string(data.get("generated_at")),
            status=normalize_handoff_status(
                _optional_string(data.get("status")) or "open"
            ),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            created_by=ActorRef.from_dict(data.get("created_by")),
            created_from_harness=HarnessRef.from_dict(data.get("created_from_harness"))
            if data.get("created_from_harness")
            else None,
            intended_actor_type=(
                normalize_actor_type(v)
                if (v := _optional_string(data.get("intended_actor_type")))
                else None
            ),
            intended_actor_name=_optional_string(data.get("intended_actor_name")),
            intended_harness=_optional_string(data.get("intended_harness")),
            source_run_id=_optional_string(data.get("source_run_id")),
            resumes_run_id=_optional_string(data.get("resumes_run_id")),
            claim_run_id=_optional_string(data.get("claim_run_id")),
            lock_policy=normalize_lock_policy(
                _optional_string(data.get("lock_policy")) or "none"
            ),
            released_lock_id=_optional_string(data.get("released_lock_id")),
            claimed_at=_optional_string(data.get("claimed_at")),
            claimed_by=ActorRef.from_dict(data.get("claimed_by"))
            if data.get("claimed_by")
            else None,
            claimed_in_harness=HarnessRef.from_dict(data.get("claimed_in_harness"))
            if data.get("claimed_in_harness")
            else None,
            summary=_optional_string(data.get("summary")),
            next_action=_optional_string(data.get("next_action")),
            context_body=_optional_string(data.get("context_body")) or "",
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
        )

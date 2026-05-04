from __future__ import annotations

from dataclasses import dataclass, field

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
)
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class TaskEvent:
    ts: str
    event: str
    task_id: str
    actor: ActorRef
    harness: HarnessRef | None = None
    event_id: str = field(
        default_factory=lambda: (
            "evt-"
            + utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
        )
    )
    data: dict[str, object] = field(default_factory=dict)
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "event"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "event_id": self.event_id,
            "ts": self.ts,
            "event": self.event,
            "task_id": self.task_id,
            "actor": self.actor.to_dict(),
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TaskEvent:
        _require_contract(data, expected_object_type="event")
        payload = data.get("data")
        return cls(
            event_id=_string_value(data, "event_id"),
            ts=_string_value(data, "ts"),
            event=_string_value(data, "event"),
            task_id=_string_value(data, "task_id"),
            actor=ActorRef.from_dict(data.get("actor")),
            harness=HarnessRef.from_dict(data.get("harness"))
            if data.get("harness") is not None
            else None,
            data=payload if isinstance(payload, dict) else {},
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )

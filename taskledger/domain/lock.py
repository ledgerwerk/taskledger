from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from taskledger.domain._model_utils import (
    _int_value,
    _lock_stage_from_data,
    _optional_int,
    _optional_string,
    _require_contract,
    _string_value,
)
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    ActiveTaskStatusStage,
    RunType,
)
from taskledger.errors import LaunchError


@dataclass(slots=True, frozen=True)
class TaskLock:
    lock_id: str
    task_id: str
    stage: ActiveTaskStatusStage
    run_id: str
    created_at: str
    expires_at: str | None
    reason: str
    holder: ActorRef
    lease_seconds: int = 7200
    last_heartbeat_at: str | None = None
    broken_at: str | None = None
    broken_by: ActorRef | None = None
    broken_reason: str | None = None
    actor: ActorRef | None = None
    harness: HarnessRef | None = None
    transfer_history: tuple[tuple[str, str, str], ...] = ()
    transfer_date: str | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "lock"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "lock_id": self.lock_id,
            "task_id": self.task_id,
            "stage": self.stage,
            "run_type": self.run_type,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "lease_seconds": self.lease_seconds,
            "last_heartbeat_at": self.last_heartbeat_at,
            "reason": self.reason,
            "holder": self.holder.to_dict(),
            "broken_at": self.broken_at,
            "broken_by": (
                self.broken_by.to_dict() if self.broken_by is not None else None
            ),
            "broken_reason": self.broken_reason,
            "actor": self.actor.to_dict() if self.actor is not None else None,
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "transfer_history": [list(entry) for entry in self.transfer_history],
            "transfer_date": self.transfer_date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TaskLock:
        _require_contract(data, expected_object_type="lock")
        stage = _lock_stage_from_data(data)
        if stage not in {"planning", "implementing", "validating"}:
            raise LaunchError(f"Unsupported lock stage: {stage}")

        # Deserialize transfer_history
        transfer_history_data = data.get("transfer_history", [])
        transfer_history: tuple[tuple[str, str, str], ...] = ()
        if isinstance(transfer_history_data, list):
            for entry in transfer_history_data:
                if isinstance(entry, list | tuple) and len(entry) == 3:
                    transfer_history = transfer_history + (tuple(entry),)

        return cls(
            lock_id=_string_value(data, "lock_id"),
            task_id=_string_value(data, "task_id"),
            stage=cast(ActiveTaskStatusStage, stage),
            run_id=_string_value(data, "run_id"),
            created_at=_string_value(data, "created_at"),
            expires_at=_optional_string(data.get("expires_at")),
            reason=_string_value(data, "reason"),
            holder=ActorRef.from_dict(data.get("holder")),
            lease_seconds=_optional_int(data.get("lease_seconds")) or 7200,
            last_heartbeat_at=_optional_string(data.get("last_heartbeat_at")),
            broken_at=_optional_string(data.get("broken_at")),
            broken_by=ActorRef.from_dict(data.get("broken_by"))
            if data.get("broken_by") is not None
            else None,
            broken_reason=_optional_string(data.get("broken_reason")),
            actor=ActorRef.from_dict(data.get("actor"))
            if data.get("actor") is not None
            else None,
            harness=HarnessRef.from_dict(data.get("harness"))
            if data.get("harness") is not None
            else None,
            transfer_history=transfer_history,
            transfer_date=_optional_string(data.get("transfer_date")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )

    @property
    def run_type(self) -> RunType:
        return cast(
            RunType,
            {
                "planning": "planning",
                "implementing": "implementation",
                "validating": "validation",
            }[self.stage],
        )

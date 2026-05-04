from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain._model_utils import (
    _int_value,
    _optional_int,
    _optional_string,
    _require_contract,
    _string_value,
)
from taskledger.domain.actor import ActorRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
)
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class ReleaseRecord:
    version: str
    boundary_task_id: str
    created_at: str = field(default_factory=utc_now_iso)
    created_by: ActorRef = field(default_factory=ActorRef)
    note: str | None = None
    changelog_file: str | None = None
    task_count: int | None = None
    previous_version: str | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "release"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "version": self.version,
            "boundary_task_id": self.boundary_task_id,
            "created_at": self.created_at,
            "created_by": self.created_by.to_dict(),
            "note": self.note,
            "changelog_file": self.changelog_file,
            "task_count": self.task_count,
            "previous_version": self.previous_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReleaseRecord:
        _require_contract(data, expected_object_type="release")
        return cls(
            version=_string_value(data, "version"),
            boundary_task_id=_string_value(data, "boundary_task_id"),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            created_by=ActorRef.from_dict(data.get("created_by")),
            note=_optional_string(data.get("note")),
            changelog_file=_optional_string(data.get("changelog_file")),
            task_count=_optional_int(data.get("task_count")),
            previous_version=_optional_string(data.get("previous_version")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )

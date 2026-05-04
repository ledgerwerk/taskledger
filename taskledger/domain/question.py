from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain._model_utils import (
    _int_value,
    _optional_int,
    _optional_string,
    _require_contract,
    _string_value,
)
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    QuestionStatus,
    normalize_question_status,
)
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class QuestionRecord:
    id: str
    task_id: str
    question: str
    plan_version: int | None = None
    status: QuestionStatus = "open"
    created_at: str = field(default_factory=utc_now_iso)
    answered_at: str | None = None
    answered_by: str | None = None
    answered_by_actor: ActorRef | None = None
    asked_by_actor: ActorRef | None = None
    asked_in_harness: HarnessRef | None = None
    required_for_plan: bool = False
    answer_source: str | None = None
    answer: str | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "question"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "id": self.id,
            "task_id": self.task_id,
            "plan_version": self.plan_version,
            "status": self.status,
            "created_at": self.created_at,
            "answered_at": self.answered_at,
            "answered_by": self.answered_by,
            "answered_by_actor": (
                self.answered_by_actor.to_dict()
                if self.answered_by_actor is not None
                else None
            ),
            "asked_by_actor": (
                self.asked_by_actor.to_dict()
                if self.asked_by_actor is not None
                else None
            ),
            "asked_in_harness": (
                self.asked_in_harness.to_dict()
                if self.asked_in_harness is not None
                else None
            ),
            "required_for_plan": self.required_for_plan,
            "answer_source": self.answer_source,
            "question": self.question,
            "answer": self.answer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> QuestionRecord:
        _require_contract(data, expected_object_type="question")
        return cls(
            id=_string_value(data, "id"),
            task_id=_string_value(data, "task_id"),
            question=_string_value(data, "question"),
            plan_version=_optional_int(data.get("plan_version")),
            status=normalize_question_status(_string_value(data, "status")),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            answered_at=_optional_string(data.get("answered_at")),
            answered_by=_optional_string(data.get("answered_by")),
            answered_by_actor=ActorRef.from_dict(data.get("answered_by_actor"))
            if data.get("answered_by_actor") is not None
            else None,
            asked_by_actor=ActorRef.from_dict(data.get("asked_by_actor"))
            if data.get("asked_by_actor") is not None
            else None,
            asked_in_harness=HarnessRef.from_dict(data.get("asked_in_harness"))
            if data.get("asked_in_harness") is not None
            else None,
            required_for_plan=bool(data.get("required_for_plan", False)),
            answer_source=_optional_string(data.get("answer_source")),
            answer=_optional_string(data.get("answer")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )

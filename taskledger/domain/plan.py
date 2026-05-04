from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain._model_utils import (
    _dict_list,
    _int_value,
    _optional_int,
    _optional_string,
    _plan_id,
    _plan_version_from_id,
    _require_contract,
    _string_tuple,
    _string_value,
)
from taskledger.domain.actor import ActorRef
from taskledger.domain.sidecars import AcceptanceCriterion, TaskTodo
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    PlanStatus,
    normalize_plan_status,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class PlanRecord:
    task_id: str
    plan_version: int
    body: str
    status: PlanStatus = "proposed"
    created_at: str = field(default_factory=utc_now_iso)
    created_by: ActorRef = field(default_factory=ActorRef)
    supersedes: int | None = None
    question_refs: tuple[str, ...] = ()
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    criteria: tuple[AcceptanceCriterion, ...] = ()
    todos: tuple[TaskTodo, ...] = ()
    generation_reason: str | None = None
    based_on_question_ids: tuple[str, ...] = ()
    based_on_answer_hash: str | None = None
    approved_at: str | None = None
    approved_by: ActorRef | None = None
    approval_note: str | None = None
    approval_source: str | None = None
    approved_plan_hash: str | None = None
    goal: str | None = None
    files: tuple[str, ...] = ()
    test_commands: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    todos_waived_reason: str | None = None
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "plan"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "version": self.plan_version,
            "plan_version": self.plan_version,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by.to_dict(),
            "supersedes": self.supersedes,
            "question_refs": list(self.question_refs),
            "criteria": [item.to_dict() for item in self.criteria],
            "todos": [item.to_dict() for item in self.todos],
            "generation_reason": self.generation_reason,
            "based_on_question_ids": list(self.based_on_question_ids),
            "based_on_answer_hash": self.based_on_answer_hash,
            "supersedes_plan_id": (
                _plan_id(self.supersedes) if self.supersedes is not None else None
            ),
            "approved_at": self.approved_at,
            "approved_by": (
                self.approved_by.to_dict() if self.approved_by is not None else None
            ),
            "approval_note": self.approval_note,
            "approval_source": self.approval_source,
            "approved_plan_hash": self.approved_plan_hash,
            "body": self.body,
            "goal": self.goal,
            "files": list(self.files),
            "test_commands": list(self.test_commands),
            "expected_outputs": list(self.expected_outputs),
            "todos_waived_reason": self.todos_waived_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PlanRecord:
        _require_contract(data, expected_object_type="plan")
        plan_version = (
            _optional_int(data.get("plan_version"))
            or _optional_int(data.get("version"))
            or _plan_version_from_id(_optional_string(data.get("plan_id")))
        )
        if plan_version is None:
            raise LaunchError("Missing or invalid 'plan_version' value.")
        return cls(
            task_id=_string_value(data, "task_id"),
            plan_version=plan_version,
            body=_optional_string(data.get("body")) or "",
            status=normalize_plan_status(_string_value(data, "status")),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            created_by=ActorRef.from_dict(data.get("created_by")),
            supersedes=_optional_int(data.get("supersedes")),
            question_refs=_string_tuple(data.get("question_refs")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            criteria=tuple(
                AcceptanceCriterion.from_dict(item)
                for item in _dict_list(data.get("criteria"))
            ),
            todos=tuple(
                TaskTodo.from_dict(item) for item in _dict_list(data.get("todos"))
            ),
            generation_reason=_optional_string(data.get("generation_reason")),
            based_on_question_ids=(
                _string_tuple(data.get("based_on_question_ids"))
                or _string_tuple(data.get("question_refs"))
            ),
            based_on_answer_hash=_optional_string(data.get("based_on_answer_hash")),
            approved_at=_optional_string(data.get("approved_at")),
            approved_by=ActorRef.from_dict(data.get("approved_by"))
            if data.get("approved_by") is not None
            else None,
            approval_note=_optional_string(data.get("approval_note")),
            approval_source=_optional_string(data.get("approval_source")),
            approved_plan_hash=_optional_string(data.get("approved_plan_hash")),
            goal=_optional_string(data.get("goal")),
            files=_string_tuple(data.get("files")),
            test_commands=_string_tuple(data.get("test_commands")),
            expected_outputs=_string_tuple(data.get("expected_outputs")),
            todos_waived_reason=_optional_string(data.get("todos_waived_reason")),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )

    @property
    def plan_id(self) -> str:
        return _plan_id(self.plan_version)

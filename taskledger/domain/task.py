from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain._model_utils import (
    _dict_list,
    _first_string,
    _int_value,
    _optional_int,
    _optional_parent_relation,
    _optional_string,
    _plan_id,
    _plan_version_value,
    _require_contract,
    _string_tuple,
    _string_value,
)
from taskledger.domain.actor import ActorRef
from taskledger.domain.sidecars import FileLink, TaskTodo
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    TaskStatusStage,
    TaskType,
    normalize_task_status_stage,
    normalize_task_type,
)
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class TaskRecord:
    id: str
    slug: str
    title: str
    body: str
    status_stage: TaskStatusStage = "draft"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    description_summary: str | None = None
    priority: str | None = None
    labels: tuple[str, ...] = ()
    owner: str | None = None
    introduction_ref: str | None = None
    requirements: tuple[str, ...] = ()
    file_links: tuple[FileLink, ...] = ()
    todos: tuple[TaskTodo, ...] = ()
    latest_plan_version: int | None = None
    accepted_plan_version: int | None = None
    latest_planning_run: str | None = None
    latest_implementation_run: str | None = None
    latest_validation_run: str | None = None
    code_change_log_refs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    parent_task_id: str | None = None
    parent_relation: str | None = None
    closed_at: str | None = None
    closed_by: ActorRef | None = None
    closure_note: str | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "task"
    task_type: TaskType = "managed"
    recorded_at: str | None = None
    recorded_by: ActorRef | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "status": self.status_stage,
            "status_stage": self.status_stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description_summary": self.description_summary,
            "priority": self.priority,
            "labels": list(self.labels),
            "owner": self.owner,
            "intro_refs": list(self.intro_refs),
            "introduction_ref": self.introduction_ref,
            "requirements": list(self.requirements),
            "file_links": [item.to_dict() for item in self.file_links],
            "todos": [item.to_dict() for item in self.todos],
            "latest_plan": self.latest_plan,
            "latest_plan_version": self.latest_plan_version,
            "accepted_plan": self.accepted_plan,
            "accepted_plan_version": self.accepted_plan_version,
            "latest_planning_run": self.latest_planning_run,
            "latest_implementation_run": self.latest_implementation_run,
            "latest_validation_run": self.latest_validation_run,
            "code_change_log_refs": list(self.code_change_log_refs),
            "notes": list(self.notes),
            "body": self.body,
            "task_type": self.task_type,
        }
        if self.parent_task_id is not None:
            payload["parent_task_id"] = self.parent_task_id
        if self.parent_relation is not None:
            payload["parent_relation"] = self.parent_relation
        if self.closed_at is not None:
            payload["closed_at"] = self.closed_at
        if self.closed_by is not None:
            payload["closed_by"] = self.closed_by.to_dict()
        if self.closure_note is not None:
            payload["closure_note"] = self.closure_note
        if self.recorded_at is not None:
            payload["recorded_at"] = self.recorded_at
        if self.recorded_by is not None:
            payload["recorded_by"] = self.recorded_by.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TaskRecord:
        _require_contract(data, expected_object_type="task")
        return cls(
            id=_string_value(data, "id"),
            slug=_string_value(data, "slug"),
            title=_string_value(data, "title"),
            body=_optional_string(data.get("body")) or "",
            status_stage=normalize_task_status_stage(
                _optional_string(data.get("status"))
                or _string_value(data, "status_stage")
            ),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
            description_summary=_optional_string(data.get("description_summary")),
            priority=_optional_string(data.get("priority")),
            labels=_string_tuple(data.get("labels")),
            owner=_optional_string(data.get("owner")),
            introduction_ref=_optional_string(data.get("introduction_ref"))
            or _first_string(data.get("intro_refs")),
            requirements=_string_tuple(data.get("requirements")),
            file_links=tuple(
                FileLink.from_dict(item) for item in _dict_list(data.get("file_links"))
            ),
            todos=tuple(
                TaskTodo.from_dict(item) for item in _dict_list(data.get("todos"))
            ),
            latest_plan_version=_optional_int(data.get("latest_plan_version"))
            or _plan_version_value(data.get("latest_plan")),
            accepted_plan_version=_optional_int(data.get("accepted_plan_version"))
            or _plan_version_value(data.get("accepted_plan")),
            latest_planning_run=_optional_string(data.get("latest_planning_run")),
            latest_implementation_run=_optional_string(
                data.get("latest_implementation_run")
            ),
            latest_validation_run=_optional_string(data.get("latest_validation_run")),
            code_change_log_refs=_string_tuple(data.get("code_change_log_refs")),
            notes=_string_tuple(data.get("notes")),
            parent_task_id=_optional_string(data.get("parent_task_id")),
            parent_relation=_optional_parent_relation(data.get("parent_relation")),
            closed_at=_optional_string(data.get("closed_at")),
            closed_by=ActorRef.from_dict(data.get("closed_by"))
            if data.get("closed_by") is not None
            else None,
            closure_note=_optional_string(data.get("closure_note")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
            task_type=normalize_task_type(
                _optional_string(data.get("task_type")) or "managed"
            ),
            recorded_at=_optional_string(data.get("recorded_at")),
            recorded_by=ActorRef.from_dict(data.get("recorded_by"))
            if data.get("recorded_by") is not None
            else None,
        )

    @property
    def status(self) -> TaskStatusStage:
        return self.status_stage

    @property
    def intro_refs(self) -> tuple[str, ...]:
        return (self.introduction_ref,) if self.introduction_ref else ()

    @property
    def latest_plan(self) -> str | None:
        if self.latest_plan_version is None:
            return None
        return _plan_id(self.latest_plan_version)

    @property
    def accepted_plan(self) -> str | None:
        if self.accepted_plan_version is None:
            return None
        return _plan_id(self.accepted_plan_version)


@dataclass(slots=True, frozen=True)
class IntroductionRecord:
    id: str
    slug: str
    title: str
    body: str
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    labels: tuple[str, ...] = ()
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "intro"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "labels": list(self.labels),
            "body": self.body,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> IntroductionRecord:
        _require_contract(data, expected_object_type="intro")
        return cls(
            id=_string_value(data, "id"),
            slug=_string_value(data, "slug"),
            title=_string_value(data, "title"),
            body=_optional_string(data.get("body")) or "",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
            labels=_string_tuple(data.get("labels")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )

from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain._model_utils import (
    _dict_list,
    _int_or_default,
    _int_value,
    _optional_int,
    _optional_string,
    _require_contract,
    _require_sidecar_contract,
    _string_tuple,
    _string_value,
)
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    FileLinkKind,
    ValidationCheckStatus,
    normalize_file_link_kind,
    normalize_validation_check_status,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


def _waiver_to_dict(actor: ActorRef, reason: str, created_at: str) -> dict[str, object]:
    return {
        "actor": actor.to_dict(),
        "reason": reason,
        "created_at": created_at,
    }


def _waiver_from_dict(
    data: object,
    *,
    invalid_message: str,
) -> tuple[ActorRef, str, str] | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise LaunchError(invalid_message)
    return (
        ActorRef.from_dict(data.get("actor")),
        _string_value(data, "reason"),
        _optional_string(data.get("created_at")) or utc_now_iso(),
    )


@dataclass(slots=True, frozen=True)
class FileLink:
    path: str
    kind: FileLinkKind = "code"
    label: str | None = None
    required_for_validation: bool = False
    id: str | None = None
    task_id: str | None = None
    target_type: str | None = None
    baseline_hash: str | None = None
    baseline_size: int | None = None
    baseline_mtime: str | None = None
    baseline_exists: bool | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "link"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "path": self.path,
            "kind": self.kind,
            "label": self.label,
            "required_for_validation": self.required_for_validation,
            "target_type": self.target_type,
            "baseline_hash": self.baseline_hash,
            "baseline_size": self.baseline_size,
            "baseline_mtime": self.baseline_mtime,
            "baseline_exists": self.baseline_exists,
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> FileLink:
        if not isinstance(data, dict):
            raise LaunchError("Invalid file link: expected mapping.")
        _require_sidecar_contract(data, expected_object_type="link")
        return cls(
            id=_optional_string(data.get("id")),
            task_id=_optional_string(data.get("task_id")),
            path=_string_value(data, "path"),
            kind=normalize_file_link_kind(_optional_string(data.get("kind")) or "code"),
            label=_optional_string(data.get("label")),
            required_for_validation=bool(data.get("required_for_validation", False)),
            target_type=_optional_string(data.get("target_type")),
            baseline_hash=_optional_string(data.get("baseline_hash")),
            baseline_size=_optional_int(data.get("baseline_size")),
            baseline_mtime=_optional_string(data.get("baseline_mtime")),
            baseline_exists=(
                bool(data["baseline_exists"])
                if data.get("baseline_exists") is not None
                else None
            ),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_or_default(
                data.get("schema_version"), TASKLEDGER_SCHEMA_VERSION
            ),
            object_type=_optional_string(data.get("object_type")) or "link",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
        )


@dataclass(slots=True, frozen=True)
class TaskTodo:
    id: str
    text: str
    done: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    source: str | None = None
    mandatory: bool = False
    # Extended fields for richer todo tracking
    status: str = "open"  # Will be validated to TodoStatus
    active_at: str | None = None
    blocked_reason: str | None = None
    done_at: str | None = None
    skipped_at: str | None = None
    completed_by: ActorRef | None = None
    completed_in_harness: HarnessRef | None = None
    skipped_by: ActorRef | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)
    artifact_refs: tuple[str, ...] = field(default_factory=tuple)
    change_refs: tuple[str, ...] = field(default_factory=tuple)
    command_refs: tuple[str, ...] = field(default_factory=tuple)
    source_plan_id: str | None = None
    source_question_ids: tuple[str, ...] = field(default_factory=tuple)
    validation_hint: str | None = None
    worker_step_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "text": self.text,
            "done": self.done,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "mandatory": self.mandatory,
            "status": self.status,
            "active_at": self.active_at,
            "blocked_reason": self.blocked_reason,
            "done_at": self.done_at,
            "skipped_at": self.skipped_at,
            "completed_by": self.completed_by.to_dict() if self.completed_by else None,
            "completed_in_harness": (
                self.completed_in_harness.to_dict()
                if self.completed_in_harness
                else None
            ),
            "skipped_by": self.skipped_by.to_dict() if self.skipped_by else None,
            "evidence": list(self.evidence),
            "artifact_refs": list(self.artifact_refs),
            "change_refs": self.change_refs,
            "command_refs": self.command_refs,
            "source_plan_id": self.source_plan_id,
            "source_question_ids": list(self.source_question_ids),
            "validation_hint": self.validation_hint,
        }
        if self.worker_step_id is not None:
            payload["worker_step_id"] = self.worker_step_id
        return payload

    @classmethod
    def from_dict(cls, data: object) -> TaskTodo:
        if not isinstance(data, dict):
            raise LaunchError("Invalid todo: expected mapping.")

        # Enforce version compatibility for v2 records
        _require_sidecar_contract(data, expected_object_type="todo")

        # Handle backward compatibility: infer status from done field if not present
        status_raw = _optional_string(data.get("status"))
        if status_raw is None:
            status = "done" if bool(data.get("done", False)) else "open"
        else:
            from taskledger.domain.states import normalize_todo_status

            status = normalize_todo_status(status_raw)

        # Parse completed_by and skipped_by
        completed_by_data = data.get("completed_by")
        completed_by = (
            ActorRef.from_dict(completed_by_data) if completed_by_data else None
        )
        completed_in_harness_data = data.get("completed_in_harness")
        completed_in_harness = (
            HarnessRef.from_dict(completed_in_harness_data)
            if completed_in_harness_data
            else None
        )
        skipped_by_data = data.get("skipped_by")
        skipped_by = ActorRef.from_dict(skipped_by_data) if skipped_by_data else None

        # Parse evidence and refs
        evidence = _string_tuple(data.get("evidence"))
        artifact_refs = _string_tuple(data.get("artifact_refs")) or _string_tuple(
            data.get("artifacts")
        )
        change_refs = _string_tuple(data.get("change_refs")) or _string_tuple(
            data.get("changes")
        )
        command_refs = _string_tuple(data.get("command_refs"))

        return cls(
            id=_string_value(data, "id"),
            text=_string_value(data, "text"),
            done=bool(data.get("done", False)),
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
            source=_optional_string(data.get("source")),
            mandatory=bool(data.get("mandatory", False)),
            status=status,
            active_at=_optional_string(data.get("active_at")),
            blocked_reason=_optional_string(data.get("blocked_reason")),
            done_at=_optional_string(data.get("done_at")),
            skipped_at=_optional_string(data.get("skipped_at")),
            completed_by=completed_by,
            completed_in_harness=completed_in_harness,
            skipped_by=skipped_by,
            evidence=evidence,
            artifact_refs=artifact_refs,
            change_refs=change_refs,
            command_refs=command_refs,
            source_plan_id=_optional_string(data.get("source_plan_id")),
            source_question_ids=_string_tuple(data.get("source_question_ids")),
            validation_hint=_optional_string(data.get("validation_hint")),
            worker_step_id=_optional_string(data.get("worker_step_id")),
        )


@dataclass(slots=True, frozen=True)
class AcceptanceCriterion:
    id: str
    text: str
    mandatory: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "mandatory": self.mandatory,
        }

    @classmethod
    def from_dict(cls, data: object) -> AcceptanceCriterion:
        if not isinstance(data, dict):
            raise LaunchError("Invalid acceptance criterion: expected mapping.")
        return cls(
            id=_string_value(data, "id"),
            text=_string_value(data, "text"),
            mandatory=bool(data.get("mandatory", True)),
        )


@dataclass(slots=True, frozen=True)
class CriterionWaiver:
    actor: ActorRef = field(default_factory=ActorRef)
    reason: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return _waiver_to_dict(self.actor, self.reason, self.created_at)

    @classmethod
    def from_dict(cls, data: object) -> CriterionWaiver | None:
        parsed = _waiver_from_dict(
            data,
            invalid_message="Invalid criterion waiver: expected mapping.",
        )
        if parsed is None:
            return None
        actor, reason, created_at = parsed
        return cls(
            actor=actor,
            reason=reason,
            created_at=created_at,
        )


@dataclass(slots=True, frozen=True)
class DependencyWaiver:
    actor: ActorRef = field(default_factory=ActorRef)
    reason: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return _waiver_to_dict(self.actor, self.reason, self.created_at)

    @classmethod
    def from_dict(cls, data: object) -> DependencyWaiver | None:
        parsed = _waiver_from_dict(
            data,
            invalid_message="Invalid dependency waiver: expected mapping.",
        )
        if parsed is None:
            return None
        actor, reason, created_at = parsed
        return cls(
            actor=actor,
            reason=reason,
            created_at=created_at,
        )


@dataclass(slots=True, frozen=True)
class DependencyRequirement:
    task_id: str
    required_status: str = "done"
    waiver: DependencyWaiver | None = None
    id: str | None = None
    required_task_id: str | None = None
    parent_task_id: str | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "requirement"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "task_id": self.required_task_id or self.task_id,
            "required_task_id": self.required_task_id or self.task_id,
            "parent_task_id": self.parent_task_id,
            "required_status": self.required_status,
            "waiver": self.waiver.to_dict() if self.waiver is not None else None,
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> DependencyRequirement:
        if not isinstance(data, dict):
            raise LaunchError("Invalid dependency requirement: expected mapping.")
        _require_sidecar_contract(data, expected_object_type="requirement")
        task_id = _optional_string(data.get("required_task_id")) or _string_value(
            data, "task_id"
        )
        return cls(
            id=_optional_string(data.get("id")),
            task_id=task_id,
            required_task_id=_optional_string(data.get("required_task_id")) or task_id,
            parent_task_id=_optional_string(data.get("parent_task_id")),
            required_status=_optional_string(data.get("required_status")) or "done",
            waiver=DependencyWaiver.from_dict(data.get("waiver")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_or_default(
                data.get("schema_version"), TASKLEDGER_SCHEMA_VERSION
            ),
            object_type=_optional_string(data.get("object_type")) or "requirement",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
        )


@dataclass(slots=True, frozen=True)
class ValidationCheck:
    name: str
    id: str | None = None
    criterion_id: str | None = None
    status: ValidationCheckStatus = "pass"
    details: str | None = None
    evidence: tuple[str, ...] = ()
    waiver: CriterionWaiver | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "criterion_id": self.criterion_id,
            "name": self.name,
            "status": self.status,
            "details": self.details,
            "evidence": list(self.evidence),
            "waiver": self.waiver.to_dict() if self.waiver is not None else None,
        }
        return payload

    @classmethod
    def from_dict(cls, data: object) -> ValidationCheck:
        if not isinstance(data, dict):
            raise LaunchError("Invalid validation check: expected mapping.")
        identifier = _optional_string(data.get("id")) or _optional_string(
            data.get("criterion_id")
        )
        status = normalize_validation_check_status(_string_value(data, "status"))
        criterion_id = _optional_string(data.get("criterion_id")) or (
            identifier if status != "not_run" else None
        )
        if status != "not_run" and criterion_id is None:
            raise LaunchError(
                "Validation checks must reference a criterion_id "
                "unless status is not_run."
            )
        return cls(
            id=identifier,
            criterion_id=criterion_id,
            name=_string_value(data, "name"),
            status=status,
            details=_optional_string(data.get("details")),
            evidence=_string_tuple(data.get("evidence")),
            waiver=CriterionWaiver.from_dict(data.get("waiver")),
        )


@dataclass(slots=True, frozen=True)
class TodoCollection:
    task_id: str
    todos: tuple[TaskTodo, ...] = ()
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "todos"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "task_id": self.task_id,
            "todos": [item.to_dict() for item in self.todos],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TodoCollection:
        _require_contract(data, expected_object_type="todos")
        return cls(
            task_id=_string_value(data, "task_id"),
            todos=tuple(
                TaskTodo.from_dict(item) for item in _dict_list(data.get("todos"))
            ),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )


@dataclass(slots=True, frozen=True)
class LinkCollection:
    task_id: str
    links: tuple[FileLink, ...] = ()
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "links"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "task_id": self.task_id,
            "links": [item.to_dict() for item in self.links],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LinkCollection:
        _require_contract(data, expected_object_type="links")
        return cls(
            task_id=_string_value(data, "task_id"),
            links=tuple(
                FileLink.from_dict(item) for item in _dict_list(data.get("links"))
            ),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )


@dataclass(slots=True, frozen=True)
class RequirementCollection:
    task_id: str
    requirements: tuple[DependencyRequirement, ...] = ()
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "requirements"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "task_id": self.task_id,
            "requirements": [item.to_dict() for item in self.requirements],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RequirementCollection:
        _require_contract(data, expected_object_type="requirements")
        return cls(
            task_id=_string_value(data, "task_id"),
            requirements=tuple(
                DependencyRequirement.from_dict(item)
                for item in _dict_list(data.get("requirements"))
            ),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )
